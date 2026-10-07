const STAGES = [
  ["detect", "Detect", "anomaly models"],
  ["correlate", "Find root cause", "metrics, logs, call graph"],
  ["agent", "Agent reasoning", "explain and propose"],
  ["gate", "Safety gate", "deterministic policy"],
  ["approval", "Human approval", "only when required"],
  ["remediate", "Remediate", "allow-listed action"],
  ["verify", "Verify", "re-check telemetry"],
];

export default function LoopStrip({ incident }) {
  const idx = incident ? STAGES.findIndex((s) => s[0] === incident.stage) : -1;
  const finished = incident?.stage === "done";
  const skippedApproval = incident?.gate?.decision === "ALLOW_AUTO";
  const retrying = (incident?.iteration || 0) > 0;
  const label = !incident ? "Closed loop: a failed fix sends the agent back to investigate"
    : retrying ? `Attempt ${incident.iteration + 1}: the last fix did not hold, investigating again`
    : "Closed loop: a failed fix sends the agent back to investigate";
  return (
    <div className="panel">
      <div className="loop">
        {STAGES.map(([id, name, sub], i) => {
          let cls = "";
          if (incident) {
            if (id === "approval" && skippedApproval && !incident.approval) cls = "skipped";
            else if (finished) cls = incident.status === "resolved" || i < 4 ? "done" : "";
            else if (i < idx) cls = "done";
            else if (i === idx) cls = id === "approval" ? "active human" : "active";
          }
          if (finished && incident.status === "escalated" && id === "verify") cls = "fail";
          return <div key={id} className={`stage ${cls}`}><b>{name}</b><span>{sub}</span></div>;
        })}
        <div className={`loopback ${retrying || idx === 6 ? "hot" : ""}`} data-label={label} />
      </div>
    </div>
  );
}
