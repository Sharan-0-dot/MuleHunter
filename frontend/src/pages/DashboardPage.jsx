import React, { useState, useEffect, useCallback } from "react";
import TopBar from "../components/TopBar";
import AlertFeed from "../components/AlertFeed";
import GraphView from "../components/GraphView";
import DetailPanel from "../components/DetailPanel";
import AttackLauncher from "../components/AttackLauncher";
import Toast from "../components/Toast";
import { apiFetch, ReconnectingWebSocket } from "../api/client";

export default function DashboardPage() {
  const [alerts, setAlerts] = useState([]);
  const [selectedClusterId, setSelectedClusterId] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [newestAlertId, setNewestAlertId] = useState(null);
  const [lastClusterAlert, setLastClusterAlert] = useState(null);
  const [lastPiAck, setLastPiAck] = useState(null);
  const [isRedAlertFlashing, setIsRedAlertFlashing] = useState(false);
  const [isPresentationMode, setIsPresentationMode] = useState(false);

  const [metrics, setMetrics] = useState({
    tx_processed: 0,
    alerts_count: 0,
    prevented_inr: 0,
    sim_speed: 10,
    is_running: true,
    pi_connected: 0,
    last_pi_ack: null,
  });

  const [simSpeed, setSimSpeed] = useState(10);
  const [wsStatus, setWsStatus] = useState("disconnected");
  const [toasts, setToasts] = useState([]);
  const [officer, setOfficer] = useState({ id: "O-1", name: "Officer A", role: "officer" });

  // Ensure default demo officer credentials in sessionStorage
  useEffect(() => {
    try {
      const defaultOfficer = { id: "O-1", name: "Officer A", role: "officer" };
      sessionStorage.setItem("mh_officer", JSON.stringify(defaultOfficer));
      sessionStorage.setItem("mh_token", "demo-token");
      setOfficer(defaultOfficer);
    } catch (_) {}
  }, []);

  const handleLogout = () => {
    addToast("Compliance session locked to Officer A for hackathon demo", "info");
  };

  const addToast = useCallback((message, type = "info") => {
    const id = Date.now() + Math.random().toString(36).substring(2, 6);
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  const dismissToast = (id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  // Keyboard shortcut: F key toggles presentation mode
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.target && e.target.matches("input, textarea, select")) return;
      if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        setIsPresentationMode((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Simulator controls
  const handleStartSim = async () => {
    try {
      await apiFetch("/api/sim/start", {
        method: "POST",
        body: JSON.stringify({ speed: Number(simSpeed) }),
      });
      setMetrics((prev) => ({ ...prev, is_running: true }));
      addToast(`Simulator started at ${simSpeed}x`, "success");
    } catch (err) {
      addToast(`Failed to start simulator: ${err.message}`, "error");
    }
  };

  const handleSpeedChange = async (newSpeed) => {
    const val = Number(newSpeed);
    setSimSpeed(val);
    try {
      await apiFetch("/api/sim/start", {
        method: "POST",
        body: JSON.stringify({ speed: val }),
      });
      setMetrics((prev) => ({ ...prev, is_running: true, sim_speed: val }));
      addToast(`Simulation speed set to ${val}x`, "info");
    } catch (_) {}
  };

  // Initial fetch of clusters and metrics
  useEffect(() => {
    let isMounted = true;

    // Initial clusters
    apiFetch("/api/clusters")
      .then((data) => {
        if (isMounted && Array.isArray(data)) {
          setAlerts(data.slice(0, 100));
          if (data.length > 0 && !selectedClusterId) {
            setSelectedClusterId(data[0].cluster_id);
          }
        }
      })
      .catch((err) => {
        console.warn("Could not fetch clusters", err);
      });

    // Metrics poll function (handles both old and new backend shapes)
    const fetchMetrics = () => {
      apiFetch("/api/metrics")
        .then((data) => {
          if (isMounted && data) {
            setMetrics((prev) => ({
              ...prev,
              tx_processed: data.tx_processed ?? prev.tx_processed,
              alerts_count: data.alerts_count ?? prev.alerts_count,
              prevented_inr: data.prevented_inr ?? prev.prevented_inr,
              sim_speed: data.sim_speed ?? prev.sim_speed,
              is_running: data.is_running ?? prev.is_running,
              pi_connected: data.pi_connected ?? prev.pi_connected ?? 0,
              last_pi_ack: data.last_pi_ack ?? prev.last_pi_ack ?? null,
            }));
            if (data.sim_speed && typeof data.sim_speed === "number") {
              setSimSpeed(data.sim_speed);
            }
          }
        })
        .catch((err) => {
          console.warn("Metrics poll error", err);
        });
    };

    fetchMetrics();
    const metricsTimer = setInterval(fetchMetrics, 3000);

    return () => {
      isMounted = false;
      clearInterval(metricsTimer);
    };
  }, []);

  // WebSocket /ws/dashboard connection
  useEffect(() => {
    const ws = new ReconnectingWebSocket(
      "/ws/dashboard",
      (msg) => {
        if (!msg) return;

        if (msg.type === "tx_batch") {
          setMetrics((prev) => ({
            ...prev,
            tx_processed: prev.tx_processed + (msg.count || 1),
          }));
        } else if (msg.type === "cluster_alert") {
          setAlerts((prev) => {
            const exists = prev.some((a) => a.cluster_id === msg.cluster_id);
            if (exists) return prev;
            return [msg, ...prev].slice(0, 100);
          });
          setMetrics((prev) => ({ ...prev, alerts_count: prev.alerts_count + 1 }));

          // Track new alert for visual alerts & re-centering
          setNewestAlertId(msg.alert_id || msg.cluster_id);
          setLastClusterAlert(msg);
          setSelectedClusterId(msg.cluster_id);

          // Red alert pulses graph border
          if (msg.level === "red") {
            setIsRedAlertFlashing(true);
            setTimeout(() => setIsRedAlertFlashing(false), 2000);
          }

          addToast(
            `🚨 ${msg.level?.toUpperCase()} Alert: ${msg.cluster_id} (${Math.round(
              (msg.risk_score || 0) * 100
            )}% risk)`,
            msg.level === "red" ? "error" : "warning"
          );
        } else if (msg.type === "cluster_updated") {
          setAlerts((prev) =>
            prev.map((a) => (a.cluster_id === msg.cluster_id ? { ...a, ...msg } : a))
          );
        } else if (msg.type === "pi_ack") {
          setLastPiAck(msg);
          setMetrics((prev) => ({
            ...prev,
            last_pi_ack: msg,
          }));
          setAlerts((prev) =>
            prev.map((a) => {
              if (a.alert_id === msg.alert_id || a.cluster_id === msg.cluster_id) {
                let status = a.pi_status;
                if (msg.event === "received") status = "received";
                else if (msg.event?.startsWith("explain")) status = "heard";
                else if (msg.event === "played") status = "played";
                else if (msg.event === "timeout") status = "timeout";
                return { ...a, pi_status: status };
              }
              return a;
            })
          );
        } else if (msg.type === "frozen") {
          setAlerts((prev) =>
            prev.map((a) =>
              a.cluster_id === msg.cluster_id ? { ...a, frozen: true } : a
            )
          );
          if (msg.prevented_inr) {
            setMetrics((prev) => ({
              ...prev,
              prevented_inr: prev.prevented_inr + msg.prevented_inr,
            }));
          }
          addToast(
            `Cluster ${msg.cluster_id} frozen! Prevented INR ${msg.prevented_inr}`,
            "success"
          );
        }
      },
      (status) => {
        setWsStatus(status);
      }
    );

    return () => {
      ws.close();
    };
  }, [addToast]);

  const handleSelectCluster = (clusterId) => {
    setSelectedClusterId(clusterId);
    setSelectedNodeId(null);
  };

  const handleSelectNode = (nodeId) => {
    setSelectedNodeId(nodeId);
  };

  const handleClearSelection = () => {
    setSelectedClusterId(null);
    setSelectedNodeId(null);
  };

  const handleClusterFrozen = (clusterId, prevented) => {
    setAlerts((prev) =>
      prev.map((a) => (a.cluster_id === clusterId ? { ...a, frozen: true } : a))
    );
    setMetrics((prev) => ({
      ...prev,
      prevented_inr: prev.prevented_inr + (prevented || 0),
    }));
  };

  const [selectedClusterDetail, setSelectedClusterDetail] = useState(null);

  // Fetch full cluster detail when selectedClusterId changes
  useEffect(() => {
    if (!selectedClusterId) {
      setSelectedClusterDetail(null);
      return;
    }

    let isMounted = true;
    apiFetch(`/api/clusters/${encodeURIComponent(selectedClusterId)}`)
      .then((data) => {
        if (isMounted && data) {
          setSelectedClusterDetail(data);
        }
      })
      .catch((err) => {
        console.warn("Could not fetch cluster detail", err);
      });

    return () => {
      isMounted = false;
    };
  }, [selectedClusterId]);

  const rawSelectedCluster = alerts.find((a) => a.cluster_id === selectedClusterId);
  const selectedCluster = selectedClusterDetail || rawSelectedCluster;

  return (
    <div className={`app-container ${isPresentationMode ? "presentation-app" : ""}`}>
      <TopBar
        metrics={metrics}
        simSpeed={simSpeed}
        setSimSpeed={handleSpeedChange}
        wsStatus={wsStatus}
        officer={officer}
        isPresentationMode={isPresentationMode}
        onTogglePresentationMode={() => setIsPresentationMode((p) => !p)}
        lastPiAck={lastPiAck}
        onLogout={handleLogout}
        onToast={addToast}
      />

      <main className={`dashboard-layout ${isPresentationMode ? "presentation-mode" : ""}`}>
        {/* Left column: Alerts feed */}
        <AlertFeed
          alerts={alerts}
          selectedClusterId={selectedClusterId}
          newestAlertId={newestAlertId}
          onSelectCluster={handleSelectCluster}
        />

        {/* Center column: 3D/2D Graph + Attack Launcher in clean flex layout */}
        <section className="center-column-layout">
          <GraphView
            selectedClusterId={selectedClusterId}
            selectedNodeId={selectedNodeId}
            lastAlertId={newestAlertId}
            isRedAlertFlashing={isRedAlertFlashing}
            onSelectNode={handleSelectNode}
            onClearSelection={handleClearSelection}
            onToast={addToast}
          />
          <AttackLauncher
            onToast={addToast}
            simRunning={Boolean(metrics.is_running)}
            simSpeed={simSpeed}
            onSetSimSpeed={handleSpeedChange}
            onStartSim={handleStartSim}
            lastAlert={lastClusterAlert}
          />
        </section>

        {/* Right column: Detail inspection panel */}
        <DetailPanel
          selectedClusterId={selectedClusterId}
          selectedCluster={selectedCluster}
          selectedNodeId={selectedNodeId}
          officer={officer}
          onSelectNode={handleSelectNode}
          onToast={addToast}
          onClusterFrozen={handleClusterFrozen}
        />
      </main>

      <Toast toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
