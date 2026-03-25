"""
JT808Server  — async TCP server
ConnectionRegistry — in-memory map of  phone → TerminalConnection
"""

import asyncio
import logging
from typing import Dict, List, Optional

from core.connection import TerminalConnection
from core.handler    import MessageHandler

logger = logging.getLogger(__name__)


# ── Registry ──────────────────────────────────────────────────────────────────

class ConnectionRegistry:
    """Thread-safe (asyncio-safe) registry of live terminal connections."""

    def __init__(self) -> None:
        self._by_phone: Dict[str, TerminalConnection] = {}
        self._lock = asyncio.Lock()

    async def add(self, conn: TerminalConnection) -> None:
        if conn.phone:
            async with self._lock:
                self._by_phone[conn.phone] = conn

    async def remove(self, conn: TerminalConnection) -> None:
        if conn.phone:
            async with self._lock:
                if self._by_phone.get(conn.phone) is conn:
                    del self._by_phone[conn.phone]

    async def get(self, phone: str) -> Optional[TerminalConnection]:
        return self._by_phone.get(phone)

    def online_phones(self) -> List[str]:
        return list(self._by_phone.keys())

    def count(self) -> int:
        return len(self._by_phone)


# Shared singleton used by both server and API
registry = ConnectionRegistry()


# ── TCP Server ────────────────────────────────────────────────────────────────

class JT808Server:
    READ_TIMEOUT = 120.0   # seconds — disconnect idle terminals
    CHUNK_SIZE   = 8192

    def __init__(self, host: str, port: int, db) -> None:
        self.host    = host
        self.port    = port
        self.handler = MessageHandler(db)
        self.db      = db

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        conn = TerminalConnection(reader, writer)
        logger.info("New TCP connection from %s", conn.remote_addr)

        try:
            while True:
                try:
                    data = await asyncio.wait_for(
                        reader.read(self.CHUNK_SIZE),
                        timeout=self.READ_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.info(
                        "Idle timeout — disconnecting %s",
                        conn.phone or conn.remote_addr,
                    )
                    break

                if not data:
                    break  # clean EOF

                frames = conn.feed(data)
                for frame in frames:
                    # Update phone from frame header if not yet set
                    if frame.phone and frame.phone != "000000000000":
                        if not conn.phone:
                            conn.phone = frame.phone
                            await registry.add(conn)
                        elif conn.phone != frame.phone:
                            # Phone changed (shouldn't happen, but handle gracefully)
                            await registry.remove(conn)
                            conn.phone = frame.phone

                    await self.handler.handle(conn, frame)

                    # Re-register in case phone was just assigned
                    if conn.phone:
                        await registry.add(conn)

        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        except Exception as exc:
            logger.error(
                "Unexpected error for %s: %s",
                conn.phone or conn.remote_addr, exc, exc_info=True,
            )
        finally:
            await registry.remove(conn)
            if conn.phone:
                await self.db.set_terminal_offline(conn.phone)
            conn.close()
            logger.info(
                "Connection closed: %s (%s)",
                conn.phone or "unregistered", conn.remote_addr,
            )

    async def start(self) -> None:
        server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
            reuse_address=True,
        )
        addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
        logger.info("JT808 TCP server listening on %s", addrs)
        async with server:
            await server.serve_forever()
