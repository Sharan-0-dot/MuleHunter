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

  // Provenance / summary source badge info
  const summarySource = selectedCluster?.summary_source || "template";
  const llmStatus = selectedCluster?.llm_status;
  const badgeLabel =
    summarySource === "llm"
      ? `AI Polished${llmStatus && llmStatus !== "ok" ? ` (${llmStatus})` : ""}`
      : `Template${llmStatus ? ` (${llmStatus})` : ""}`;

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
            type="button"
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
                <span className="data-item-value" style={{ color: "#DDD6FE", fontWeight: 600 }}>
                  {formatTypology(selectedCluster.typology)}
                </span>
              </div>
              <div className="data-item">
                <span className="data-item-label">Risk Level</span>
                <span
                  className="data-item-value"
                  style={{ color: selectedCluster.level === "red" ? "#EF4444" : "#F59E0B" }}
                >
                  {selectedCluster.level?.toUpperCase()} ({Math.round((selectedCluster.risk_score || 0) * 100)}%)
                </span>
              </div>
              <div className="data-item">
                <span className="data-item-label">Total Volume</span>
                <span className="data-item-value">{formatINR(totalAmount)}</span>
              </div>
              <div className="data-item">
                <span className="data-item-label">Accounts</span>
                <span className="data-item-value">
                  {selectedCluster.accounts?.length || selectedCluster.accounts_count || 0}
                </span>
              </div>
            </div>

            {/* Large Readable Summary Text with Provenance Badge (>= 18px) */}
            {selectedCluster.summary_text && (
              <div className="summary-block">
                <div className="summary-header-row">
                  <span className="summary-header-label">Audio Brief (Officer Summary):</span>
                  <span className={`summary-source-badge ${summarySource}`}>
                    {summarySource === "llm" ? "✨ " : "📄 "}
                    {badgeLabel}
                  </span>
                </div>
                <p className="large-summary-text">"{selectedCluster.summary_text}"</p>
              </div>
            )}
          </div>

          {/* Freeze Action Button */}
          <div className="panel-section freeze-action-section">
            <button
              type="button"
              className="btn-freeze"
              disabled={!officer || isClusterFrozen || isFreezing}
              onClick={handleFreeze}
              title={
                !officer
                  ? "Log in as officer"
                  : isClusterFrozen
                  ? "Cluster already frozen"
                  : "Approve emergency freeze"
              }
            >
              {isClusterFrozen ? "✓ Cluster Frozen" : isFreezing ? "Freezing..." : "🛑 Freeze Cluster"}
            </button>
            {!officer && !isClusterFrozen && (
              <p className="freeze-tooltip">🔒 Log in as officer to approve account freeze</p>
            )}
            {isClusterFrozen && (
              <p className="freeze-prevented-label">
                Prevented INR: {formatINR(frozenPrevented || selectedCluster.prevented_inr || totalAmount || 0)}
              </p>
            )}
          </div>

          {/* Linked accounts clickable list */}
          <div className="panel-section">
            <h3 className="section-title">Linked Accounts ({selectedCluster.accounts?.length || 0})</h3>
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

          {/* Risk components decomposition */}
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

          {/* Alert & Pi Events Timeline */}
          {timeline && timeline.length > 0 && (
            <div className="panel-section">
              <h3 className="section-title">Compliance Timeline</h3>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", fontSize: "12px" }}>
                {timeline.map((item, idx) => (
                  <div
                    key={idx}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      borderBottom: "1px solid var(--border)",
                      paddingBottom: "4px",
                    }}
                  >
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

      {/* Account Node Inspection Section */}
      {nodeDetail && (
        <div className="panel-section">
          <h3 className="section-title">Account Diagnostics</h3>
          <div className="data-grid">
            <div className="data-item">
              <span className="data-item-label">Account ID</span>
              <span className="data-item-value">{nodeDetail.account_id}</span>
            </div>
            <div className="data-item">
              <span className="data-item-label">Risk Score</span>
              <span
                className="data-item-value"
                style={{
                  color:
                    nodeDetail.risk >= 0.85
                      ? "#EF4444"
                      : nodeDetail.risk >= 0.65
                      ? "#F59E0B"
                      : "#10B981",
                }}
              >
                {Math.round((nodeDetail.risk || 0) * 100)}%
              </span>
            </div>
            <div className="data-item">
              <span className="data-item-label">Inflow Volume</span>
              <span className="data-item-value">{formatINR(nodeDetail.in_amount || 0)}</span>
            </div>
            <div className="data-item">
              <span className="data-item-label">Outflow Volume</span>
              <span className="data-item-value">{formatINR(nodeDetail.out_amount || 0)}</span>
            </div>
            <div className="data-item">
              <span className="data-item-label">Status</span>
              <span className="data-item-value">
                {nodeDetail.frozen ? (
                  <span style={{ color: "#38BDF8", fontWeight: 700 }}>FROZEN</span>
                ) : (
                  <span style={{ color: "var(--color-green)" }}>ACTIVE</span>
                )}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Empty State when no cluster selected */}
      {!selectedCluster && !nodeDetail && (
        <div className="panel-empty-state">
          <span style={{ fontSize: "28px" }}>🔍</span>
          <p style={{ marginTop: "12px", color: "var(--text-secondary)" }}>
            Select an alert from the feed or a cluster in the graph to inspect AML risk factors.
          </p>
        </div>
      )}
    </aside>
  );
}
