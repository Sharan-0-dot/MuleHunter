import React, { useState, useEffect, useRef } from "react";
import { apiFetch } from "../api/client";

export const ATTACK_TYPES = [
  { id: "smurfing", key: "1", label: "Smurfing", desc: "Fan-out / fan-in aggregation" },
  { id: "round_trip", key: "2", label: "Round-Trip", desc: "Cyclic flow back to origin" },
  { id: "mule_chain", key: "3", label: "Mule Chain", desc: "Multi-hop layered chain" },
  { id: "hybrid", key: "4", label: "Hybrid", desc: "Smurfing + loop layering" },
  { id: "stealth", key: "5", label: "Stealth", desc: "Structured below ₹50k threshold" },
];

export const RING_SIZES = [
  { id: "small", label: "Small (₹3L)", amount: 300000 },
  { id: "medium", label: "Medium (₹10L)", amount: 1000000 },
  { id: "large", label: "Large (₹25L)", amount: 2500000 },
];

export default function AttackLauncher({
  onToast,
  simRunning = true,
  simSpeed = 10,
  onSetSimSpeed,
  onStartSim,
  lastAlert = null,
}) {
  const [attackType, setAttackType] = useState("round_trip");
  const [difficulty, setDifficulty] = useState(1);
  const [ringSize, setRingSize] = useState("medium");
  const [launchState, setLaunchState] = useState("idle"); // idle | sending | launched
  const [attackStartTime, setAttackStartTime] = useState(null);
  const [timerSeconds, setTimerSeconds] = useState(0);
  const [progressStatus, setProgressStatus] = useState(null); // detecting | alert_raised | warning | error
  const [alertInfo, setAlertInfo] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  const selectedSizeObj = RING_SIZES.find((s) => s.id === ringSize) || RING_SIZES[1];
  const timerRef = useRef(null);
  const attackStartTimeRef = useRef(attackStartTime);
  attackStartTimeRef.current = attackStartTime;

  // Running timer when launched
  useEffect(() => {
    if (launchState === "launched" && attackStartTime) {
      timerRef.current = setInterval(() => {
        const elapsed = Math.floor((Date.now() - attackStartTimeRef.current) / 1000);
        setTimerSeconds(elapsed);
        if (elapsed >= 60) {
          setProgressStatus((prev) => (prev === "detecting" ? "warning" : prev));
        }
      }, 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [launchState, attackStartTime]);

  // Check if a new alert arrived after launch
  useEffect(() => {
    if (lastAlert && attackStartTime) {
      const alertTime = lastAlert.created_at ? new Date(lastAlert.created_at).getTime() : Date.now();
      if (alertTime >= attackStartTime - 2000) {
        setProgressStatus("alert_raised");
        setAlertInfo(
          `${lastAlert.level ? lastAlert.level.toUpperCase() : "ALERT"}: ${lastAlert.alert_id || lastAlert.cluster_id}`
        );
        setLaunchState("idle");
      }
    }
  }, [lastAlert, attackStartTime]);

  // Keyboard shortcuts: 1-5 select attack type, Enter launches
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.target && e.target.matches("input, textarea, select")) {
        return; // Disabled while typing in form inputs
      }

      if (e.key === "1") setAttackType("smurfing");
      else if (e.key === "2") setAttackType("round_trip");
      else if (e.key === "3") setAttackType("mule_chain");
      else if (e.key === "4") setAttackType("hybrid");
      else if (e.key === "5") setAttackType("stealth");
      else if (e.key === "Enter") {
        e.preventDefault();
        handleLaunch();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [attackType, difficulty, ringSize, launchState]);

  const handleLaunch = async () => {
    if (launchState === "sending") return;

    setLaunchState("sending");
    setErrorMessage(null);
    setProgressStatus(null);
    setAlertInfo(null);

    const payload = {
      type: attackType,
      difficulty: attackType === "stealth" ? 5 : Number(difficulty),
      total_amount_inr: selectedSizeObj.amount,
    };

    try {
      const res = await apiFetch("/api/sim/attack", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      // Handle both old and new response shapes
      if (res && res.ok === false) {
        throw new Error(res.error || res.message || "Failed to inject attack ring");
      }

      const now = Date.now();
      setAttackStartTime(now);
      setTimerSeconds(0);
      setLaunchState("launched");
      setProgressStatus("detecting");

      const attackId = res?.attack_id || res?.ring_id || "RING";
      onToast(`⚡ Injected ${attackType.toUpperCase()} ring [${attackId}]!`, "success");

      // If backend auto-started sim, notify
      if (res?.started_sim && onStartSim) {
        onToast("Simulation was paused; automatically resumed for attack.", "info");
      }
    } catch (err) {
      setLaunchState("idle");
      setProgressStatus("error");
      setErrorMessage(err.message || "Attack launch failed");
      onToast(`Attack launch failed: ${err.message}`, "error");
    }
  };

  const handleSpeedSelect = (speedVal) => {
    if (onSetSimSpeed) onSetSimSpeed(speedVal);
  };

  return (
    <div className="attack-launcher-panel">
      {/* Top Header Row */}
      <div className="launcher-header-row">
        <div className="launcher-title-group">
          <span className="launcher-title-icon">⚡</span>
          <span className="launcher-title-text">Adversarial Ring Injector</span>
          <span className="launcher-hint-keys">Press [1-5] to select, [Enter] to launch</span>
        </div>

        {/* Speed Controls & Sim Status */}
        <div className="launcher-sim-status-group">
          <div
            className={`sim-status-indicator ${simRunning ? "running" : "stopped"}`}
            title={simRunning ? "Simulator is actively running" : "Simulator is stopped"}
          >
            <span className="status-dot" />
            <span className="status-label">{simRunning ? "Sim Running" : "Sim Stopped"}</span>
          </div>

          <div className="launcher-speed-controls">
            <span className="speed-label">Speed:</span>
            <select
              value={simSpeed}
              onChange={(e) => handleSpeedSelect(Number(e.target.value))}
              className="speed-select"
            >
              {[1, 2, 5, 10, 15, 20].map((s) => (
                <option key={s} value={s}>
                  {s}x
                </option>
              ))}
            </select>
            <button
              type="button"
              className={`btn-demo-speed ${simSpeed === 20 ? "active" : ""}`}
              onClick={() => handleSpeedSelect(20)}
              title="Set simulation to 20x demo speed"
            >
              🚀 Demo 20x
            </button>
          </div>
        </div>
      </div>

      {/* Main Controls Grid */}
      <div className="launcher-body-grid">
        {/* Column 1: Typology Buttons */}
        <div className="launcher-col-types">
          <span className="control-section-label">Typology (Keys 1-5):</span>
          <div className="type-buttons-group">
            {ATTACK_TYPES.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`type-btn ${attackType === t.id ? "active" : ""}`}
                onClick={() => setAttackType(t.id)}
                title={t.desc}
              >
                <span className="type-key-badge">{t.key}</span>
                <span className="type-btn-label">{t.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Column 2: Parameters (Difficulty & Size) */}
        <div className="launcher-col-params">
          {attackType !== "stealth" ? (
            <div className="param-group">
              <div className="param-header">
                <span className="control-section-label">Evasion Difficulty:</span>
                <span className="difficulty-val-badge">Level {difficulty} / 5</span>
              </div>
              <input
                type="range"
                min="1"
                max="5"
                step="1"
                value={difficulty}
                onChange={(e) => setDifficulty(Number(e.target.value))}
                className="difficulty-slider"
              />
              <div className="slider-ticks">
                <span>L1 (Fast)</span>
                <span>L3 (Decoys)</span>
                <span>L5 (Heavy Mix)</span>
              </div>
            </div>
          ) : (
            <div className="stealth-info-box">
              <span className="stealth-shield">🛡️</span>
              <div className="stealth-text">
                <strong>Stealth Scenario (Level 5):</strong>
                <span>All transactions structured below ₹50,000 threshold with decoys.</span>
              </div>
            </div>
          )}

          <div className="param-group">
            <span className="control-section-label">Laundering Volume:</span>
            <div className="ring-size-buttons">
              {RING_SIZES.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={`size-btn ${ringSize === s.id ? "active" : ""}`}
                  onClick={() => setRingSize(s.id)}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Column 3: Big Launch Button & Sim Action */}
        <div className="launcher-col-action">
          <button
            type="button"
            className={`btn-big-launch ${launchState}`}
            disabled={launchState === "sending"}
            onClick={handleLaunch}
          >
            {launchState === "sending" && "⏳ Injecting Attack..."}
            {launchState === "launched" && "🚀 Launch Another Ring"}
            {launchState === "idle" && "🚀 Launch Attack Ring"}
          </button>

          {!simRunning && (
            <button
              type="button"
              className="btn-inline-start-sim"
              onClick={onStartSim}
              title="Start simulation to advance simulated clock and process attacks"
            >
              ▶ Start Simulation Now
            </button>
          )}
        </div>
      </div>

      {/* Attack Progress Strip */}
      {progressStatus && (
        <div className={`attack-progress-strip status-${progressStatus}`}>
          {progressStatus === "detecting" && (
            <div className="strip-content">
              <span className="strip-spinner" />
              <span className="strip-text">
                Attack in progress — analyzing graph & detecting clusters... <strong>{timerSeconds} s</strong>
              </span>
              <span className="strip-sub">Target detection: &lt; 25 s at 20x</span>
            </div>
          )}

          {progressStatus === "alert_raised" && (
            <div className="strip-content">
              <span className="strip-icon-check">✓</span>
              <span className="strip-text">
                <strong>Alert Raised:</strong> {alertInfo}
              </span>
              <span className="strip-sub">Detected in {timerSeconds}s wall-clock time</span>
            </div>
          )}

          {progressStatus === "warning" && (
            <div className="strip-content">
              <span className="strip-icon-warn">⚠️</span>
              <span className="strip-text">
                No alert detected after {timerSeconds}s. The ring may have longer hop delays, or simulation is paused.
              </span>
              {!simRunning && (
                <button type="button" className="strip-action-btn" onClick={onStartSim}>
                  Resume Sim
                </button>
              )}
            </div>
          )}

          {progressStatus === "error" && (
            <div className="strip-content">
              <span className="strip-icon-error">✕</span>
              <span className="strip-text">
                <strong>Backend Error:</strong> {errorMessage}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
