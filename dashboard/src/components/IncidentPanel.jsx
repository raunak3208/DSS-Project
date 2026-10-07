import { useState } from "react";
import { api, fmtTime, short } from "../api.js";

const STATUS = { analyzing: "agent", awaiting_approval: "human", remediating: "agent", verifying: "agent", resolved: "ok", escalated: "bad" };
const STATUS_TEXT = { analyzing: "Analyzing", awaiting_approval: "Waiting for you", remediating: "Remediating", verifying: "Verifying", resolved: "Resolved", escalated: "Needs a human" };
const SEV = { medium: "warn", high: "warn", critical: "bad" };
const GATE = { ALLOW_AUTO: ["ok", "Allowed automatically"], REQUIRE_APPROVAL: ["human", "Human approval required"], DENY: ["bad", "Denied"] };
const COLS = [["cpu_pct", "CPU %"], ["mem_mb", "Mem MB"], ["p95_ms", "p95 ms"], ["err_rate", "Err"]];

function BeforeAfter({ before, after }) {
  if (!before) return null;
  const rows = Object.keys(before);
  return (
    <>
      <h3>Before and after remediation</h3>
      <table>
        <thead><tr><th>Service</th>{COLS.map(([, l]) => <th key={l}>{l}</th>)}<th>Status</th></tr></thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s}>
              <td>{short(s) || s}</td>
              {COLS.map(([k]) => {
                const b = before[s]?.[k], a = after?.[s]?.[k];
                const cls = a == null || b == null ? "" : a < b * 0.8 ? "better" : a > b * 1.2 ? "worse" : "";
                return <td key={k} className={cls}>{b ?? "-"}{after ? ` → ${a ?? "-"}` : ""}</td>;
              })}
              <td>{before[s]?.status}{after ? ` → ${after[s]?.status ?? "-"}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Approval({ incident }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async (ok) => { setBusy(true); try { await api.approve(incident.id, ok, note); } finally { setBusy(false); } };
  const p = incident.plan;
  return (
    <div className="approval">
      <b>Your decision is needed</b>
      <div>The agent wants to run <b>{p.type}</b> on <b>{p.target}</b>{p.params?.replicas ? ` (${p.params.replicas} replicas)` : ""}. Nothing runs until you choose.</div>
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional note for the audit log" aria-label="Approval note" />
      <div className="row">
        <button className="btn approve" disabled={busy} onClick={() => send(true)}>Approve and run</button>
        <button className="btn reject" disabled={busy} onClick={() => send(false)}>Reject and escalate</button>
      </div>
    </div>
  );
}

export default function IncidentPanel({ incident, learning }) {
  if (!incident) {
    return (
      <div className="panel">
        <h2>Incident</h2>
        <div className="empty">
          {learning ? "Learning normal behaviour for each service. This takes about a minute after startup."
            : "No incidents. Everything is within its learned baseline. Use Inject failure to start a demo."}
        </div>
      </div>
    );
  }
  const { analysis: a, plan: p, gate: g, rca } = incident;
  const maxScore = Math.max(...(rca || []).map((r) => r.score), 0.01);
  return (
    <div className="panel">
      <h2>Incident {incident.id}</h2>
      <div className="pills">
        <span className={`badge ${STATUS[incident.status]}`}>{STATUS_TEXT[incident.status]}</span>
        <span className={`badge ${SEV[incident.severity]}`}>Severity {incident.severity}</span>
        <span className="badge">Started {fmtTime(incident.created)}</span>
        {incident.iteration > 0 && <span className="badge agent">Attempt {incident.iteration + 1}</span>}
      </div>
      {incident.status === "escalated" && <div className="banner bad">The agent stopped and handed this to a human. See the timeline for why.</div>}
      {incident.status === "awaiting_approval" && <Approval incident={incident} />}

      {a && (
        <>
          <h3>Root cause</h3>
          <div><b>{a.root_cause_service}</b> <span className="muted">({a.fault_type.replace("_", " ")}, confidence {Math.round(a.confidence * 100)}%)</span></div>
          <div className="bars" style={{ marginTop: 6 }}>
            {(rca || []).slice(0, 4).map((r, i) => (
              <div key={r.service} className={`bar ${i === 0 ? "top" : ""}`} title={JSON.stringify(r.components)}>
                <span>{short(r.service) || r.service}</span><i style={{ width: `${(r.score / maxScore) * 100}%` }} /><span>{r.score}</span>
              </div>
            ))}
          </div>
          {rca?.[0]?.path?.length > 1 && <div className="muted" style={{ marginTop: 4 }}>Call path: {rca[0].path.map(short).join(" → ")}</div>}
          <h3>Why the agent thinks so <span className={`badge ${a.source === "llm" ? "agent" : ""}`}>{a.source === "llm" ? "LLM reasoning" : "rule-based"}</span></h3>
          <div className="explain">{a.explanation}</div>
          {a.llm_error && <div className="muted">LLM unavailable ({a.llm_error}); used rule-based reasoning instead.</div>}
          {a.validation_notes?.map((n) => <div key={n} className="muted">Guardrail: {n}</div>)}
        </>
      )}

      {p && p.type !== "none" && (
        <>
          <h3>Proposed action</h3>
          <div><b>{p.type}</b> on <b>{p.target}</b>{p.params?.replicas ? ` to ${p.params.replicas} replicas` : ""}</div>
        </>
      )}

      {g && (
        <>
          <h3>Safety gate <span className={`badge ${GATE[g.decision][0]}`}>{GATE[g.decision][1]}</span> <span className="badge">risk {g.risk}</span></h3>
          <div className="checks">
            {[...g.checks].sort((x, y) => x.passed - y.passed).map((c) => (
              <div className="check" key={c.check} title={c.note}>
                <span className={`dot ${c.passed ? "" : "fail " + c.effect}`} />
                <span>{c.check.replaceAll("_", " ")}</span><span className="muted">{c.note}</span>
              </div>
            ))}
          </div>
        </>
      )}
      {incident.approval && incident.approval.status !== "pending" && (
        <div className="muted" style={{ marginTop: 6 }}>Approval {incident.approval.status} by {incident.approval.by}{incident.approval.note ? `: ${incident.approval.note}` : ""}</div>
      )}
      {incident.execution && <div className="muted" style={{ marginTop: 6 }}>{incident.execution.ok ? "Executed" : "Failed"}: {incident.execution.detail}</div>}
      <BeforeAfter before={incident.before} after={incident.after} />
      {incident.verification && (
        <div style={{ marginTop: 6 }}>
          <span className={`badge ${incident.verification.resolved ? "ok" : "bad"}`}>{incident.verification.resolved ? "Verified fixed" : "Not fixed"}</span>{" "}
          <span className="muted">{incident.verification.remaining?.join("; ")}</span>
        </div>
      )}
      {incident.history?.length > 0 && (
        <>
          <h3>Earlier attempts</h3>
          {incident.history.map((h) => <div key={h.iteration} className="muted">Attempt {h.iteration + 1}: {h.action} on {h.target} did not fix it</div>)}
        </>
      )}
    </div>
  );
}
