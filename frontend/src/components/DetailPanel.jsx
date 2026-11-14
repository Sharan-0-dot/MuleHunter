import React, { useState, useEffect } from "react";
import { apiFetch } from "../api/client";
import { formatINR } from "./TopBar";
import { formatTypology, formatTime } from "./AlertFeed";

export default function DetailPanel({
  selectedClusterId,
  selectedCluster,
  selectedNodeId,
  officer,
  onSelectNode,
  onToast,
  onClusterFrozen,
}) {
  const [nodeDetail, setNodeDetail] = useState(null);
  const [isLoadingNode, setIsLoadingNode] = useState(false);
  const [isFreezing, setIsFreezing] = useState(false);
  const [frozenPrevented, setFrozenPrevented] = useState(null);

  // Fetch node detail when selectedNodeId changes
  useEffect(() => {
    if (!selectedNodeId) {
      setNodeDetail(null);
      return;
    }

    let isMounted = true;
    setIsLoadingNode(true);
    apiFetch(`/api/accounts/${encodeURIComponent(selectedNodeId)}`)
      .then((data) => {
        if (isMounted) {
          setNodeDetail(data);
          setIsLoadingNode(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setIsLoadingNode(false);
          console.warn("Error fetching account", err);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [selectedNodeId]);

  const handleFreeze = async () => {
    if (!selectedClusterId) return;
    if (!officer) {
      onToast("Log in as officer to approve freeze", "error");
      return;
    }

    setIsFreezing(true);
    try {
      const res = await apiFetch(`/api/clusters/${encodeURIComponent(selectedClusterId)}/freeze`, {
        method: "POST",
      });
      const prevented = res?.prevented_inr || selectedCluster?.total_amount_inr || 0;
      setFrozenPrevented(prevented);
      onToast(`Cluster ${selectedClusterId} frozen. ${formatINR(prevented)} prevented!`, "success");
      if (onClusterFrozen) onClusterFrozen(selectedClusterId, prevented);
    } catch (err) {
      onToast(`Freeze failed: ${err.message}`, "error");
    } finally {
      setIsFreezing(false);
    }
  };

  const isClusterFrozen = selectedCluster?.frozen || frozenPrevented !== null;
  const riskComponents = selectedCluster?.risk_components || selectedCluster?.features || {};
  const timeline =
    selectedCluster?.timeline ||
    (selectedCluster?.pi_events || []).map((e) => ({ event: e.event, ts: e.ts }));
  const totalAmount =
    selectedCluster?.total_amount_inr ||
    selectedCluster?.features?.total_amount ||
    0;

  return (
    <aside className="detail-panel">
      <div className="panel-header">
        <h2 className="panel-title">
          {nodeDetail
            ? `Node: ${nodeDetail.account_id}`
            : selectedCluster
            ? `Cluster: ${selectedCluster.cluster_id}`
            : "Compliance Investigation"}
        </h2>
        {nodeDetail && selectedCluster && (
          <button
            className="btn-secondary"
            style={{ fontSize: "11px", padding: "3px 8px" }}
            onClick={() => onSelectNode(null)}
          >
            Show Cluster
          </button>
        )}
      </div>

      {/* Cluster Details Section */}
      {selectedCluster && !nodeDetail && (
        <>
          <div className="panel-section">
            <h3 className="section-title">Cluster Overview</h3>
            <div className="data-grid" style={{ marginBottom: "12px" }}>
              <div className="data-item">
                <span className="data-item-label">Typology</span>
                <span className="data-item-value" style={{ color: "#DDD6FE" }}>
                  {formatTypology(selectedCluster.typology)}
                </span>
              </div>
              <div className="data-item">
                <span className="data-item-label">Risk Level</span>
                <span className="data-item-value" style={{ color: selectedCluster.level === "red" ? "#EF4444" : "#F59E0B" }}>
                  {selectedCluster.level?.toUpperCase()} ({Math.round((selectedCluster.risk_score || 0) * 100)}%)
                </span>
              </div>
              <div className="data-item">
                <span className="data-item-label">Total Amount</span>
                <span className="data-item-value">{formatINR(totalAmount)}</span>
              </div>
              <div className="data-item">
                <span className="data-item-label">Accounts</span>
                <span className="data-item-value">{selectedCluster.accounts?.length || selectedCluster.accounts_count || 0}</span>
              </div>
            </div>

            {selectedCluster.summary_text && (
              <p className="summary-text">"{selectedCluster.summary_text}"</p>
            )}
          </div>

          {/* Risk components / features if present */}
          {riskComponents && Object.keys(riskComponents).length > 0 && (
            <div className="panel-section">
              <h3 className="section-title">Risk Model Decomposition</h3>
              <div className="data-grid">
                {Object.entries(riskComponents).map(([k, v]) => (
                  <div key={k} className="data-item">
                    <span className="data-item-label">{k.replace(/_/g, " ")}</span>
                    <span className="data-item-value">
                      {typeof v === "number" ? v.toFixed(3) : String(v)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Linked accounts clickable list */}
          <div className="panel-section">
            <h3 className="section-title">Linked Accounts (Click to Inspect)</h3>
            <div className="account-chips">
              {(selectedCluster.accounts || []).map((accId) => (
                <span
                  key={accId}
                  className={`account-chip ${isClusterFrozen ? "frozen" : ""}`}
                  onClick={() => onSelectNode(accId)}
                  title="Click to focus node in graph"
                >
                  {accId}
                </span>
              ))}
            </div>
          </div>

          {/* Freeze Action Button */}
          <div className="panel-section" style={{ textAlign: "center" }}>
            <button
              className="btn-freeze"
              disabled={!officer || isClusterFrozen || isFreezing}
              onClick={handleFreeze}
              title={!officer ? "Log in as officer" : isClusterFrozen ? "Cluster already frozen" : "Approve emergency freeze"}
            >
              {isClusterFrozen ? "✓ Cluster Frozen" : isFreezing ? "Freezing..." : "🛑 Freeze Cluster"}
            </button>
            {!officer && !isClusterFrozen && (
              <p className="freeze-tooltip">🔒 Log in as officer to approve account freeze</p>
            )}
            {isClusterFrozen && (
              <p style={{ marginTop: "8px", fontSize: "13px", color: "var(--color-green)", fontWeight: 600 }}>
                Prevented INR: {formatINR(frozenPrevented || selectedCluster.prevented_inr || totalAmount || 0)}
              </p>
            )}
          </div>

          {/* Alert & Pi Events Timeline */}
          {timeline && timeline.length > 0 && (
            <div className="panel-section">
              <h3 className="section-title">Compliance Timeline</h3>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", fontSize: "12px" }}>
                {timeline.map((item, idx) => (
                  <div key={idx} style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid var(--border)", paddingBottom: "4px" }}>
                    <span style={{ color: "#DDD6FE", textTransform: "capitalize" }}>
                      {item.event.replace(/_/g, " ")}
                    </span>
                    <span style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                      {formatTime(item.ts)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Node Details (Master 8.6 fields) */}
      {nodeDetail && (
        <>
          <div className="panel-section">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
              <h3 className="section-title" style={{ margin: 0 }}>Account Profile</h3>
              {nodeDetail.frozen && <span className="badge-frozen">Frozen</span>}
            </div>

            <div className="data-grid">
              <div className="data-item">
                <span className="data-item-label">Account ID</span>
                <span className="data-item-value">{nodeDetail.account_id}</span>
              </div>
              <div className="data-item">
                <span className="data-item-label">Entity Type</span>
                <span className="data-item-value" style={{ textTransform: "capitalize" }}>
                  {nodeDetail.type || "individual"}
                </span>
              </div>
              <div className="data-item">
                <span className="data-item-label">Cluster</span>
                <span className="data-item-value">{nodeDetail.cluster_id || "None"}</span>
              </div>
              <div className="data-item">
                <span className="data-item-label">Calibrated Risk</span>
                <span className="data-item-value" style={{ color: nodeDetail.risk >= 0.7 ? "#EF4444" : "#60A5FA" }}>
                  {Math.round((nodeDetail.risk || 0) * 100)}%
                </span>
              </div>
              <div className="data-item">
                <span className="data-item-label">Total Inflow</span>
                <span className="data-item-value">{formatINR(nodeDetail.in_amount || 0)}</span>
              </div>
              <div className="data-item">
                <span className="data-item-label">Total Outflow</span>
                <span className="data-item-value">{formatINR(nodeDetail.out_amount || 0)}</span>
              </div>
              <div className="data-item">
                <span className="data-item-label">Retention Ratio</span>
                <span className="data-item-value">
                  {nodeDetail.retention_ratio !== undefined ? `${(nodeDetail.retention_ratio * 100).toFixed(1)}%` : "N/A"}
                </span>
              </div>
              <div className="data-item">
                <span className="data-item-label">In / Out Degree</span>
                <span className="data-item-value">{nodeDetail.in_degree ?? 0} in / {nodeDetail.out_degree ?? 0} out</span>
              </div>
              <div className="data-item" style={{ gridColumn: "span 2" }}>
                <span className="data-item-label">Median Hold Time</span>
                <span className="data-item-value">
                  {nodeDetail.median_hold_seconds ? `${Math.round(nodeDetail.median_hold_seconds)} s (${(nodeDetail.median_hold_seconds / 60).toFixed(1)} min)` : "N/A"}
                </span>
              </div>
            </div>
          </div>

          {/* Recent Transactions Table */}
          <div className="panel-section">
            <h3 className="section-title">Recent Transactions</h3>
            {nodeDetail.recent_tx && nodeDetail.recent_tx.length > 0 ? (
              <table className="tx-table">
                <thead>
                  <tr>
                    <th>From</th>
                    <th>To</th>
                    <th>Amount</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {nodeDetail.recent_tx.map((tx, idx) => (
                    <tr key={idx}>
                      <td style={{ color: tx.from === nodeDetail.account_id ? "#F87171" : "inherit" }}>
                        {tx.from}
                      </td>
                      <td style={{ color: tx.to === nodeDetail.account_id ? "#34D399" : "inherit" }}>
                        {tx.to}
                      </td>
                      <td style={{ fontWeight: 600 }}>{formatINR(tx.amount)}</td>
                      <td style={{ color: "var(--text-muted)" }}>{formatTime(tx.ts)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>No recent transactions recorded.</p>
            )}
          </div>
        </>
      )}

      {/* No selection prompt */}
      {!selectedCluster && !nodeDetail && (
        <div style={{ textAlign: "center", padding: "40px 16px", color: "var(--text-secondary)" }}>
          <p style={{ fontSize: "28px", marginBottom: "8px" }}>🔍</p>
          <p style={{ fontSize: "15px", fontWeight: 600, color: "#fff" }}>No Entity Selected</p>
          <p style={{ fontSize: "13px", marginTop: "4px" }}>
            Click an alert in the left feed or any node in the 3D graph to inspect cluster typology, money trails, and linked accounts.
          </p>
        </div>
      )}
    </aside>
  );
}
