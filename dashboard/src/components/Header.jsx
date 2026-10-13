import { useState } from "react";
import { api } from "../api.js";
import { friendlySvc } from "./IncidentPanel.jsx";

const FAULTS = [
  ["cpu", "CPU saturation"], ["latency", "Latency spike"], ["memory", "Memory leak"],
  ["errors", "Error burst"], ["crash", "Crash"], ["bad_deploy", "Bad deployment"],
];
const SERVICES = ["gateway", "user-service", "order-service", "payment-service", "notification-service"];

export default function Header({ data, refresh, currentUser, onLogout }) {
  const [svc, setSvc] = useState("payment-service");
  const [fault, setFault] = useState("latency");
  const [msg, setMsg] = useState("");

  const run = async (fn, ok) => {
    try {
      await fn();
      setMsg(ok);
    } catch (e) {
      setMsg(`Failed: ${e.message.slice(0, 80)}`);
    }
    refresh();
    setTimeout(() => setMsg(""), 4000);
  };

  const username = currentUser?.username || "admin";
  const role = currentUser?.role || "operator";

  return (
    <div className="panel header">
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <h1>AIOps control room</h1>
          <span className="badge agent" title="Authenticated Operator Session">
            OPERATOR: {username} ({role})
          </span>
        </div>
        <div className="sub" style={{ marginTop: 4 }}>
          Watching {data.services.length} services. Analysis engine: {data.llm?.enabled ? `Mistral AI (${data.llm.model || "small"})` : "Automated rule engine (built-in)"}
        </div>
      </div>

      <div className="controls">
        <div className="seg" role="group" aria-label="Remediation mode">
          <button
            className={data.mode === "auto" ? "on" : ""}
            onClick={() => run(() => api.setMode("auto"), "Low-risk fixes run automatically")}
          >
            Auto-fix low risk
          </button>
          <button
            className={data.mode === "approve_all" ? "on" : ""}
            onClick={() => run(() => api.setMode("approve_all"), "Every action now needs approval")}
          >
            Ask before every fix
          </button>
        </div>

        <select className="select" value={svc} onChange={(e) => setSvc(e.target.value)} aria-label="Service to break">
          {SERVICES.map((s) => <option key={s} value={s}>{friendlySvc(s)}</option>)}
        </select>
        <select className="select" value={fault} onChange={(e) => setFault(e.target.value)} aria-label="Failure type">
          {FAULTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>

        <button className="btn primary" onClick={() => run(() => api.chaos(svc, fault), `Injected ${fault} into ${svc}`)}>
          Inject failure
        </button>
        <button className="btn" onClick={() => run(api.reset, "Cleared all injected faults")}>
          Reset faults
        </button>

        {onLogout && (
          <button className="btn reject" onClick={onLogout} title="Sign out of operator session">
            Sign Out
          </button>
        )}

        {msg && <span className="muted" role="status">{msg}</span>}
      </div>
    </div>
  );
}
