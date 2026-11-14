import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";

export default function AuditPage() {
  const [auditLog, setAuditLog] = useState([]);
  const [loading, setLoading] = useState(true);
  const [verifyResult, setVerifyResult] = useState(null); // { status: "success" | "error" | "not_available", message: string }
  const [isVerifying, setIsVerifying] = useState(false);

  useEffect(() => {
    let isMounted = true;
    apiFetch("/api/audit")
      .then((data) => {
        if (isMounted) {
          setAuditLog(Array.isArray(data) ? data : []);
          setLoading(false);
        }
      })
      .catch((err) => {
        console.warn("Audit log fetch error", err);
        if (isMounted) {
          setAuditLog([]);
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const handleVerifyChain = async () => {
    setIsVerifying(true);
    setVerifyResult(null);
    try {
      const res = await apiFetch("/api/audit/verify");
      if (res && res.valid) {
        setVerifyResult({
          status: "success",
          message: `Chain Verified: All SHA-256 blocks valid (${res.verified_count || auditLog.length} entries)`,
        });
      } else {
        setVerifyResult({
          status: "error",
          message: "Verification Failed: Hash mismatch detected in audit chain",
        });
      }
    } catch (err) {
      if (err.status === 404 || err.message?.includes("404")) {
        setVerifyResult({
          status: "not_available",
          message: "Audit verification not available yet (backend M4b hardening in progress)",
        });
      } else {
        setVerifyResult({
          status: "error",
          message: `Verification Error: ${err.message}`,
        });
      }
    } finally {
      setIsVerifying(false);
    }
  };

  return (
    <div className="page-container">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <div>
          <h1 style={{ fontSize: "24px", fontWeight: 700, color: "#fff" }}>
            Immutable Compliance Audit Trail
          </h1>
          <p style={{ color: "var(--text-secondary)", fontSize: "14px" }}>
            Cryptographically linked SHA-256 event log recording alerts, physical Pi desk interactions, officer biometric logins, and freeze orders.
          </p>
        </div>
        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          <button
            className="btn-primary"
            disabled={isVerifying}
            onClick={handleVerifyChain}
          >
            {isVerifying ? "Verifying Hash Chain..." : "🔍 Verify Chain"}
          </button>
          <Link to="/" className="btn-secondary">
            ← Back to Dashboard
          </Link>
        </div>
      </div>

      {/* Verification Result Banner */}
      {verifyResult && (
        <div
          style={{
            padding: "12px 18px",
            borderRadius: "8px",
            marginBottom: "20px",
            display: "flex",
            alignItems: "center",
            gap: "10px",
            fontSize: "14px",
            fontWeight: 600,
            background:
              verifyResult.status === "success"
                ? "rgba(16, 185, 129, 0.15)"
                : verifyResult.status === "error"
                ? "rgba(239, 68, 68, 0.15)"
                : "rgba(245, 158, 11, 0.15)",
            border: `1px solid ${
              verifyResult.status === "success"
                ? "var(--color-green)"
                : verifyResult.status === "error"
                ? "var(--color-red)"
                : "var(--color-yellow)"
            }`,
            color:
              verifyResult.status === "success"
                ? "#34D399"
                : verifyResult.status === "error"
                ? "#F87171"
                : "#FBBF24",
          }}
        >
          <span style={{ fontSize: "18px" }}>
            {verifyResult.status === "success" ? "✅" : verifyResult.status === "error" ? "❌" : "ℹ️"}
          </span>
          <span>{verifyResult.message}</span>
        </div>
      )}

      {/* Audit Log Entries Table */}
      <div className="data-table-wrapper">
        <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", background: "var(--bg-surface)" }}>
          <h2 style={{ fontSize: "15px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.5px" }}>
            Hash-Chained Event Ledger ({auditLog.length} Records)
          </h2>
        </div>

        {loading ? (
          <div style={{ padding: "30px", textAlign: "center", color: "var(--text-secondary)" }}>
            Loading audit trail...
          </div>
        ) : auditLog.length === 0 ? (
          <div style={{ padding: "30px", textAlign: "center", color: "var(--text-secondary)" }}>
            No audit records created yet.
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: "50px" }}>ID</th>
                <th style={{ width: "160px" }}>Timestamp</th>
                <th style={{ width: "160px" }}>Event Type</th>
                <th>Payload</th>
                <th style={{ width: "240px" }}>Hash Chaining</th>
              </tr>
            </thead>
            <tbody>
              {auditLog.map((entry) => (
                <tr key={entry.id || entry.hash}>
                  <td className="mono" style={{ color: "var(--text-muted)" }}>
                    #{entry.id}
                  </td>
                  <td className="mono" style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                    {entry.ts ? new Date(entry.ts).toLocaleString() : "N/A"}
                  </td>
                  <td>
                    <span
                      style={{
                        background:
                          entry.event_type?.includes("frozen")
                            ? "rgba(56, 189, 248, 0.2)"
                            : entry.event_type?.includes("login")
                            ? "rgba(123, 63, 196, 0.2)"
                            : "rgba(255, 255, 255, 0.1)",
                        color:
                          entry.event_type?.includes("frozen")
                            ? "#38BDF8"
                            : entry.event_type?.includes("login")
                            ? "#DDD6FE"
                            : "#fff",
                        padding: "2px 8px",
                        borderRadius: "4px",
                        fontSize: "12px",
                        fontWeight: 600,
                        textTransform: "uppercase",
                      }}
                    >
                      {entry.event_type}
                    </span>
                  </td>
                  <td>
                    <pre
                      style={{
                        margin: 0,
                        fontSize: "11px",
                        color: "#DDD6FE",
                        background: "rgba(0, 0, 0, 0.2)",
                        padding: "4px 8px",
                        borderRadius: "4px",
                        overflowX: "auto",
                        maxWidth: "400px",
                      }}
                    >
                      {typeof entry.payload === "object"
                        ? JSON.stringify(entry.payload, null, 1)
                        : String(entry.payload || "{}")}
                    </pre>
                  </td>
                  <td className="mono" style={{ fontSize: "10px" }}>
                    <div style={{ color: "var(--text-muted)", marginBottom: "2px" }} title={entry.prev_hash}>
                      prev: {entry.prev_hash ? `${entry.prev_hash.substring(0, 14)}...` : "Genesis"}
                    </div>
                    <div style={{ color: "var(--color-green)", fontWeight: 600 }} title={entry.hash}>
                      curr: {entry.hash ? `${entry.hash.substring(0, 18)}...` : "N/A"}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
