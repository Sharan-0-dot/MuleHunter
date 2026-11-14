# Mule Hunter — Hardware Teammate Handoff & Runbook

Welcome to the real Mule Hunter backend! This document provides everything you need to connect your Raspberry Pi and ESP32 desk unit directly to the real AML detection backend.

---

## 1. Backend Server Overview

- **Port**: Currently running on **Port 8001** (`REAL_PORT`).
  > **Note on Port Switch**: When we are ready for final full-system integration, the real backend will move to **Port 8000** (replacing the mock backend).
- **Auto-detected LAN IP**: Automatically bound to your local network IP (e.g., `http://10.63.67.11:8001` or your current hotspot IP).
- **Shared Secret**: `mulehunter-demo-secret` (used for all HMAC-SHA256 signatures).
- **Command to launch real backend manually**:
  ```powershell
  cd backend
  .\.venv\Scripts\uvicorn.exe app.main:app --app-dir . --host 0.0.0.0 --port 8001
  ```

---

## 2. Triggering Attacks & Controlling Simulation with `curl`

You can control the live stream and trigger real laundering rings at any time to test the Pi's alert reception, LED, buzzer, and audio playback:

### Start the simulation stream
```bash
curl -X POST http://<LAPTOP_LAN_IP>:8001/api/sim/start -H "Content-Type: application/json" -d '{"speed": 10}'
```

### Pause the simulation stream
```bash
curl -X POST http://<LAPTOP_LAN_IP>:8001/api/sim/stop
```

### Reset the simulation stream (clears clusters and resets clock)
```bash
curl -X POST http://<LAPTOP_LAN_IP>:8001/api/sim/reset
```

### Launch an attack ring
Attack types: `round_trip`, `smurfing`, `mule_chain`, `hybrid`, `stealth`. Difficulty: `1` to `5`.
```bash
# Example 1: Round Trip (cyclic return, fast detection)
curl -X POST http://<LAPTOP_LAN_IP>:8001/api/sim/attack \
  -H "Content-Type: application/json" \
  -d '{"type": "round_trip", "difficulty": 2}'

# Example 2: Smurfing (fan-out -> fan-in)
curl -X POST http://<LAPTOP_LAN_IP>:8001/api/sim/attack \
  -H "Content-Type: application/json" \
  -d '{"type": "smurfing", "difficulty": 3}'

# Example 3: Hybrid (smurfing + chain + loop)
curl -X POST http://<LAPTOP_LAN_IP>:8001/api/sim/attack \
  -H "Content-Type: application/json" \
  -d '{"type": "hybrid", "difficulty": 2}'
```

---

## 3. Messages the Raspberry Pi Receives (`/ws/pi`)

Connect your WebSocket client to:
`ws://<LAPTOP_LAN_IP>:8001/ws/pi`

### 1. Alert Message (`type: "alert"`)
Pushed when a laundering cluster is detected and verified:
```json
{
  "type": "alert",
  "alert_id": "A-0001",
  "cluster_id": "C-0001",
  "level": "red",
  "risk_score": 0.88,
  "typology": "round_tripping",
  "accounts_count": 6,
  "total_amount_inr": 1250000,
  "wav_url": "http://<LAPTOP_LAN_IP>:8001/static/audio/C-0001.wav",
  "listen_seconds": 25,
  "created_at": "2026-11-15T10:42:12Z"
}
```
- **Actions on Pi**:
  1. Download WAV from `wav_url`.
  2. Activate LED (Red, Yellow, or Green).
  3. Sound buzzer pattern matching `level`.
  4. Post acknowledgement: `event: "received"` via `POST /api/pi/ack`.
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
Sent when an officer approves a freeze on the dashboard:
```json
{
  "type": "clear",
  "cluster_id": "C-0001"
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

SHARED_SECRET = "mulehunter-demo-secret"
BACKEND_URL = "http://<LAPTOP_LAN_IP>:8001"

def send_pi_ack(alert_id, event):
    payload = {
        "alert_id": alert_id,
        "event": event,  # "received" | "explain_voice" | "explain_joystick" | "played"
        "ts": "2026-11-15T10:42:15Z"
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

## 5. ESP32 Biometric Desk Unit Integration

The biometric flow works identically on port 8001:

1. **Browser** opens challenge: `POST /api/auth/challenge` -> `{"challenge_id": "L-91ab", "expires_at": "..."}` and connects `ws://<LAPTOP_LAN_IP>:8001/ws/auth/L-91ab`.
2. **Bridge script** polls `GET /api/auth/challenge/pending` every 500 ms.
3. On fingerprint match on the ESP32, bridge sends HMAC-signed POST:
   ```json
   POST /api/auth/fingerprint
   Header: X-Signature: <hex_hmac>
   Body: {"challenge_id": "L-91ab", "sensor_id": 1, "confidence": 142}
   ```
4. **Officer Mappings**:
   - `sensor_id: 1` or `2` -> **Officer A** (`O-1`)
   - `sensor_id: 3` or `4` -> **Officer B** (`O-2`)
   - `sensor_id: 5` -> **Admin** (`O-3`)
5. Backend broadcasts `{"type": "login_ok", "token": "<jwt>", "officer": {...}}` on `/ws/auth/L-91ab` and logs in the officer.
6. Fallback password: `POST /api/auth/password {"username": "officer", "password": "demo123"}`.
