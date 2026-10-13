import { useState, useEffect } from "react";
import { useOverview, getAuthToken, clearAuthToken, api } from "./api.js";
import Header from "./components/Header.jsx";
import LoopStrip from "./components/LoopStrip.jsx";
import ServiceGraph, { ServiceCards } from "./components/ServiceGraph.jsx";
import MetricCharts from "./components/MetricCharts.jsx";
import IncidentPanel from "./components/IncidentPanel.jsx";
import { Anomalies, Logs, Predictions, Timeline } from "./components/Feeds.jsx";
import AuthPage from "./components/AuthPage.jsx";

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(() => Boolean(getAuthToken()));
  const [currentUser, setCurrentUser] = useState(null);
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [selected, setSelected] = useState("gateway");

  // Validate session on load
  useEffect(() => {
    const token = getAuthToken();
    if (!token) {
      setIsAuthenticated(false);
      setCheckingAuth(false);
      return;
    }

    api.me()
      .then((res) => {
        if (res.authenticated) {
          setIsAuthenticated(true);
          setCurrentUser(res.user);
        } else {
          clearAuthToken();
          setIsAuthenticated(false);
        }
      })
      .catch(() => {
        clearAuthToken();
        setIsAuthenticated(false);
      })
      .finally(() => {
        setCheckingAuth(false);
      });
  }, []);

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch (e) {
      // Ignore logout errors
    }
    clearAuthToken();
    setIsAuthenticated(false);
    setCurrentUser(null);
  };

  const handleAuthenticated = (user) => {
    setCurrentUser(user);
    setIsAuthenticated(true);
  };

  // Only poll overview if authenticated
  const { data, error, refresh } = useOverview(2000, isAuthenticated);

  // If checking initial session, show sleek loader
  if (checkingAuth) {
    return (
      <div className="auth-container">
        <div className="auth-card auth-loading-card">
          <div className="auth-spinner large" />
          <p className="muted" style={{ marginTop: 12 }}>Verifying operator security credentials...</p>
        </div>
      </div>
    );
  }

  // Not authenticated: Show Authentication Page FIRST!
  if (!isAuthenticated) {
    return <AuthPage onAuthenticated={handleAuthenticated} />;
  }

  // Waiting for data once authenticated
  if (!data) {
    return (
      <div className="app">
        <div className="panel" style={{ textAlign: "center", padding: "40px 20px" }}>
          {error ? (
            <div style={{ color: "var(--bad)" }}>
              <h3>Connection error</h3>
              <p>Cannot reach the controller API ({error}). Make sure backend is running.</p>
              <button className="btn primary" onClick={refresh} style={{ marginTop: 8 }}>Retry Connection</button>
            </div>
          ) : (
            <div className="muted">
              <div className="auth-spinner large" style={{ margin: "0 auto 12px" }} />
              Connecting to AIOps stream controller...
            </div>
          )}
        </div>
      </div>
    );
  }

  const svc = data.services.find((s) => s.service === selected) || data.services[0];
  const inc = data.incident;
  const live = inc && !["resolved", "escalated"].includes(inc.status);

  return (
    <div className="app">
      <Header
        data={data}
        refresh={refresh}
        currentUser={currentUser}
        onLogout={handleLogout}
      />
      {error && <div className="banner bad">Lost connection to the controller ({error}). Showing the last data received.</div>}
      <LoopStrip incident={inc} />
      <div className="grid-main">
        <div className="panel">
          <h2>Service health and dependencies</h2>
          <ServiceGraph services={data.services} edges={data.edges} rootCause={live ? inc.root_cause : null} selected={selected} onSelect={setSelected} />
          <ServiceCards services={data.services} selected={selected} onSelect={setSelected} />
        </div>
        <IncidentPanel incident={inc} learning={data.learning} />
      </div>
      <MetricCharts service={svc} />
      <div className="grid-3">
        <Timeline events={data.timeline} />
        <div style={{ display: "grid", gap: 14, alignContent: "start" }}>
          <Predictions predictions={data.predictions} />
          <Anomalies anomalies={data.anomalies} />
        </div>
        <Logs logs={data.logs} />
      </div>
    </div>
  );
}
