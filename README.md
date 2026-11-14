# Mule Hunter ⚡
### Autonomous AI-Powered Anti-Money Laundering (AML) & Mule Ring Detection Platform

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![React 18](https://img.shields.io/badge/react-18.3.1-blue.svg)](https://reactjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![Three.js](https://img.shields.io/badge/WebGL-Three.js-black.svg)](https://threejs.org/)

Mule Hunter is an end-to-end, production-grade Anti-Money Laundering (AML) defense platform that detects, visualizes, and neutralizes complex money laundering rings and mule account networks in real time. 

Combining **temporal graph pattern mining**, an **XGBoost machine learning classifier** with calibrated composite risk scoring, an **offline/online natural language briefing pipeline**, an **authenticated IoT compliance officer desk (Raspberry Pi)**, and an **interactive 3D WebGL compliance dashboard**, Mule Hunter bridges the gap between high-speed banking graph detection and immediate physical intervention.

---

## 🏛️ System Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │    Synthetic Banking Stream (Zero Leakage)    │
                    │   2,000 Accounts · P2P, Payroll, Merchants   │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │     48-Hour Sliding Graph Window (NetworkX)   │
                    │  Per-Edge Aggregates · Exact Eviction Queue  │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │     Graph Topology Detectors & Clustering    │
                    │   Smurfing · Cycles (SCC) · Pass-Through     │
                    │     Hybrid · Sub-Threshold Evasion Struct    │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │    Calibrated Machine Learning Risk Engine   │
                    │    Scale-Free Features · XGBoost Model       │
                    │    Risk = 0.5 * P(mule) + 0.5 * Exposure     │
                    └───────┬──────────────────────────────┬───────┘
                            │                              │
            Green / Yellow / Red Alert                     │
                            ▼                              ▼
┌───────────────────────────────────────┐  ┌───────────────────────────────────────┐
│     Multi-Modal Voice & TTS Pipeline  │  │   3D WebGL Dashboard (React + Vite)   │
│  - Deterministic / LLM Polish (GPT)   │  │  - 3D Force-Directed Graph View       │
│  - 16-bit PCM Mono Audio Synthesis    │  │  - Real-Time WebSocket Feeds          │
│  - Exact Master 8.2 JSON Alert Push   │  │  - Adversarial Attack Launcher        │
└───────────────────┬───────────────────┘  │  - Fullscreen Presentation Mode (F)   │
                    │                      └───────────────────┬───────────────────┘
                    ▼                                          │
┌───────────────────────────────────────┐                      │
│   Raspberry Pi Hardware Alert Desk    │                      │
│  - Tri-Color LED Status & Buzzer      │                      │
│  - Speaker Audio Briefing Playback    │                      │
│  - HMAC-SHA256 Signed Acks            │                      │
│  - Vosk Keyword & Joystick Trigger    │                      │
└───────────────────┬───────────────────┘                      │
                    │                                          │
                    ▼                                          ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│             Biometric Authorization & Cryptographic Defense Pipeline             │
│  - Hardware Fingerprint Authentication (AS608) -> JWT Officer Session            │
│  - Real-Time Emergency Cluster Freeze (Blocks Pending Txs & Pushes Clear)        │
│  - SHA-256 Hash-Chained Immutable Audit Trail (Tamper-Evident Verification)      │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🌟 Key Capabilities

### 1. Real-Time Graph Sliding Window & Evasion Topology Detection
- **48-Hour Temporal Sliding Window**: Maintains per-edge financial transaction aggregates (`total`, `count`, `first_ts`, `last_ts`) with exact eviction and zero historical leakage.
- **Graph Topology Detectors**:
  - **Smurfing (Fan-Out / Fan-In)**: Identifies layered structuring of funds from a primary source into mule accounts and consolidation into destination accounts.
  - **Circular Loops (Round-Tripping)**: SCC-pruned cycle detection (size 3–50 accounts, flow $\ge$ ₹5,000) identifying cyclic laundering returning to origin.
  - **Pass-Through Chains**: Multi-hop layered mule accounts with retention ratios between $0.75$ and $1.35$.
  - **Hybrid Rings**: Multi-stage smurfing feeding into pass-through chains with cyclic return loops.
  - **Stealth Structuring**: Detects evasive micro-transfers structured strictly below standard ₹50,000 regulatory thresholds.
- **Candidate Clustering**: Disjoint Set Union (DSU) grouping with core-account preservation that prevents giant component collapse while preserving community structure.

### 2. Machine Learning Risk Model with Composite Urgency Scoring
- **XGBoost Classifier**: Trained on scale-free graph features (degree balance, volume variance, temporal velocity, cycle density).
- **Probability Calibration**: Isotonic / Platt regression calibrates output probabilities to accurate risk likelihoods.
- **Composite Urgency Scoring**:
  $$\text{risk\_score} = 0.5 \cdot p + 0.5 \cdot \text{exposure}, \quad \text{where } \text{exposure} = \min\left(1, \frac{\text{total\_amount\_inr}}{2,500,000}\right)$$
- **Urgency Bands**:
  - **Green** ($0.40 \le \text{risk} < 0.65$): Low volume or early-stage suspicious movement.
  - **Yellow** ($0.65 \le \text{risk} < 0.85$): Significant volume multi-hop structured routing.
  - **Red** ($\text{risk} \ge 0.85$): High-severity large laundering syndicate requiring immediate freeze.

### 3. Multi-Modal Audio Briefs & Provenance Tracking
- **Deterministic Natural Language Summaries**: Concise, spoken-friendly briefs under 45 words ending with the actionable directive: *"Log in to the dashboard for linked accounts."*
- **Optional LLM Polish**: Integration with OpenRouter (`openai/gpt-4o-mini`) using strict validation checks (numerical fidelity, verbatim closing sentence, $\le 55$ words) with worker thread timeouts and deterministic fallback.
- **Offline TTS Synthesis**: Audio synthesized directly to 16-bit PCM mono WAV files ($\le 25\text{s}$) served via static endpoints for instant playback.

### 4. Physical Compliance Officer Desk (Raspberry Pi)
- **Real-Time WebSocket Feed (`/ws/pi`)**: Pushes alert payloads directly to the physical compliance desk.
- **Hardware Indicators**:
  - Multi-color LEDs (Red, Yellow, Green) reflecting severity level.
  - Piezo buzzer tones announcing alert arrivals.
  - Offline Vosk keyword listener (*"explain"*) and tactile joystick trigger for spoken audio playback.
- **HMAC-SHA256 Authenticated Acknowledgements**: Every signal from the desk (`received`, `explain_voice`, `explain_joystick`, `played`) is verified with HMAC signatures (`X-Signature`).
- **Escalation Protocol**: Dispatches escalation warnings if an alert is not acknowledged within 30 seconds.

### 5. Biometric Officer Defense & Cryptographic Audit Trail
- **Biometric Fingerprint Authentication**: AS608 optical fingerprint sensor verification generating signed JWT officer sessions.
- **Emergency Account Freeze (`POST /api/clusters/{id}/freeze`)**: Immediately freezes all accounts in the cluster, prevents upcoming transactions from executing, sends a `clear` signal to silence the physical desk, and logs prevented INR telemetry.
- **Tamper-Evident SHA-256 Audit Trail**: Hash-chained event ledger (`hash = sha256(prev_hash + canonical_json)`). Any unauthorized modification to past entries immediately invalidates the cryptographic chain via `GET /api/audit/verify`.

### 6. Interactive 3D WebGL Compliance Dashboard
- **React 18 + Three.js**: Force-directed 3D graph with WebGL rendering and 2D canvas fallback.
- **ResizeObserver Centering**: Exact viewport bounding-box synchronization with centroid camera positioning.
- **Adversarial Attack Launcher**: Interactive controls to inject all 5 laundering typologies across difficulties 1–5 with small, medium, and large volume options, real-time detection timers, and 20x demo speed presets.
- **Presentation Mode**: Fullscreen projector mode toggleable via the **`F`** key.

---

## 📂 Repository Layout

```
.
├── backend/
│   ├── app/
│   │   ├── config.py             # Server configuration & environment variables
│   │   ├── db.py                 # SQLite persistence schema & queries
│   │   ├── engine.py             # Live streaming simulation & detection orchestrator
│   │   ├── main.py               # FastAPI application, endpoints & WebSockets
│   │   ├── audit.py              # Cryptographic hash-chained audit logger
│   │   ├── detect/
│   │   │   ├── window.py         # 48-hour sliding graph window with exact eviction
│   │   │   ├── patterns.py       # Smurfing, cycle, chain & hybrid graph detectors
│   │   │   ├── clusters.py       # DSU candidate clustering & feature extraction
│   │   │   ├── baseline.py       # Naive & tuned rule-based threshold baselines
│   │   │   └── model.py          # Calibrated XGBoost classifier & risk scoring
│   │   ├── sim/
│   │   │   ├── generator.py      # Synthetic financial stream with zero label leakage
│   │   │   └── attacks.py        # 5 attack ring injectors with difficulty knobs
│   │   └── summary/
│   │       ├── templates.py      # Spoken template natural language summaries
│   │       ├── llm.py            # LLM polish with strict validation & provenance
│   │       └── tts.py            # Offline TTS mono WAV synthesizer
│   ├── scripts/
│   │   ├── test_real.py          # Integration contract verification suite
│   │   ├── detect_check.py       # Graph detector quality & timing benchmarks
│   │   ├── evaluate.py           # Machine learning model validation evaluation
│   │   ├── soak_real.py          # 10-minute high-throughput stability soak test
│   │   ├── tamper_demo.py        # Cryptographic audit tampering verification demo
│   │   └── measure_attacks.py    # Wall-clock attack-to-alert latency benchmark
│   ├── data/                     # Offline datasets, metrics, and SQLite database
│   ├── static/audio/             # Synthesized WAV audio alerts
│   └── requirements.txt          # Python dependencies
│
├── frontend/
│   ├── src/
│   │   ├── api/client.js         # HTTP fetch wrapper & reconnecting WebSocket
│   │   ├── components/
│   │   │   ├── GraphView.jsx     # 3D/2D force graph with ResizeObserver centering
│   │   │   ├── AlertFeed.jsx     # Animated slide-in alert feed & status badges
│   │   │   ├── AttackLauncher.jsx# Adversarial ring injector with timer & shortcuts
│   │   │   ├── DetailPanel.jsx   # Cluster inspector, 18px summary & freeze action
│   │   │   ├── TopBar.jsx        # Telemetry counters, Pi status & presentation mode
│   │   │   └── Toast.jsx         # Non-blocking notification toasts
│   │   ├── mock/                 # Standalone offline mock server & dataset
│   │   ├── pages/                # DashboardPage, MetricsPage, AuditPage, LoginPage
│   │   └── styles/index.css      # Dark theme styling, animations & layout grid
│   ├── package.json              # Frontend dependencies & build scripts
│   └── vite.config.js            # Vite configuration
│
└── README.md                     # Comprehensive project documentation
```

---

## 🚀 Quick Start Guide

### Prerequisites
- **Python 3.11+**
- **Node.js 18+** & **npm**

---

### Step 1: Set Up Backend

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create local environment file
cp .env.example .env
```

To enable optional LLM polish, add your OpenRouter API key in `backend/.env`:
```env
OPENROUTER_API_KEY=your-openrouter-key-here
OPENROUTER_MODEL=openai/gpt-4o-mini
```

Start the backend server on **Port 8001**:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

---

### Step 2: Set Up Frontend

In a separate terminal:
```bash
cd frontend

# Install packages
npm install

# Build production bundle
npm run build

# Start frontend development server
npm run dev
```

Open your browser at **`http://localhost:5173`**.

---

### Step 3: Run Standalone Offline Mock Mode (Optional)
If you wish to demo the frontend independently without running the Python backend:
1. In `frontend/.env`, set:
   ```env
   VITE_API_BASE=http://localhost:8001
   VITE_MOCK=1
   ```
2. Start the development server (`npm run dev`). The in-browser mock server simulates all background streaming ticks, 3D laundering rings, WebSocket events, and physical desk interactions.

---

## 🧪 Verification & Test Suites

The platform includes comprehensive test suites covering all integration points:

### 1. End-to-End Contract Verification
Tests WebSocket connectivity, attack injection, Master 8.2 alert schema compliance, WAV audio validation, HMAC signature verification, biometric login, cluster freeze, and audit logging:
```bash
python backend/scripts/test_real.py
```

### 2. Graph Detector Quality Gates
Validates cycle search runtime, span limits, candidate cluster purity, and zero historical leakage:
```bash
python backend/scripts/detect_check.py
```

### 3. Machine Learning Model Evaluation
Compares calibrated XGBoost performance against naive and tuned regulatory threshold baselines:
```bash
python backend/scripts/evaluate.py
```

### 4. Cryptographic Tamper Demonstration
Proves that modifying historical audit ledger entries causes immediate cryptographic chain rejection:
```bash
python backend/scripts/tamper_demo.py
```

### 5. High-Throughput Soak Test
Runs 48 simulated hours of streaming traffic with concurrent attack injections, measuring tick runtimes and memory stability:
```bash
python backend/scripts/soak_real.py
```

---

## 📡 Hardware Desk Integration (Raspberry Pi)

### Connection Details
- **WebSocket Feed**: `ws://<SERVER_IP>:8001/ws/pi`
- **Shared Secret**: `mulehunter-demo-secret` (used for all HMAC-SHA256 signatures)
- **Health Check**: `http://<SERVER_IP>:8001/api/metrics`

### Alert Reception Schema (Master 8.2 Contract)
```json
{
  "type": "alert",
  "alert_id": "A-0001",
  "cluster_id": "C-0001",
  "level": "red",
  "risk_score": 0.92,
  "typology": "round_tripping",
  "accounts_count": 7,
  "total_amount_inr": 2500000,
  "wav_url": "http://<SERVER_IP>:8001/static/audio/C-0001.wav",
  "listen_seconds": 25,
  "created_at": "2026-11-15T10:42:12Z"
}
```

### Sending HMAC-Signed Acknowledgements
Every mutating event from the Raspberry Pi requires an HMAC-SHA256 signature in the `X-Signature` header:
$$\text{Signature} = \text{HMAC-SHA256}(\text{key} = \text{"mulehunter-demo-secret"}, \text{body} = \text{raw\_json\_bytes})$$

```python
import hmac, hashlib, json, requests
from datetime import datetime, timezone

SHARED_SECRET = "mulehunter-demo-secret"
BACKEND_URL = "http://<SERVER_IP>:8001"

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
    return requests.post(f"{BACKEND_URL}/api/pi/ack", data=body_bytes, headers=headers)
```

---

## 🌐 REST API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/sim/start` | POST | Starts the live simulation stream with an optional `{"speed": 20}` multiplier |
| `/api/sim/stop` | POST | Pauses the live simulation stream |
| `/api/sim/reset` | POST | Clears alerts, clusters, and resets state counters cleanly |
| `/api/sim/attack` | POST | Injects an adversarial laundering ring (`type`, `difficulty`, `total_amount_inr`) |
| `/api/metrics` | GET | Returns live counters, simulation speed, `pi_connected`, and `last_pi_ack` |
| `/api/graph` | GET | Returns nodes and links for 3D visualization, with optional `?cluster_id=&hops=1` |
| `/api/clusters` | GET | Lists detected active clusters |
| `/api/clusters/{id}` | GET | Returns full cluster breakdown, accounts, timeline, and risk components |
| `/api/clusters/{id}/freeze` | POST | Enforces JWT officer authorization to freeze cluster accounts and block transfers |
| `/api/accounts/{id}` | GET | Returns diagnostic profile for an individual account (inflow, outflow, risk) |
| `/api/audit` | GET | Lists recent hash-chained immutable audit log records |
| `/api/audit/verify` | GET | Cryptographically validates the integrity of the entire SHA-256 hash chain |
| `/api/pi/ack` | POST | Receives HMAC-SHA256 authenticated acknowledgements from the Raspberry Pi desk |
| `/ws/dashboard` | WebSocket | Broadcasts `tx_batch`, `cluster_alert`, `cluster_updated`, `pi_ack`, and `frozen` |
| `/ws/pi` | WebSocket | Pushes alerts, keepalive pings, clear commands, and escalation warnings to the Pi desk |
| `/ws/auth/{id}` | WebSocket | Broadcasts `login_ok` upon successful biometric sensor verification |

---

## 🎭 Live Demonstration Playbook

Follow these steps to demonstrate the full platform live:

1. **Launch Dashboard**: Open `http://localhost:5173`. Notice the real-time transaction counter incrementing in the top bar.
2. **Inject Smurfing Ring**:
   - In the Adversarial Ring Injector panel, press key **`1`** (Smurfing), select **Medium (₹10L)**, and press **`Enter`**.
   - Notice the *"Attack in progress"* strip with live timer.
   - Within seconds, the ring is detected: an alert is raised, the row slides into the feed, and the 3D camera smoothly flies to frame the smurfing fan-out structure in the center of the canvas.
3. **Physical Hardware Desk Notification**:
   - The Raspberry Pi triggers its audio briefing and lights up the severity LED.
   - Speak *"explain"* or press the joystick: the desk plays the audio brief and updates the TopBar with the acknowledgement.
4. **Stealth Scenario Demonstration**:
   - In the launcher, press key **`5`** (Stealth) and click **Launch**.
   - Traditional fixed regulatory threshold baselines miss this ring completely because every hop is structured below ₹50,000.
   - Mule Hunter's temporal graph model identifies the coordinated multi-node structuring and raises a high-confidence alert.
5. **Biometric Emergency Freeze**:
   - In the right-hand inspection panel, view the plain-language summary and AI provenance badge.
   - Click **🛑 Freeze Cluster**.
   - The accounts are instantly frozen, subsequent transactions are blocked, prevented INR accumulates in the telemetry bar, and a `clear` signal is transmitted to silence the physical desk.
6. **Verify Cryptographic Audit Chain**:
   - Navigate to `/audit` or call `GET /api/audit/verify`.
   - Observe that all alert creations, logins, hardware acknowledgements, and freeze actions are cryptographically chained and validated (`ok: true`).

---

## 📄 License
This project is licensed under the MIT License — see the LICENSE file for details.
