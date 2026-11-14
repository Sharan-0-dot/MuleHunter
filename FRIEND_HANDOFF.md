# Mule Hunter — Hardware Teammate Handoff & Runbook (Raspberry Pi Compliance Desk)

Welcome to the real Mule Hunter backend! The backend is running on **Port 8000** (`http://0.0.0.0:8000`). This document provides everything you need to connect your Raspberry Pi alert desk directly to the live AML detection pipeline.

---

## 1. Backend Server Overview & Connection Details

- **Port**: **8000** (`http://<LAPTOP_LAN_IP>:8000`).
- **WebSocket Feed for Pi**: `ws://<LAPTOP_LAN_IP>:8000/ws/pi`
- **Shared Secret**: `mulehunter-demo-secret` (used for all HMAC-SHA256 signatures).
- **Auto-detected Laptop LAN IP**: Check your laptop's Wi-Fi IP address on the shared hotspot (e.g., `192.168.43.x`).
- **Health Check from Pi**:
  ```bash
  curl http://<LAPTOP_LAN_IP>:8000/api/metrics
  ```

---

## 2. Controlling the Simulation & Triggering Test Alerts

You can control the live stream and trigger laundering rings at any time to test the Pi's alert reception, LED, buzzer, and audio playback:

### Start the simulation stream
```bash
curl -X POST http://<LAPTOP_LAN_IP>:8000/api/sim/start -H "Content-Type: application/json" -d '{"speed": 10}'
```

### Pause the simulation stream
```bash
curl -X POST http://<LAPTOP_LAN_IP>:8000/api/sim/stop
```

### Reset the simulation stream (clears clusters, alerts, audit log, and resets counters)
```bash
curl -X POST http://<LAPTOP_LAN_IP>:8000/api/sim/reset
```

### Launch an attack ring with custom laundering size
Attack types: `round_trip`, `smurfing`, `mule_chain`, `hybrid`, `stealth`. Difficulty: `1` to `5`.
The optional `total_amount_inr` scales the ring's total volume to hit specific urgency bands:
- **300,000 INR (3 Lakh)** ➔ **GREEN** alert (0.40 - 0.65)
- **1,000,000 INR (10 Lakh)** ➔ **YELLOW** alert (0.65 - 0.85)
- **2,500,000 INR (25 Lakh)** ➔ **RED** alert (>= 0.85)

```bash
# Example 1: Green alert test (3 lakh INR)
curl -X POST http://<LAPTOP_LAN_IP>:8000/api/sim/attack \
  -H "Content-Type: application/json" \
  -d '{"type": "round_trip", "difficulty": 2, "total_amount_inr": 300000}'

# Example 2: Yellow alert test (10 lakh INR)
curl -X POST http://<LAPTOP_LAN_IP>:8000/api/sim/attack \
  -H "Content-Type: application/json" \
  -d '{"type": "smurfing", "difficulty": 3, "total_amount_inr": 1000000}'

# Example 3: Red alert test (25 lakh INR)
curl -X POST http://<LAPTOP_LAN_IP>:8000/api/sim/attack \
  -H "Content-Type: application/json" \
  -d '{"type": "round_trip", "difficulty": 2, "total_amount_inr": 2500000}'

# Example 4: Stealth ring (structures all hops strictly below 50,000 threshold)
curl -X POST http://<LAPTOP_LAN_IP>:8000/api/sim/attack \
  -H "Content-Type: application/json" \
  -d '{"type": "stealth", "difficulty": 5}'
```

---

## 3. Messages the Raspberry Pi Receives (`/ws/pi`)

Connect your WebSocket client to:
`ws://<LAPTOP_LAN_IP>:8000/ws/pi`

### 1. Alert Message (`type: "alert"`)
Pushed when a laundering cluster is confirmed by the detection pipeline (exact Master 8.2 contract):
```json
{
  "type": "alert",
  "alert_id": "A-0001",
  "cluster_id": "C-0001",
  "level": "red",
  "risk_score": 0.88,
  "typology": "round_tripping",
  "accounts_count": 6,
  "total_amount_inr": 2500000,
  "wav_url": "http://<LAPTOP_LAN_IP>:8000/static/audio/C-0001.wav",
  "listen_seconds": 25,
  "created_at": "2026-11-15T10:42:12Z"
}
```
- **Actions on Pi**:
  1. Download WAV from `wav_url`.
  2. Activate LED (Red, Yellow, or Green matching `level`).
  3. Sound buzzer pattern matching `level`.
  4. Post acknowledgement: `event: "received"` via `POST /api/pi/ack` (HMAC signed).
  5. Start Vosk keyword listener or joystick listener for `listen_seconds` (25s).
  6. On voice keyword or joystick press: play downloaded audio through speaker and post `event: "explain_voice"` or `event: "explain_joystick"`.
  7. On playback finish: post `event: "played"`.

### 2. Keepalive Ping (`type: "ping"`)
Sent by server every 10 seconds:
```json
{"type": "ping"}
```
Pi replies with:
```json
{"type": "pong"}
```

### 3. Escalation Message (`type: "escalate"`)
Sent if no `explain_*` ack is received within `listen_seconds + 5` (30s total):
```json
{
  "type": "escalate",
  "alert_id": "A-0001"
}
```
- **Action on Pi**: Intensify LED blink or buzzer tone until acknowledged or cleared.

### 4. Clear Message (`type: "clear"`)
Sent when an officer freezes the cluster on the dashboard:
```json
{
  "type": "clear",
  "alert_id": "A-0001"
}
```
- **Action on Pi**: Turn off LEDs and buzzer; return to idle standby.

---

## 4. How to Send Pi Acknowledgements (`POST /api/pi/ack`)

All mutating requests from the Pi require an HMAC-SHA256 signature in the `X-Signature` header:
- **Algorithm**: `HMAC-SHA256(key = "mulehunter-demo-secret", data = raw_json_body_bytes).hexdigest()`

### Python snippet for Pi:
```python
import hmac, hashlib, json, requests
from datetime import datetime, timezone

SHARED_SECRET = "mulehunter-demo-secret"
BACKEND_URL = "http://<LAPTOP_LAN_IP>:8000"

def send_pi_ack(alert_id, event):
    payload = {
        "alert_id": alert_id,
        "event": event,  # "received" | "explain_voice" | "explain_joystick" | "played"
        "ts": datetime.now(timezone.utc).isoformat()
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = hmac.new(SHARED_SECRET.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        "X-Signature": sig
    }
    resp = requests.post(f"{BACKEND_URL}/api/pi/ack", data=body_bytes, headers=headers)
    return resp.status_code == 200
```

---

## 5. Account Freeze & Cryptographic Audit Verification

### Freezing a Cluster
From dashboard (or curl):
```bash
curl -X POST http://<LAPTOP_LAN_IP>:8000/api/clusters/C-0001/freeze
```
- Freezes all accounts in the cluster and blocks pending transactions.
- Accumulates prevented INR in server telemetry (`/api/metrics`).
- Sends `clear` to `/ws/pi` to immediately deactivate LEDs/buzzer on the Pi.
- Broadcasts `frozen` event to `/ws/dashboard`.
- Records `freeze` event into the tamper-evident SHA-256 audit trail.

### Verifying the Audit Trail
```bash
# Fetch recent audit entries
curl http://<LAPTOP_LAN_IP>:8000/api/audit?limit=20

# Cryptographically verify SHA-256 hash chain
curl http://<LAPTOP_LAN_IP>:8000/api/audit/verify
# Response: {"ok": true, "entries": 6, "first_bad_index": null}
```
