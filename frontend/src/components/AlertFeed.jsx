import React from "react";
import { formatINR } from "./TopBar";

export function formatTypology(t) {
  if (!t) return "Unknown Typology";
  const map = {
    smurfing_fan_out_fan_in: "Smurfing (Structuring & Aggregation)",
    smurfing: "Smurfing (Structuring & Aggregation)",
    round_tripping: "Round-Trip Laundering Loop",
    round_trip: "Round-Trip Laundering Loop",
    mule_chain: "Multi-Hop Mule Pass-Through Chain",
    hybrid: "Hybrid Smurfing & Layered Loop",
    stealth: "Stealth Sub-Threshold Structuring",
    fan_out: "Fan-Out Dispersal",
    fan_in: "Fan-In Consolidation",
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

export default function AlertFeed({
  alerts = [],
  selectedClusterId = null,
  newestAlertId = null,
  onSelectCluster,
}) {
  return (
    <aside className="alert-feed">
      <div className="feed-header">
        <h2 className="feed-title">🚨 Compliance Alerts</h2>
        <span className="feed-count">{alerts.length} total</span>
      </div>

      <div className="feed-list">
        {alerts.length === 0 ? (
          <div className="feed-empty-state">
            <span className="empty-icon">🛡️</span>
            <span className="empty-title">No alerts yet. Launch an attack.</span>
            <span className="empty-subtitle">
              Choose a typology in the panel below and click Launch to observe real-time detection.
            </span>
          </div>
        ) : (
          alerts.map((alert) => {
            const isSelected = selectedClusterId === alert.cluster_id;
            const isNewFlash =
              newestAlertId &&
              (alert.alert_id === newestAlertId || alert.cluster_id === newestAlertId);

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
            const amount = getClusterAmount(alert);
            const numAccounts = getAccountsCount(alert);

            return (
              <div
                key={alert.alert_id || alert.cluster_id}
                className={`alert-row ${isSelected ? "selected" : ""} ${
                  isNewFlash ? "new-alert-flash" : ""
                } ${alert.level || "red"}`}
                onClick={() => onSelectCluster(alert.cluster_id)}
              >
                <div className="alert-row-header">
                  <span className={`level-chip ${levelClass}`}>
                    {alert.level?.toUpperCase() || "ALERT"}
                  </span>
                  <span className="alert-id-text">
                    {alert.alert_id || alert.cluster_id}
                  </span>
                  <span className="alert-time-text">
                    {formatTime(alert.created_at)}
                  </span>
                </div>

                <div className="alert-row-typology">
                  {formatTypology(alert.typology)}
                </div>

                <div className="alert-row-meta">
                  <div className="meta-item">
                    <span className="meta-label">Risk</span>
                    <span
                      className="meta-val"
                      style={{
                        color:
                          alert.level === "red"
                            ? "#EF4444"
                            : alert.level === "yellow"
                            ? "#F59E0B"
                            : "#10B981",
                        fontWeight: 700,
                      }}
                    >
                      {riskPct}%
                    </span>
                  </div>

                  <div className="meta-item">
                    <span className="meta-label">Amount</span>
                    <span className="meta-val">{formatINR(amount)}</span>
                  </div>

                  <div className="meta-item">
                    <span className="meta-label">Nodes</span>
                    <span className="meta-val">{numAccounts} accs</span>
                  </div>
                </div>

                {/* Pi Desk Progress Badge */}
                {piStatus && (
                  <div className="alert-row-pi-status">
                    <span className={`pi-badge ${piStatus}`}>
                      {piStatus === "received" && "Pi: Alert Received"}
                      {piStatus === "heard" && "Pi: Voice Keyword Heard"}
                      {piStatus === "played" && "Pi: Audio Played ✓"}
                      {piStatus === "timeout" && "Pi: Ack Timeout ⚠️"}
                    </span>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
