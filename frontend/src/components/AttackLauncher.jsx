import React, { useState } from "react";
import { apiFetch } from "../api/client";

const ATTACK_TYPES = [
  { id: "smurfing", label: "Smurfing" },
  { id: "round_trip", label: "Round-Trip" },
  { id: "mule_chain", label: "Mule Chain" },
  { id: "hybrid", label: "Hybrid" },
  { id: "stealth", label: "Stealth" },
];

const RING_SIZES = [
  { id: "small", label: "Small (₹3L)", amount: 300000 },
  { id: "medium", label: "Medium (₹10L)", amount: 1000000 },
  { id: "large", label: "Large (₹25L)", amount: 2500000 },
];

export default function AttackLauncher({ onToast }) {
  const [attackType, setAttackType] = useState("round_trip");
  const [difficulty, setDifficulty] = useState(2);
  const [ringSize, setRingSize] = useState("medium");
  const [isLaunching, setIsLaunching] = useState(false);

  const selectedSizeObj = RING_SIZES.find((s) => s.id === ringSize) || RING_SIZES[1];

  const handleLaunch = async () => {
    setIsLaunching(true);
    try {
      const payload = {
        type: attackType,
        difficulty: attackType === "stealth" ? 5 : Number(difficulty),
        total_amount_inr: selectedSizeObj.amount,
      };

      const res = await apiFetch("/api/sim/attack", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      onToast(`⚡ Injected ${attackType.toUpperCase()} ring! (${selectedSizeObj.label})`, "success");
    } catch (err) {
      onToast(`Attack launch failed: ${err.message}`, "error");
    } finally {
      setIsLaunching(false);
    }
  };

  return (
    <div className="attack-launcher-container">
      <div className="launcher-title">
        <span>⚡ Adversarial Attack Launcher</span>
        <span className="launcher-badge">Live Demo</span>
      </div>

      {/* Typology selection */}
      <div className="launcher-row">
        <div className="launcher-label">
          <span>Typology Pattern:</span>
          <span style={{ color: "#DDD6FE", textTransform: "capitalize" }}>{attackType}</span>
        </div>
        <div className="launcher-types">
          {ATTACK_TYPES.map((t) => (
            <button
              key={t.id}
              className={`type-btn ${attackType === t.id ? "active" : ""}`}
              onClick={() => setAttackType(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Difficulty slider (hidden for stealth) */}
      {attackType !== "stealth" ? (
        <div className="launcher-row">
          <div className="launcher-label">
            <span>Evasion Difficulty:</span>
            <span style={{ fontWeight: 700, color: difficulty >= 4 ? "#EF4444" : "#F59E0B" }}>
              Level {difficulty} / 5
            </span>
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
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "var(--text-muted)" }}>
            <span>L1 (Naive)</span>
            <span>L3 (Decoys)</span>
            <span>L5 (Heavy Mixing)</span>
          </div>
        </div>
      ) : (
        <div className="launcher-row" style={{ background: "rgba(123, 63, 196, 0.15)", padding: "8px", borderRadius: "4px", border: "1px dashed var(--accent)" }}>
          <div style={{ fontSize: "12px", color: "#DDD6FE" }}>
            🛡️ <strong>Stealth Scenario:</strong> Strict difficulty 5 structuring below ₹50,000 threshold. Threshold baselines miss this.
          </div>
        </div>
      )}

      {/* Ring size */}
      <div className="launcher-row">
        <div className="launcher-label">
          <span>Laundering Volume:</span>
        </div>
        <div className="ring-sizes">
          {RING_SIZES.map((s) => (
            <button
              key={s.id}
              className={`size-btn ${ringSize === s.id ? "active" : ""}`}
              onClick={() => setRingSize(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <button
        className="btn-launch-attack"
        disabled={isLaunching}
        onClick={handleLaunch}
      >
        {isLaunching ? "Injecting Attack..." : "🚀 Launch Attack Ring"}
      </button>
    </div>
  );
}
