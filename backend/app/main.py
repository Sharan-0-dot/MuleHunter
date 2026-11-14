"""
Mule Hunter — Real Backend Application (FastAPI).

Binds on port 8001 (REAL_PORT).
Full implementations of:
  - Simulator controls: /api/sim/start, /stop, /reset, /attack
  - Real-time Graph & Node views: /api/graph, /api/clusters, /api/accounts/{id}
  - Metrics & Evaluation reporting: /api/metrics
  - Hardware Raspberry Pi integration: /ws/pi, /api/pi/ack (HMAC signed)
  - Hardware Biometric authentication: /api/auth/challenge, /api/auth/fingerprint, /ws/auth/{id}
  - Dashboard WebSockets: /ws/dashboard
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Dict, Optional, Set

from fastapi import FastAPI, HTTPException, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import jwt
from pydantic import BaseModel
import numpy as np

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import (
    SHARED_SECRET,
    JWT_SECRET,
    REAL_PORT,
    get_public_base_url,
)
from app.engine import engine
from app.db import (
    get_officer_by_sensor_id,
    list_clusters,
    get_cluster_detail,
)

METRICS_VAL_FULL_PATH = backend_dir / "data" / "metrics_val_full.json"
METRICS_PATH = backend_dir / "data" / "metrics.json"
STATIC_DIR = backend_dir / "static"


def verify_hmac_signature(body_bytes: bytes, signature: Optional[str]) -> bool:
    """Verifies hex HMAC-SHA256 signature against SHARED_SECRET."""
    if not signature:
        return False
    expected = hmac.new(SHARED_SECRET.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def create_officer_jwt(officer: dict) -> str:
    """Creates signed JWT for officer session."""
    payload = {
        "sub": officer["id"],
        "name": officer["name"],
        "role": officer["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=8),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Warm up graph window and launch streaming engine
    engine.warmup()
    await engine.start()
    yield
    # Shutdown
    await engine.stop()


app = FastAPI(title="Mule Hunter AML Backend", lifespan=lifespan)

# Open CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static audio files
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Simulator Endpoints
# ---------------------------------------------------------------------------
class SimStartRequest(BaseModel):
    speed: Optional[float] = 10.0


@app.post("/api/sim/start")
async def sim_start(req: SimStartRequest = SimStartRequest()):
    await engine.start(req.speed)
    return {"ok": True, "speed": engine.sim_speed, "sim_time": engine.sim_time.isoformat()}


@app.post("/api/sim/stop")
async def sim_stop():
    await engine.stop()
    return {"ok": True, "sim_time": engine.sim_time.isoformat()}


@app.post("/api/sim/reset")
async def sim_reset():
    await engine.reset()
    return {"ok": True, "sim_time": engine.sim_time.isoformat()}


class AttackRequest(BaseModel):
    type: str
    difficulty: int = 1


@app.post("/api/sim/attack")
async def sim_attack(req: AttackRequest):
    res = engine.launch_attack(req.type, req.difficulty)
    return res


# ---------------------------------------------------------------------------
# Graph, Clusters & Account Views
# ---------------------------------------------------------------------------
@app.get("/api/graph")
async def get_graph(cluster_id: Optional[str] = Query(None), hops: int = Query(1)):
    """Returns focused graph centered on cluster_id with 1-hop neighbours and background nodes."""
    return engine.get_focused_graph(cluster_id=cluster_id, hops=hops)


@app.get("/api/clusters")
async def get_clusters():
    """Lists all tracked laundering clusters."""
    return list_clusters()


@app.get("/api/clusters/{cluster_id}")
async def get_cluster(cluster_id: str):
    """Returns cluster metadata, summary, accounts list, and alert timeline."""
    c = get_cluster_detail(cluster_id)
    if not c:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")
    return c


@app.get("/api/accounts/{account_id}")
async def get_account(account_id: str):
    """Returns account detail conforming to master 8.6 contract."""
    acc = engine.get_account_detail(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return acc


@app.get("/api/metrics")
async def get_metrics():
    """Serves persisted evaluation metrics alongside real-time engine telemetry."""
    saved_metrics = {}
    path_to_read = METRICS_VAL_FULL_PATH if METRICS_VAL_FULL_PATH.exists() else METRICS_PATH
    if path_to_read.exists():
        try:
            with open(path_to_read, "r") as f:
                saved_metrics = json.load(f)
        except Exception:
            pass

    mean_tick = round(float(np.mean(engine.tick_runtimes_ms)), 2) if engine.tick_runtimes_ms else 0.0

    return {
        "tx_processed": engine.tx_processed_count,
        "alerts_count": engine.alerts_count,
        "prevented_inr": round(engine.prevented_inr, 2),
        "mean_tick_ms": mean_tick,
        "sim_time": engine.sim_time.isoformat(),
        "sim_speed": engine.sim_speed,
        "is_running": engine.is_running,
        "metrics": saved_metrics,
    }


@app.get("/api/dev/ground_truth")
async def get_dev_ground_truth():
    """Development-only endpoint returning server-side ground truth for soak/test scripts."""
    gt_serialized = {}
    for ring_id, d in engine.server_ground_truth.items():
        gt_serialized[ring_id] = {
            "ring_id": ring_id,
            "attack_type": d["attack_type"],
            "difficulty": d["difficulty"],
            "ring_accounts": list(d["ring_accounts"]),
            "total_amount": d["total_amount"],
            "start_ts": d["start_ts"].isoformat(),
            "end_ts": d["end_ts"].isoformat(),
        }
    return gt_serialized


# ---------------------------------------------------------------------------
# Hardware Raspberry Pi Integration
# ---------------------------------------------------------------------------
@app.post("/api/pi/ack")
async def pi_ack(request: Request, x_signature: Optional[str] = Header(None)):
    """Receives HMAC-signed acknowledgements from Raspberry Pi."""
    body_bytes = await request.body()
    if not verify_hmac_signature(body_bytes, x_signature):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    data = json.loads(body_bytes.decode("utf-8"))
    alert_id = data.get("alert_id", "")
    event = data.get("event", "")
    ts = data.get("ts", datetime.now(timezone.utc).isoformat())

    engine.handle_pi_ack(alert_id, event, ts)
    return {"ok": True}


@app.websocket("/ws/pi")
async def websocket_pi(websocket: WebSocket):
    """Dedicated WebSocket for Raspberry Pi alert dispatch & keepalive."""
    await websocket.accept()
    engine.pi_websockets.add(websocket)

    async def _ping_loop():
        while True:
            await asyncio.sleep(10.0)
            try:
                await websocket.send_text(json.dumps({"type": "ping"}))
            except Exception:
                break

    ping_task = asyncio.create_task(_ping_loop())
    try:
        while True:
            msg_text = await websocket.receive_text()
            try:
                msg = json.loads(msg_text)
                if msg.get("type") == "pong":
                    pass
                elif msg.get("type") == "clear":
                    # Pi clear signal forward
                    await engine._broadcast_dashboard({"type": "pi_clear"})
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        ping_task.cancel()
        engine.pi_websockets.discard(websocket)


@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """WebSocket feed for dashboard browser client."""
    await websocket.accept()
    engine.dashboard_websockets.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        engine.dashboard_websockets.discard(websocket)


# ---------------------------------------------------------------------------
# Biometric Authentication Flow (ESP32 -> Bridge -> Backend)
# ---------------------------------------------------------------------------
@app.post("/api/auth/challenge")
async def auth_challenge():
    """Generates 30-second auth challenge for biometric desk scanner."""
    challenge_id = f"L-{secrets.token_hex(2)}"
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    engine.pending_challenges[challenge_id] = expires_at
    return {
        "challenge_id": challenge_id,
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@app.get("/api/auth/challenge/pending")
async def auth_challenge_pending():
    """Polled by USB bridge script to retrieve active biometric challenge."""
    now = datetime.now(timezone.utc)
    for cid, exp in list(engine.pending_challenges.items()):
        if exp > now:
            return {"challenge_id": cid}
        else:
            engine.pending_challenges.pop(cid, None)
    return {"challenge_id": None}


@app.websocket("/ws/auth/{challenge_id}")
async def websocket_auth(websocket: WebSocket, challenge_id: str):
    """Awaits biometric match confirmation from bridge."""
    await websocket.accept()
    engine.auth_websockets[challenge_id] = websocket
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        engine.auth_websockets.pop(challenge_id, None)


@app.post("/api/auth/fingerprint")
async def auth_fingerprint(request: Request, x_signature: Optional[str] = Header(None)):
    """Receives biometric sensor match from bridge via HMAC-signed POST."""
    body_bytes = await request.body()
    if not verify_hmac_signature(body_bytes, x_signature):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    data = json.loads(body_bytes.decode("utf-8"))
    challenge_id = data.get("challenge_id")
    sensor_id = data.get("sensor_id")

    ws = engine.auth_websockets.get(challenge_id)

    # Check challenge validity
    exp = engine.pending_challenges.get(challenge_id)
    if not exp or datetime.now(timezone.utc) > exp:
        if ws:
            await ws.send_text(json.dumps({"type": "login_failed", "reason": "expired"}))
        raise HTTPException(status_code=400, detail="Challenge expired or invalid")

    officer = get_officer_by_sensor_id(sensor_id)
    if not officer:
        if ws:
            await ws.send_text(json.dumps({"type": "login_failed", "reason": "unknown_finger"}))
        raise HTTPException(status_code=404, detail="Officer not registered")

    token = create_officer_jwt(officer)
    if ws:
        await ws.send_text(json.dumps({
            "type": "login_ok",
            "token": token,
            "officer": officer,
        }))

    # Clear pending challenge
    engine.pending_challenges.pop(challenge_id, None)
    return {"ok": True}


class PasswordLoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/password")
async def auth_password(req: PasswordLoginRequest):
    """Fallback password authentication for stage safety."""
    if req.username == "officer" and req.password == "demo123":
        officer = {"id": "O-1", "name": "Officer A", "role": "officer"}
        token = create_officer_jwt(officer)
        return {"token": token, "officer": officer}
    elif req.username == "admin" and req.password == "admin123":
        officer = {"id": "O-3", "name": "Admin", "role": "admin"}
        token = create_officer_jwt(officer)
        return {"token": token, "officer": officer}
    raise HTTPException(status_code=401, detail="Invalid credentials")
