"""
JT/T 808-2019  Frame Codec
──────────────────────────────────────────────────────────────────────────────
Frame layout (after removing 0x7E markers and un-escaping):

  [ Header (12 B) ][ Body (0-N B) ][ Checksum (1 B) ]

Header:
  Message ID       2 B  big-endian uint16
  Body Properties  2 B  bits[0-9]=body length, bit13=sub-packet flag
  Phone Number     6 B  BCD (12 digits, left-padded with 0)
  Serial Number    2 B  big-endian uint16

Sub-packet item (present only when bit13 of Body Properties is set):
  Total Packets    2 B
  Packet Number    2 B

Escape rules (applied AFTER building, BEFORE sending):
  0x7E → 0x7D 0x02
  0x7D → 0x7D 0x01
"""

import struct
from dataclasses import dataclass
from typing import Optional

FRAME_MARKER = 0x7E
ESCAPE_CHAR  = 0x7D


# ── Helpers ────────────────────────────────────────────────────────────────────

def bcd_encode(phone: str) -> bytes:
    """12-digit phone string → 6 bytes BCD."""
    s = phone.zfill(12)[:12]
    return bytes(int(s[i:i+2], 16) for i in range(0, 12, 2))


def bcd_decode(b: bytes) -> str:
    """6 bytes BCD → 12-char phone string."""
    return "".join(f"{byte:02x}" for byte in b)


def xor_checksum(data: bytes) -> int:
    cs = 0
    for b in data:
        cs ^= b
    return cs


def unescape(data: bytes) -> bytes:
    """Remove JT808 byte-stuffing."""
    result = bytearray()
    i = 0
    while i < len(data):
        if data[i] == ESCAPE_CHAR and i + 1 < len(data):
            nxt = data[i + 1]
            if nxt == 0x02:
                result.append(FRAME_MARKER)
            elif nxt == 0x01:
                result.append(ESCAPE_CHAR)
            else:
                # Unknown escape – pass through both bytes
                result.append(ESCAPE_CHAR)
                result.append(nxt)
            i += 2
        else:
            result.append(data[i])
            i += 1
    return bytes(result)


def escape(data: bytes) -> bytes:
    """Apply JT808 byte-stuffing."""
    result = bytearray()
    for b in data:
        if b == FRAME_MARKER:
            result += b"\x7d\x02"
        elif b == ESCAPE_CHAR:
            result += b"\x7d\x01"
        else:
            result.append(b)
    return bytes(result)


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class JT808Frame:
    msg_id:        int
    phone:         str          # 12-digit BCD string
    serial_no:     int
    body:          bytes
    sub_packet:    bool  = False
    total_packets: int   = 0
    packet_no:     int   = 0


# ── Parse ──────────────────────────────────────────────────────────────────────

def parse_frame(raw: bytes) -> Optional[JT808Frame]:
    """
    Parse a fully de-escaped frame (without the 0x7E markers).
    Returns None if the frame is too short or the checksum fails.
    """
    if len(raw) < 13:                      # header(12) + checksum(1)
        return None

    # Verify checksum
    if xor_checksum(raw[:-1]) != raw[-1]:
        return None

    msg_id  = struct.unpack_from(">H", raw, 0)[0]
    props   = struct.unpack_from(">H", raw, 2)[0]
    body_len        = props & 0x03FF
    sub_packet_flag = (props >> 13) & 1
    phone           = bcd_decode(raw[4:10])
    serial_no       = struct.unpack_from(">H", raw, 10)[0]

    offset = 12
    total_packets = packet_no = 0
    if sub_packet_flag:
        if len(raw) < 17:
            return None
        total_packets, packet_no = struct.unpack_from(">HH", raw, 12)
        offset = 16

    body = raw[offset: offset + body_len]
    if len(body) < body_len:
        return None

    return JT808Frame(
        msg_id        = msg_id,
        phone         = phone,
        serial_no     = serial_no,
        body          = body,
        sub_packet    = bool(sub_packet_flag),
        total_packets = total_packets,
        packet_no     = packet_no,
    )


# ── Build ──────────────────────────────────────────────────────────────────────

def build_frame(msg_id: int, body: bytes, phone: str, serial_no: int) -> bytes:
    """
    Assemble a complete JT808 wire frame (with 0x7E markers and escaping).
    """
    body_len = len(body)
    props    = body_len & 0x03FF       # no encryption, no sub-packet
    header   = (
        struct.pack(">HH", msg_id, props)
        + bcd_encode(phone)
        + struct.pack(">H", serial_no)
    )
    payload = header + body
    cs      = xor_checksum(payload)
    return bytes([FRAME_MARKER]) + escape(payload + bytes([cs])) + bytes([FRAME_MARKER])
