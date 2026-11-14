import React, { useState, useEffect, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import { apiFetch, ReconnectingWebSocket, IS_MOCK } from "../api/client";
import { mockServer } from "../mock/mockServer";

export default function LoginPage() {
  const navigate = useNavigate();
  const [challengeId, setChallengeId] = useState(null);
  const [expiresAt, setExpiresAt] = useState(null);
  const [secondsLeft, setSecondsLeft] = useState(30);
  const [isExpired, setIsExpired] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [username, setUsername] = useState("officer");
  const [password, setPassword] = useState("demo123");
  const [isLoggingIn, setIsLoggingIn] = useState(false);

  const wsRef = useRef(null);
  const timerRef = useRef(null);

  const initChallenge = async () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (timerRef.current) {
      clearInterval(timerRef.current);
    }

    setErrorMessage(null);
    setIsExpired(false);
    setSecondsLeft(30);

    try {
      const res = await apiFetch("/api/auth/challenge", { method: "POST" });
      if (res && res.challenge_id) {
        setChallengeId(res.challenge_id);
        const exp = new Date(res.expires_at || Date.now() + 30000).getTime();
        setExpiresAt(exp);

        // Start countdown
        timerRef.current = setInterval(() => {
          const remaining = Math.max(0, Math.ceil((exp - Date.now()) / 1000));
          setSecondsLeft(remaining);
          if (remaining <= 0) {
            setIsExpired(true);
            clearInterval(timerRef.current);
          }
        }, 500);

        // Open WebSocket /ws/auth/{challenge_id}
        wsRef.current = new ReconnectingWebSocket(
          `/ws/auth/${res.challenge_id}`,
          (msg) => {
            if (msg.type === "login_ok") {
              sessionStorage.setItem("mh_token", msg.token);
              sessionStorage.setItem("mh_officer", JSON.stringify(msg.officer));
              navigate("/");
            } else if (msg.type === "login_failed") {
              setErrorMessage(`Login failed: ${msg.reason || "Unauthorized sensor match"}`);
            }
          },
          (status) => {
            // WS status
          }
        );
      }
    } catch (err) {
      setErrorMessage(`Failed to initiate biometric challenge: ${err.message}`);
    }
  };

  useEffect(() => {
    initChallenge();
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const handleSimulateScan = () => {
    if (IS_MOCK && challengeId) {
      mockServer.simulateBiometricScan(challengeId);
    }
  };

  const handlePasswordSubmit = async (e) => {
    e.preventDefault();
    setErrorMessage(null);
    setIsLoggingIn(true);
    try {
      const res = await apiFetch("/api/auth/password", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      if (res && res.token) {
        sessionStorage.setItem("mh_token", res.token);
        sessionStorage.setItem("mh_officer", JSON.stringify(res.officer));
        navigate("/");
      }
    } catch (err) {
      setErrorMessage(`Password login failed: ${err.message}`);
    } finally {
      setIsLoggingIn(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-card">
        <div className="login-icon-scanner">
          <div className="scanner-ring" />
          <span style={{ fontSize: "36px" }}>👆</span>
        </div>

        <h1 className="login-title">Compliance Officer Authentication</h1>
        <p className="login-subtitle">
          {isExpired ? "Challenge expired" : "Scan your finger on the desk sensor"}
        </p>

        {errorMessage && <div className="login-error-box">{errorMessage}</div>}

        <div className="countdown-box">
          <div className="countdown-time" style={{ color: isExpired ? "#EF4444" : "var(--accent)" }}>
            {isExpired ? "EXPIRED" : `${secondsLeft}s`}
          </div>
          <div className="challenge-id-badge">
            Challenge ID: <strong>{challengeId || "Connecting..."}</strong>
          </div>
          <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "4px" }}>
            Waiting for ESP32 + R307S serial bridge signal
          </div>
        </div>

        {isExpired ? (
          <button className="btn-primary" style={{ width: "100%", marginBottom: "12px" }} onClick={initChallenge}>
            ↺ Regenerate Challenge
          </button>
        ) : (
          IS_MOCK && (
            <button
              className="btn-secondary"
              style={{ width: "100%", marginBottom: "12px", background: "#1F1B3C", borderColor: "var(--accent)" }}
              onClick={handleSimulateScan}
            >
              ⚡ Simulate Desk Fingerprint Tap (Mock Demo)
            </button>
          )
        )}

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Link to="/" style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
            ← Back to Dashboard (Read-Only)
          </Link>
          <button
            style={{ background: "transparent", color: "var(--accent-hover)", fontSize: "13px" }}
            onClick={() => setShowPasswordForm(!showPasswordForm)}
          >
            {showPasswordForm ? "Hide Password Form" : "Use Password Fallback"}
          </button>
        </div>

        {/* Password Fallback Form */}
        {showPasswordForm && (
          <form className="password-fallback-form" onSubmit={handlePasswordSubmit}>
            <div className="form-group">
              <label>Officer Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="officer"
                required
              />
            </div>
            <div className="form-group">
              <label>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="demo123"
                required
              />
            </div>
            <button type="submit" className="btn-primary" disabled={isLoggingIn}>
              {isLoggingIn ? "Authenticating..." : "Login with Password"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
