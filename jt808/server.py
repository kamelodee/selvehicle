"""
Async TCP Server for JT/T 808-2019 terminals.
Each connection is handled in its own coroutine.
"""

import asyncio
import logging
import os
from typing import Optional

from .models import SessionLocal, create_tables
from .protocol import extract_frames, parse_message
from .handlers import dispatch, conn_mgr

logger = logging.getLogger(__name__)

TCP_HOST = os.getenv("TCP_HOST", "0.0.0.0")
TCP_PORT = int(os.getenv("TCP_PORT", "8808"))
IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT_SECS", "120"))   # 2 min idle → disconnect
READ_CHUNK   = 4096


async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peername = writer.get_extra_info("peername")
    client_ip = peername[0] if peername else "unknown"
    phone: Optional[str] = None
    buf = b""

    logger.info(f"New connection from {client_ip}")

    try:
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(READ_CHUNK), timeout=IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                logger.info(f"[{phone or client_ip}] idle timeout — closing")
                break

            if not chunk:
                logger.info(f"[{phone or client_ip}] disconnected")
                break

            buf += chunk
            frames, buf = extract_frames(buf)

            for payload in frames:
                msg = parse_message(payload)
                if not msg:
                    logger.warning(f"[{client_ip}] invalid frame (bad checksum or too short)")
                    continue

                phone = msg.header.phone

                # Register writer so API can push commands
                conn_mgr.register(phone, writer)

                db = SessionLocal()
                try:
                    response = await dispatch(msg, db, writer, client_ip)
                    if response:
                        writer.write(response)
                        await writer.drain()
                except Exception as e:
                    logger.exception(f"[{phone}] error handling msg 0x{msg.header.msg_id:04X}: {e}")
                finally:
                    db.close()

    except ConnectionResetError:
        logger.info(f"[{phone or client_ip}] connection reset")
    except Exception as e:
        logger.exception(f"[{phone or client_ip}] unexpected error: {e}")
    finally:
        if phone:
            conn_mgr.unregister(phone)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.info(f"[{phone or client_ip}] connection closed")


async def run_tcp_server():
    create_tables()
    server = await asyncio.start_server(handle_connection, TCP_HOST, TCP_PORT)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    logger.info(f"Selvehicle TCP server listening on {addrs}")
    async with server:
        await server.serve_forever()
