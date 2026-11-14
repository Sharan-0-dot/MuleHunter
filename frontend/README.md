# Mule Hunter — Frontend Command Desk

A high-performance AML compliance dashboard built with **React 18 + Vite**, **react-force-graph-3d**, **react-force-graph-2d**, **Three.js**, and **Recharts**. Designed for high-contrast presentation visibility on projectors (dark theme with `#7B3FC4` accent and $\ge 16\text{px}$ readable typography).

---

## Quick Start

### 1. Run in Mock Mode (Default Offline Demo)
Mock mode simulates the full streaming pipeline in-browser with fake clusters, a 7-node laundering ring, background transaction ticks, Pi desk acknowledgements, biometric fingerprint login, and freeze events without needing the backend running.

```bash
cd frontend
# Ensure .env has:
# VITE_API_BASE=http://localhost:8001
# VITE_MOCK=1

npm install
npm run dev
```
Open [http://localhost:5173](http://localhost:5173).

---

### 2. Run with Real Backend (Port 8001)
To connect directly to the live streaming FastAPI backend:

```bash
cd frontend
# In .env, set:
# VITE_API_BASE=http://localhost:8001
# VITE_MOCK=0

npm run dev
```

---

### 3. Production Build
```bash
npm run build
npm run preview
```

---

## Implemented Pages & Verified Features

### 1. `/login` — Biometric Desk Scanner & Fallback
- **Physical Biometric Challenge**: Initiates `POST /api/auth/challenge` to obtain a 30-second challenge ID and connects to `/ws/auth/{challenge_id}`.
- **30s Countdown**: Visual countdown timer; displays a "Regenerate Challenge" button when expired.
- **Mock Demo Simulator**: In mock mode, a "Simulate Desk Fingerprint Tap" button instantly triggers the sensor match event.
- **Officer Session**: On `login_ok`, stores JWT token and officer payload in `sessionStorage` (`mh_token`, `mh_officer`) and auto-redirects to `/`.
- **Stage Safety Fallback**: Form for username/password (`officer` / `demo123`). Shows reasons if authentication fails.

### 2. `/` — Real-Time 3D Compliance Dashboard
- **Top Bar**:
  - Controls: Start, Stop, Reset (`POST /api/sim/start`, `/stop`, `/reset`), and simulation speed multiplier (1×–20×).
  - Live Counters: Real-time transactions processed, alert counter, and prevented INR (polled every 3s from `/api/metrics`).
  - WebSocket indicator: Live pulse dot (green = connected, yellow = reconnecting, red = disconnected).
  - Officer Chip: Shows authenticated officer name and Logout button (or Login prompt).
- **Left: Alert Feed**:
  - Live feed loaded from `GET /api/clusters` and updated in real-time via `/ws/dashboard` (`cluster_alert`, `cluster_updated`, `pi_ack`, `frozen`).
  - Capped at the latest 100 alerts to prevent UI lag.
  - Rows show: Risk level chip (green / yellow / red), human-readable typology, account count, formatted amount in Lakh/Crore, risk percentage, and timestamp.
  - Raspberry Pi Desk status badges: updates dynamically from `pi_ack` events (`⚡ Received`, `🎙️ Explain Heard`, `🔊 Audio Played`, `⏱️ Timeout`).
  - Clicking any alert highlights and focuses the cluster.
- **Center: 3D Force Graph (`react-force-graph-3d`) + 2D Fallback (`react-force-graph-2d`)**:
  - Smooth Object Merging: Merges incoming graph snapshots by node ID in-place, preserving coordinates and velocities so node positions never jump.
  - Dynamic Coloring: Risk-based color spectrum (calm blue $\to$ yellow $\to$ red), volume-scaled radius, and ice-blue (`#38BDF8`) for frozen accounts.
  - Focused Subgraphs: Clicking an alert focuses the cluster subgraph + 1-hop neighbours and dims background nodes; camera flies smoothly to the cluster.
  - Flow Particles: Directional particles on transaction edges with width scaled by monetary volume.
  - Click-to-Inspect: Clicking any node flies the camera directly to it and loads its detailed profile in the right panel.
  - Controls: 3D/2D toggle button, Esc key clears selection, and hard cap at 600 nodes.
- **Right: Detail Inspection Panel**:
  - Node Details: Conforms to Master 8.6 contract (`account_id`, `type`, `cluster_id`, `risk`, `in_amount`, `out_amount`, `retention_ratio`, `in_degree`, `out_degree`, `median_hold_seconds`, `frozen`, and `recent_tx` table).
  - Cluster Details: Typology, risk decomposition, plain-language summary, clickable accounts list (focuses node in graph), and compliance timeline.
  - Freeze Cluster Action: Disabled with tooltip *"Log in as officer"* when unauthenticated; when logged in, calls `POST /api/clusters/{id}/freeze` with Bearer token and displays prevented INR from the `frozen` event.
- **Bottom-Left: Adversarial Attack Launcher**:
  - Prominent control panel for live judging demonstrations.
  - 5 Typologies: `Smurfing`, `Round-Trip`, `Mule Chain`, `Hybrid`, `Stealth`.
  - Difficulty knob: Slider from 1 to 5 (automatically hidden for Stealth attacks which strictly structure below threshold).
  - Volume sizes: Small (₹3L), Medium (₹10L), Large (₹25L).
  - Big prominent **Launch Attack Ring** button dispatching to `POST /api/sim/attack`.

### 3. `/metrics` — Benchmarking & Evaluation Page
- **Synthetic Data Banner**: Displays *"Synthetic data, validation split"* badge.
- **Metrics Table**: Account-level precision, recall, F1, and ring recall comparing Fixed Baseline (50k), Tuned Baseline ($T = \text{₹120k}$), Rules Only, and Rules + XGBoost.
- **Recharts Visualization**: Interactive line chart showing F1 score across evasion difficulties 1 through 5.
- **Stealth Scenario Breakdown**: Dedicated analysis showing how naive threshold baselines collapse to $\approx 1\%$ F1 while graph-based ML maintains $\approx 70.5\%$ F1.
- **Operational Metrics**: False alerts per legit day ($0.00$), median detection latency, and total INR prevented.

### 4. `/audit` — Immutable Audit Ledger
- Shows SHA-256 hash-chained event records (alert creation, Pi acknowledgements, biometric logins, and freeze orders).
- **Verify Chain Action**: Button calls `GET /api/audit/verify` displaying a green checkmark on valid chain or red on mismatch; gracefully handles 404 with *"Audit verification not available yet"* if backend hardening (M4b) is in progress.
