"""
TerminalConnection — wraps asyncio StreamReader/Writer with:
  • Frame assembly buffer
  • Per-connection outgoing serial counter
  • Convenience send_frame()
"""

import asyncio
import logging
from typing import List, Optional

from protocol.codec import (
    JT808Frame,
    FRAME_MARKER,
    build_frame,
    parse_frame,
    unescape,
)

logger = logging.getLogger(__name__)


class TerminalConnection:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.reader  = reader
        self.writer  = writer
        self.phone:  Optional[str] = None
        self.authenticated: bool   = False

        self._serial  = 0
        self._buf     = bytearray()

        addr = writer.get_extra_info("peername")
        self.remote_addr = f"{addr[0]}:{addr[1]}" if addr else "unknown"

    # ── Serial counter ────────────────────────────────────────────────────────

    def next_serial(self) -> int:
        self._serial = (self._serial + 1) & 0xFFFF
        return self._serial

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_frame(self, msg_id: int, body: bytes) -> None:
        phone  = self.phone or "000000000000"
        serial = self.next_serial()
        raw    = build_frame(msg_id, body, phone, serial)
        try:
            self.writer.write(raw)
            await self.writer.drain()
            logger.debug(
                "→ 0x%04X  serial=%d  to=%s  len=%d",
                msg_id, serial, self.phone, len(body),
            )
        except (ConnectionResetError, BrokenPipeError) as exc:
            logger.warning("Send failed to %s: %s", self.phone, exc)

    # ── Close ─────────────────────────────────────────────────────────────────

    def close(self) -> None:
        try:
            self.writer.close()
        except Exception:
            pass

    # ── Frame assembly ────────────────────────────────────────────────────────

    def feed(self, data: bytes) -> List[JT808Frame]:
        """
        Append raw TCP data to the internal buffer.
        Returns all complete, valid frames found.
        """
        self._buf.extend(data)
        frames: List[JT808Frame] = []

        while True:
            # Locate the opening 0x7E
            start = self._buf.find(FRAME_MARKER)
            if start == -1:
                self._buf.clear()
                break

            # Discard any garbage before the first marker
            if start > 0:
                logger.debug(
                    "Discarding %d byte(s) before frame marker from %s",
                    start, self.remote_addr,
                )
                del self._buf[:start]

            # Find the closing 0x7E
            end = self._buf.find(FRAME_MARKER, 1)
            if end == -1:
                # Frame incomplete — wait for more data
                break

            # Extract the escaped payload between the two markers
            raw_escaped = bytes(self._buf[1:end])
            del self._buf[: end + 1]

            if not raw_escaped:
                # Back-to-back markers → skip
                continue

            raw = unescape(raw_escaped)
            frame = parse_frame(raw)
            if frame:
                frames.append(frame)
                logger.debug(
                    "← 0x%04X  serial=%d  from=%s  body=%d B",
                    frame.msg_id, frame.serial_no, self.remote_addr, len(frame.body),
                )
            else:
                logger.warning(
                    "Bad frame (checksum / length) from %s – discarded",
                    self.remote_addr,
                )

        return frames
