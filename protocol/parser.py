"""
Parsers for terminal → platform messages.
"""

import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional


# ── Location Report (0x0200) ──────────────────────────────────────────────────

@dataclass
class LocationReport:
    # Basic info
    alarm_flags:     int
    status:          int
    latitude:        float        # decimal degrees (+N / -S)
    longitude:       float        # decimal degrees (+E / -W)
    altitude:        int          # metres
    speed:           float        # km/h
    direction:       int          # 0-359 degrees
    time:            datetime     # UTC

    # Raw additional info items  {info_id: raw_bytes}
    additional: Dict[int, bytes] = field(default_factory=dict)

    # Parsed standard additional items
    mileage:          Optional[float] = None   # km  (0x01)
    fuel_level:       Optional[float] = None   # L   (0x02)
    can_speed:        Optional[float] = None   # km/h (0x03)
    signal_strength:  Optional[int]   = None   # (0x30)
    satellites:       Optional[int]   = None   # (0x31)

    # Custom additional (0xEE)  — Table 2-3
    alarm_status:     Optional[int]   = None   # 0x00 / 0x01
    ecu_ignition:     Optional[int]   = None   # 0x00 / 0x01

    def to_dict(self) -> dict:
        return {
            "alarm_flags":    self.alarm_flags,
            "status":         self.status,
            "latitude":       self.latitude,
            "longitude":      self.longitude,
            "altitude":       self.altitude,
            "speed":          self.speed,
            "direction":      self.direction,
            "time":           self.time.isoformat(),
            "mileage":        self.mileage,
            "fuel_level":     self.fuel_level,
            "can_speed":      self.can_speed,
            "signal_strength": self.signal_strength,
            "satellites":     self.satellites,
            "alarm_status":   self.alarm_status,
            "ecu_ignition":   self.ecu_ignition,
        }


def _bcd6_to_datetime(b: bytes) -> datetime:
    """6-byte BCD  YYMMDDhhmmss  → UTC datetime."""
    s = "".join(f"{byte:02x}" for byte in b)
    try:
        return datetime.strptime("20" + s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def parse_location_report(body: bytes) -> LocationReport:
    """
    Parse message body of 0x0200 Location Information Report.

    Basic structure (28 bytes):
      Alarm Flag   4 B  DWORD
      Status       4 B  DWORD
      Latitude     4 B  DWORD  (1/10^6 degrees)
      Longitude    4 B  DWORD  (1/10^6 degrees)
      Altitude     2 B  WORD   (metres)
      Speed        2 B  WORD   (1/10 km/h)
      Direction    2 B  WORD   (degrees)
      Time         6 B  BCD    (YYMMDDhhmmss UTC)
    Followed by additional info items.
    """
    if len(body) < 28:
        raise ValueError(f"Location body too short: {len(body)} < 28")

    alarm_flags = struct.unpack_from(">I", body, 0)[0]
    status      = struct.unpack_from(">I", body, 4)[0]
    lat_raw     = struct.unpack_from(">I", body, 8)[0]
    lon_raw     = struct.unpack_from(">I", body, 12)[0]
    altitude    = struct.unpack_from(">H", body, 16)[0]
    speed_raw   = struct.unpack_from(">H", body, 18)[0]
    direction   = struct.unpack_from(">H", body, 20)[0]
    time_bcd    = body[22:28]

    lat = lat_raw / 1_000_000.0
    lon = lon_raw / 1_000_000.0
    # Status bit 2 → South;  bit 3 → West
    if (status >> 2) & 1:
        lat = -lat
    if (status >> 3) & 1:
        lon = -lon

    report = LocationReport(
        alarm_flags = alarm_flags,
        status      = status,
        latitude    = lat,
        longitude   = lon,
        altitude    = altitude,
        speed       = speed_raw / 10.0,
        direction   = direction,
        time        = _bcd6_to_datetime(time_bcd),
    )

    # ── Additional information items ──────────────────────────────────────────
    offset = 28
    while offset + 2 <= len(body):
        info_id  = body[offset]
        info_len = body[offset + 1]
        offset  += 2

        if offset + info_len > len(body):
            break  # truncated — stop parsing extras

        info_data = body[offset: offset + info_len]
        report.additional[info_id] = info_data

        if info_id == 0x01 and info_len >= 4:
            report.mileage = struct.unpack_from(">I", info_data)[0] / 10.0

        elif info_id == 0x02 and info_len >= 2:
            report.fuel_level = struct.unpack_from(">H", info_data)[0] / 10.0

        elif info_id == 0x03 and info_len >= 2:
            report.can_speed = struct.unpack_from(">H", info_data)[0] / 10.0

        elif info_id == 0x30 and info_len >= 1:
            report.signal_strength = info_data[0]

        elif info_id == 0x31 and info_len >= 1:
            report.satellites = info_data[0]

        elif info_id == 0xEE and info_len >= 2:
            # Table 2-3 custom additional info
            report.alarm_status = info_data[0]   # 0x01=alarm / 0x00=normal
            report.ecu_ignition = info_data[1]   # 0x01=prohibited / 0x00=allowed

        offset += info_len

    return report


# ── Terminal Registration (0x0100) ─────────────────────────────────────────────

@dataclass
class RegistrationInfo:
    province_id:   int
    city_id:       int
    manufacturer:  str   # 5 bytes
    device_type:   str   # up to 20 bytes
    device_id:     str   # 7 bytes
    plate_color:   int
    plate_no:      str


def parse_registration(body: bytes) -> RegistrationInfo:
    if len(body) < 37:
        raise ValueError("Registration body too short")

    province_id  = struct.unpack_from(">H", body, 0)[0]
    city_id      = struct.unpack_from(">H", body, 2)[0]
    manufacturer = body[4:9].decode("gbk", errors="replace").rstrip("\x00")
    device_type  = body[9:29].decode("gbk", errors="replace").rstrip("\x00")
    device_id    = body[29:36].decode("gbk", errors="replace").rstrip("\x00")
    plate_color  = body[36]
    plate_no     = body[37:].decode("gbk", errors="replace").rstrip("\x00") if len(body) > 37 else ""

    return RegistrationInfo(
        province_id  = province_id,
        city_id      = city_id,
        manufacturer = manufacturer,
        device_type  = device_type,
        device_id    = device_id,
        plate_color  = plate_color,
        plate_no     = plate_no,
    )


# ── General Response (0x0001) ─────────────────────────────────────────────────

@dataclass
class TerminalGeneralResponse:
    response_serial: int
    response_msg_id: int
    result:          int


def parse_terminal_general_response(body: bytes) -> TerminalGeneralResponse:
    if len(body) < 5:
        raise ValueError("General response body too short")
    resp_serial, resp_id, result = struct.unpack_from(">HHB", body, 0)
    return TerminalGeneralResponse(resp_serial, resp_id, result)
