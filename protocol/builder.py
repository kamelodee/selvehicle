"""
Builders for platform → terminal messages.
All functions return the raw *body* bytes; wrap with codec.build_frame().
"""

import struct
from datetime import datetime, timezone
from typing import Dict, List


# ── 0x8001  Platform General Response ────────────────────────────────────────

def build_platform_general_response(
    response_serial: int,
    response_msg_id: int,
    result: int = 0,
) -> bytes:
    """
    result: 0=OK  1=Fail  2=Msg error  3=Unsupported  4=Alarm ACK
    """
    return struct.pack(">HHB", response_serial, response_msg_id, result)


# ── 0x8100  Terminal Registration Response ────────────────────────────────────

def build_registration_response(
    response_serial: int,
    result: int = 0,
    auth_code: str = "",
) -> bytes:
    """
    result: 0=OK  1=vehicle already registered  2=no such vehicle
            3=terminal already registered  4=no such terminal
    auth_code is only present when result == 0.
    """
    body = struct.pack(">HB", response_serial, result)
    if result == 0 and auth_code:
        body += auth_code.encode("ascii")
    return body


# ── 0x8004  Query Server Time Response ───────────────────────────────────────

def build_server_time_response() -> bytes:
    """6-byte BCD  YYMMDDhhmmss (UTC)."""
    now = datetime.now(timezone.utc)
    s   = now.strftime("%y%m%d%H%M%S")
    return bytes(int(s[i: i + 2]) for i in range(0, 12, 2))


# ── 0x8105  Terminal Control ──────────────────────────────────────────────────

def build_control_command(command_word: int, params: bytes = b"") -> bytes:
    """
    Custom command words (from the protocol doc):
      100  Vehicle Power On
      101  Vehicle Power Off
      102  Start Alarm
      103  Stop Alarm
    """
    return struct.pack(">H", command_word) + params


# ── 0x8103  Set Terminal Parameters ──────────────────────────────────────────

def build_set_parameters(params: Dict[int, bytes]) -> bytes:
    """
    params: {param_id (uint32): value_bytes}
    Custom parameters:
      0xFF01 BYTE  ECU ignition prohibition switch (1=prohibit, 0=allow)
      0xFF02 BYTE  Geo-fence switch (1=enabled, 0=disabled)
    """
    body = bytes([len(params)])
    for param_id, value in params.items():
        body += struct.pack(">IB", param_id, len(value)) + value
    return body


# ── 0x8106  Query Specific Terminal Parameters ────────────────────────────────

def build_query_parameters(param_ids: List[int]) -> bytes:
    """param_ids: list of uint32 parameter IDs."""
    body = bytes([len(param_ids)])
    for pid in param_ids:
        body += struct.pack(">I", pid)
    return body


# ── Area / Route management helpers ──────────────────────────────────────────

def build_set_circular_area(areas: List[dict]) -> bytes:
    """
    Each area dict:
      id (uint32), attrs (uint16), lat (float), lon (float), radius (uint32),
      optional start_time (str YYMMDDhhmmss), end_time, max_speed (uint16),
      overspeed_duration (uint8)
    """
    body = bytes([0x00, len(areas)])  # action=update, count
    for a in areas:
        lat = int(a["lat"] * 1_000_000)
        lon = int(a["lon"] * 1_000_000)
        body += struct.pack(">IHHII", a["id"], a.get("attrs", 0), lat, lon, a["radius"])
    return body


def build_delete_circular_area(area_ids: List[int]) -> bytes:
    body = bytes([len(area_ids)])
    for aid in area_ids:
        body += struct.pack(">I", aid)
    return body
