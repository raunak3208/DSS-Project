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

export function humanizeAnomaly(detail, type) {
  if (!detail) return "";

  // Latency: "p95_ms 326.2 vs baseline 156.8 (z=6.8)"
  const latMatch = detail.match(/p95_ms\s+([\d.]+)\s+vs\s+baseline\s+([\d.]+)/i);
  if (latMatch) {
    const cur = parseFloat(latMatch[1]);
    const base = parseFloat(latMatch[2]);
    const ratio = base > 0 ? (cur / base).toFixed(1) : "2.0";
    return `Response time spiked to ${Math.round(cur)} ms (normally ~${Math.round(base)} ms, ${ratio}x slower)`;
  }

  // Error rate: "err_rate 0.2 vs baseline 0.0 (z=10.7)"
  const errMatch = detail.match(/err_rate\s+([\d.]+)\s+vs\s+baseline\s+([\d.]+)/i);
  if (errMatch) {
    const curPct = Math.round(parseFloat(errMatch[1]) * 100);
    const basePct = Math.round(parseFloat(errMatch[2]) * 100);
    return `Error spike: ${curPct}% of requests failing (normally ${basePct}%)`;
  }

  // CPU: "cpu_pct 90.5 vs baseline 12.0"
  const cpuMatch = detail.match(/cpu_pct\s+([\d.]+)\s+vs\s+baseline\s+([\d.]+)/i);
  if (cpuMatch) {
    const cur = Math.round(parseFloat(cpuMatch[1]));
    const base = Math.round(parseFloat(cpuMatch[2]));
    return `High CPU load: ${cur}% utilization (normally ~${base}%)`;
  }

  // Memory: "mem_mb 240 vs baseline 80"
  const memMatch = detail.match(/mem_mb\s+([\d.]+)\s+vs\s+baseline\s+([\d.]+)/i);
  if (memMatch) {
    const cur = Math.round(parseFloat(memMatch[1]));
    const base = Math.round(parseFloat(memMatch[2]));
    return `Memory surge: ${cur} MB allocated (normally ~${base} MB)`;
  }

  // Log error templates: "error template repeating: POST /api/checkout failed status=<*>..."
  if (detail.includes("error template repeating:") || detail.includes("POST /api/")) {
    let clean = detail
      .replace("error template repeating:", "")
      .replace(/<[*]>/g, "")
      .replace(/status=\s*/g, "")
      .replace(/failed\s+reason=/g, "due to ")
      .replace(/\s+/g, " ")
      .trim();
    return `Recurring error pattern: ${clean}`;
  }

  // Unreachable / Heartbeat
  if (detail.includes("no telemetry")) {
    const secMatch = detail.match(/for\s+(\d+)s/);
    const secs = secMatch ? `${secMatch[1]}s` : "recently";
    return `Service stopped responding (no heartbeat for ${secs})`;
  }

  // Multivariate
  if (detail.includes("unusual combination")) {
    return "Multi-metric irregularity detected across response time, CPU and memory";
  }

  // Fallback: clean up math notation like (z=6.8)
  return detail.replace(/\(z=[\d.]+\)/g, "").trim();
}

const DETECTOR_NAMES = {
  ewma_control_chart: "Baseline Check",
  drain_log_parser: "Log Pattern",
  isolation_forest: "Multi-Metric",
  heartbeat: "Availability Check",
};

export function Anomalies({ anomalies }) {
  return (
    <div className="panel">
      <h2>Detected anomalies</h2>
      <div className="list">
        {anomalies.length === 0 && <div className="empty">No anomalies detected.</div>}
        {anomalies.map((a) => (
          <div key={a.id} className="ev" style={{ gridTemplateColumns: "62px 120px 1fr" }}>
            <span className="mono">{fmtTime(a.ts)}</span>
            <span>
              <b>{short(a.service) || a.service}</b>{" "}
              <span className={`badge ${a.severity === "high" ? "bad" : a.severity === "medium" ? "warn" : ""}`}>
                {a.type}
              </span>
            </span>
            <span>
              {humanizeAnomaly(a.detail, a.type)}{" "}
              <span className="muted" style={{ fontSize: 11 }}>
                ({DETECTOR_NAMES[a.detector] || a.detector.replaceAll("_", " ")})
              </span>
            </span>
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
