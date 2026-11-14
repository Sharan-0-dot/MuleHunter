/**
 * In-browser Mock Server for Mule Hunter.
 * Simulates REST endpoints and WebSocket events when VITE_MOCK=1.
 */

import {
  MOCK_CLUSTERS,
  MOCK_ACCOUNTS,
  generateMockGraph,
  MOCK_METRICS,
  MOCK_AUDIT,
} from "./mockData.js";

class MockServer {
  constructor() {
    this.clusters = JSON.parse(JSON.stringify(MOCK_CLUSTERS));
    this.accounts = JSON.parse(JSON.stringify(MOCK_ACCOUNTS));
    this.metrics = JSON.parse(JSON.stringify(MOCK_METRICS));
    this.metrics.pi_connected = 1;
    this.metrics.last_pi_ack = {
      event: "played",
      alert_id: "A-0001",
      time: new Date().toISOString(),
    };
    this.audit = JSON.parse(JSON.stringify(MOCK_AUDIT));
    this.simSpeed = 10.0;
    this.isRunning = true;
    this.dashboardListeners = new Set();
    this.authListeners = new Map(); // challengeId -> Set of callbacks
    this.activeChallenge = null;
    this.timer = null;
    this.eventIndex = 0;

    this.startBackgroundLoop();
  }

  startBackgroundLoop() {
    if (this.timer) clearInterval(this.timer);

    this.timer = setInterval(() => {
      if (!this.isRunning) return;

      // Increment tx_processed counter
      this.metrics.tx_processed += Math.floor(this.simSpeed * 2.5);

      // 1. Emit tx_batch every tick
      this.broadcastDashboard({
        type: "tx_batch",
        count: Math.floor(this.simSpeed * 2.5),
        ts: new Date().toISOString(),
      });

      this.eventIndex++;

      // Every ~15 ticks, emit a simulated cluster alert or pi_ack
      if (this.eventIndex % 15 === 0) {
        const typologies = ["smurfing_fan_out_fan_in", "round_tripping", "mule_chain", "hybrid"];
        const randTypology = typologies[Math.floor(Math.random() * typologies.length)];
        const newId = `C-00${Math.floor(Math.random() * 90) + 10}`;
        const newAlert = {
          type: "cluster_alert",
          alert_id: `A-${newId.slice(2)}`,
          cluster_id: newId,
          level: Math.random() > 0.4 ? "red" : "yellow",
          risk_score: +(0.7 + Math.random() * 0.28).toFixed(2),
          typology: randTypology,
          accounts_count: Math.floor(Math.random() * 7) + 4,
          total_amount_inr: Math.floor(Math.random() * 1500000) + 250000,
          created_at: new Date().toISOString(),
          summary_text: `Alert. Accounts moved funds matching ${randTypology}. Log in to the dashboard for linked accounts.`,
          pi_status: "received",
        };

        // Add to mock clusters if not present
        if (!this.clusters.some((c) => c.cluster_id === newId)) {
          this.clusters.unshift(newAlert);
          this.metrics.alerts_count++;
        }

        this.broadcastDashboard(newAlert);

        // Schedule realistic Pi progression: received -> heard -> played
        setTimeout(() => {
          this.handlePiAck(newAlert.alert_id, newId, "received");
        }, 1500);

        setTimeout(() => {
          this.handlePiAck(newAlert.alert_id, newId, "explain_voice");
        }, 3500);

        setTimeout(() => {
          this.handlePiAck(newAlert.alert_id, newId, "played");
        }, 6500);
      }
    }, 1000);
  }

  handlePiAck(alertId, clusterId, event) {
    const cluster = this.clusters.find((c) => c.cluster_id === clusterId);
    if (cluster) {
      if (event === "received") cluster.pi_status = "received";
      else if (event.startsWith("explain")) cluster.pi_status = "heard";
      else if (event === "played") cluster.pi_status = "played";
    }

    this.metrics.last_pi_ack = {
      event: event,
      alert_id: alertId,
      time: new Date().toISOString(),
    };

    this.broadcastDashboard({
      type: "pi_ack",
      alert_id: alertId,
      cluster_id: clusterId,
      event: event,
      ts: new Date().toISOString(),
    });
  }

  broadcastDashboard(msg) {
    this.dashboardListeners.forEach((listener) => {
      try {
        listener(msg);
      } catch (err) {
        console.error("Dashboard listener error", err);
      }
    });
  }

  // Dashboard WS subscribe
  subscribeDashboard(cb) {
    this.dashboardListeners.add(cb);
    return () => this.dashboardListeners.delete(cb);
  }

  // Auth WS subscribe
  subscribeAuth(challengeId, cb) {
    if (!this.authListeners.has(challengeId)) {
      this.authListeners.set(challengeId, new Set());
    }
    this.authListeners.get(challengeId).add(cb);

    return () => {
      const set = this.authListeners.get(challengeId);
      if (set) {
        set.delete(cb);
        if (set.size === 0) this.authListeners.delete(challengeId);
      }
    };
  }

  // Trigger simulated biometric scan
  simulateBiometricScan(challengeId) {
    const listeners = this.authListeners.get(challengeId);
    if (!listeners || listeners.size === 0) return false;

    const payload = {
      type: "login_ok",
      token: "mock-jwt-officer-token-xyz123",
      officer: {
        id: "O-1",
        name: "Officer A",
        role: "officer",
      },
    };

    listeners.forEach((cb) => cb(payload));

    // Audit log entry
    this.audit.push({
      id: this.audit.length + 1,
      ts: new Date().toISOString(),
      event_type: "officer_login",
      payload: { officer_id: "O-1", officer_name: "Officer A", method: "biometric_fingerprint" },
      prev_hash: this.audit[this.audit.length - 1]?.hash || "0000000000000000",
      hash: "mock-sha256-login-hash-" + Math.random().toString(36).substring(2, 10),
    });

    return true;
  }

  // Mock REST handlers
  async handleRequest(path, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const url = new URL(path, "http://localhost");
    const pathname = url.pathname;

    // Simulate network delay 50-100ms
    await new Promise((r) => setTimeout(r, 60));

    // Simulator controls
    if (pathname === "/api/sim/start" && method === "POST") {
      const body = options.body ? JSON.parse(options.body) : {};
      if (body.speed) this.simSpeed = body.speed;
      this.isRunning = true;
      this.metrics.is_running = true;
      this.metrics.sim_speed = this.simSpeed;
      return { ok: true, speed: this.simSpeed, sim_time: new Date().toISOString() };
    }

    if (pathname === "/api/sim/stop" && method === "POST") {
      this.isRunning = false;
      this.metrics.is_running = false;
      return { ok: true, sim_time: new Date().toISOString() };
    }

    if (pathname === "/api/sim/reset" && method === "POST") {
      this.metrics.tx_processed = 0;
      this.metrics.alerts_count = 0;
      this.metrics.prevented_inr = 0;
      this.clusters = JSON.parse(JSON.stringify(MOCK_CLUSTERS));
      return { ok: true, sim_time: new Date().toISOString() };
    }

    if (pathname === "/api/sim/attack" && method === "POST") {
      const body = options.body ? JSON.parse(options.body) : {};
      const newClusterId = `C-00${Math.floor(Math.random() * 90) + 10}`;
      const amount = body.total_amount_inr || (body.difficulty === 5 ? 300000 : 1000000);
      const newCluster = {
        cluster_id: newClusterId,
        typology: body.type || "round_tripping",
        level: "red",
        risk_score: +(0.85 + Math.random() * 0.12).toFixed(2),
        accounts_count: body.type === "stealth" ? 12 : 7,
        total_amount_inr: amount,
        created_at: new Date().toISOString(),
        summary_text: `Red alert. Injected ${body.type} attack at difficulty ${body.difficulty || 5}. Log in to the dashboard for linked accounts.`,
        frozen: false,
        accounts: ["ACC-1001", "ACC-1002", "ACC-1003", "ACC-1004", "ACC-1005", "ACC-1006", "ACC-1007"],
        pi_status: "received",
      };

      this.clusters.unshift(newCluster);
      this.metrics.alerts_count++;

      // Broadcast alert to dashboard
      setTimeout(() => {
        this.broadcastDashboard({
          type: "cluster_alert",
          ...newCluster,
        });
      }, 500);

      return {
        ok: true,
        started_sim: true,
        attack_id: `RING-${newClusterId}`,
        ring_id: `RING-${newClusterId}`,
        cluster_id: newClusterId,
        attack_type: body.type,
        difficulty: body.difficulty,
        accounts: newCluster.accounts,
      };
    }

    // Graph
    if (pathname === "/api/graph" && method === "GET") {
      const clusterId = url.searchParams.get("cluster_id");
      return generateMockGraph(clusterId);
    }

    // Clusters
    if (pathname === "/api/clusters" && method === "GET") {
      return this.clusters;
    }

    if (pathname.startsWith("/api/clusters/") && method === "GET") {
      const cid = pathname.split("/")[3];
      const found = this.clusters.find((c) => c.cluster_id === cid);
      if (!found) throw new Error("Cluster not found");
      return found;
    }

    // Freeze cluster
    if (pathname.includes("/freeze") && method === "POST") {
      const parts = pathname.split("/");
      const clusterId = parts[3];
      const cluster = this.clusters.find((c) => c.cluster_id === clusterId);
      if (cluster) {
        cluster.frozen = true;
        const prevented = cluster.total_amount_inr || 420000;
        this.metrics.prevented_inr += prevented;

        // Freeze accounts in that cluster
        (cluster.accounts || []).forEach((accId) => {
          if (this.accounts[accId]) this.accounts[accId].frozen = true;
        });

        const frozenEvent = {
          type: "frozen",
          cluster_id: clusterId,
          prevented_inr: prevented,
          accounts_count: cluster.accounts?.length || 7,
          ts: new Date().toISOString(),
        };

        this.broadcastDashboard(frozenEvent);

        // Audit entry
        this.audit.push({
          id: this.audit.length + 1,
          ts: new Date().toISOString(),
          event_type: "cluster_frozen",
          payload: { cluster_id: clusterId, prevented_inr: prevented },
          prev_hash: this.audit[this.audit.length - 1]?.hash || "0000",
          hash: "mock-hash-freeze-" + Math.random().toString(36).substring(2, 10),
        });

        return { ok: true, cluster_id: clusterId, prevented_inr: prevented };
      }
      return { ok: true, prevented_inr: 420000 };
    }

    // Account details
    if (pathname.startsWith("/api/accounts/") && method === "GET") {
      const accId = pathname.split("/")[3];
      const acc = this.accounts[accId] || {
        account_id: accId,
        type: "individual",
        cluster_id: null,
        risk: 0.15,
        in_amount: 50000,
        out_amount: 48000,
        retention_ratio: 0.04,
        in_degree: 2,
        out_degree: 2,
        median_hold_seconds: 300,
        frozen: false,
        recent_tx: [
          { from: "ACC-EXT-1", to: accId, amount: 25000, ts: new Date().toISOString() },
          { from: accId, to: "ACC-EXT-2", amount: 24000, ts: new Date().toISOString() },
        ],
      };
      return acc;
    }

    // Metrics
    if (pathname === "/api/metrics" && method === "GET") {
      return this.metrics;
    }

    // Audit list
    if (pathname === "/api/audit" && method === "GET") {
      return this.audit;
    }

    // Audit verify
    if (pathname === "/api/audit/verify" && method === "GET") {
      return { ok: true, valid: true, verified_count: this.audit.length };
    }

    // Auth challenge
    if (pathname === "/api/auth/challenge" && method === "POST") {
      const challengeId = `L-${Math.random().toString(36).substring(2, 6)}`;
      const expiresAt = new Date(Date.now() + 30000).toISOString();
      this.activeChallenge = challengeId;
      return { challenge_id: challengeId, expires_at: expiresAt };
    }

    // Auth password
    if (pathname === "/api/auth/password" && method === "POST") {
      const body = options.body ? JSON.parse(options.body) : {};
      if (body.username === "officer" && body.password === "demo123") {
        return {
          token: "mock-jwt-officer-token",
          officer: { id: "O-1", name: "Officer A", role: "officer" },
        };
      }
      if (body.username === "admin" && body.password === "admin123") {
        return {
          token: "mock-jwt-admin-token",
          officer: { id: "O-3", name: "Admin", role: "admin" },
        };
      }
      const err = new Error("Invalid username or password");
      err.status = 401;
      throw err;
    }

    throw new Error(`Mock endpoint not found: ${pathname}`);
  }
}

export const mockServer = new MockServer();
