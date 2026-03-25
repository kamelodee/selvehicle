"""
JT/T 808-2019 Protocol Codec
Handles encoding, decoding, escaping, and checksum for all message types.
"""

import struct
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime, timezone

# ─── Constants ────────────────────────────────────────────────────────────────

FLAG = 0x7E
ESC  = 0x7D

# Message IDs
MSG_TERMINAL_GENERAL_RESP  = 0x0001
MSG_PLATFORM_GENERAL_RESP  = 0x8001
MSG_HEARTBEAT              = 0x0002
MSG_QUERY_SERVER_TIME      = 0x0004
MSG_QUERY_SERVER_TIME_RESP = 0x8004
MSG_TERMINAL_REGISTER      = 0x0100
MSG_TERMINAL_REGISTER_RESP = 0x8100
MSG_TERMINAL_UNREGISTER    = 0x0003
MSG_TERMINAL_AUTH          = 0x0102
MSG_LOCATION_REPORT        = 0x0200
MSG_SET_PARAMS             = 0x8103
MSG_QUERY_PARAMS           = 0x8106
MSG_QUERY_PARAMS_RESP      = 0x0104
MSG_TERMINAL_CONTROL       = 0x8105
MSG_SET_CIRCULAR_AREA      = 0x8600
MSG_SET_RECT_AREA          = 0x8602
MSG_SET_POLYGON_AREA       = 0x8604
MSG_SET_ROUTE              = 0x8606

# Custom Parameter IDs (Section 4)
PARAM_ECU_IGNITION_SWITCH  = 0xFF01
PARAM_GEOFENCE_SWITCH      = 0xFF02

# Custom Control Command Words (Section 3)
CMD_VEHICLE_POWER_ON       = 100
CMD_VEHICLE_POWER_OFF      = 101
CMD_START_ALARM            = 102
CMD_STOP_ALARM             = 103

# Additional Info IDs (Section 2.2)
ADD_INFO_MILEAGE           = 0x01
ADD_INFO_FUEL              = 0x02
ADD_INFO_SPEED_CAN         = 0x03
ADD_INFO_ALARM_ID          = 0x04
ADD_INFO_EXT_SIGNAL        = 0x25
ADD_INFO_IO_STATUS         = 0x2A
ADD_INFO_ANALOG            = 0x2B
ADD_INFO_SIGNAL_STRENGTH   = 0x30
ADD_INFO_GNSS_SATS         = 0x31
ADD_INFO_CUSTOM            = 0xEE


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class JT808Header:
    msg_id: int
    phone: str          # 12-digit string
    serial_no: int
    body_length: int = 0
    encrypt_type: int = 0
    subpackage: bool = False
    total_packets: int = 0
    packet_no: int = 0


@dataclass
class LocationAdditionalInfo:
    mileage: Optional[int] = None           # 1/10 km
    fuel: Optional[int] = None              # 1/10 L
    speed_can: Optional[int] = None         # 1/10 km/h
    alarm_id: Optional[int] = None
    ext_signal: Optional[int] = None
    io_status: Optional[int] = None
    analog: Optional[int] = None
    signal_strength: Optional[int] = None
    gnss_satellites: Optional[int] = None
    custom_alarm_status: Optional[int] = None   # 0x01=alarm, 0x00=normal
    custom_ecu_ignition: Optional[int] = None   # 0x01=prohibited, 0x00=allowed


@dataclass
class LocationReport:
    alarm_flag: int
    status: int
    latitude: float         # degrees
    longitude: float        # degrees
    altitude: int           # meters
    speed: float            # km/h
    direction: int          # 0-359 degrees
    timestamp: datetime
    additional: LocationAdditionalInfo = field(default_factory=LocationAdditionalInfo)

    @property
    def is_gps_valid(self) -> bool:
        return bool(self.status & (1 << 1))  # bit 1 = lat/lng valid

    @property
    def is_ignition_on(self) -> bool:
        return bool(self.status & (1 << 0))  # bit 0 = ACC on


@dataclass
class JT808Message:
    header: JT808Header
    body: bytes
    raw: bytes = b""


# ─── Escape / Unescape ────────────────────────────────────────────────────────

def escape(data: bytes) -> bytes:
    """Escape 0x7E → 0x7D 0x02 and 0x7D → 0x7D 0x01"""
    result = bytearray()
    for b in data:
        if b == FLAG:
            result += bytes([ESC, 0x02])
        elif b == ESC:
            result += bytes([ESC, 0x01])
        else:
            result.append(b)
    return bytes(result)


def unescape(data: bytes) -> bytes:
    """Reverse escape: 0x7D 0x02 → 0x7E, 0x7D 0x01 → 0x7D"""
    result = bytearray()
    i = 0
    while i < len(data):
        if data[i] == ESC and i + 1 < len(data):
            if data[i + 1] == 0x02:
                result.append(FLAG)
            elif data[i + 1] == 0x01:
                result.append(ESC)
            else:
                result.append(data[i])
                result.append(data[i + 1])
            i += 2
        else:
            result.append(data[i])
            i += 1
    return bytes(result)


# ─── Checksum ─────────────────────────────────────────────────────────────────

def checksum(data: bytes) -> int:
    """XOR of all bytes"""
    result = 0
    for b in data:
        result ^= b
    return result


# ─── BCD Helpers ──────────────────────────────────────────────────────────────

def bcd_encode(s: str, length: int) -> bytes:
    """Encode numeric string to BCD bytes, right-aligned, zero-padded"""
    s = s.zfill(length * 2)
    return bytes(int(s[i:i+2], 16) for i in range(0, len(s), 2))


def bcd_decode(data: bytes) -> str:
    """Decode BCD bytes to numeric string"""
    return ''.join(f'{b:02X}' for b in data)


def bcd_decode_time(data: bytes) -> datetime:
    """Decode 6-byte BCD time YY-MM-DD-HH-MM-SS → datetime (UTC)"""
    s = bcd_decode(data)
    year   = int(s[0:2]) + 2000
    month  = int(s[2:4])
    day    = int(s[4:6])
    hour   = int(s[6:8])
    minute = int(s[8:10])
    second = int(s[10:12])
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def bcd_encode_time(dt: datetime) -> bytes:
    """Encode datetime → 6-byte BCD"""
    s = dt.strftime('%y%m%d%H%M%S')
    return bcd_encode(s, 6)


# ─── Frame Framing ────────────────────────────────────────────────────────────

def frame(inner: bytes) -> bytes:
    """Wrap inner bytes with FLAG, escaping, and checksum"""
    cs = checksum(inner)
    escaped = escape(inner + bytes([cs]))
    return bytes([FLAG]) + escaped + bytes([FLAG])


def extract_frames(buf: bytes):
    """
    Extract complete JT/T 808 frames from a byte buffer.
    Returns (list_of_frame_payloads, remaining_buffer)
    Each payload is the raw unescaped content between the flags (excl. flags).
    """
    frames = []
    while True:
        start = buf.find(FLAG)
        if start == -1:
            break
        end = buf.find(FLAG, start + 1)
        if end == -1:
            buf = buf[start:]
            break
        raw_frame = buf[start+1:end]
        buf = buf[end:]          # keep the end FLAG as potential next start
        if len(raw_frame) == 0:
            buf = buf[1:]
            continue
        payload = unescape(raw_frame)
        frames.append(payload)
    return frames, buf


# ─── Header Encode / Decode ───────────────────────────────────────────────────

def encode_header(header: JT808Header, body_len: int) -> bytes:
    """Encode message header (13 bytes for non-subpackage)"""
    props = body_len & 0x03FF
    props |= (header.encrypt_type & 0x07) << 10
    if header.subpackage:
        props |= (1 << 13)

    phone_bcd = bcd_encode(header.phone, 6)
    hdr = struct.pack('>HH', header.msg_id, props)
    hdr += phone_bcd
    hdr += struct.pack('>H', header.serial_no)

    if header.subpackage:
        hdr += struct.pack('>HH', header.total_packets, header.packet_no)

    return hdr


def decode_header(data: bytes) -> tuple[JT808Header, int]:
    """
    Parse header from raw (unescaped, no flags) bytes.
    Returns (JT808Header, offset_after_header).
    """
    msg_id, props = struct.unpack_from('>HH', data, 0)
    body_len    = props & 0x03FF
    encrypt     = (props >> 10) & 0x07
    subpackage  = bool(props & (1 << 13))

    phone_bcd   = data[4:10]
    phone       = bcd_decode(phone_bcd)
    serial_no,  = struct.unpack_from('>H', data, 10)

    offset = 12
    total_packets = packet_no = 0
    if subpackage:
        total_packets, packet_no = struct.unpack_from('>HH', data, 12)
        offset = 16

    hdr = JT808Header(
        msg_id=msg_id,
        phone=phone,
        serial_no=serial_no,
        body_length=body_len,
        encrypt_type=encrypt,
        subpackage=subpackage,
        total_packets=total_packets,
        packet_no=packet_no,
    )
    return hdr, offset


# ─── Message Build / Parse ────────────────────────────────────────────────────

def build_message(msg_id: int, phone: str, serial_no: int, body: bytes) -> bytes:
    """Build a complete framed JT/T 808 message"""
    hdr = JT808Header(msg_id=msg_id, phone=phone, serial_no=serial_no)
    header_bytes = encode_header(hdr, len(body))
    inner = header_bytes + body
    return frame(inner)


def parse_message(payload: bytes) -> Optional[JT808Message]:
    """
    Parse an unescaped payload (without FLAG bytes).
    Validates checksum. Returns JT808Message or None.
    """
    if len(payload) < 13:
        return None
    # Last byte is checksum
    cs_expected = payload[-1]
    cs_actual   = checksum(payload[:-1])
    if cs_expected != cs_actual:
        return None

    header, offset = decode_header(payload)
    body = payload[offset:-1]  # exclude checksum
    return JT808Message(header=header, body=body, raw=payload)


# ─── Location Report Parser ───────────────────────────────────────────────────

def parse_location_report(body: bytes) -> LocationReport:
    """Parse message body of 0x0200 Location Information Report"""
    alarm_flag, status, lat_raw, lng_raw, alt, spd, direction = struct.unpack_from('>IIIIHHH', body, 0)
    time_bcd = body[22:28]
    timestamp = bcd_decode_time(time_bcd)

    # Convert raw values
    latitude  = lat_raw / 1_000_000.0
    longitude = lng_raw / 1_000_000.0
    # bit 4 of status: south latitude
    if status & (1 << 4):
        latitude = -latitude
    # bit 5 of status: west longitude
    if status & (1 << 5):
        longitude = -longitude

    speed = spd / 10.0   # 1/10 km/h → km/h

    additional = LocationAdditionalInfo()
    offset = 28

    while offset + 2 <= len(body):
        info_id     = body[offset]
        info_len    = body[offset + 1]
        info_data   = body[offset + 2: offset + 2 + info_len]
        offset     += 2 + info_len

        if info_id == ADD_INFO_MILEAGE and info_len == 4:
            additional.mileage, = struct.unpack('>I', info_data)
        elif info_id == ADD_INFO_FUEL and info_len == 2:
            additional.fuel, = struct.unpack('>H', info_data)
        elif info_id == ADD_INFO_SPEED_CAN and info_len == 2:
            additional.speed_can, = struct.unpack('>H', info_data)
        elif info_id == ADD_INFO_ALARM_ID and info_len == 2:
            additional.alarm_id, = struct.unpack('>H', info_data)
        elif info_id == ADD_INFO_EXT_SIGNAL and info_len == 4:
            additional.ext_signal, = struct.unpack('>I', info_data)
        elif info_id == ADD_INFO_IO_STATUS and info_len == 2:
            additional.io_status, = struct.unpack('>H', info_data)
        elif info_id == ADD_INFO_ANALOG and info_len == 4:
            additional.analog, = struct.unpack('>I', info_data)
        elif info_id == ADD_INFO_SIGNAL_STRENGTH and info_len == 1:
            additional.signal_strength = info_data[0]
        elif info_id == ADD_INFO_GNSS_SATS and info_len == 1:
            additional.gnss_satellites = info_data[0]
        elif info_id == ADD_INFO_CUSTOM and info_len >= 2:
            # Table 2-3: custom additional info
            additional.custom_alarm_status = info_data[0]
            additional.custom_ecu_ignition = info_data[1]

    return LocationReport(
        alarm_flag=alarm_flag,
        status=status,
        latitude=latitude,
        longitude=longitude,
        altitude=alt,
        speed=speed,
        direction=direction,
        timestamp=timestamp,
        additional=additional,
    )


# ─── Response Builders ────────────────────────────────────────────────────────

def build_platform_general_response(
    phone: str, serial_no: int,
    resp_serial: int, resp_msg_id: int, result: int = 0
) -> bytes:
    """Build 0x8001 Platform General Response"""
    body = struct.pack('>HHB', resp_serial, resp_msg_id, result)
    return build_message(MSG_PLATFORM_GENERAL_RESP, phone, serial_no, body)


def build_terminal_register_response(
    phone: str, serial_no: int,
    resp_serial: int, result: int, auth_code: str = ""
) -> bytes:
    """Build 0x8100 Terminal Registration Response"""
    body = struct.pack('>HB', resp_serial, result)
    if result == 0:
        body += auth_code.encode('gbk')
    return build_message(MSG_TERMINAL_REGISTER_RESP, phone, serial_no, body)


def build_query_server_time_response(
    phone: str, serial_no: int, resp_serial: int
) -> bytes:
    """Build 0x8004 Query Server Time Response"""
    now = datetime.now(timezone.utc)
    body = bcd_encode_time(now)
    return build_message(MSG_QUERY_SERVER_TIME_RESP, phone, serial_no, body)


def build_terminal_control(
    phone: str, serial_no: int, command_word: int, params: bytes = b""
) -> bytes:
    """Build 0x8105 Terminal Control Command"""
    body = struct.pack('>H', command_word) + params
    return build_message(MSG_TERMINAL_CONTROL, phone, serial_no, body)


def build_set_params(
    phone: str, serial_no: int, params: Dict[int, bytes]
) -> bytes:
    """Build 0x8103 Set Terminal Parameters"""
    body = bytes([len(params)])
    for param_id, value in params.items():
        body += struct.pack('>IB', param_id, len(value)) + value
    return build_message(MSG_SET_PARAMS, phone, serial_no, body)


def build_query_params(
    phone: str, serial_no: int, param_ids: list[int]
) -> bytes:
    """Build 0x8106 Query Specific Terminal Parameters"""
    body = bytes([len(param_ids)])
    for pid in param_ids:
        body += struct.pack('>I', pid)
    return build_message(MSG_QUERY_PARAMS, phone, serial_no, body)
