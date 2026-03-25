"""
MessageHandler — dispatches incoming frames to the right sub-handler
and sends appropriate responses.
"""

import logging
import struct
from typing import TYPE_CHECKING

from protocol import constants as MSG
from protocol.builder import (
    build_platform_general_response,
    build_registration_response,
    build_server_time_response,
)
from protocol.parser import (
    parse_location_report,
    parse_registration,
    parse_terminal_general_response,
)

if TYPE_CHECKING:
    from core.connection import TerminalConnection
    from storage.database import Database

logger = logging.getLogger(__name__)


class MessageHandler:
    def __init__(self, db: "Database") -> None:
        self.db = db

    # ── Dispatcher ────────────────────────────────────────────────────────────

    async def handle(self, conn: "TerminalConnection", frame) -> None:
        mid = frame.msg_id
        handlers = {
            MSG.TERMINAL_GENERAL_RESPONSE:  self._on_general_response,
            MSG.TERMINAL_HEARTBEAT:         self._on_heartbeat,
            MSG.TERMINAL_REGISTRATION:      self._on_registration,
            MSG.TERMINAL_UNREGISTRATION:    self._on_unregistration,
            MSG.QUERY_SERVER_TIME:          self._on_query_time,
            MSG.TERMINAL_AUTHENTICATION:    self._on_authentication,
            MSG.LOCATION_INFO_REPORT:       self._on_location_report,
            MSG.QUERY_TERMINAL_PARAMS_RESP: self._on_params_response,
        }
        handler = handlers.get(mid)
        if handler:
            try:
                await handler(conn, frame)
            except Exception as exc:
                logger.error(
                    "Error in handler for 0x%04X from %s: %s",
                    mid, conn.phone, exc, exc_info=True,
                )
        else:
            logger.info("Unhandled msg_id=0x%04X from %s", mid, conn.phone or conn.remote_addr)

    # ── Sub-handlers ──────────────────────────────────────────────────────────

    async def _on_general_response(self, conn, frame):
        try:
            resp = parse_terminal_general_response(frame.body)
            logger.info(
                "Terminal ACK: resp_serial=%d msg_id=0x%04X result=%d phone=%s",
                resp.response_serial, resp.response_msg_id, resp.result, conn.phone,
            )
        except Exception as exc:
            logger.warning("Could not parse terminal general response: %s", exc)

    async def _on_heartbeat(self, conn, frame):
        logger.debug("Heartbeat from %s", conn.phone)
        body = build_platform_general_response(frame.serial_no, MSG.TERMINAL_HEARTBEAT)
        await conn.send_frame(MSG.PLATFORM_GENERAL_RESPONSE, body)

    async def _on_registration(self, conn, frame):
        conn.phone = frame.phone
        try:
            reg = parse_registration(frame.body)
            logger.info(
                "Registration: phone=%s plate=%s device=%s manufacturer=%s",
                conn.phone, reg.plate_no, reg.device_id, reg.manufacturer,
            )
            await self.db.upsert_terminal(
                conn.phone,
                plate_no     = reg.plate_no,
                device_id    = reg.device_id,
                manufacturer = reg.manufacturer,
            )
        except Exception as exc:
            logger.warning("Could not parse registration body: %s", exc)
            await self.db.upsert_terminal(conn.phone)

        auth_code = conn.phone  # use phone as auth token (simple approach)
        body = build_registration_response(frame.serial_no, result=0, auth_code=auth_code)
        await conn.send_frame(MSG.TERMINAL_REGISTRATION_RESP, body)

    async def _on_unregistration(self, conn, frame):
        logger.info("Terminal unregistered: %s", conn.phone)
        body = build_platform_general_response(frame.serial_no, MSG.TERMINAL_UNREGISTRATION)
        await conn.send_frame(MSG.PLATFORM_GENERAL_RESPONSE, body)

    async def _on_query_time(self, conn, frame):
        body = build_server_time_response()
        await conn.send_frame(MSG.QUERY_SERVER_TIME_RESP, body)

    async def _on_authentication(self, conn, frame):
        conn.phone         = frame.phone
        conn.authenticated = True
        logger.info("Terminal authenticated: %s", conn.phone)
        await self.db.upsert_terminal(conn.phone)
        body = build_platform_general_response(
            frame.serial_no, MSG.TERMINAL_AUTHENTICATION, result=0
        )
        await conn.send_frame(MSG.PLATFORM_GENERAL_RESPONSE, body)

    async def _on_location_report(self, conn, frame):
        if not conn.phone:
            conn.phone = frame.phone
        try:
            loc = parse_location_report(frame.body)
            await self.db.insert_location(conn.phone, loc)
            logger.info(
                "Location  phone=%-14s  lat=%.6f  lon=%.6f  spd=%.1f km/h  "
                "alt=%dm  alarm=%d  sats=%s",
                conn.phone, loc.latitude, loc.longitude, loc.speed,
                loc.altitude, loc.alarm_flags, loc.satellites,
            )
        except Exception as exc:
            logger.error("Location parse error from %s: %s", conn.phone, exc, exc_info=True)

        # Always acknowledge
        body = build_platform_general_response(frame.serial_no, MSG.LOCATION_INFO_REPORT)
        await conn.send_frame(MSG.PLATFORM_GENERAL_RESPONSE, body)

    async def _on_params_response(self, conn, frame):
        logger.info("Params response from %s (%d bytes)", conn.phone, len(frame.body))
        await self.db.store_params_response(conn.phone, frame.body)
