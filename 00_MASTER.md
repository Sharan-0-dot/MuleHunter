# 00 — MASTER: "Mule Hunter" (Build Beyond'26, PS 2.1)

> Read this file FIRST, then your personal file (01 = Person 1 software, 02 = Person 2 hardware).
> If you are an AI coding assistant: this is the single source of truth. If your file and this one disagree, THIS file wins. Do not invent new endpoints, field names or pins without telling the human.

---

## 1. What we are building (one paragraph)

**Mule Hunter** is a streaming anti-money-laundering (AML) system for **PS 2.1: Graph-Based Detection of Layered Money Laundering Networks**. It models transactions as a temporal, directed, weighted graph, detects fan-in/fan-out dispersion, cyclic round-tripping and rapid pass-through mule chains, groups them into ranked clusters, labels each with its typology, writes a plain-language summary of the money trail, and reports precision/recall/F1 against a threshold-based baseline. On top of this, a **physical compliance desk** (Raspberry Pi) alerts the bank officer with LEDs and a buzzer, listens for the spoken keyword "explain", and reads the summary aloud. The **web dashboard** provides an interactive compliance workstation with an active officer session, where a clickable 3D graph shows the cluster and every linked account, and the officer can approve an emergency freeze.

**We are entering PS 2.1 ONLY.** Hardware, voice and the attack simulator are presentation/evaluation layers for the same problem statement. In the pitch: the attack simulator is "adversarial evaluation data", the Pi is the "alert delivery channel", the dashboard provides "maker-checker officer authorization".

## 2. Team and ownership

| | Person 1 (Sharan) | Person 2 (Friend) |
|---|---|---|
| Owns | ALL software: simulator, detection, ML, metrics, summaries, TTS, backend API, 3D web dashboard | ALL hardware: Pi alert box (LEDs, buzzer, audio playback, joystick / voice ack) |
| Tools | Antigravity CLI + Gemini Pro | Own laptop, SSH into the Pi, no AI tooling (so file 02 is very explicit) |
| Context file | 01_PERSON1_SOFTWARE.md | 02_PERSON2_HARDWARE.md |

Rule: after Person 1's software is stable, Person 1 helps with hardware (wiring, Pi debugging, demo rehearsal).

## 3. Hardware inventory

Raspberry Pi 3B+ (1GB RAM), USB mic, speaker (3.5mm or USB), piezo buzzer, red/yellow/green LEDs + resistors, joystick (use push-button or stick click), batteries / power bank, jumper wires, breadboard.

## 4. Architecture

```
                         ┌──────────────────────── LAPTOP (demo laptop = Person 1's) ────────────────────────┐
                         │                                                                                  │
 Simulator ─tx stream──► │  FastAPI backend (port 8000)                                                     │
 (attack launcher)       │   ├─ Sliding-window temporal graph (NetworkX)                                    │
                         │   ├─ Detectors: fan-out/fan-in, cycles, mule chains                              │
                         │   ├─ Cluster builder + XGBoost risk score + typology label                       │
                         │   ├─ Summary (template, optional Gemini polish) ──► TTS ──► static/audio/*.wav   │
                         │   ├─ SQLite (tx, clusters, accounts, officers, audit log hash-chained)           │
                         │   ├─ REST + WebSocket (/ws/dashboard, /ws/pi)                                    │
                         │   └─ Serves .wav files at /static/audio/                                         │
                         │                                                                                  │
 Browser (React+Vite) ◄──┤  3D clickable graph, alert feed, attack launcher, metrics page, audit trail     │
                         └──────────────────────────────────────────────────────────────────────────────────┘
                                     │  Wi-Fi (phone hotspot / laptop hotspot)
                                     ▼
                  RASPBERRY PI 3B+ ("compliance desk")
                   WebSocket client ◄── /ws/pi  (alert JSON)
                   downloads .wav → sets LED (G/Y/R) → piezo → listens 25s (Vosk, keyword "explain")
                   "explain" heard OR joystick pressed → plays .wav → POST /api/pi/ack (HMAC signed)
```

Key design choices (do not change without agreement):
- **Pi is a WebSocket CLIENT** of the backend (it dials out). The backend never needs the Pi's IP.
- **Direct compliance access**: The browser dashboard connects directly to the backend with an active compliance officer session, allowing instant investigation and one-click freeze.
- **TTS runs on the laptop**; the Pi only downloads and plays a pre-made `.wav`.
- **Voice is keyword-only** ("explain"), via Vosk with a restricted grammar. Joystick button is a silent fallback for the same action.
- **No Kafka.** The simulator feeds an in-process queue; updates go to the browser over WebSocket.

## 5. End-to-end demo flow

1. Dashboard shows normal live traffic (3D graph, mostly calm).
2. Presenter clicks **Launch Attack → Smurfing / Round-trip / Mule chain / Hybrid / Stealth**.
3. Backend detects the pattern, builds the cluster, scores risk, labels typology, writes the summary, generates the `.wav`, persists everything.
4. Backend pushes an `alert` message to the Pi over `/ws/pi`; browser gets `cluster_alert` and flies the camera to the cluster (nodes turn red).
5. Pi: LED goes green/yellow/red by risk level, piezo buzzes, mic opens for ~25 s.
6. Officer says "**explain**" (or presses the joystick). Pi plays the summary, which ends with "Check the dashboard for linked accounts."
7. Officer views the cluster on the dashboard; active session immediately displays cluster details.
8. Officer clicks nodes (account details), reviews linked accounts, approves **Freeze cluster**. Frozen accounts turn ice-blue, further transfers from them are blocked, and the UI shows "₹ prevented".
9. Metrics page: precision/recall/F1 for baseline vs ours, plus F1-vs-attack-difficulty chart. Audit page shows the hash-chained log (alert → officer ack → freeze).

## 6. Network rules (read before touching Wi-Fi)

- Use a **phone hotspot** (or laptop hotspot). College Wi-Fi often blocks device-to-device traffic. Test in hour 1. Keep an Ethernet cable as a backup path to the Pi.
- Backend binds `0.0.0.0:8000`. Pi config has `BACKEND_URL=http://<laptop-ip>:8000`.
- Laptop firewall: allow inbound TCP 8000 (Windows: allow Python through Private network).
- Keep everything in a shared `.env` style config (values below).

## 7. Shared configuration (identical on both sides)

```
BACKEND_URL      = http://<LAPTOP_IP>:8000
SHARED_SECRET    = mulehunter-demo-secret      # change before the demo, used for HMAC
LISTEN_SECONDS   = 25
AUDIO_FORMAT     = WAV, PCM 16-bit, mono, 22050 Hz (or 16000/44100; Pi plays any via aplay)
KEYWORD          = explain
```

**HMAC signing (used by Pi ack):**
header `X-Signature` = hex of HMAC-SHA256(SHARED_SECRET, raw request body bytes).
Python reference (both sides use exactly this):
```python
import hmac, hashlib
sig = hmac.new(SHARED_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()
headers = {"X-Signature": sig, "Content-Type": "application/json"}
```
Backend rejects missing/invalid signatures with 401.

## 8. Interface contracts (SINGLE SOURCE OF TRUTH)

### 8.1 Risk levels
`risk_score` is a **composite severity** in [0, 1] combining model probability and exposure:

```
p        = calibrated model probability (triggers alert when p >= 0.40)
exposure = min(1.0, total_amount_inr / 2,500,000)
risk_score = 0.5 * p + 0.5 * exposure
```

Alerts are only raised when `p >= ALERT_MIN (0.40)`. Urgency bands apply to the composite `risk_score`:
- `green`:  0.40 – 0.65 (low)
- `yellow`: 0.65 – 0.85 (medium)
- `red`:    >= 0.85 (high)

`risk_components: {"probability": p, "exposure": exposure}` is exposed on `GET /api/clusters/{id}` and the `cluster_alert` dashboard WebSocket event (not on the Pi alert payload).

Severity is **composite risk**, not just amount. (Thresholds are tunable by Person 1; the three level names are fixed.)

### 8.2 Alert: backend → Pi (WebSocket `ws://<laptop>:8000/ws/pi`)
```json
{
  "type": "alert",
  "alert_id": "A-0007",
  "cluster_id": "C-0007",
  "level": "red",
  "risk_score": 0.91,
  "typology": "round_tripping",
  "accounts_count": 7,
  "total_amount_inr": 420000,
  "wav_url": "http://<laptop-ip>:8000/static/audio/C-0007.wav",
  "listen_seconds": 25,
  "created_at": "2026-11-15T10:42:11Z"
}
```
`typology` ∈ `smurfing_fan_out_fan_in | fan_out | fan_in | round_tripping | mule_chain | hybrid`.
Other messages on the same socket:
```json
{"type": "escalate", "alert_id": "A-0007"}     // no officer response within the window → Pi blinks LED
{"type": "clear",    "alert_id": "A-0007"}     // officer froze/closed the cluster → Pi stops, LED off
{"type": "ping"}                                // keepalive every 10s; Pi may reply {"type":"pong"}
```

### 8.3 Pi → backend acknowledgement (HTTP POST `/api/pi/ack`, HMAC signed)
```json
{ "alert_id": "A-0007", "event": "received", "ts": "2026-11-15T10:42:12Z" }
```
`event` ∈ `received` (wav downloaded, LED+buzzer started) | `explain_voice` | `explain_joystick` | `played` (finished playing) | `timeout` (no explain within window). Response: `{"ok": true}`.

### 8.4 Compliance Officer Session (Maker-Checker Authorization)
The web dashboard operates with a pre-authenticated Compliance Officer session (`Officer A`, role `officer`, ID `O-1`) designed for hackathon stage review:
- Every action (such as freezing accounts) is authenticated and tied to Officer A in the SHA-256 audit ledger.
- The JWT bearer token is automatically provided by the dashboard client.
- Mutate endpoints verify officer/admin role permissions before executing freeze commands.
- Optional stage safety fallback: `POST /api/auth/password {"username":"officer","password":"demo123"}` → `{token, officer}`.

### 8.5 REST API (Person 1 implements, all JSON; CORS open)
| Method + path | Purpose |
|---|---|
| `POST /api/sim/start`, `/stop`, `/reset` | control background traffic (`start` body: `{"speed":1..20}`) |
| `POST /api/sim/attack` | body `{"type":"smurfing\|round_trip\|mule_chain\|hybrid\|stealth","difficulty":1..5,"total_amount_inr":300000}` (`total_amount_inr` optional; scales ring total; stealth always structures below 50k threshold) |
| `GET /api/graph?cluster_id=C-0007&hops=1` | nodes+links for 3D view (focused subgraph; default = live sampled graph) |
| `GET /api/clusters`, `GET /api/clusters/{id}` | cluster list / detail (accounts, typology, risk, summary text, timeline) |
| `GET /api/accounts/{id}` | node details (see 8.6) |
| `POST /api/clusters/{id}/freeze` | requires JWT / officer session; freezes all accounts in cluster; sends `clear` to Pi |
| `GET /api/metrics` | precision/recall/F1 baseline vs ours, F1-by-difficulty, latency, ₹ prevented |
| `GET /api/audit` | hash-chained audit entries |
| `POST /api/pi/ack` | Pi acknowledgement (8.3) |
| `POST /api/auth/password` | optional manual auth check |
| `GET /static/audio/{cluster_id}.wav` | summary audio |
| `POST /mock/trigger?level=red` | **mock backend only** (see 8.7) |

WebSockets: `/ws/dashboard` (browser events: `tx_batch`, `cluster_alert`, `cluster_updated`, `pi_ack`, `frozen`), `/ws/pi` (8.2).

### 8.6 Account (node) detail shape
```json
{ "account_id":"ACC-1042", "type":"individual|merchant|business", "cluster_id":"C-0007",
  "risk":0.88, "in_amount":210000, "out_amount":204000, "retention_ratio":0.03,
  "in_degree":1, "out_degree":3, "median_hold_seconds":420, "frozen":false,
  "recent_tx":[{"from":"ACC-1042","to":"ACC-2210","amount":68000,"ts":"..."}] }
```

### 8.7 Mock backend (Person 1 ships this within the FIRST HOUR so hardware can proceed in parallel)
A tiny FastAPI app `mock_backend.py` implementing `/ws/pi`, `/api/pi/ack`, `/api/auth/*`, `/static/audio/*.wav` with 3 pre-made sample wavs (`green.wav`, `yellow.wav`, `red.wav`) and `POST /mock/trigger?level=red|yellow|green` which pushes an alert to the Pi. Person 2 builds and tests against it; the real backend later replaces it with no hardware code changes.

## 9. Detection and evaluation (summary; details in file 01)

- Streaming sliding window (simulated hours) over a temporal directed weighted graph.
- Detectors: **fan-out / fan-in** (many counterparties, similar amounts, short window), **time-respecting cycles** (3–6 hops, high amount retention), **mule chains** (pass-through ratio ≥ 0.9, short hold time, ≥ 3 consecutive nodes), and **reconvergence** (fan-out from a source whose branches meet at a common destination).
- Detected pattern instances are merged (union-find on shared accounts) into **clusters**; an **XGBoost** model scores each cluster 0–1 from cluster features; typology = dominant pattern.
- Legit traffic contains **hard negatives** (payroll fan-out, merchant fan-in, big one-off purchases) so the model must learn to separate them. This is the honest part of our evaluation.
- Baseline: per-transaction amount threshold (threshold tuned on training data so it is a fair baseline).
- Protocol: train on seeds 1–5, difficulty 1–3; test on held-out seeds 100–104, difficulty 1–5. Report account-level precision/recall/F1, F1-vs-difficulty for baseline vs ours, detection latency, ₹ prevented by freeze.
- Headline claim: "our detector stays robust as launderers adapt (split amounts, delays, decoy hops); a threshold rule collapses."

## 10. Timeline (15–16 hours) with sync checkpoints

| Hour | Person 1 (software) | Person 2 (hardware) | Sync |
|---|---|---|---|
| 0–1 | **[DONE - M0]** Repo, `.env`, **mock_backend.py + sample wavs**, share with Person 2 | Flash/SSH Pi, Wi-Fi via hotspot, install Python deps, test LEDs/piezo/mic/speaker individually | **H1: contracts agreed, mock backend running, Pi reaches it** |
| 1–5 | **[DONE - M1 & M2]** Simulator + attack generators, graph window, detectors | Pi alert service (WS client, LED, buzzer, wav download/play, joystick) | |
| 5–8 | **[DONE - M3]** Clusters, features, XGBoost, baseline, metrics | Vosk keyword listener, state machine, ack POSTs, auto-start on boot | **H8: first real alert → Pi lights/buzzes/plays** |
| 8–12 | **[DONE - M4a & M4b]** FastAPI endpoints, summaries, TTS, 3D dashboard, node panel, attack launcher | Pi alert integration with real backend, audio speaker playback, physical ack | |
| 12–14 | **[DONE]** Freeze flow, audit chain, metrics page, polish | Pi alert desk enclosure/cable tidy, noise testing | **H13: physical Pi alert desk works end to end** |
| 14–16 | Full demo rehearsals (×3), fix bugs, record backup video | Rehearsals, power/cables, spare fallback checks | **No new features after H14** |

## 11. Cut order if we fall behind (cut from the top)

1. Hash-chained audit page polish, Gemini summary polish (template summary is fine)
2. Direct dashboard officer bypass (active session enabled by default)
3. OLED status screens
4. 3D → keep 2D fallback toggle
5. Escalation behaviour
**NEVER cut:** held-out metrics + adversarial difficulty chart, the Pi alert (LED+buzzer+explain playback), the clickable graph.

## 12. Demo script (about 5 minutes)

1. 20 s: problem (rule-based AML checks one transaction at a time).
2. 30 s: show live graph, mention hard negatives (payroll, merchants) in normal traffic.
3. 60 s: launch **Round-trip** → Pi buzzes red → say "explain" → speaker reads summary.
4. 40 s: review cluster on dashboard → click nodes → show linked accounts → freeze → "₹ prevented".
5. 60 s: launch **Stealth hybrid** (amounts under the threshold). Baseline misses it, ours catches it. Show metrics page.
6. 30 s: architecture slide + conclusions.

Fallbacks: joystick instead of voice; pre-recorded backup video; sample wavs stored on the Pi.

## 13. Likely judge questions

- *Why not just a threshold?* → Show the stealth attack the baseline misses.
- *Is the data real?* → No, synthetic with ground truth; we say so. IBM synthetic AML dataset can be mentioned as a validation path if time permits.
- *How does it scale?* → Sliding window bounds graph size; detectors are incremental; prototype not bank-scale.
- *False positives?* → Hard negatives in the data; risk levels so low-risk gets low-urgency alerts.

## 14. Working rules

- One git repo: `backend/` + `frontend/` (Person 1), `pi/` (Person 2). Commit small, often.
- Contract change = message the other person first, then edit THIS file.
- Test with the real backend on port 8000.
- Keep a printed/phone checklist for demo setup (power, hotspot, backend running, Pi service running).
