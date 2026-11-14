import React from "react";
import { NavLink } from "react-router-dom";
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

export function formatPiEventName(ev) {
  if (!ev) return "";
  const map = {
    received: "Alert received",
    explain_voice: "Voice keyword heard",
    explain_joystick: "Joystick trigger",
    played: "Audio played",
    timeout: "Response timeout",
  };
  return map[ev] || ev.replace(/_/g, " ");
}

export default function TopBar({
  metrics,
  simSpeed,
  setSimSpeed,
  wsStatus,
  officer,
  isPresentationMode,
  onTogglePresentationMode,
  lastPiAck,
  onLogout,
  onToast,
}) {
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

  // Pi connection state
  const isPiConnected = Boolean(metrics?.pi_connected && metrics.pi_connected > 0);
  const piAck = lastPiAck || metrics?.last_pi_ack;
  const piEventText = piAck?.event ? formatPiEventName(piAck.event) : null;

  return (
    <header className={`topbar ${isPresentationMode ? "presentation-topbar" : ""}`}>
      <div className="topbar-brand">
        <div className="topbar-logo">
          <span>⚡ Mule Hunter</span>
          <span className="badge-aml">PS 2.1</span>
          {IS_MOCK && <span className="mock-badge">MOCK MODE</span>}
        </div>

        {/* Hide secondary navigation in Presentation Mode */}
        {!isPresentationMode && (
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
        )}
      </div>

      {/* Primary Simulator Controls */}
      <div className="topbar-sim-controls">
        <button
          type="button"
          className="btn-sim btn-sim-start"
          onClick={handleStart}
          title="Start simulation loop"
        >
          ▶ Start
        </button>
        <button
          type="button"
          className="btn-sim btn-sim-stop"
          onClick={handleStop}
          title="Stop simulation loop"
        >
          ⏸ Stop
        </button>
        <button
          type="button"
          className="btn-sim btn-sim-reset"
          onClick={handleReset}
          title="Reset simulation state"
        >
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

      {/* Counters */}
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

      {/* Status Indicators (Pi Desk, WebSocket, Presentation Toggle) */}
      <div className="topbar-status">
        {/* Raspberry Pi Connection & Event Indicator */}
        <div
          className={`pi-connection-chip ${isPiConnected ? "connected" : "standby"}`}
          title={
            isPiConnected
              ? `Raspberry Pi Compliance Desk is online (${metrics.pi_connected} client)`
              : "Raspberry Pi Compliance Desk is in standby (waiting for /ws/pi client)"
          }
        >
          <span className={`pi-status-dot ${isPiConnected ? "dot-online" : "dot-standby"}`} />
          <span className="pi-chip-label">Pi Desk:</span>
          <span className="pi-chip-state">{isPiConnected ? "Online" : "Standby"}</span>
          {piEventText && <span className="pi-chip-event">· {piEventText}</span>}
        </div>

        {/* WebSocket Status */}
        <div
          className="ws-status-chip"
          title={`WebSocket Status: ${wsStatus}`}
        >
          <span className={`ws-status-dot ws-status-${wsStatus}`} />
          <span style={{ color: "var(--text-secondary)", textTransform: "capitalize", fontSize: "12px" }}>
            {wsStatus}
          </span>
        </div>

        {/* Fullscreen / Presentation Mode Toggle */}
        <button
          type="button"
          className={`btn-presentation-toggle ${isPresentationMode ? "active" : ""}`}
          onClick={onTogglePresentationMode}
          title="Toggle Fullscreen Presentation Mode (F key)"
        >
          {isPresentationMode ? "✕ Exit Fullscreen (F)" : "📽️ Presentation (F)"}
        </button>

        {/* Officer info */}
        <div className="officer-chip">
          <span className="officer-role-label">Officer:</span>
          <span className="officer-name">{officer?.name || "Officer A"}</span>
          <span className="officer-active-badge">ACTIVE</span>
        </div>
      </div>
    </header>
  );
}
