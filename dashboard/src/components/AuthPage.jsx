import { useState, useEffect } from "react";
import { api, setAuthToken, ApiError } from "../api.js";

export default function AuthPage({ onAuthenticated }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [failedAttempts, setFailedAttempts] = useState(0);
  const [remainingAttempts, setRemainingAttempts] = useState(5);
  const [isLocked, setIsLocked] = useState(false);
  const [lockSeconds, setLockSeconds] = useState(0);

  // Check initial lockout status on mount
  useEffect(() => {
    let active = true;
    api.authStatus(username).then((st) => {
      if (!active) return;
      if (st.locked) {
        setIsLocked(true);
        setLockSeconds(st.remaining_seconds || 120);
        setFailedAttempts(5);
        setRemainingAttempts(0);
      } else {
        setFailedAttempts(st.failed_attempts || 0);
        setRemainingAttempts(st.remaining_attempts ?? 5);
      }
    }).catch(() => {});
    return () => { active = false; };
  }, []);

  // Countdown timer when locked
  useEffect(() => {
    if (!isLocked || lockSeconds <= 0) return;
    const timer = setInterval(() => {
      setLockSeconds((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          setIsLocked(false);
          setFailedAttempts(0);
          setRemainingAttempts(5);
          setErrorMsg("");
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [isLocked, lockSeconds]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (isLocked || loading) return;

    if (!username.trim() || !password) {
      setErrorMsg("Please enter both Operator ID and password");
      return;
    }

    setLoading(true);
    setErrorMsg("");

    try {
      const res = await api.login(username.trim(), password);
      if (res.token) {
        setAuthToken(res.token);
        if (onAuthenticated) {
          onAuthenticated(res.user);
        }
      }
    } catch (err) {
      if (err instanceof ApiError) {
        const data = err.data;
        if (err.status === 423 || data?.locked) {
          setIsLocked(true);
          const rem = data?.remaining_seconds || 120;
          setLockSeconds(rem);
          setFailedAttempts(5);
          setRemainingAttempts(0);
          setErrorMsg(data?.detail || "Account locked for 2 minutes due to 5 consecutive failed login attempts.");
        } else if (err.status === 429) {
          setErrorMsg("Rate limit reached: Maximum 40 requests per second allowed. Please wait a second.");
        } else if (err.status === 401) {
          const attempts = data?.failed_attempts ?? (failedAttempts + 1);
          const rem = data?.remaining_attempts ?? Math.max(0, 5 - attempts);
          setFailedAttempts(attempts);
          setRemainingAttempts(rem);
          setErrorMsg(data?.detail || `Invalid credentials. Attempt ${attempts} of 5 before 2-minute lockout.`);
        } else {
          setErrorMsg(err.message || "Authentication failed");
        }
      } else {
        setErrorMsg(err.message || "Failed to reach controller API");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleFillCredentials = (u, p) => {
    setUsername(u);
    setPassword(p);
    setErrorMsg("");
  };

  const formatTimer = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  };

  const lockoutProgress = isLocked ? Math.max(0, Math.min(100, (lockSeconds / 120) * 100)) : 0;

  return (
    <div className="auth-container">
      {/* Background ambient glow effect */}
      <div className="auth-ambient-glow" />

      <div className="auth-card">
        {/* Brand Header */}
        <div className="auth-header">
          <div className="auth-logo-badge">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              <path d="m9 12 2 2 4-4" />
            </svg>
          </div>
          <h1 className="auth-title">AIOps Control Center</h1>
          <p className="auth-subtitle">Operator Authentication & Autonomous Telemetry Gateway</p>
        </div>

        {/* Security badges */}
        <div className="auth-security-badges">
          <span className="auth-badge rps" title="Maximum 40 requests/second allowed">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            Rate Limit: 40 req/s
          </span>
          <span className={`auth-badge lockout ${isLocked ? "active-lock" : ""}`} title="5 failed attempts triggers 2-minute lockout">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            {isLocked ? `Locked (${formatTimer(lockSeconds)})` : "Lockout: 5 tries / 2 min"}
          </span>
        </div>

        {/* Lockout Warning Banner */}
        {isLocked && (
          <div className="auth-lockout-banner" role="alert">
            <div className="lockout-banner-top">
              <div className="lockout-icon-pulse">🔒</div>
              <div className="lockout-text">
                <strong>SECURITY LOCKOUT ACTIVE</strong>
                <span>5 consecutive incorrect attempts detected. Access is temporarily locked.</span>
              </div>
            </div>
            <div className="lockout-countdown-box">
              <span className="lockout-label">Time Remaining:</span>
              <span className="lockout-timer">{formatTimer(lockSeconds)}</span>
            </div>
            <div className="lockout-progress-track">
              <div className="lockout-progress-fill" style={{ width: `${lockoutProgress}%` }} />
            </div>
          </div>
        )}

        {/* Error / Attempt Banner */}
        {!isLocked && errorMsg && (
          <div className="auth-error-banner" role="alert">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Attempts tracker dots */}
        {!isLocked && failedAttempts > 0 && (
          <div className="auth-attempts-tracker">
            <div className="attempts-label">
              Failed attempts: <strong>{failedAttempts} / 5</strong>
              <span className="attempts-remaining-text">({remainingAttempts} attempt{remainingAttempts === 1 ? "" : "s"} before 2-min lock)</span>
            </div>
            <div className="attempts-pills">
              {[1, 2, 3, 4, 5].map((slot) => (
                <div
                  key={slot}
                  className={`attempt-pill ${slot <= failedAttempts ? "failed" : "available"}`}
                  title={slot <= failedAttempts ? `Failed attempt ${slot}` : `Available attempt ${slot}`}
                />
              ))}
            </div>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="auth-form" noValidate>
          <div className="form-group">
            <label htmlFor="auth-username">Operator ID / Username</label>
            <div className="input-with-icon">
              <svg className="input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
              <input
                id="auth-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Operator username (e.g. admin)"
                disabled={isLocked || loading}
                autoComplete="username"
                required
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="auth-password">Password</label>
            <div className="input-with-icon">
              <svg className="input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <input
                id="auth-password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password"
                disabled={isLocked || loading}
                autoComplete="current-password"
                required
              />
              <button
                type="button"
                className="toggle-password-btn"
                onClick={() => setShowPassword(!showPassword)}
                tabIndex={-1}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                ) : (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                )}
              </button>
            </div>
          </div>

          <button
            type="submit"
            className={`auth-submit-btn ${isLocked ? "locked" : ""}`}
            disabled={isLocked || loading}
          >
            {isLocked ? (
              <>🔒 Locked ({formatTimer(lockSeconds)})</>
            ) : loading ? (
              <span className="spinner-wrap">
                <span className="auth-spinner" />
                Authenticating...
              </span>
            ) : (
              <>Sign In to Control Center &rarr;</>
            )}
          </button>
        </form>

        {/* Quick Credentials Helper */}
        <div className="auth-quick-creds">
          <div className="quick-creds-title">Demo Operator Credentials</div>
          <div className="quick-creds-grid">
            <button
              type="button"
              className="quick-cred-chip"
              disabled={isLocked}
              onClick={() => handleFillCredentials("admin", "admin123")}
            >
              <span className="cred-role">Administrator</span>
              <code className="cred-details">admin / admin123</code>
            </button>
            <button
              type="button"
              className="quick-cred-chip"
              disabled={isLocked}
              onClick={() => handleFillCredentials("operator", "operator123")}
            >
              <span className="cred-role">SRE Operator</span>
              <code className="cred-details">operator / operator123</code>
            </button>
          </div>
        </div>

        {/* Footer Policy Notes */}
        <div className="auth-footer-note">
          <div className="footer-shield-row">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            <span>Deterministic 12-check safety gate protects all remediation actions</span>
          </div>
        </div>
      </div>
    </div>
  );
}
