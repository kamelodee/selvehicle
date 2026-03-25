"""
Seed the database with default test data.
Run: python seed.py
"""

from datetime import datetime, timezone, timedelta
import random
from dotenv import load_dotenv
load_dotenv()

from passlib.context import CryptContext
from jt808.models import create_tables, SessionLocal, Terminal, LocationRecord, CommandLog, ParameterLog, User

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

TERMINALS = [
    dict(
        phone="13800000001",
        auth_code="AUTH001",
        authenticated=True,
        last_ip="192.168.1.101",
        province_id=11,
        city_id=1101,
        manufacturer="YUWEI",
        device_model="GT06N",
        device_id="DEV00000001",
        plate_color=2,
        plate_no="京A12345",
    ),
    dict(
        phone="13800000002",
        auth_code="AUTH002",
        authenticated=True,
        last_ip="192.168.1.102",
        province_id=31,
        city_id=3101,
        manufacturer="CONCOX",
        device_model="TR06",
        device_id="DEV00000002",
        plate_color=1,
        plate_no="沪B67890",
    ),
    dict(
        phone="13800000003",
        auth_code=None,
        authenticated=False,
        last_ip=None,
        province_id=44,
        city_id=4401,
        manufacturer="JIMI",
        device_model="JM-VG01",
        device_id="DEV00000003",
        plate_color=1,
        plate_no="粤C11111",
    ),
]

# Rough starting coords (lat, lon) per terminal — Beijing, Shanghai, Guangzhou
START_COORDS = [
    (39.9042, 116.4074),
    (31.2304, 121.4737),
    (23.1291, 113.2644),
]


def random_location(phone, base_lat, base_lon, minutes_ago, idx):
    now = datetime.now(timezone.utc)
    received = now - timedelta(minutes=minutes_ago)
    device_t = received - timedelta(seconds=2)
    lat = base_lat + random.uniform(-0.05, 0.05)
    lon = base_lon + random.uniform(-0.05, 0.05)
    return LocationRecord(
        phone=phone,
        received_at=received,
        device_time=device_t,
        latitude=round(lat, 6),
        longitude=round(lon, 6),
        altitude=random.randint(10, 200),
        speed=round(random.uniform(0, 120), 1),
        direction=random.randint(0, 359),
        alarm_flag=0,
        status=1,
        gps_valid=True,
        ignition_on=random.choice([True, False]),
        mileage=random.randint(1000, 500000),
        fuel=random.randint(0, 800),
        signal_strength=random.randint(10, 31),
        gnss_satellites=random.randint(4, 12),
        alarm_status=0,
        ecu_ignition=1,
    )


def seed():
    create_tables()
    db = SessionLocal()
    try:
        seeded = 0
        now = datetime.now(timezone.utc)

        # Default admin user
        if not db.query(User).filter_by(username="admin").first():
            db.add(User(username="admin", hashed_pw=_pwd_ctx.hash("admin123")))
            db.commit()
            print("  created user: admin / admin123")

        for i, tdata in enumerate(TERMINALS):
            existing = db.query(Terminal).filter_by(phone=tdata["phone"]).first()
            if existing:
                print(f"  terminal {tdata['phone']} already exists — skipping")
                continue

            t = Terminal(
                **tdata,
                registered_at=now - timedelta(days=random.randint(1, 30)),
                last_seen_at=now - timedelta(minutes=random.randint(1, 60)) if tdata["authenticated"] else None,
            )
            db.add(t)
            db.flush()

            # 20 location records per authenticated terminal
            if tdata["authenticated"]:
                base_lat, base_lon = START_COORDS[i]
                for j in range(20):
                    db.add(random_location(tdata["phone"], base_lat, base_lon, minutes_ago=j * 5, idx=j))

                # A couple of command logs
                db.add(CommandLog(
                    phone=tdata["phone"],
                    sent_at=now - timedelta(minutes=30),
                    msg_id=0x8105,
                    command_word=0x01,
                    params={"command": "power_on"},
                    serial_no=1,
                    acked=True,
                    ack_result=0,
                    acked_at=now - timedelta(minutes=29),
                ))
                db.add(CommandLog(
                    phone=tdata["phone"],
                    sent_at=now - timedelta(minutes=10),
                    msg_id=0x8105,
                    command_word=0x02,
                    params={"command": "power_off"},
                    serial_no=2,
                    acked=False,
                ))

                # A parameter log
                db.add(ParameterLog(
                    phone=tdata["phone"],
                    direction="set",
                    params={"0xFF01": "01", "0xFF02": "00"},
                    serial_no=3,
                ))

            seeded += 1
            print(f"  seeded terminal {tdata['phone']}")

        db.commit()
        print(f"\nDone. {seeded} terminal(s) added.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
