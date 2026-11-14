/**
 * API & WebSocket Client for Mule Hunter
 * Supports both Mock mode (VITE_MOCK=1) and Real Backend mode (VITE_MOCK=0).
 */

import { mockServer } from "../mock/mockServer";

let activeApiBase = import.meta.env.VITE_API_BASE || "http://localhost:8000";
export const API_BASE = activeApiBase;
export const IS_MOCK =
  import.meta.env.VITE_MOCK === "1" ||
  import.meta.env.VITE_MOCK === 1 ||
  import.meta.env.VITE_MOCK === true ||
  import.meta.env.VITE_MOCK === "true";

// Derive WebSocket base URL
export function getWsBase() {
  if (activeApiBase.startsWith("https://")) {
    return activeApiBase.replace("https://", "wss://");
  }
  return activeApiBase.replace("http://", "ws://");
}

export const WS_BASE = getWsBase();

/**
 * HTTP fetch wrapper with automatic port fallback (8001 <-> 8000) and clear error reporting
 */
export async function apiFetch(path, options = {}) {
  if (IS_MOCK) {
    return mockServer.handleRequest(path, options);
  }

  const token = sessionStorage.getItem("mh_token");
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  let response;
  try {
    response = await fetch(`${activeApiBase}${path}`, {
      ...options,
      headers,
    });
  } catch (err) {
    // Network error: try alternate port (8001 <-> 8000)
    const altPort = activeApiBase.includes(":8001")
      ? activeApiBase.replace(":8001", ":8000")
      : activeApiBase.includes(":8000")
      ? activeApiBase.replace(":8000", ":8001")
      : null;

    if (altPort) {
      try {
        response = await fetch(`${altPort}${path}`, {
          ...options,
          headers,
        });
        // Switched port successfully
        activeApiBase = altPort;
      } catch (_) {
        throw new Error(
          `Backend connection refused. Ensure backend is running: uvicorn app.main:app --app-dir backend --port 8001`
        );
      }
    } else {
      throw new Error(`Backend connection refused at ${activeApiBase}.`);
    }
  }

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}: ${response.statusText}`;
    try {
      const errJson = await response.json();
      if (errJson) {
        if (typeof errJson.detail === "string") {
          errorDetail = errJson.detail;
        } else if (Array.isArray(errJson.detail)) {
          errorDetail = errJson.detail.map((d) => d.msg || d.loc?.join(".") || JSON.stringify(d)).join("; ");
        } else if (errJson.error) {
          errorDetail = errJson.error;
        } else if (errJson.message) {
          errorDetail = errJson.message;
        }
      }
    } catch (_) {}
    const err = new Error(errorDetail);
    err.status = response.status;
    throw err;
  }

  // Handle empty or json response
  try {
    return await response.json();
  } catch (_) {
    return { ok: true };
  }
}

/**
 * WebSocket manager with auto-reconnect and exponential backoff
 */
export class ReconnectingWebSocket {
  constructor(path, onMessage, onStatusChange) {
    this.path = path;
    this.onMessage = onMessage;
    this.onStatusChange = onStatusChange || (() => {});
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectDelay = 10000;
    this.isClosedManually = false;
    this.mockUnsub = null;

    this.connect();
  }

  connect() {
    if (this.isClosedManually) return;

    if (IS_MOCK) {
      this.onStatusChange("connected");
      if (this.path === "/ws/dashboard") {
        this.mockUnsub = mockServer.subscribeDashboard((data) => {
          this.onMessage(data);
        });
      } else if (this.path.startsWith("/ws/auth/")) {
        const challengeId = this.path.split("/").pop();
        this.mockUnsub = mockServer.subscribeAuth(challengeId, (data) => {
          this.onMessage(data);
        });
      }
      return;
    }

    let wsBase = getWsBase();
    if (this.reconnectAttempts % 2 === 1) {
      wsBase = wsBase.includes(":8001")
        ? wsBase.replace(":8001", ":8000")
        : wsBase.includes(":8000")
        ? wsBase.replace(":8000", ":8001")
        : wsBase;
    }
    const fullUrl = `${wsBase}${this.path}`;
    try {
      this.ws = new WebSocket(fullUrl);
    } catch (err) {
      console.warn("WebSocket init error", err);
      this.scheduleReconnect();
      return;
    }

    this.onStatusChange(this.reconnectAttempts > 0 ? "reconnecting" : "disconnected");

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.onStatusChange("connected");
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.onMessage(data);
      } catch (e) {
        console.warn("Failed to parse WS JSON message", event.data);
      }
    };

    this.ws.onerror = () => {
      this.onStatusChange("disconnected");
    };

    this.ws.onclose = () => {
      if (!this.isClosedManually) {
        this.onStatusChange("reconnecting");
        this.scheduleReconnect();
      } else {
        this.onStatusChange("disconnected");
      }
    };
  }

  scheduleReconnect() {
    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectDelay);
    setTimeout(() => {
      this.connect();
    }, delay);
  }

  send(data) {
    if (IS_MOCK) return;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(typeof data === "string" ? data : JSON.stringify(data));
    }
  }

  close() {
    this.isClosedManually = true;
    if (this.mockUnsub) {
      this.mockUnsub();
      this.mockUnsub = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.onStatusChange("disconnected");
  }
}
