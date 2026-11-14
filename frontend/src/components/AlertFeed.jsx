import React from "react";
import { formatINR } from "./TopBar";

export function formatTypology(t) {
  if (!t) return "Unknown Typology";
  const map = {
    smurfing_fan_out_fan_in: "Smurfing (Fan-Out/In)",
    smurfing: "Smurfing",
    round_tripping: "Round Tripping",
    round_trip: "Round Tripping",
    mule_chain: "Mule Chain",
    hybrid: "Hybrid Attack",
    stealth: "Stealth Attack",
    fan_out: "Fan-Out",
    fan_in: "Fan-In",
  };
  return map[t] || t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatTime(isoStr) {
  if (!isoStr) return "";
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch (_) {
    return isoStr;
  }
}

export function getClusterAmount(alert) {
  if (alert.total_amount_inr) return Number(alert.total_amount_inr);
  if (alert.features?.total_amount) return Number(alert.features.total_amount);
  if (alert.summary_text) {
    const matchLakh = alert.summary_text.match(/(\d+(?:\.\d+)?)\s+lakh/i);
    if (matchLakh) return Number(matchLakh[1]) * 100000;
    const matchCrore = alert.summary_text.match(/(\d+(?:\.\d+)?)\s+crore/i);
    if (matchCrore) return Number(matchCrore[1]) * 10000000;
    const matchRupees = alert.summary_text.match(/(\d+(?:,\d+)*)\s+rupees/i);
    if (matchRupees) return Number(matchRupees[1].replace(/,/g, ""));
  }
  return 0;
}

export function getAccountsCount(alert) {
  if (alert.accounts_count) return alert.accounts_count;
  if (Array.isArray(alert.accounts)) return alert.accounts.length;
  if (alert.features?.n_accounts) return alert.features.n_accounts;
  if (alert.summary_text) {
    const match = alert.summary_text.match(/(\d+)\s+accounts/i);
    if (match) return Number(match[1]);
  }
  return 0;
}

export default function AlertFeed({ alerts, selectedClusterId, onSelectCluster }) {
  return (
    <aside className="alert-feed">
      <div className="feed-header">
        <h2 className="feed-title">🚨 Compliance Alerts</h2>
        <span className="feed-count">{alerts.length} total (capped at 100)</span>
      </div>

      <div className="feed-list">
        {alerts.length === 0 ? (
          <div
            style={{
              padding: "24px 16px",
              textAlign: "center",
              color: "var(--text-secondary)",
              fontSize: "14px",
            }}
          >
            No laundering alerts detected yet. Live stream monitoring...
          </div>
        ) : (
          alerts.map((alert) => {
            const isSelected = selectedClusterId === alert.cluster_id;
            const levelClass =
              alert.level === "red"
                ? "level-red"
                : alert.level === "yellow"
                ? "level-yellow"
                : "level-green";

            const riskPct = alert.risk_score
              ? Math.round(Number(alert.risk_score) * 100)
              : 0;

            const piStatus = alert.pi_status;

            return (
              <div
                key={alert.alert_id || alert.cluster_id}
                className={`alert-row ${isSelected ? "selected" : ""}`}
                onClick={() => onSelectCluster(alert.cluster_id)}
              >
                <div className="alert-row-header">
                  <span className={`level-chip ${levelClass}`}>
                    {alert.level || "ALERT"}
                  </span>
                  <span className="alert-risk" style={{ color: "var(--accent-hover)" }}>
                    {riskPct}% Risk
                  </span>
                </div>

                <div className="alert-typology">
                  {formatTypology(alert.typology)}
                </div>

                <div className="alert-meta">
                  <span>{getAccountsCount(alert)} accounts</span>
                  <span style={{ fontWeight: 600, color: "#fff" }}>
                    {formatINR(getClusterAmount(alert))}
                  </span>
                  <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                    {formatTime(alert.created_at || alert.first_seen)}
                  </span>
                </div>

                <div className="alert-pi-status">
                  <span style={{ color: "var(--text-muted)", fontSize: "11px" }}>Pi Desk:</span>
                  {piStatus === "received" && (
                    <span className="pi-badge received" title="Alert received by Raspberry Pi">
                      ⚡ Received
                    </span>
                  )}
                  {piStatus === "heard" && (
                    <span className="pi-badge heard" title="Voice or Joystick keyword 'explain' heard">
                      🎙️ Explain Heard
                    </span>
                  )}
                  {piStatus === "played" && (
                    <span className="pi-badge played" title="Spoken audio summary finished playback">
                      🔊 Audio Played
                    </span>
                  )}
                  {piStatus === "timeout" && (
                    <span className="pi-badge timeout" title="Officer response timed out">
                      ⏱️ Timeout
                    </span>
                  )}
                  {!piStatus && (
                    <span className="pi-badge" style={{ opacity: 0.6 }}>
                      Queued
                    </span>
                  )}
                  {alert.frozen && (
                    <span className="badge-frozen" style={{ marginLeft: "auto" }}>
                      Frozen
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
