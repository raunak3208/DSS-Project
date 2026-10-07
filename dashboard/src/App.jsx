import { useState } from "react";
import { useOverview } from "./api.js";
import Header from "./components/Header.jsx";
import LoopStrip from "./components/LoopStrip.jsx";
import ServiceGraph, { ServiceCards } from "./components/ServiceGraph.jsx";
import MetricCharts from "./components/MetricCharts.jsx";
import IncidentPanel from "./components/IncidentPanel.jsx";
import { Anomalies, Logs, Predictions, Timeline } from "./components/Feeds.jsx";

export default function App() {
  const { data, error, refresh } = useOverview(2000);
  const [selected, setSelected] = useState("gateway");
  if (!data) {
    return <div className="app"><div className="panel">{error ? `Cannot reach the controller API (${error}). Is docker compose up?` : "Loading..."}</div></div>;
  }
  const svc = data.services.find((s) => s.service === selected) || data.services[0];
  const inc = data.incident;
  const live = inc && !["resolved", "escalated"].includes(inc.status);
  return (
    <div className="app">
      <Header data={data} refresh={refresh} />
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
