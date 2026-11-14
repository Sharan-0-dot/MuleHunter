import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { apiFetch, IS_MOCK } from "../api/client";

export function formatINR(val) {
  if (val === null || val === undefined || isNaN(val)) return "₹0";
  const num = Number(val);
  if (num >= 10000000) {
    return `₹${(num / 10000000).toFixed(2)} Cr`;
  }
  if (num >= 100000) {
    return `₹${(num / 100000).toFixed(2)} L`;
  }
  return `₹${num.toLocaleString("en-IN")}`;
}

export default function TopBar({
  metrics,
  simSpeed,
  setSimSpeed,
  wsStatus,
  officer,
  onLogout,
  onToast,
}) {
  const navigate = useNavigate();

  const handleStart = async () => {
    try {
      await apiFetch("/api/sim/start", {
        method: "POST",
        body: JSON.stringify({ speed: Number(simSpeed) }),
      });
      onToast("Simulator started", "success");
    } catch (err) {
      onToast(`Failed to start simulator: ${err.message}`, "error");
    }
  };

  const handleStop = async () => {
    try {
      await apiFetch("/api/sim/stop", { method: "POST" });
      onToast("Simulator stopped", "info");
    } catch (err) {
      onToast(`Failed to stop simulator: ${err.message}`, "error");
    }
  };

  const handleReset = async () => {
    try {
      await apiFetch("/api/sim/reset", { method: "POST" });
      onToast("Simulator reset", "info");
    } catch (err) {
      onToast(`Failed to reset simulator: ${err.message}`, "error");
    }
  };

  const handleSpeedChange = async (e) => {
    const val = Number(e.target.value);
    setSimSpeed(val);
    try {
      await apiFetch("/api/sim/start", {
        method: "POST",
        body: JSON.stringify({ speed: val }),
      });
    } catch (_) {}
  };

  return (
    <header className="topbar">
      <div className="topbar-brand">
        <div className="topbar-logo">
          <span>⚡ Mule Hunter</span>
          <span className="badge-aml">PS 2.1</span>
          {IS_MOCK && (
            <span
              style={{
                fontSize: "10px",
                background: "#F59E0B",
                color: "#000",
                padding: "2px 6px",
                borderRadius: "4px",
                fontWeight: 700,
              }}
            >
              MOCK MODE
            </span>
          )}
        </div>
        <nav className="nav-links">
          <NavLink to="/" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
            Dashboard
          </NavLink>
          <NavLink to="/metrics" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
            Metrics
          </NavLink>
          <NavLink to="/audit" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
            Audit
          </NavLink>
        </nav>
      </div>

      <div className="topbar-sim-controls">
        <button className="btn-sim btn-sim-start" onClick={handleStart} title="Start simulation loop">
          ▶ Start
        </button>
        <button className="btn-sim btn-sim-stop" onClick={handleStop} title="Stop simulation loop">
          ⏸ Stop
        </button>
        <button className="btn-sim btn-sim-reset" onClick={handleReset} title="Reset simulation state">
          ↺ Reset
        </button>
        <div className="speed-control">
          <span>Speed:</span>
          <select value={simSpeed} onChange={handleSpeedChange}>
            {[1, 2, 5, 10, 15, 20].map((s) => (
              <option key={s} value={s}>
                {s}x
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="topbar-counters">
        <div className="counter-chip">
          <span className="counter-label">Tx Processed</span>
          <span className="counter-value">{metrics?.tx_processed?.toLocaleString() ?? "0"}</span>
        </div>
        <div className="counter-chip">
          <span className="counter-label">Alerts</span>
          <span className="counter-value alert-val">{metrics?.alerts_count ?? "0"}</span>
        </div>
        <div className="counter-chip">
          <span className="counter-label">Prevented INR</span>
          <span className="counter-value prevented">{formatINR(metrics?.prevented_inr ?? 0)}</span>
        </div>
      </div>

      <div className="topbar-status">
        <div
          style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px" }}
          title={`WebSocket Status: ${wsStatus}`}
        >
          <span className={`ws-status-dot ws-status-${wsStatus}`} />
          <span style={{ color: "var(--text-secondary)", textTransform: "capitalize" }}>
            {wsStatus}
          </span>
        </div>

        <div className="officer-chip" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>Compliance Officer:</span>
          <span className="officer-name" style={{ fontWeight: 600, color: "#DDD6FE" }}>
            {officer?.name || "Officer A"}
          </span>
          <span
            style={{
              fontSize: "10px",
              background: "#059669",
              color: "#fff",
              padding: "2px 6px",
              borderRadius: "4px",
              fontWeight: 700,
            }}
          >
            ACTIVE
          </span>
        </div>
      </div>
    </header>
  );
}
