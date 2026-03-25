"""
Database models and session management.
Defaults to SQLite for dev; set DATABASE_URL env var for MySQL/PostgreSQL in production.

MySQL example:
    DATABASE_URL=mysql+pymysql://root:password@localhost:3306/vehi_db
"""

import os
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    DateTime, Boolean, BigInteger, Text, JSON
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./jt808.db")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,       # reconnect after dropped connections
        pool_recycle=3600,        # recycle connections every hour (MySQL wait_timeout)
        pool_size=10,
        max_overflow=20,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    """Admin users for the dashboard"""
    __tablename__ = "users"

    id           = Column(Integer, primary_key=True, index=True)
    username     = Column(String(64), unique=True, index=True, nullable=False)
    hashed_pw    = Column(String(128), nullable=False)
    created_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Terminal(Base):
    """Registered vehicle terminals"""
    __tablename__ = "terminals"

    id            = Column(Integer, primary_key=True, index=True)
    phone         = Column(String(20), unique=True, index=True, nullable=False)
    auth_code     = Column(String(64), nullable=True)
    authenticated = Column(Boolean, default=False)
    registered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen_at  = Column(DateTime(timezone=True), nullable=True)
    last_ip       = Column(String(64), nullable=True)
    province_id   = Column(Integer, nullable=True)
    city_id       = Column(Integer, nullable=True)
    manufacturer  = Column(String(20), nullable=True)   # GBK, up to 5 chars × 3 bytes utf8mb4
    device_model  = Column(String(60), nullable=True)
    device_id     = Column(String(60), nullable=True)
    plate_color   = Column(Integer, nullable=True)
    plate_no      = Column(String(40), nullable=True)


class LocationRecord(Base):
    """Location reports from terminals (0x0200)"""
    __tablename__ = "location_records"

    id               = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    phone            = Column(String(20), index=True, nullable=False)
    received_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    device_time      = Column(DateTime(timezone=True), nullable=True)

    # Position
    latitude         = Column(Float, nullable=True)
    longitude        = Column(Float, nullable=True)
    altitude         = Column(Integer, nullable=True)    # meters
    speed            = Column(Float, nullable=True)      # km/h
    direction        = Column(Integer, nullable=True)    # degrees

    # Flags
    alarm_flag       = Column(BigInteger, default=0)
    status           = Column(BigInteger, default=0)
    gps_valid        = Column(Boolean, default=False)
    ignition_on      = Column(Boolean, default=False)

    # Additional info
    mileage          = Column(Integer, nullable=True)    # 1/10 km
    fuel             = Column(Integer, nullable=True)    # 1/10 L
    speed_can        = Column(Integer, nullable=True)    # 1/10 km/h
    signal_strength  = Column(Integer, nullable=True)
    gnss_satellites  = Column(Integer, nullable=True)
    io_status        = Column(Integer, nullable=True)
    analog           = Column(Integer, nullable=True)
    alarm_status     = Column(Integer, nullable=True)    # custom 0xEE
    ecu_ignition     = Column(Integer, nullable=True)    # custom 0xEE


class CommandLog(Base):
    """Log of control commands sent to terminals"""
    __tablename__ = "command_logs"

    id           = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    phone        = Column(String(20), index=True, nullable=False)
    sent_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    msg_id       = Column(Integer, nullable=False)       # e.g. 0x8105
    command_word = Column(Integer, nullable=True)        # for 0x8105
    params       = Column(JSON, nullable=True)
    serial_no    = Column(Integer, nullable=True)
    acked        = Column(Boolean, default=False)
    ack_result   = Column(Integer, nullable=True)
    acked_at     = Column(DateTime(timezone=True), nullable=True)


class ParameterLog(Base):
    """Log of parameter sets/queries"""
    __tablename__ = "parameter_logs"

    id           = Column(BigInteger, primary_key=True, autoincrement=True, index=True)
    phone        = Column(String(20), index=True, nullable=False)
    logged_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    direction    = Column(String(4))  # "set" or "get"
    params       = Column(JSON, nullable=False)
    serial_no    = Column(Integer, nullable=True)


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
