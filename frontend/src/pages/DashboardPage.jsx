import React, { useState, useEffect, useRef, useCallback } from "react";
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
  const [metrics, setMetrics] = useState({
    tx_processed: 0,
    alerts_count: 0,
    prevented_inr: 0,
    sim_speed: 10,
    is_running: true,
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

    // Metrics poll function
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
            }));
            if (data.sim_speed) setSimSpeed(data.sim_speed);
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
          addToast(`New ${msg.level?.toUpperCase()} alert: ${msg.cluster_id}`, "error");
        } else if (msg.type === "cluster_updated") {
          setAlerts((prev) =>
            prev.map((a) => (a.cluster_id === msg.cluster_id ? { ...a, ...msg } : a))
          );
        } else if (msg.type === "pi_ack") {
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
          addToast(`Cluster ${msg.cluster_id} frozen! Prevented INR ${msg.prevented_inr}`, "success");
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
    <div className="app-container">
      <TopBar
        metrics={metrics}
        simSpeed={simSpeed}
        setSimSpeed={setSimSpeed}
        wsStatus={wsStatus}
        officer={officer}
        onLogout={handleLogout}
        onToast={addToast}
      />

      <main className="dashboard-layout">
        {/* Left column: Alerts feed */}
        <AlertFeed
          alerts={alerts}
          selectedClusterId={selectedClusterId}
          onSelectCluster={handleSelectCluster}
        />

        {/* Center column: 3D/2D Graph */}
        <GraphView
          selectedClusterId={selectedClusterId}
          selectedNodeId={selectedNodeId}
          onSelectNode={handleSelectNode}
          onClearSelection={handleClearSelection}
          onToast={addToast}
        />

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

        {/* Bottom-left attack launcher */}
        <AttackLauncher onToast={addToast} />
      </main>

      <Toast toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
