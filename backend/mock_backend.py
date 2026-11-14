import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
from typing import Dict, Optional, Set

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import jwt
from pydantic import BaseModel

# Load environment variables
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

SHARED_SECRET = os.getenv("SHARED_SECRET", "mulehunter-demo-secret")
LISTEN_SECONDS = int(os.getenv("LISTEN_SECONDS", "25"))
JWT_SECRET = os.getenv("JWT_SECRET", "dev-jwt-secret")
PORT = int(os.getenv("PORT", "8000"))

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
AUDIO_DIR = STATIC_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def get_lan_ip() -> str:
    """Auto-detect laptop LAN IP via UDP socket trick."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def verify_signature(body_bytes: bytes, signature: Optional[str]) -> bool:
    if not signature:
        return False
    expected = hmac.new(SHARED_SECRET.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def create_token(officer: dict) -> str:
    payload = {
        "sub": officer["id"],
        "name": officer["name"],
        "role": officer["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=8),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


# In-memory state
pi_clients: Set[WebSocket] = set()
auth_clients: Dict[str, Set[WebSocket]] = {}
challenges: Dict[str, datetime] = {}
latest_challenge_id: Optional[str] = None
alert_seq = 0

# Sensor ID mapping
SENSOR_MAP = {
    1: {"id": "O-1", "name": "Officer A", "role": "officer"},
    2: {"id": "O-1", "name": "Officer A", "role": "officer"},
    3: {"id": "O-2", "name": "Officer B", "role": "officer"},
    4: {"id": "O-2", "name": "Officer B", "role": "officer"},
    5: {"id": "O-3", "name": "Admin", "role": "admin"},
}

LEVEL_PROFILES = {
    "red": {
        "risk_score": 0.91,
        "typology": "round_tripping",
        "accounts_count": 7,
        "total_amount_inr": 420000,
    },
    "yellow": {
        "risk_score": 0.72,
        "typology": "mule_chain",
        "accounts_count": 5,
        "total_amount_inr": 180000,
    },
    "green": {
        "risk_score": 0.50,
        "typology": "fan_out",
        "accounts_count": 4,
        "total_amount_inr": 65000,
    },
}


async def ping_pi_clients():
    """Send {"type":"ping"} every 10 seconds to all connected Pi clients."""
    while True:
        await asyncio.sleep(10)
        if pi_clients:
            dead = set()
            for client in list(pi_clients):
                try:
                    await client.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    dead.add(client)
            pi_clients.difference_update(dead)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ping_task = asyncio.create_task(ping_pi_clients())
    yield
    ping_task.cancel()
    try:
        await ping_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Mule Hunter Mock Backend", lifespan=lifespan)

# CORS open
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files at /static
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------- WebSocket /ws/pi ----------------
@app.websocket("/ws/pi")
async def ws_pi(websocket: WebSocket):
    await websocket.accept()
    pi_clients.add(websocket)
    print(f"[WS /ws/pi] Pi client connected. Total connected: {len(pi_clients)}")
    try:
        while True:
            text = await websocket.receive_text()
            try:
                data = json.loads(text)
                if data.get("type") == "pong":
                    # Keepalive response received
                    pass
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        pi_clients.discard(websocket)
        print(f"[WS /ws/pi] Pi client disconnected. Remaining: {len(pi_clients)}")


# ---------------- POST /mock/trigger ----------------
@app.post("/mock/trigger")
async def mock_trigger(level: str = Query(..., pattern="^(red|yellow|green)$")):
    global alert_seq
    alert_seq += 1
    alert_id = f"A-{alert_seq:04d}"
    cluster_id = f"C-{alert_seq:04d}"

    profile = LEVEL_PROFILES[level]
    lan_ip = get_lan_ip()
    wav_url = f"http://{lan_ip}:{PORT}/static/audio/{level}.wav"
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    alert_data = {
        "type": "alert",
        "alert_id": alert_id,
        "cluster_id": cluster_id,
        "level": level,
        "risk_score": profile["risk_score"],
        "typology": profile["typology"],
        "accounts_count": profile["accounts_count"],
        "total_amount_inr": profile["total_amount_inr"],
        "wav_url": wav_url,
        "listen_seconds": LISTEN_SECONDS,
        "created_at": now_iso,
    }

    # Push to all connected Pi clients
    delivered = 0
    dead = set()
    alert_json = json.dumps(alert_data)
    for client in list(pi_clients):
        try:
            await client.send_text(alert_json)
            delivered += 1
        except Exception:
            dead.add(client)
    pi_clients.difference_update(dead)

    print(f"[TRIGGER] Sent alert {alert_id} ({level}) to {delivered} Pi client(s)")
    return {"alert": alert_data, "recipients": delivered}


# ---------------- POST /api/pi/ack ----------------
@app.post("/api/pi/ack")
async def pi_ack(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("X-Signature")

    if not verify_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        event_data = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    print(f"[PI ACK] Received event: {event_data}")
    return {"ok": True}


# ---------------- Auth: challenge & pending ----------------
@app.post("/api/auth/challenge")
async def create_challenge():
    global latest_challenge_id
    challenge_id = f"L-{secrets.token_hex(2)}"
    expires_at_dt = datetime.now(timezone.utc) + timedelta(seconds=30)
    challenges[challenge_id] = expires_at_dt
    latest_challenge_id = challenge_id
    expires_at_iso = expires_at_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[AUTH] Challenge created: {challenge_id}, expires at {expires_at_iso}")
    return {"challenge_id": challenge_id, "expires_at": expires_at_iso}


@app.get("/api/auth/challenge/pending")
async def get_pending_challenge():
    global latest_challenge_id
    now = datetime.now(timezone.utc)
    # Check if latest challenge is still valid
    if latest_challenge_id:
        exp = challenges.get(latest_challenge_id)
        if exp and exp > now:
            return {"challenge_id": latest_challenge_id}
    # Otherwise check any unexpired challenge
    for cid, exp in list(challenges.items()):
        if exp > now:
            return {"challenge_id": cid}
    return {"challenge_id": None}


# ---------------- Auth: WebSocket /ws/auth/{challenge_id} ----------------
@app.websocket("/ws/auth/{challenge_id}")
async def ws_auth(websocket: WebSocket, challenge_id: str):
    await websocket.accept()
    if challenge_id not in auth_clients:
        auth_clients[challenge_id] = set()
    auth_clients[challenge_id].add(websocket)
    print(f"[WS /ws/auth/{challenge_id}] Auth client connected")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if challenge_id in auth_clients:
            auth_clients[challenge_id].discard(websocket)
            if not auth_clients[challenge_id]:
                del auth_clients[challenge_id]
        print(f"[WS /ws/auth/{challenge_id}] Auth client disconnected")


# ---------------- Auth: Fingerprint ----------------
@app.post("/api/auth/fingerprint")
async def auth_fingerprint(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("X-Signature")

    if not verify_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    challenge_id = data.get("challenge_id")
    sensor_id = data.get("sensor_id")
    confidence = data.get("confidence")

    now = datetime.now(timezone.utc)
    exp = challenges.get(challenge_id) if challenge_id else None

    # Check expiration
    if not exp or exp <= now:
        msg = {"type": "login_failed", "reason": "expired"}
        await _push_auth_message(challenge_id, msg)
        print(f"[AUTH FP] Login failed for challenge {challenge_id}: expired")
        return {"ok": False, "reason": "expired"}

    # Check sensor_id mapping
    officer = SENSOR_MAP.get(sensor_id)
    if not officer:
        msg = {"type": "login_failed", "reason": "unknown_finger"}
        await _push_auth_message(challenge_id, msg)
        print(f"[AUTH FP] Login failed for sensor_id {sensor_id}: unknown_finger")
        return {"ok": False, "reason": "unknown_finger"}

    # Success: produce JWT and push login_ok
    token = create_token(officer)
    msg = {"type": "login_ok", "token": token, "officer": officer}
    await _push_auth_message(challenge_id, msg)
    print(f"[AUTH FP] Login OK for {officer['name']} ({officer['role']}), sensor_id={sensor_id}, confidence={confidence}")
    return {"ok": True, "officer": officer, "token": token}


async def _push_auth_message(challenge_id: Optional[str], msg: dict):
    if not challenge_id or challenge_id not in auth_clients:
        return
    dead = set()
    text = json.dumps(msg)
    for client in list(auth_clients[challenge_id]):
        try:
            await client.send_text(text)
        except Exception:
            dead.add(client)
    auth_clients[challenge_id].difference_update(dead)


# ---------------- Auth: Password Fallback ----------------
class PasswordLogin(BaseModel):
    username: str
    password: str


@app.post("/api/auth/password")
async def auth_password(body: PasswordLogin):
    if body.username == "officer" and body.password == "demo123":
        officer = {"id": "O-1", "name": "Officer A", "role": "officer"}
        token = create_token(officer)
        print("[AUTH PWD] Successful password login for officer")
        return {"token": token, "officer": officer}
    raise HTTPException(status_code=401, detail="Invalid credentials")


if __name__ == "__main__":
    import uvicorn
    print(f"Starting Mule Hunter mock backend on 0.0.0.0:{PORT}...")
    print(f"Auto-detected LAN IP: {get_lan_ip()}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
