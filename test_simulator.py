"""
JT/T 808-2019 Terminal Simulator
Simulates a vehicle terminal connecting to the server for local testing.

Usage:
    python test_simulator.py [--host 127.0.0.1] [--port 8808]

What it does:
    1. Connects to the server
    2. Sends Terminal Registration (0x0100)
    3. Authenticates with the returned auth code (0x0102)
    4. Sends heartbeats (0x0002) every 5 seconds
    5. Sends Location Reports (0x0200) every 8 seconds with GPS drift
    6. Handles server responses and prints them
"""

import asyncio
import argparse
import logging
import struct
import random
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from jt808.protocol import (
    build_message, parse_message, extract_frames,
    bcd_encode, bcd_encode_time,
    MSG_TERMINAL_REGISTER, MSG_TERMINAL_AUTH,
    MSG_HEARTBEAT, MSG_LOCATION_REPORT,
    MSG_PLATFORM_GENERAL_RESP, MSG_TERMINAL_REGISTER_RESP,
    MSG_QUERY_SERVER_TIME, MSG_QUERY_SERVER_TIME_RESP,
    ADD_INFO_MILEAGE, ADD_INFO_FUEL, ADD_INFO_SIGNAL_STRENGTH,
    ADD_INFO_GNSS_SATS, ADD_INFO_CUSTOM,
)
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("simulator")

# ── Simulated vehicle config ───────────────────────────────────────────────────
PHONE       = "013244567890"   # 12-digit BCD phone (6 bytes) — change to your SIM number
PLATE_NO    = "GH-EV-001"
DEVICE_ID   = "TEST_TERM_001"

# Accra, Ghana base position
BASE_LAT    = 5.603717
BASE_LNG    = -0.186964


class TerminalSimulator:
    def __init__(self, host: str, port: int):
        self.host     = host
        self.port     = port
        self.phone    = PHONE
        self.serial   = 0
        self.auth_code = ""
        self.authenticated = False
        self.reader   = None
        self.writer   = None
        self.buf      = b""
        self.mileage  = 12000 * 10   # 1200.0 km in 1/10 km units
        self.fuel     = 450          # 45.0 L in 1/10 L units
        self.lat      = BASE_LAT
        self.lng      = BASE_LNG
        self.speed    = 0.0

    def next_serial(self) -> int:
        self.serial = (self.serial + 1) & 0xFFFF
        return self.serial

    # ── Frame helpers ─────────────────────────────────────────────────────────

    async def send(self, data: bytes):
        self.writer.write(data)
        await self.writer.drain()

    async def recv_message(self, timeout=10):
        """Read until we get at least one complete frame"""
        while True:
            try:
                chunk = await asyncio.wait_for(self.reader.read(4096), timeout=timeout)
            except asyncio.TimeoutError:
                return None
            if not chunk:
                return None
            self.buf += chunk
            frames, self.buf = extract_frames(self.buf)
            for payload in frames:
                msg = parse_message(payload)
                if msg:
                    return msg

    # ── Message builders ──────────────────────────────────────────────────────

    def build_registration(self) -> bytes:
        province_id = 440          # Guangdong (placeholder)
        city_id     = 100
        manufacturer = b"ACME\x00"                    # 5 bytes
        device_model = DEVICE_ID.encode('gbk').ljust(20, b'\x00')[:20]
        device_id    = b"SN0000000000000000000"[:20]
        plate_color  = 1           # blue
        plate_no     = PLATE_NO.encode('gbk')

        body = (
            struct.pack('>HH', province_id, city_id)
            + manufacturer
            + device_model
            + device_id
            + bytes([plate_color])
            + plate_no
        )
        return build_message(MSG_TERMINAL_REGISTER, self.phone, self.next_serial(), body)

    def build_auth(self, auth_code: str) -> bytes:
        body = auth_code.encode('gbk')
        return build_message(MSG_TERMINAL_AUTH, self.phone, self.next_serial(), body)

    def build_heartbeat(self) -> bytes:
        return build_message(MSG_HEARTBEAT, self.phone, self.next_serial(), b"")

    def build_location(self, alarm: bool = False, ignition: bool = True) -> bytes:
        alarm_flag = 0x00000001 if alarm else 0x00000000

        # Status bits
        status = 0
        status |= (1 << 0)   # ACC on (ignition)
        status |= (1 << 1)   # GPS located
        # bit 4 = S lat (0 = N), bit 5 = W lng (1 = W)
        if self.lat < 0:
            status |= (1 << 4)
        if self.lng < 0:
            status |= (1 << 5)

        lat_raw = int(abs(self.lat) * 1_000_000)
        lng_raw = int(abs(self.lng) * 1_000_000)
        alt     = 50           # 50 m
        spd     = int(self.speed * 10)
        direction = random.randint(0, 359)
        ts      = datetime.now(timezone.utc)

        body = struct.pack('>IIIIHHH',
            alarm_flag, status,
            lat_raw, lng_raw,
            alt, spd, direction
        ) + bcd_encode_time(ts)

        # Additional info items
        body += bytes([ADD_INFO_MILEAGE, 4]) + struct.pack('>I', self.mileage)
        body += bytes([ADD_INFO_FUEL, 2])    + struct.pack('>H', self.fuel)
        body += bytes([ADD_INFO_SIGNAL_STRENGTH, 1, random.randint(15, 31)])
        body += bytes([ADD_INFO_GNSS_SATS,      1, random.randint(8, 14)])

        # Custom 0xEE — alarm status + ECU ignition
        custom_payload = bytes([
            0x01 if alarm else 0x00,          # alarm status
            0x00,                              # ECU ignition allowed
        ])
        body += bytes([ADD_INFO_CUSTOM, len(custom_payload)]) + custom_payload

        return build_message(MSG_LOCATION_REPORT, self.phone, self.next_serial(), body)

    # ── Simulation loop ───────────────────────────────────────────────────────

    def _drift_position(self):
        """Simulate slow vehicle movement"""
        self.lat   += random.uniform(-0.0003, 0.0003)
        self.lng   += random.uniform(-0.0003, 0.0003)
        self.speed  = random.uniform(0, 80)
        self.mileage += random.randint(0, 5)
        self.fuel    = max(0, self.fuel - random.randint(0, 2))

    async def run(self):
        log.info(f"Connecting to {self.host}:{self.port} as phone={self.phone}")
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        log.info("Connected!")

        # 1. Register
        log.info("→ Sending Registration (0x0100)")
        await self.send(self.build_registration())
        resp = await self.recv_message()
        if not resp or resp.header.msg_id != MSG_TERMINAL_REGISTER_RESP:
            log.error("No registration response — server may not be running")
            return

        result = resp.body[2]   # 0=success
        if result == 0:
            self.auth_code = resp.body[3:].decode('gbk', errors='replace')
            log.info(f"← Registration OK  auth_code={self.auth_code!r}")
        else:
            log.error(f"← Registration FAILED result={result}")
            return

        # 2. Authenticate
        log.info("→ Sending Authentication (0x0102)")
        await self.send(self.build_auth(self.auth_code))
        resp = await self.recv_message()
        if resp and resp.header.msg_id == MSG_PLATFORM_GENERAL_RESP:
            ack_result = resp.body[4]
            if ack_result == 0:
                self.authenticated = True
                log.info("← Authenticated OK")
            else:
                log.error(f"← Authentication FAILED result={ack_result}")
                return

        # 3. Main loop — heartbeats + location reports
        log.info("─── Entering main loop (Ctrl+C to stop) ───")
        hb_counter  = 0
        loc_counter = 0
        alarm_sent  = False

        while True:
            await asyncio.sleep(5)
            hb_counter += 1

            # Heartbeat every 5 seconds
            log.info(f"→ Heartbeat #{hb_counter}")
            await self.send(self.build_heartbeat())

            # Location every 2 heartbeats (~10 seconds)
            if hb_counter % 2 == 0:
                loc_counter += 1
                self._drift_position()

                # Simulate an alarm on the 3rd location report
                trigger_alarm = (loc_counter == 3 and not alarm_sent)
                if trigger_alarm:
                    alarm_sent = True
                    log.warning(f"→ Location Report #{loc_counter} *** WITH ALARM ***")
                else:
                    log.info(f"→ Location Report #{loc_counter}  lat={self.lat:.6f} lng={self.lng:.6f} spd={self.speed:.1f}km/h")

                await self.send(self.build_location(alarm=trigger_alarm))

            # Drain any incoming messages (ACKs, commands from server)
            try:
                incoming = await asyncio.wait_for(self.recv_message(timeout=0.5), timeout=0.5)
                if incoming:
                    self._handle_incoming(incoming)
            except asyncio.TimeoutError:
                pass

    def _handle_incoming(self, msg):
        mid = msg.header.msg_id
        if mid == MSG_PLATFORM_GENERAL_RESP:
            log.info(f"← Platform ACK for serial={struct.unpack_from('>H', msg.body, 0)[0]}")
        elif mid == 0x8105:
            cmd_word = struct.unpack_from('>H', msg.body, 0)[0]
            cmd_name = {100:"POWER_ON", 101:"POWER_OFF", 102:"START_ALARM", 103:"STOP_ALARM"}.get(cmd_word, str(cmd_word))
            log.warning(f"← CONTROL COMMAND received: {cmd_name} (word={cmd_word})")
        elif mid == 0x8103:
            log.info(f"← SET PARAMS received  body_hex={msg.body.hex()}")
        elif mid == 0x8106:
            log.info(f"← QUERY PARAMS received body_hex={msg.body.hex()}")
        elif mid == 0x8004:
            log.info(f"← Server time response")
        else:
            log.info(f"← msg_id=0x{mid:04X}  body_hex={msg.body.hex()[:40]}")


async def main():
    parser = argparse.ArgumentParser(description="JT/T 808 Terminal Simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8808)
    args = parser.parse_args()

    sim = TerminalSimulator(args.host, args.port)
    try:
        await sim.run()
    except KeyboardInterrupt:
        log.info("Simulator stopped")
    except ConnectionRefusedError:
        log.error(f"Could not connect to {args.host}:{args.port} — is the server running?")


if __name__ == "__main__":
    asyncio.run(main())
