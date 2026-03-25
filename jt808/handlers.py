"""
Message Handlers
Each handler receives (message, db_session, connection_manager) and returns
bytes to send back, or None for no reply.
"""

import logging
import secrets
import struct
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .models import Terminal, LocationRecord, CommandLog, ParameterLog
from .protocol import (
    JT808Message, LocationReport,
    MSG_TERMINAL_GENERAL_RESP,
    MSG_HEARTBEAT,
    MSG_TERMINAL_REGISTER,
    MSG_TERMINAL_UNREGISTER,
    MSG_TERMINAL_AUTH,
    MSG_LOCATION_REPORT,
    MSG_QUERY_PARAMS_RESP,
    MSG_QUERY_SERVER_TIME,
    parse_location_report,
    build_platform_general_response,
    build_terminal_register_response,
    build_query_server_time_response,
    bcd_decode,
)

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Tracks active TCP connections keyed by phone number.
    Used by the API to push commands to connected terminals.
    """
    def __init__(self):
        self._connections: dict[str, asyncio.StreamWriter] = {}
        self._serials: dict[str, int] = {}

    def register(self, phone: str, writer):
        self._connections[phone] = writer
        self._serials.setdefault(phone, 0)

    def unregister(self, phone: str):
        self._connections.pop(phone, None)

    def is_online(self, phone: str) -> bool:
        return phone in self._connections

    def online_phones(self) -> list[str]:
        return list(self._connections.keys())

    def next_serial(self, phone: str) -> int:
        self._serials[phone] = (self._serials.get(phone, 0) + 1) & 0xFFFF
        return self._serials[phone]

    async def send(self, phone: str, data: bytes) -> bool:
        writer = self._connections.get(phone)
        if not writer:
            return False
        try:
            writer.write(data)
            await writer.drain()
            return True
        except Exception as e:
            logger.warning(f"[{phone}] send failed: {e}")
            self.unregister(phone)
            return False


import asyncio   # placed here to avoid circular at module level


# Global singleton (created in server.py, imported in api.py)
conn_mgr = ConnectionManager()


# ─── Dispatch ─────────────────────────────────────────────────────────────────

async def dispatch(
    msg: JT808Message,
    db: Session,
    writer,
    client_ip: str,
) -> Optional[bytes]:
    """Route a parsed message to the correct handler."""
    phone  = msg.header.phone
    mid    = msg.header.msg_id
    serial = msg.header.serial_no

    # Keep terminal last-seen up to date
    _touch_terminal(phone, client_ip, db)

    if mid == MSG_TERMINAL_REGISTER:
        return handle_registration(msg, db)

    elif mid == MSG_TERMINAL_AUTH:
        return handle_authentication(msg, db)

    elif mid == MSG_TERMINAL_UNREGISTER:
        return handle_unregistration(msg, db)

    elif mid == MSG_HEARTBEAT:
        return build_platform_general_response(phone, _srv_serial(phone), serial, mid)

    elif mid == MSG_QUERY_SERVER_TIME:
        return build_query_server_time_response(phone, _srv_serial(phone), serial)

    elif mid == MSG_LOCATION_REPORT:
        return handle_location_report(msg, db)

    elif mid == MSG_TERMINAL_GENERAL_RESP:
        handle_terminal_ack(msg, db)
        return None  # no reply to a response

    elif mid == MSG_QUERY_PARAMS_RESP:
        handle_params_response(msg, db)
        return None

    else:
        logger.debug(f"[{phone}] unhandled msg_id=0x{mid:04X}")
        return build_platform_general_response(phone, _srv_serial(phone), serial, mid)


# ─── Handlers ─────────────────────────────────────────────────────────────────

def handle_registration(msg: JT808Message, db: Session) -> bytes:
    phone    = msg.header.phone
    body     = msg.body
    serial   = msg.header.serial_no

    try:
        province_id, city_id = struct.unpack_from('>HH', body, 0)
        manufacturer = body[4:9].decode('gbk', errors='replace').rstrip('\x00')
        device_model = body[9:29].decode('gbk', errors='replace').rstrip('\x00')
        device_id    = body[29:49].decode('gbk', errors='replace').rstrip('\x00')
        plate_color  = body[49]
        plate_no     = body[50:].decode('gbk', errors='replace').rstrip('\x00')
    except Exception as e:
        logger.warning(f"[{phone}] registration parse error: {e}")
        return build_terminal_register_response(phone, _srv_serial(phone), serial, 1)

    terminal = db.query(Terminal).filter_by(phone=phone).first()
    auth_code = secrets.token_hex(8)

    if not terminal:
        terminal = Terminal(phone=phone)
        db.add(terminal)

    terminal.province_id  = province_id
    terminal.city_id      = city_id
    terminal.manufacturer = manufacturer
    terminal.device_model = device_model
    terminal.device_id    = device_id
    terminal.plate_color  = plate_color
    terminal.plate_no     = plate_no
    terminal.auth_code    = auth_code
    terminal.authenticated = False
    db.commit()

    logger.info(f"[{phone}] registered — plate={plate_no} auth_code={auth_code}")
    return build_terminal_register_response(phone, _srv_serial(phone), serial, 0, auth_code)


def handle_authentication(msg: JT808Message, db: Session) -> bytes:
    phone    = msg.header.phone
    serial   = msg.header.serial_no
    auth_code = msg.body.decode('gbk', errors='replace').rstrip('\x00')

    terminal = db.query(Terminal).filter_by(phone=phone).first()
    if not terminal or terminal.auth_code != auth_code:
        logger.warning(f"[{phone}] authentication FAILED (code={auth_code})")
        result = 1
    else:
        terminal.authenticated = True
        db.commit()
        logger.info(f"[{phone}] authenticated")
        result = 0

    return build_platform_general_response(phone, _srv_serial(phone), serial, msg.header.msg_id, result)


def handle_unregistration(msg: JT808Message, db: Session) -> bytes:
    phone  = msg.header.phone
    serial = msg.header.serial_no
    conn_mgr.unregister(phone)
    logger.info(f"[{phone}] unregistered")
    return build_platform_general_response(phone, _srv_serial(phone), serial, msg.header.msg_id)


def handle_location_report(msg: JT808Message, db: Session) -> bytes:
    phone  = msg.header.phone
    serial = msg.header.serial_no

    try:
        loc = parse_location_report(msg.body)
    except Exception as e:
        logger.error(f"[{phone}] location parse error: {e}")
        return build_platform_general_response(phone, _srv_serial(phone), serial, msg.header.msg_id, 1)

    add = loc.additional
    record = LocationRecord(
        phone           = phone,
        device_time     = loc.timestamp,
        latitude        = loc.latitude,
        longitude       = loc.longitude,
        altitude        = loc.altitude,
        speed           = loc.speed,
        direction       = loc.direction,
        alarm_flag      = loc.alarm_flag,
        status          = loc.status,
        gps_valid       = loc.is_gps_valid,
        ignition_on     = loc.is_ignition_on,
        mileage         = add.mileage,
        fuel            = add.fuel,
        speed_can       = add.speed_can,
        signal_strength = add.signal_strength,
        gnss_satellites = add.gnss_satellites,
        io_status       = add.io_status,
        analog          = add.analog,
        alarm_status    = add.custom_alarm_status,
        ecu_ignition    = add.custom_ecu_ignition,
    )
    db.add(record)
    db.commit()

    logger.debug(
        f"[{phone}] location lat={loc.latitude:.6f} lng={loc.longitude:.6f} "
        f"spd={loc.speed:.1f}km/h alarm={loc.alarm_flag:#010x}"
    )
    return build_platform_general_response(phone, _srv_serial(phone), serial, msg.header.msg_id)


def handle_terminal_ack(msg: JT808Message, db: Session):
    """Handle 0x0001 Terminal General Response — marks pending command as acked"""
    phone = msg.header.phone
    try:
        resp_serial, resp_msg_id, result = struct.unpack_from('>HHB', msg.body, 0)
    except Exception:
        return

    cmd = (
        db.query(CommandLog)
        .filter_by(phone=phone, serial_no=resp_serial, acked=False)
        .first()
    )
    if cmd:
        cmd.acked     = True
        cmd.ack_result = result
        cmd.acked_at  = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"[{phone}] command serial={resp_serial} acked result={result}")


def handle_params_response(msg: JT808Message, db: Session):
    """Handle 0x0104 Query Terminal Parameters Response"""
    phone  = msg.header.phone
    body   = msg.body
    offset = 3  # skip response serial (2) + param count (1)
    params: dict = {}

    while offset + 5 <= len(body):
        param_id,  = struct.unpack_from('>I', body, offset)
        param_len  = body[offset + 4]
        param_val  = body[offset + 5: offset + 5 + param_len]
        params[f"0x{param_id:04X}"] = param_val.hex()
        offset    += 5 + param_len

    log = ParameterLog(phone=phone, direction="get", params=params)
    db.add(log)
    db.commit()
    logger.info(f"[{phone}] params response: {params}")


# ─── Helpers ──────────────────────────────────────────────────────────────────

_server_serial: dict[str, int] = {}


def _srv_serial(phone: str) -> int:
    _server_serial[phone] = (_server_serial.get(phone, 0) + 1) & 0xFFFF
    return _server_serial[phone]


def _touch_terminal(phone: str, ip: str, db: Session):
    terminal = db.query(Terminal).filter_by(phone=phone).first()
    if not terminal:
        terminal = Terminal(phone=phone)
        db.add(terminal)
    terminal.last_seen_at = datetime.now(timezone.utc)
    terminal.last_ip = ip
    db.commit()
