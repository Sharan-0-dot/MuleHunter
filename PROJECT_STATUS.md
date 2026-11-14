# Mule Hunter — Project Status

## Milestone Checklist

| Milestone | Description | Status |
|---|---|---|
| **M0** | Contracts, folder skeleton, mock backend (`mock_backend.py`), sample audio (`.wav`), test suite (`test_mock.py`) | **Done** |
| **M1** | Simulator (`generator.py`, `attacks.py`), legit traffic + hard negatives, difficulty knobs, Step 0 fixes applied, `sim_check.py` | **Done, fixes applied** |
| **M2** | Detectors (sliding window, fan-out/in, cycles, mule chains, reconvergence) + cluster builder (`window.py`, `patterns.py`, `clusters.py`, `detect_check.py`) | **Done (Step A quality fixes passed)** |
| **M3** | XGBoost risk model, baseline threshold rule, evaluation script (`evaluate.py`) | **Done** |
| **M4a** | Live pipeline: simulator -> detection -> model -> alert -> summary -> wav -> push to Pi and dashboard (`engine.py`, `main.py`, `test_real.py`, `soak_real.py`) | **Done** |
| **M4b** | Backend hardening (officer role-based freeze, clear signal to Pi, hash-chained audit log) | **Done** |
| **M5** | Frontend 3D dashboard (React + Vite + `react-force-graph-3d`, direct dashboard compliance access) | **Done** |
| **M6** | Final integration & hardware desk live demo | In Progress |

---

## What Was Built

### Milestone M0 (Completed)
- **Folder structure**: Complete backend directory layout according to `01_PERSON1_SOFTWARE.md` section 3.
- **Mock backend (`backend/mock_backend.py`)**: Running on Port 8000 for hardware partner testing.
- **Sample Audio Files**: Pre-made sample WAVs for red, yellow, green alert scenarios.
- **Test suite (`backend/scripts/test_mock.py`)**: End-to-end integration test suite verifying WebSocket, HTTP trigger, audio download, valid/invalid HMAC ack, challenge/response, and auth.

### Milestone M1 (Completed, Step 0 Fixes Applied)
- **Data Models with Zero Label Leakage (`backend/app/sim/generator.py`)**:
  - `Transaction` dataclass with observable fields only: `tx_id`, `ts`, `src`, `dst`, `amount`, `kind`.
  - Separate `GroundTruth` and `DatasetGroundTruth` tracking `ring_id`, `ring_type`, `ring_accounts`, `ring_tx_ids`, and amounts for training/evaluation code.
  - Accounts pool of 2,000 accounts: 1,400 individuals, 400 merchants, 200 businesses.
- **Attack Ring Injectors (`backend/app/sim/attacks.py`)**:
  - 5 attack typologies: `smurfing`, `round_trip`, `mule_chain`, `hybrid`, `stealth`.

### Milestone M2 (Completed, Step A Quality Fixes Passed)
- **Sliding Graph Window (`backend/app/detect/window.py`)**:
  - `SlidingWindow(window_hours=48.0)` with exact eviction and per-(u, v) edge aggregates.
- **Quality Fixes (Step A Gates G1-G6 All Passed)**:
  - Ring span capped at <= 36.0h (< 0.75 * WINDOW_HOURS).
  - Cycle search pruned to SCCs (size 3-50), edge flow >= 5k INR: cap hit dropped from 53.55% to 0.00%, mean tick runtime = 22.18 ms.
  - Giant component prevention with strict core-account DSU sharing: legit p99 = 18.0 (<= 40), max = 20 (<= 80).
  - Mule chain pass-through upper bound (`0.75 <= pass_through <= 1.35`) preventing employer bridging.
  - Gate G4: Diff 1-3 found = 36/36 (100%), coverage = 90.4%, purity = 95.4%. Typology accuracy = 91.7%.

### Milestone M3 (Completed)
- **Baselines & Calibrated Model (`backend/app/detect/baseline.py`, `model.py`)**:
  - `baseline_fixed` (50k INR) & `baseline_tuned` ($T = \text{INR } 120,000$).
  - XGBoost classifier with Isotonic probability calibrator persisted to `model.json` and `calibrator.joblib`.
  - Evaluation on validation split: Rules + XGBoost achieved F1 = 0.7390 (**35.5x improvement** over fixed baseline), Ring Detected Recall = 96.7%, Prevented INR = 10,835,303.79 INR.

### Milestone M4a (Completed)
- **Step 0 — Exact Risk Bands Restored & Full Grid Evaluation**:
  - Restored master bands in `.env` and `config.py`: `ALERT_MIN=0.40`, `GREEN_MAX=0.65`, `YELLOW_MAX=0.85`.
  - Evaluated full grid (110 simulation runs: 4 types x 5 diffs x 5 seeds + 5 stealth + 5 legit) to `backend/data/metrics_val_full.json`.
  - True-ring clusters reach calibrated risk score 1.0000 across p10 to p100 deciles (readily reaching red >= 0.85).
  - Legit clusters max calibrated risk score = 0.3208 (< 0.40 ALERT_MIN).
  - Stealth attack scenario: Rules + XGBoost achieved F1 = 0.7051 and Ring Recall = 80.0%, while fixed baseline collapsed to F1 = 0.0156 and Ring Recall = 20.0%, and tuned baseline scored F1 = 0.0093 and Ring Recall = 0.0%.
- **Step 1 — Configuration & Environment**:
  - Configured `REAL_PORT=8001`, `PUBLIC_BASE_URL` (auto-detected LAN IP fallback), `OPENROUTER_*`, `LLM_*`, and timing parameters. Confirmed `.env` is gitignored.
- **Step 2 — Real-Time Streaming & Alert Engine (`backend/app/engine.py`)**:
  - Owns simulated clock (1x-20x), 48h sliding window, candidate clustering, `ClusterTracker` with stable `C-xxxx` IDs.
  - Background asyncio wall-clock loop advancing every ~500 ms with detection ticks every 15 sim-minutes.
  - Strict push sequence: SQLite DB persist -> Audio verify -> `/ws/pi` push -> `/ws/dashboard` broadcast.
  - Escalation monitor: dispatches `{"type": "escalate"}` to Pi if no voice/joystick ack within `listen_seconds + 5` (30s).
- **Step 3 — Spoken Summaries & Audio Generation (`backend/app/summary/*`)**:
  - `templates.py`: Deterministic spoken-friendly templates under 45 words ending with `"Log in to the dashboard for linked accounts."`
  - `llm.py`: Optional OpenRouter LLM polish with strict validation (number preservation, exact closing sentence, <= 55 words) and silent fallback.
  - `tts.py`: `pyttsx3` WAV synthesizer generating mono 16-bit PCM <= 25s with fallback to pre-made WAVs on timeout/failure.
- **Step 4 — Database Persistence (`backend/app/db.py`)**:
  - SQLite tables: `alerts`, `clusters`, `alert_tx`, `officers`, `pi_events`.
- **Step 5 — REST API & WebSockets (`backend/app/main.py`)**:
  - Runs on port 8001.
  - Implements `/api/sim/start`, `/stop`, `/reset`, `/attack`, `/api/graph`, `/api/clusters`, `/api/accounts/{id}`, `/api/metrics`, `/api/pi/ack` (HMAC-SHA256 verified), `/ws/pi`, `/ws/dashboard`, `/ws/auth/{id}`.
- **Step 6 — Contract Test Suite (`backend/scripts/test_real.py`)**:
  - Executed against live server on port 8001. All 9 contract checks passed:
    - Master 8.2 alert fields and types verified.
    - WAV audio downloaded: mono 16-bit PCM, 22050 Hz, 15.32s duration (<= 25s limit).
    - HMAC signature verification: 200 on valid, 401 on forged signature.
    - Dashboard events received: `tx_batch`, `cluster_alert`, `pi_ack`.
    - Attack launch to alert pushed latency: 52.33s wall-clock time.
- **Step 7 — 10-Minute Soak Test (`backend/scripts/soak_real.py`)**:
  - Ran for 10 minutes at `SIM_SPEED=10` (~100 sim-hours), processing 18,750 transactions.
  - Injected 6 attacks across difficulties 1-4: **100.0% ring recall (6 / 6 rings alerted)**.
  - Mean detection tick runtime: 248.88 ms (< 500 ms target).
  - RAM memory growth: +0.1 MB (4.2 MB -> 4.3 MB).
- **Step 8 — Hardware Teammate Handoff (`FRIEND_HANDOFF.md`)**:
  - Complete guide created detailing port 8000 endpoints, curl commands, WebSocket schemas, and HMAC signing.

### Milestone M4b (Completed)
- **Live Pipeline Fixes & Diagnostic Resolution**:
  - Root cause of 320 false alerts / sim-hour identified: streaming path generated payroll & large purchases every 500ms due to misapplied `max(1, ...)` thresholds.
  - Unified `TransactionStream` with `generate_dataset` code path (identical 6,431 txs, identical kind mix, identical amount distribution across 24h).
  - Implemented `engine.run_headless(sim_hours, attacks=[...])` advancing identical detection, window, clustering, and tracker code without wall-clock sleeps (48h replay in 25.5s).
  - Tracker continuity: Replaced Jaccard with overlap coefficient matching ($|A \cap B| / \min(|A|,|B|) \ge 0.5$) with 4-tick grace retention.
  - Alert hygiene: `confirm_ticks=2` consecutive ticks required before initial alert; re-alerting restricted to upward band jumps.
  - Gate G1 Passed: 0.000 false alerts / sim-hour (limit $\le 2.0$), 5/6 rings alerted (limit $\ge 5$), mean tick runtime 60.68ms.
- **Severity Scoring & Dynamic Ring Sizing**:
  - Alert trigger decoupled from urgency severity: trigger on $p \ge 0.40$, composite $\text{risk\_score} = 0.5 \cdot p + 0.5 \cdot \text{exposure}$, where $\text{exposure} = \min(1, \frac{\text{total\_amount\_inr}}{2,500,000})$.
  - Verified sizing on round_trip diff 2: 3 Lakh -> GREEN, 10 Lakh -> YELLOW, 25 Lakh -> RED.
  - Exposes `risk_components: {"probability": p, "exposure": exposure}` on `/api/clusters/{id}` and dashboard WebSocket event.
  - Updated `00_MASTER.md` sections 8.1 and 8.5.
- **Login-Protected Freeze & Real-Time Defense Signals**:
  - `POST /api/clusters/{id}/freeze` enforces `Authorization: Bearer <jwt>` with role `officer` or `admin` (401 on unauthorized).
  - Marks accounts frozen; engine drops subsequent transactions and accumulates `prevented_inr`.
  - Pushes `clear` with `alert_id` to `/ws/pi` (turns off LEDs/buzzer).
  - Broadcasts `frozen` event to `/ws/dashboard`.
  - `/api/sim/reset` clears frozen accounts and counters cleanly.
- **Cryptographic Tamper-Evident Audit Trail**:
  - `audit_log` table with `hash = sha256(prev_hash + canonical_json)`.
  - Logs `alert_created`, `pi_ack`, `escalate`, `login_ok`, `login_failed`, and `freeze`.
  - `GET /api/audit?limit=50` and `GET /api/audit/verify -> {"ok": bool, "entries": n, "first_bad_index": null}`.
  - `backend/scripts/tamper_demo.py`: Demonstrates direct database tampering immediately flipping verification to `ok=False`.
- **End-to-End Contract Verification (`backend/scripts/test_real.py`)**:
  - 100% pass across all 11 integration checks on port 8001.

### Milestone M5 (Completed & Hardened for Live Demo)
- **Frontend Architecture (`frontend/`)**:
  - Stack: Vite + React 18, `react-router-dom`, `react-force-graph-3d`, `react-force-graph-2d`, `three`, `recharts`.
  - Dark theme with accent `#7B3FC4`, CSS variables, projector-readable body font ($\ge 16\text{px}$).
  - Full Mock Mode (`VITE_MOCK=1`) and Live Server mode (`VITE_MOCK=0`, port 8001).
- **Task 1 — Attack Launcher Diagnosis & Complete Rebuild**:
  - Diagnosed failure: `frontend/.env` targeted port 8000 instead of 8001, simulation stopped state blocked ring execution silently, and UI lacked progress timer/state.
  - Rebuilt `AttackLauncher.jsx`: Typology buttons (`smurfing`, `round_trip`, `mule_chain`, `hybrid`, `stealth`), difficulty slider 1–5 (hidden for stealth), ring sizes (₹3L, ₹10L, ₹25L sending `total_amount_inr`), and unified launch button (`idle`, `sending`, `launched`).
  - "Attack in progress" strip: Real-time timer ("detecting... 12 s"), switches to "Alert raised" when `cluster_alert` arrives, or warning after 60s. Inline "Start simulation" button when sim is paused.
  - Dedicated Speed control with "Demo 20x" preset and live status dot (running/stopped).
  - Keyboard shortcuts: Keys 1–5 select typology, Enter launches (disabled inside form inputs).
- **Task 2 — Graph Centering & Viewport Sizing**:
  - Diagnosed right-shift bug: `ForceGraph3D/2D` defaulted to `window.innerWidth` (1920px) rather than center column width (1200px), placing canvas origin $(0,0)$ at $80\%$ across container. Center grid column lacked `min-width: 0`.
  - Sizing fix: Integrated `ResizeObserver` observing `.graph-canvas-wrapper`, passing exact `width` and `height` props to `ForceGraph3D` and `ForceGraph2D`. Center grid column given `minmax(0, 1fr)`.
  - Smart camera centering: Computes cluster bounding centroid and radius $R$, framing cluster with $D = \max(180, \min(650, R \cdot 2.8 + 120))$ via `cameraPosition(..., 800)`. Re-centers strictly on explicit selection or new alert arrival, never jumping on 3s data polls.
  - Added dedicated "🎯 Re-center" button in toolbar and `Esc` key shortcut. Layout stabilized with gentle d3 center force and `d3VelocityDecay(0.25)`.
- **Task 3 — Projector Demo Polish**:
  - Alert animations: New alerts trigger `@keyframes alertSlideIn` and level colour pulse. Red alerts trigger a 2-second red border pulse around the graph (`@keyframes redBorderPulse`).
  - Top bar Raspberry Pi indicator: Green dot when `pi_connected > 0`, grey when standby, displaying the last Pi event phrase (e.g. "Voice keyword heard", "Audio played") from `last_pi_ack`.
  - Empty states: Clean empty state in alert feed ("No alerts yet. Launch an attack.") and graph loading overlay.
  - Fullscreen / Presentation mode (`F` key or button): Maximizes graph and alert feed, hides secondary navigation, preserves Launcher and Freeze button.
  - Readability: Summary text in DetailPanel enlarged to 18px (`.large-summary-text`), plain-language typology phrases, and provenance badge for `summary_source` ("AI Polished" / "Template") with `llm_status`.
- **Build Verification**: `npm run build` passes with 0 errors in 8.08s. All 5 typologies verified against live backend on 8001 and mock server.

---

## Files Created / Modified in M4b

- `backend/app/audit.py`
- `backend/app/engine.py`
- `backend/app/main.py`
- `backend/app/sim/generator.py`
- `backend/app/sim/attacks.py`
- `backend/app/detect/tracker.py`
- `backend/app/db.py`
- `backend/scripts/soak_real.py`
- `backend/scripts/test_real.py`
- `backend/scripts/tamper_demo.py`
- `backend/scripts/test_sizing.py`
- `backend/scripts/compare_traffic.py`
- `00_MASTER.md`
- `FRIEND_HANDOFF.md`
- `PROJECT_STATUS.md`
- `NOTES.md`

---

## Known Issues

- **Port 8000 Mock Backend**: `backend/mock_backend.py` is running untouched on port 8000 for hardware partner testing.
- **Port 8001 Real Backend**: Real backend running with 100% contract compliance on port 8001 (`REAL_PORT`). Ready to move to port 8000 when team gives the signal.

---

## Decisions Made

- **One Traffic Generator**: Replaced divergent streaming generator with chunks drawn from `generate_dataset` for zero distribution shift between batch and streaming.
- **Overlap Matching with Grace**: Overlap coefficient matching preserves cluster identity during temporal evolution, and 4-tick grace retention prevents cluster ID fragmentation.
- **Composite Urgency Scoring**: Decoupled binary detection confidence from urgency severity by incorporating transaction volume exposure ($\text{risk\_score} = 0.5 \cdot p + 0.5 \cdot \text{exposure}$).

---

## What's Next

- **Milestone M6**: Final system rehearsal, live Pi hardware pairing, and pitch deck preparation.
