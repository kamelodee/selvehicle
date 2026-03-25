"""
FastAPI REST API
Provides admin endpoints for:
  - Viewing terminals and their status
  - Querying location history
  - Sending control commands (0x8105)
  - Setting / querying parameters (0x8103 / 0x8106)
  - Viewing command logs
"""

import os
import struct
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from passlib.context import CryptContext

from .models import (
    get_db, Terminal, LocationRecord, CommandLog, ParameterLog, User
)
from .protocol import (
    build_terminal_control, build_set_params, build_query_params,
    CMD_VEHICLE_POWER_ON, CMD_VEHICLE_POWER_OFF,
    CMD_START_ALARM, CMD_STOP_ALARM,
    PARAM_ECU_IGNITION_SWITCH, PARAM_GEOFENCE_SWITCH,
    MSG_TERMINAL_CONTROL, MSG_SET_PARAMS, MSG_QUERY_PARAMS,
)
from .handlers import conn_mgr, _srv_serial

logger = logging.getLogger(__name__)

# ─── Auth config ──────────────────────────────────────────────────────────────

SECRET_KEY  = os.getenv("SECRET_KEY", "change-me-in-production-use-a-long-random-string")
ALGORITHM   = "HS256"
TOKEN_EXPIRE_HOURS = int(os.getenv("TOKEN_EXPIRE_HOURS", "8"))

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _hash_pw(pw: str) -> str:
    return pwd_ctx.hash(pw)


def _verify_pw(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def _create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def _get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired token",
                        headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise exc
    except JWTError:
        raise exc
    user = db.query(User).filter_by(username=username).first()
    if not user:
        raise exc
    return user

app = FastAPI(
    title="Selvehicle",
    version="1.0.1",
    description="Selvehicle vehicle terminal management API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(os.path.join(_static_dir, "index.html"))


# ─── Schemas ──────────────────────────────────────────────────────────────────

class TerminalOut(BaseModel):
    phone: str
    authenticated: bool
    online: bool = False
    registered_at: Optional[datetime]
    last_seen_at: Optional[datetime]
    last_ip: Optional[str]
    plate_no: Optional[str]
    device_model: Optional[str]

    class Config:
        from_attributes = True


class LocationOut(BaseModel):
    id: int
    phone: str
    received_at: datetime
    device_time: Optional[datetime]
    latitude: Optional[float]
    longitude: Optional[float]
    altitude: Optional[int]
    speed: Optional[float]
    direction: Optional[int]
    alarm_flag: Optional[int]
    gps_valid: Optional[bool]
    ignition_on: Optional[bool]
    mileage: Optional[int]
    fuel: Optional[int]
    signal_strength: Optional[int]
    gnss_satellites: Optional[int]
    alarm_status: Optional[int]
    ecu_ignition: Optional[int]

    class Config:
        from_attributes = True


class ControlCommandRequest(BaseModel):
    command: str   # "power_on" | "power_off" | "start_alarm" | "stop_alarm"


class SetParamsRequest(BaseModel):
    ecu_ignition_prohibited: Optional[bool] = None   # PARAM_ECU_IGNITION_SWITCH
    geofence_enabled: Optional[bool] = None           # PARAM_GEOFENCE_SWITCH


class CommandLogOut(BaseModel):
    id: int
    phone: str
    sent_at: datetime
    msg_id: int
    command_word: Optional[int]
    params: Optional[Dict]
    serial_no: Optional[int]
    acked: bool
    ack_result: Optional[int]
    acked_at: Optional[datetime]

    class Config:
        from_attributes = True


COMMAND_MAP = {
    "power_on":    CMD_VEHICLE_POWER_ON,
    "power_off":   CMD_VEHICLE_POWER_OFF,
    "start_alarm": CMD_START_ALARM,
    "stop_alarm":  CMD_STOP_ALARM,
}


# ─── Auth endpoints ───────────────────────────────────────────────────────────

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


@app.post("/auth/login", response_model=TokenOut, tags=["Auth"])
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Obtain a JWT access token (username + password form)"""
    user = db.query(User).filter_by(username=form.username).first()
    if not user or not _verify_pw(form.password, user.hashed_pw):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Incorrect username or password")
    return TokenOut(access_token=_create_token(user.username))


@app.get("/auth/me", tags=["Auth"])
def me(current_user: User = Depends(_get_current_user)):
    """Return the currently authenticated user"""
    return {"username": current_user.username}


# ─── Terminals ────────────────────────────────────────────────────────────────

@app.get("/terminals", response_model=List[TerminalOut], tags=["Terminals"])
def list_terminals(db: Session = Depends(get_db), _: User = Depends(_get_current_user)):
    """List all registered terminals with online status"""
    terminals = db.query(Terminal).order_by(Terminal.last_seen_at.desc()).all()
    result = []
    for t in terminals:
        d = TerminalOut.model_validate(t)
        d.online = conn_mgr.is_online(t.phone)
        result.append(d)
    return result


@app.get("/terminals/online", tags=["Terminals"])
def list_online_terminals(_: User = Depends(_get_current_user)):
    """List phones that currently have an active TCP connection"""
    return {"online": conn_mgr.online_phones()}


@app.get("/terminals/{phone}", response_model=TerminalOut, tags=["Terminals"])
def get_terminal(phone: str, db: Session = Depends(get_db), _: User = Depends(_get_current_user)):
    t = db.query(Terminal).filter_by(phone=phone).first()
    if not t:
        raise HTTPException(404, "Terminal not found")
    d = TerminalOut.model_validate(t)
    d.online = conn_mgr.is_online(phone)
    return d


# ─── Location ─────────────────────────────────────────────────────────────────

@app.get("/terminals/{phone}/locations", response_model=List[LocationOut], tags=["Location"])
def get_locations(
    phone: str,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(_get_current_user),
):
    """Retrieve location history for a terminal"""
    records = (
        db.query(LocationRecord)
        .filter_by(phone=phone)
        .order_by(LocationRecord.received_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return records


@app.get("/terminals/{phone}/locations/latest", response_model=LocationOut, tags=["Location"])
def get_latest_location(phone: str, db: Session = Depends(get_db), _: User = Depends(_get_current_user)):
    """Get the most recent location report for a terminal"""
    record = (
        db.query(LocationRecord)
        .filter_by(phone=phone)
        .order_by(LocationRecord.received_at.desc())
        .first()
    )
    if not record:
        raise HTTPException(404, "No location data found")
    return record


# ─── Control Commands (0x8105) ────────────────────────────────────────────────

@app.post("/terminals/{phone}/control", tags=["Commands"])
async def send_control_command(
    phone: str,
    req: ControlCommandRequest,
    db: Session = Depends(get_db),
    _: User = Depends(_get_current_user),
):
    """
    Send a control command to the terminal.
    Commands: power_on, power_off, start_alarm, stop_alarm
    """
    _check_online(phone)
    cmd_word = COMMAND_MAP.get(req.command)
    if cmd_word is None:
        raise HTTPException(400, f"Unknown command '{req.command}'. Valid: {list(COMMAND_MAP)}")

    serial = _srv_serial(phone)
    data   = build_terminal_control(phone, serial, cmd_word)

    log = CommandLog(
        phone=phone,
        msg_id=MSG_TERMINAL_CONTROL,
        command_word=cmd_word,
        params={"command": req.command},
        serial_no=serial,
    )
    db.add(log)
    db.commit()

    sent = await conn_mgr.send(phone, data)
    if not sent:
        raise HTTPException(503, "Failed to send — terminal may have disconnected")

    logger.info(f"[{phone}] sent control command={req.command} (word={cmd_word})")
    return {"status": "sent", "serial_no": serial, "command": req.command}


# ─── Parameter Set (0x8103) ───────────────────────────────────────────────────

@app.post("/terminals/{phone}/params/set", tags=["Parameters"])
async def set_parameters(
    phone: str,
    req: SetParamsRequest,
    db: Session = Depends(get_db),
    _: User = Depends(_get_current_user),
):
    """
    Set terminal parameters.
    - ecu_ignition_prohibited: true = TBOX prohibits ignition, false = allow
    - geofence_enabled: true = geo-fence on, false = off
    """
    _check_online(phone)
    params: Dict[int, bytes] = {}

    if req.ecu_ignition_prohibited is not None:
        params[PARAM_ECU_IGNITION_SWITCH] = bytes([1 if req.ecu_ignition_prohibited else 0])

    if req.geofence_enabled is not None:
        params[PARAM_GEOFENCE_SWITCH] = bytes([1 if req.geofence_enabled else 0])

    if not params:
        raise HTTPException(400, "Provide at least one parameter to set")

    serial = _srv_serial(phone)
    data   = build_set_params(phone, serial, params)

    param_log: Dict[str, Any] = {
        f"0x{k:04X}": v.hex() for k, v in params.items()
    }
    log = ParameterLog(phone=phone, direction="set", params=param_log, serial_no=serial)
    db.add(log)

    cmd = CommandLog(
        phone=phone, msg_id=MSG_SET_PARAMS,
        params=param_log, serial_no=serial
    )
    db.add(cmd)
    db.commit()

    sent = await conn_mgr.send(phone, data)
    if not sent:
        raise HTTPException(503, "Failed to send")

    logger.info(f"[{phone}] set params {param_log}")
    return {"status": "sent", "serial_no": serial, "params": param_log}


# ─── Parameter Query (0x8106) ─────────────────────────────────────────────────

@app.post("/terminals/{phone}/params/query", tags=["Parameters"])
async def query_parameters(
    phone: str,
    param_ids: Optional[List[str]] = None,
    db: Session = Depends(get_db),
    _: User = Depends(_get_current_user),
):
    """
    Query terminal parameters. Provide param IDs as hex strings e.g. ["0xFF01","0xFF02"].
    Leave body empty to query all custom params.
    """
    _check_online(phone)
    ids_int = [PARAM_ECU_IGNITION_SWITCH, PARAM_GEOFENCE_SWITCH]

    if param_ids:
        try:
            ids_int = [int(p, 16) for p in param_ids]
        except ValueError:
            raise HTTPException(400, "param_ids must be hex strings e.g. 0xFF01")

    serial = _srv_serial(phone)
    data   = build_query_params(phone, serial, ids_int)

    log = ParameterLog(
        phone=phone, direction="get",
        params={"queried": [f"0x{i:04X}" for i in ids_int]},
        serial_no=serial,
    )
    db.add(log)
    db.commit()

    sent = await conn_mgr.send(phone, data)
    if not sent:
        raise HTTPException(503, "Failed to send")

    return {"status": "sent", "serial_no": serial, "queried_params": [f"0x{i:04X}" for i in ids_int]}


# ─── Logs ─────────────────────────────────────────────────────────────────────

@app.get("/terminals/{phone}/commands", response_model=List[CommandLogOut], tags=["Logs"])
def get_command_logs(
    phone: str,
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(_get_current_user),
):
    """List command history for a terminal including ACK status"""
    return (
        db.query(CommandLog)
        .filter_by(phone=phone)
        .order_by(CommandLog.sent_at.desc())
        .limit(limit)
        .all()
    )


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "online_terminals": len(conn_mgr.online_phones())}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _check_online(phone: str):
    if not conn_mgr.is_online(phone):
        raise HTTPException(409, f"Terminal {phone} is not currently connected")
