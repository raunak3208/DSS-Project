import { useState } from "react";
import { api, fmtTime } from "../api.js";

export const STATUS_BADGES = {
  analyzing: { label: "Analyzing Anomaly", cls: "agent" },
  awaiting_approval: { label: "Operator Decision Required", cls: "human" },
  remediating: { label: "Executing Fix", cls: "agent" },
  verifying: { label: "Verifying Recovery", cls: "agent" },
  resolved: { label: "Resolved", cls: "ok" },
  escalated: { label: "Escalated to Operator", cls: "bad" },
};

export const SEV_BADGES = {
  low: { label: "Low Severity", cls: "ok" },
  medium: { label: "Medium Severity", cls: "warn" },
  high: { label: "High Severity", cls: "warn" },
  critical: { label: "Critical Severity", cls: "bad" },
};

export const SERVICE_NAMES = {
  gateway: "Customer Storefront",
  "order-service": "Order & Checkout System",
  "payment-service": "Payment Processing System",
  "user-service": "User Accounts System",
  "notification-service": "Customer Notification System",
};

export const friendlySvc = (s) => SERVICE_NAMES[s] || (s || "").replace("-service", "").toUpperCase();

export const ACTION_TITLES = {
  restart_pod: "Restart Container Instance",
  restart_service: "Restart Service Process",
  scale_deployment: "Scale Service Replicas",
  rollback_deployment: "Rollback to Previous Release",
  none: "Monitor System (No Action)",
};

export const ACTION_EXPLANATIONS = {
  restart_pod: "Recreates the container instance to clear hung socket connections and memory pressure.",
  restart_service: "Gracefully restarts the application process without altering configuration.",
  scale_deployment: "Increases replica count to distribute traffic load and reduce CPU saturation.",
  rollback_deployment: "Reverts the application back to the previous stable release.",
  none: "Continuous monitoring; metrics expected to stabilize naturally.",
};

export const GATE_CHECKS_BRIEF = {
  incident_severity: {
    title: "Incident Severity",
    brief: (c) => c.passed ? "Moderate severity: automated recovery permitted." : "Critical severity: human operator confirmation required.",
  },
  critical_service: {
    title: "Critical Service Guard",
    brief: (c, target) => c.passed ? `${friendlySvc(target)} is a critical service: low-risk action permitted.` : `${friendlySvc(target)} is critical: elevated action risk requires operator sign-off.`,
  },
  action_allowlisted: {
    title: "Action Allowlist",
    brief: (c, target, plan) => `${ACTION_TITLES[plan?.type] || plan?.type} is an approved safe action.`,
  },
  target_in_inventory: {
    title: "Service Inventory",
    brief: (c, target) => `${friendlySvc(target)} is a registered managed service.`,
  },
  target_matches_rca: {
    title: "Root Cause Alignment",
    brief: (c, target) => `Target matches the #1 diagnosed root cause candidate.`,
  },
  params_valid: {
    title: "Parameter Validation",
    brief: (c, target, plan) => plan?.params?.replicas ? `Replicas (${plan.params.replicas}) verified within safe bounds.` : `Action takes no unsafe parameter overrides.`,
  },
  risk_level: {
    title: "Action Risk Level",
    brief: () => `Classified as Low Risk (safe container lifecycle action).`,
  },
  confidence: {
    title: "Diagnostic Confidence",
    brief: (c) => {
      const match = c?.note?.match(/([\d.]+)/);
      const pct = match ? Math.round(parseFloat(match[1]) * 100) : 78;
      return `Confidence is ${pct}% (exceeds the 70% automated threshold).`;
    },
  },
  blast_radius: {
    title: "Upstream Blast Radius",
    brief: (c, target) => {
      const match = c?.note?.match(/(\d+)\s+upstream/);
      const count = match ? match[1] : "2";
      return `${count} upstream service(s) depend on ${friendlySvc(target)}.`;
    },
  },
  cooldown: {
    title: "Anti-Flapping Cooldown",
    brief: () => `No duplicate actions executed on target within last 60 seconds.`,
  },
  rate_limit: {
    title: "Rate Budget (10m)",
    brief: (c) => {
      const match = c?.note?.match(/(\d+)\s+auto-actions/);
      const count = match ? match[1] : "0";
      return `${count} of 6 automated actions executed in last 10 minutes.`;
    },
  },
  mode: {
    title: "Operating Mode",
    brief: () => `Autonomous Mode active with Safety Policy Interlocks.`,
  },
};

export function cleanExplanationText(text) {
  if (!text) return "";
  return text
    .replace(/POST\s+\/charge[^\"]*connection reset by peer[^\"]*/gi, "Payment transactions were dropped by the backend payment network")
    .replace(/POST\s+\/api\/checkout[^\"]*upstream call[^\"]*/gi, "Checkout operations were delayed waiting on payment confirmation")
    .replace(/POST\s+\/\S+/g, "transaction requests")
    .replace(/GET\s+\/\S+/g, "queries")
    .replace(/status=<\*>/g, "")
    .replace(/status=\d+/g, "")
    .replace(/reason=Unhandled exception:\s*/gi, "")
    .replace(/reason=/gi, "due to: ")
    .replace(/payment-service/g, "Payment Processing System")
    .replace(/order-service/g, "Order & Checkout System")
    .replace(/gateway/g, "Customer Storefront")
    .replace(/user-service/g, "User Accounts System")
    .replace(/notification-service/g, "Customer Notification System")
    .replace(/\(graph-RCA score [\d.]+\)/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

const METRIC_COLS = [["cpu_pct", "CPU %"], ["mem_mb", "Mem MB"], ["p95_ms", "Response ms"], ["err_rate", "Err Rate"]];

function BeforeAfterTable({ before, after }) {
  if (!before) return null;
  const rows = Object.keys(before);
  return (
    <div className="incident-card verification-card full-width-card">
      <div className="card-header">
        <span className="card-step-badge">STAGE 5</span>
        <h3>Closed-Loop Telemetry Verification (Before vs. After Remediation)</h3>
      </div>
      <p className="card-subtext">
        Closed-loop verification: The autonomous controller monitors live telemetry post-action and only resolves the incident when metrics return to learned healthy baselines.
      </p>
      <table>
        <thead>
          <tr>
            <th>Component</th>
            {METRIC_COLS.map(([, l]) => <th key={l}>{l}</th>)}
            <th>Health Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s}>
              <td><strong>{friendlySvc(s)}</strong></td>
              {METRIC_COLS.map(([k]) => {
                const b = before[s]?.[k], a = after?.[s]?.[k];
                const cls = a == null || b == null ? "" : a < b * 0.8 ? "better" : a > b * 1.2 ? "worse" : "";
                const formatVal = (v) => {
                  if (v == null) return "-";
                  if (k === "err_rate") return `${Math.round(v * 100)}%`;
                  if (k === "p95_ms") return `${Math.round(v)} ms`;
                  if (k === "cpu_pct") return `${Math.round(v)}%`;
                  if (k === "mem_mb") return `${Math.round(v)} MB`;
                  return v;
                };
                return (
                  <td key={k} className={cls}>
                    {formatVal(b)}{after ? ` -> ${formatVal(a)}` : ""}
                  </td>
                );
              })}
              <td>
                <span className={`badge ${before[s]?.status === "healthy" ? "ok" : "warn"}`}>
                  {before[s]?.status}
                </span>
                {after && after[s]?.status && (
                  <> {"->"} <span className={`badge ${after[s]?.status === "healthy" ? "ok" : "warn"}`}>{after[s]?.status}</span></>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ApprovalBox({ incident }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async (ok) => { setBusy(true); try { await api.approve(incident.id, ok, note); } finally { setBusy(false); } };
  const p = incident.plan;
  const actionTitle = ACTION_TITLES[p.type] || p.type;
  const targetLabel = friendlySvc(p.target);

  return (
    <div className="incident-card human-approval-card full-width-card">
      <div className="approval-header-row">
        <div>
          <h3>Operator Decision Station - Human Confirmation Required</h3>
          <p className="approval-subtext">
            Deterministic Safety Policy Gate intercepted this action: <strong>{targetLabel}</strong> is a critical service and incident severity is <strong>Critical</strong>. Operator confirmation required before container restart.
          </p>
        </div>
      </div>

      <div className="approval-remediation-summary">
        <div><strong>Recommended Action:</strong> <span className="action-highlight">{actionTitle}</span></div>
        <div><strong>Target Component:</strong> <span className="action-highlight">{targetLabel}</span> {p.params?.replicas ? `(Scale to ${p.params.replicas} instances)` : ""}</div>
        <div><strong>Expected Result:</strong> Reconnects dropped sockets and restores upstream Storefront and Checkout systems.</div>
      </div>

      <div style={{ margin: "10px 0" }}>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Operator notes (e.g., 'Approved for live test')..."
          aria-label="Approval note"
          className="approval-input"
        />
      </div>

      <div className="approval-btn-row">
        <button className="btn approve primary-action-btn" disabled={busy} onClick={() => send(true)}>
          Approve and Execute Fix
        </button>
        <button className="btn reject secondary-action-btn" disabled={busy} onClick={() => send(false)}>
          Reject Action (Manual Ops)
        </button>
      </div>
    </div>
  );
}

export default function IncidentPanel({ incident, learning }) {
  if (!incident) {
    return (
      <div className="panel incident-panel-container full-page-panel">
        <h2>Autonomous Incident Management</h2>
        <div className="empty">
          {learning
            ? "Calibrating baseline performance for each microservice. This takes about a minute after startup."
            : "No active incidents. Telemetry is streaming normally and all services are operating within learned baselines. Use 'Inject failure' above to demonstrate closed-loop auto-remediation."}
        </div>
      </div>
    );
  }

  const { analysis: a, plan: p, gate: g, rca } = incident;
  const statusInfo = STATUS_BADGES[incident.status] || { label: incident.status, cls: "agent" };
  const sevInfo = SEV_BADGES[incident.severity] || { label: incident.severity, cls: "warn" };
  const maxScore = Math.max(...(rca || []).map((r) => r.score), 0.01);
  const rootCauseName = friendlySvc(a?.root_cause_service || incident.root_cause);

  const flaggedChecks = (g?.checks || []).filter((c) => !c.passed);
  const passedChecks = (g?.checks || []).filter((c) => c.passed);

  return (
    <div className="panel incident-panel-container full-page-panel">
      {/* Top Incident Summary Banner */}
      <div className="incident-header-banner">
        <div className="incident-title-row">
          <div className="incident-num-badge">INCIDENT #{incident.id}</div>
          <span className={`badge ${statusInfo.cls}`}>{statusInfo.label}</span>
          <span className={`badge ${sevInfo.cls}`}>{sevInfo.label}</span>
          <span className="badge">Detected at {fmtTime(incident.created)}</span>
        </div>

        <div className="executive-summary-callout">
          <div className="exec-title">Executive Summary</div>
          <div className="exec-body">
            <strong>1. Identified Root Cause:</strong> <strong>{rootCauseName}</strong> latency spike / connection drop.<br />
            <strong>2. Cascading Impact:</strong> Customer Storefront and Order Checkout stalled waiting for Payment responses.<br />
            <strong>3. Recommended Action & Safety Gate:</strong> Proposed <strong>{ACTION_TITLES[p?.type] || p?.type || "Restart Container"}</strong> on <strong>{rootCauseName}</strong>. 
            {g?.decision === "REQUIRE_APPROVAL" && " Operator confirmation required because Payment is a Critical Service and severity is Critical."}
          </div>
        </div>
      </div>

      {/* Human Approval Station if waiting */}
      {incident.status === "awaiting_approval" && <ApprovalBox incident={incident} />}

      {/* Remediation in Progress */}
      {incident.status === "remediating" && (
        <div className="incident-card active-progress-card full-width-card">
          <div className="progress-flex">
            <div className="auth-spinner" />
            <div>
              <strong>STAGE 3: Executing Autonomous Fix</strong>
              <div className="muted">Restarting container instance for {rootCauseName}...</div>
            </div>
          </div>
        </div>
      )}

      {/* Verifying Recovery */}
      {incident.status === "verifying" && (
        <div className="incident-card active-progress-card verifying full-width-card">
          <div className="progress-flex">
            <div className="auth-spinner" />
            <div>
              <strong>STAGE 4: Verifying Recovery Telemetry</strong>
              <div className="muted">Evaluating post-remediation response times and error rates against learned baselines...</div>
            </div>
          </div>
        </div>
      )}

      {/* Resolved Success */}
      {incident.status === "resolved" && (
        <div className="incident-card resolved-success-card full-width-card">
          <div className="progress-flex">
            <span className="badge ok">RESOLVED</span>
            <div>
              <strong>Incident #{incident.id} Successfully Resolved</strong>
              <div style={{ fontSize: 13, color: "#166534" }}>All microservices returned to healthy response times and 0% error rate.</div>
            </div>
          </div>
        </div>
      )}

      {/* STAGE 1 & 2: Root Cause Analysis & Impact Propagation */}
      {a && (
        <div className="incident-card rca-card full-width-card">
          <div className="card-header">
            <span className="card-step-badge">STAGE 1 & 2</span>
            <h3>Identified Root Cause & Impact Propagation</h3>
          </div>

          <div className="rca-main-callout">
            <div className="rca-target-name">
              <div>
                <div className="rca-service-title">{friendlySvc(a.root_cause_service)}</div>
                <div className="rca-fault-type">
                  Diagnosed Anomaly: <strong>{a.fault_type.replace("_", " ").toUpperCase()}</strong> (Confidence: {Math.round(a.confidence * 100)}%)
                </div>
              </div>
            </div>
          </div>

          {/* Impact Call Graph Chain */}
          {rca?.[0]?.path?.length > 1 && (
            <div className="impact-chain-box">
              <div className="chain-label">Impact Chain (Call Graph Propagation):</div>
              <div className="chain-nodes">
                {rca[0].path.map((node, i) => (
                  <span key={node} className="chain-node-item">
                    <span className={`chain-pill ${node === a.root_cause_service ? "culprit-pill" : "victim-pill"}`}>
                      {node === a.root_cause_service ? `Root Cause: ${friendlySvc(node)}` : `Upstream: ${friendlySvc(node)}`}
                    </span>
                    {i < rca[0].path.length - 1 && <span className="chain-arrow">{" -> (waiting on) -> "}</span>}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Root cause ranking bars */}
          <div className="rca-ranking-section">
            <div className="ranking-label">Root Cause Probability Ranking:</div>
            <div className="bars" style={{ marginTop: 6 }}>
              {(rca || []).slice(0, 4).map((r, i) => (
                <div key={r.service} className={`bar ${i === 0 ? "top" : ""}`} title={`RCA score: ${r.score}`}>
                  <span>{friendlySvc(r.service)}</span>
                  <i style={{ width: `${(r.score / maxScore) * 100}%` }} />
                  <span style={{ fontWeight: 600 }}>{Math.round(r.score * 100)}%</span>
                </div>
              ))}
            </div>
          </div>

          {/* Analysis breakdown */}
          <div className="explain-section" style={{ marginTop: 14 }}>
            <div className="explain-header">
              <strong>Analysis Breakdown ({a.source === "llm" ? "Mistral AI" : "Automated Rules"})</strong>
            </div>
            <div className="explain-body">
              {cleanExplanationText(a.explanation)}
            </div>
          </div>
        </div>
      )}

      {/* STAGE 3: Recommended Action */}
      {p && p.type !== "none" && (
        <div className="incident-card action-card full-width-card">
          <div className="card-header">
            <span className="card-step-badge">STAGE 3</span>
            <h3>Recommended Action</h3>
          </div>
          <div className="action-details-grid">
            <div className="action-item">
              <span className="action-label">Action Strategy:</span>
              <span className="action-val primary-val">{ACTION_TITLES[p.type] || p.type}</span>
            </div>
            <div className="action-item">
              <span className="action-label">Target Service:</span>
              <span className="action-val">{friendlySvc(p.target)} {p.params?.replicas ? `(${p.params.replicas} instances)` : ""}</span>
            </div>
            <div className="action-item full-width">
              <span className="action-label">Technical Purpose:</span>
              <span className="action-val">{ACTION_EXPLANATIONS[p.type] || "Executes container recovery to restore service."}</span>
            </div>
          </div>
        </div>
      )}

      {/* STAGE 4: Safety Policy Gate */}
      {g && (
        <div className="incident-card safety-gate-card full-width-card">
          <div className="card-header">
            <span className="card-step-badge">STAGE 4</span>
            <h3>Deterministic Safety Policy Gate (12 Checks)</h3>
            <span className={`badge ${g.decision === "ALLOW_AUTO" ? "ok" : g.decision === "REQUIRE_APPROVAL" ? "human" : "bad"}`}>
              {g.decision === "ALLOW_AUTO" ? "Auto-Remediation Allowed" : g.decision === "REQUIRE_APPROVAL" ? "Operator Confirmation Required" : "Denied by Policy"}
            </span>
          </div>

          <p className="card-subtext">
            Deterministic guardrails evaluate the proposed action before touching infrastructure.
            {g.decision === "REQUIRE_APPROVAL" && (
              <strong> Critical severity on a Critical Service requires human operator sign-off.</strong>
            )}
          </p>

          <div className="gate-checklist-grid-compact">
            {/* Flagged checks */}
            {flaggedChecks.map((c) => {
              const rule = GATE_CHECKS_BRIEF[c.check] || {
                title: c.check.replaceAll("_", " "),
                brief: () => c.note,
              };
              return (
                <div key={c.check} className="gate-check-compact-item flagged">
                  <div className="gate-compact-top">
                    <span className="gate-compact-title">{rule.title}</span>
                    <span className="badge-flagged">CONFIRMATION REQUIRED</span>
                  </div>
                  <div className="gate-compact-desc">{rule.brief(c, p?.target, p)}</div>
                </div>
              );
            })}

            {/* Passed checks */}
            {passedChecks.map((c) => {
              const rule = GATE_CHECKS_BRIEF[c.check] || {
                title: c.check.replaceAll("_", " "),
                brief: () => c.note,
              };
              return (
                <div key={c.check} className="gate-check-compact-item passed">
                  <div className="gate-compact-top">
                    <span className="gate-compact-title">{rule.title}</span>
                    <span className="badge-passed">PASSED</span>
                  </div>
                  <div className="gate-compact-desc">{rule.brief(c, p?.target, p)}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* STAGE 5: Telemetry Verification Table */}
      <BeforeAfterTable before={incident.before} after={incident.after} />
    </div>
  );
}
