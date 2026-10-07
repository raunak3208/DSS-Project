import { useState } from "react";
import { fmtTime, short } from "../api.js";

const STAGE = { detect: "detected", correlate: "correlated", rca: "root cause", agent: "agent", gate: "safety gate", approval: "approval",
  remediation: "remediation", verification: "verification", resolved: "resolved", escalated: "escalated" };
const STAGE_BADGE = { gate: "agent", agent: "agent", approval: "human", resolved: "ok", escalated: "bad", remediation: "warn" };

export function Timeline({ events }) {
  return (
    <div className="panel">
      <h2>Incident timeline</h2>
      <div className="list">
        {events.length === 0 && <div className="empty">Events appear here as the loop runs.</div>}
        {events.map((e) => (
          <div key={e.id} className={`ev ${e.stage === "detect" ? "sys" : ""}`}>
            <span className="mono">{fmtTime(e.ts)}</span>
            <span><span className={`badge ${STAGE_BADGE[e.stage] || ""}`}>{STAGE[e.stage] || e.stage}</span></span>
            <span>{e.summary}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Anomalies({ anomalies }) {
  return (
    <div className="panel">
      <h2>Detected anomalies</h2>
      <div className="list">
        {anomalies.length === 0 && <div className="empty">No anomalies detected.</div>}
        {anomalies.map((a) => (
          <div key={a.id} className="ev" style={{ gridTemplateColumns: "62px 120px 1fr" }}>
            <span className="mono">{fmtTime(a.ts)}</span>
            <span><b>{short(a.service) || a.service}</b> <span className={`badge ${a.severity === "high" ? "bad" : a.severity === "medium" ? "warn" : ""}`}>{a.type}</span></span>
            <span>{a.detail} <span className="muted">via {a.detector.replaceAll("_", " ")}</span></span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Predictions({ predictions }) {
  const label = { memory_exhaustion: "will run out of memory", latency_slo_breach: "will breach its latency target", cpu_saturation: "will saturate its CPU" };
  return (
    <div className="panel">
      <h2>Predicted failures</h2>
      {predictions.length === 0 ? <div className="empty">No service is trending toward failure.</div> : predictions.map((p) => (
        <div key={p.service + p.kind} style={{ marginBottom: 6 }}>
          <span className="badge warn">in about {Math.round(p.eta_s)}s</span> <b>{p.service}</b> {label[p.kind] || p.kind}
          <div className="muted">Rising {p.slope}/s, now {p.current}, trend fit {Math.round(p.confidence * 100)}%</div>
        </div>
      ))}
    </div>
  );
}

export function Logs({ logs }) {
  const [level, setLevel] = useState("ALL");
  const [svc, setSvc] = useState("all");
  const names = [...new Set(logs.map((l) => l.service))].sort();
  const rows = logs.filter((l) => (level === "ALL" || l.level === level) && (svc === "all" || l.service === svc));
  return (
    <div className="panel">
      <h2>Logs</h2>
      <div className="controls" style={{ marginBottom: 8 }}>
        <div className="seg">{["ALL", "ERROR", "WARN", "INFO"].map((l) => <button key={l} className={level === l ? "on" : ""} onClick={() => setLevel(l)}>{l === "ALL" ? "All" : l[0] + l.slice(1).toLowerCase()}</button>)}</div>
        <select className="select" value={svc} onChange={(e) => setSvc(e.target.value)} aria-label="Filter by service">
          <option value="all">All services</option>{names.map((n) => <option key={n}>{n}</option>)}
        </select>
      </div>
      <div className="logs">
        {rows.length === 0 && <div className="muted">No matching log lines.</div>}
        {rows.slice(0, 100).map((l, i) => <div key={i} className={`lvl-${l.level}`}>{fmtTime(l.ts)} {l.service} {l.msg}</div>)}
      </div>
    </div>
  );
}
