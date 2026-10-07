import { useState } from "react";
import { api, short } from "../api.js";

const FAULTS = [
  ["cpu", "CPU saturation"], ["latency", "Latency spike"], ["memory", "Memory leak"],
  ["errors", "Error burst"], ["crash", "Crash"], ["bad_deploy", "Bad deployment"],
];
const SERVICES = ["gateway", "user-service", "order-service", "payment-service", "notification-service"];

export default function Header({ data, refresh }) {
  const [svc, setSvc] = useState("payment-service");
  const [fault, setFault] = useState("latency");
  const [msg, setMsg] = useState("");
  const run = async (fn, ok) => {
    try { await fn(); setMsg(ok); } catch (e) { setMsg(`Failed: ${e.message.slice(0, 80)}`); }
    refresh();
    setTimeout(() => setMsg(""), 4000);
  };
  return (
    <div className="panel header">
      <div>
        <h1>AIOps control room</h1>
        <div className="sub">
          Watching {data.services.length} services. Reasoning engine: {data.llm.enabled ? `${data.llm.provider} (${data.llm.model})` : "built-in rules (no LLM configured)"}
        </div>
      </div>
      <div className="controls">
        <div className="seg" role="group" aria-label="Remediation mode">
          <button className={data.mode === "auto" ? "on" : ""} onClick={() => run(() => api.setMode("auto"), "Low-risk fixes run automatically")}>Auto-fix low risk</button>
          <button className={data.mode === "approve_all" ? "on" : ""} onClick={() => run(() => api.setMode("approve_all"), "Every action now needs approval")}>Ask before every fix</button>
        </div>
        <select className="select" value={svc} onChange={(e) => setSvc(e.target.value)} aria-label="Service to break">
          {SERVICES.map((s) => <option key={s} value={s}>{short(s) || s}</option>)}
        </select>
        <select className="select" value={fault} onChange={(e) => setFault(e.target.value)} aria-label="Failure type">
          {FAULTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <button className="btn primary" onClick={() => run(() => api.chaos(svc, fault), `Injected ${fault} into ${svc}`)}>Inject failure</button>
        <button className="btn" onClick={() => run(api.reset, "Cleared all injected faults")}>Reset faults</button>
        {msg && <span className="muted" role="status">{msg}</span>}
      </div>
    </div>
  );
}
