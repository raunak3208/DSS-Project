import { friendlySvc } from "./IncidentPanel.jsx";

const NODE_POS = {
  gateway: {
    x: 40,
    y: 100,
    w: 190,
    h: 80,
    cx: 135,
    cy: 140,
    role: "INGRESS GATEWAY",
    tier: "Tier 1",
  },
  "user-service": {
    x: 375,
    y: 28,
    w: 190,
    h: 80,
    cx: 470,
    cy: 68,
    role: "ACCOUNTS & AUTH",
    tier: "Tier 2",
  },
  "order-service": {
    x: 375,
    y: 172,
    w: 190,
    h: 80,
    cx: 470,
    cy: 212,
    role: "CORE CHECKOUT",
    tier: "Tier 2",
  },
  "payment-service": {
    x: 710,
    y: 40,
    w: 190,
    h: 80,
    cx: 805,
    cy: 80,
    role: "CRITICAL PAYMENT",
    tier: "Tier 3",
  },
  "notification-service": {
    x: 710,
    y: 172,
    w: 190,
    h: 80,
    cx: 805,
    cy: 212,
    role: "EVENT WORKER",
    tier: "Tier 3",
  },
};

const EDGE_ATTACH = {
  "gateway->user-service": { x1: 230, y1: 120, x2: 375, y2: 68 },
  "gateway->order-service": { x1: 230, y1: 160, x2: 375, y2: 212 },
  "order-service->payment-service": { x1: 565, y1: 192, x2: 710, y2: 80 },
  "order-service->notification-service": { x1: 565, y1: 212, x2: 710, y2: 212 },
  "order-service->user-service": { x1: 470, y1: 172, x2: 470, y2: 108 },
};

export default function ServiceGraph({ services, edges, rootCause, selected, onSelect }) {
  const byService = Object.fromEntries(services.map((s) => [s.service, s]));

  return (
    <div className="topology-container">
      <div className="topology-header-bar">
        <div>
          <div className="topology-title-row">
            <h3>Microservices Architecture & Live Call Topology</h3>
            <span className="badge agent">5 Monitored Services</span>
            <span className="badge ok">Real-Time Telemetry</span>
          </div>
          <div className="topology-subtext">
            Interactive distributed trace graph. Click any component to inspect telemetry and anomaly baselines below.
          </div>
        </div>

        <div className="topology-legend">
          <span className="legend-item"><span className="legend-dot ok" /> Healthy</span>
          <span className="legend-item"><span className="legend-dot warn" /> Stalled Upstream</span>
          <span className="legend-item"><span className="legend-dot bad" /> Culprit Root Cause</span>
        </div>
      </div>

      <div className="topology-canvas-wrap">
        <svg
          className="topology-svg"
          viewBox="0 0 940 280"
          role="img"
          aria-label="Microservice call graph topology"
        >
          <defs>
            {/* Subtle background grid pattern for light theme */}
            <pattern id="topoGrid" width="24" height="24" patternUnits="userSpaceOnUse">
              <circle cx="2" cy="2" r="1.2" fill="#cbd5e1" opacity="0.65" />
            </pattern>

            {/* Soft card shadow */}
            <filter id="cardShadow" x="-6%" y="-6%" width="112%" height="116%">
              <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="#0f172a" floodOpacity="0.06" />
            </filter>

            {/* Arrow markers */}
            <marker id="arr-normal" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0 1L8 5L0 9z" fill="#94a3b8" />
            </marker>
            <marker id="arr-alert" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0 1L8 5L0 9z" fill="#dc2626" />
            </marker>
            <marker id="arr-warn" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0 1L8 5L0 9z" fill="#d97706" />
            </marker>
          </defs>

          {/* Clean light grid background */}
          <rect width="100%" height="100%" fill="#f8fafc" rx="8" />
          <rect width="100%" height="100%" fill="url(#topoGrid)" rx="8" />

          {/* Tier Guide Labels */}
          <text x="50" y="22" fill="#64748b" fontSize="10.5" fontWeight="700" letterSpacing="0.08em">TIER 1: INGRESS</text>
          <text x="385" y="22" fill="#64748b" fontSize="10.5" fontWeight="700" letterSpacing="0.08em">TIER 2: CORE SERVICES</text>
          <text x="720" y="22" fill="#64748b" fontSize="10.5" fontWeight="700" letterSpacing="0.08em">TIER 3: BACKEND & WORKERS</text>

          {/* Edge Dependency Lines */}
          {edges.map((e) => {
            const key = `${e.src}->${e.dst}`;
            const attach = EDGE_ATTACH[key];
            if (!attach) return null;

            const isCulpritEdge = rootCause === e.dst || (rootCause === "payment-service" && e.dst === "payment-service");
            const isWarnEdge = e.err_rate > 0.05 || e.avg_ms > 300;
            const markerId = isCulpritEdge ? "arr-alert" : isWarnEdge ? "arr-warn" : "arr-normal";
            const lineColor = isCulpritEdge ? "#dc2626" : isWarnEdge ? "#d97706" : "#94a3b8";
            const midX = (attach.x1 + attach.x2) / 2;
            const midY = (attach.y1 + attach.y2) / 2;

            return (
              <g key={key} className="topology-edge-group">
                {/* Glow for culprit edge */}
                {isCulpritEdge && (
                  <line
                    x1={attach.x1} y1={attach.y1}
                    x2={attach.x2} y2={attach.y2}
                    stroke="#fee2e2" strokeWidth="6" opacity="0.8"
                  />
                )}
                {/* Base Line */}
                <line
                  x1={attach.x1} y1={attach.y1}
                  x2={attach.x2} y2={attach.y2}
                  stroke={lineColor}
                  strokeWidth={isCulpritEdge ? 2.5 : 1.8}
                  strokeDasharray={isCulpritEdge ? "6 4" : "none"}
                  markerEnd={`url(#${markerId})`}
                  className={isCulpritEdge ? "pulse-edge" : ""}
                />
                {/* Floating Edge Latency Pill */}
                <rect
                  x={midX - 22} y={midY - 10}
                  width="44" height="18"
                  rx="4"
                  fill="#ffffff"
                  stroke={lineColor}
                  strokeWidth="1"
                />
                <text
                  x={midX} y={midY + 2.5}
                  textAnchor="middle"
                  fill="#334155"
                  fontSize="10"
                  fontFamily="monospace"
                  fontWeight="600"
                >
                  {Math.round(e.avg_ms)}ms
                </text>
              </g>
            );
          })}

          {/* Node Cards */}
          {Object.entries(NODE_POS).map(([name, pos]) => {
            const s = byService[name] || {};
            const isRoot = rootCause === name;
            const isSelected = selected === name;
            const isDegraded = s.status === "degraded" || s.status === "down";
            const p95Val = s.p95_ms != null ? `${Math.round(s.p95_ms)}ms` : "-";
            const errVal = s.err_rate != null ? `${Math.round(s.err_rate * 100)}%` : "0%";
            const rpsVal = s.rps != null ? `${s.rps.toFixed(1)} rps` : "-";

            // Border and fill for light theme
            const cardFill = isRoot
              ? "#fef2f2"
              : isDegraded
              ? "#fffbeb"
              : "#ffffff";

            const strokeColor = isRoot
              ? "#ef4444"
              : isSelected
              ? "#0284c7"
              : isDegraded
              ? "#f59e0b"
              : "#cbd5e1";

            const strokeWidth = isRoot ? 2.5 : isSelected ? 2.5 : 1.5;

            return (
              <g
                key={name}
                onClick={() => onSelect(name)}
                style={{ cursor: "pointer" }}
                role="button"
                tabIndex={0}
                aria-label={`${friendlySvc(name)} status ${s.status || "unknown"}`}
              >
                {/* Pulsing red halo for root cause */}
                {isRoot && (
                  <rect
                    x={pos.x - 4}
                    y={pos.y - 4}
                    width={pos.w + 8}
                    height={pos.h + 8}
                    rx="12"
                    fill="none"
                    stroke="#ef4444"
                    strokeWidth="2"
                    className="pulse-halo"
                  />
                )}

                {/* Card Background */}
                <rect
                  x={pos.x}
                  y={pos.y}
                  width={pos.w}
                  height={pos.h}
                  rx="8"
                  fill={cardFill}
                  stroke={strokeColor}
                  strokeWidth={strokeWidth}
                  filter="url(#cardShadow)"
                />

                {/* Header Role Bar */}
                <text
                  x={pos.x + 10}
                  y={pos.y + 18}
                  fill={isRoot ? "#b91c1c" : "#64748b"}
                  fontSize="8.5"
                  fontWeight="750"
                  fontFamily="monospace"
                  letterSpacing="0.06em"
                >
                  {pos.role}
                </text>

                {/* Status Indicator Tag */}
                {isRoot ? (
                  <g>
                    <rect x={pos.x + pos.w - 76} y={pos.y + 8} width="68" height="15" rx="3" fill="#fee2e2" stroke="#fca5a5" strokeWidth="0.8" />
                    <text x={pos.x + pos.w - 42} y={pos.y + 19} textAnchor="middle" fill="#b91c1c" fontSize="8" fontWeight="800">
                      ROOT CAUSE
                    </text>
                  </g>
                ) : isDegraded ? (
                  <g>
                    <rect x={pos.x + pos.w - 64} y={pos.y + 8} width="56" height="15" rx="3" fill="#fef3c7" stroke="#fde047" strokeWidth="0.8" />
                    <text x={pos.x + pos.w - 36} y={pos.y + 19} textAnchor="middle" fill="#92400e" fontSize="8" fontWeight="800">
                      STALLED
                    </text>
                  </g>
                ) : (
                  <g>
                    <circle cx={pos.x + pos.w - 55} cy={pos.y + 15} r="3" fill="#10b981" />
                    <text x={pos.x + pos.w - 46} y={pos.y + 18} fill="#047857" fontSize="8.5" fontWeight="700">
                      HEALTHY
                    </text>
                  </g>
                )}

                {/* Friendly Service Name */}
                <text
                  x={pos.x + 10}
                  y={pos.y + 40}
                  fill="#0f172a"
                  fontSize="12.5"
                  fontWeight="750"
                >
                  {friendlySvc(name)}
                </text>

                {/* Telemetry Metrics Bar */}
                <g transform={`translate(${pos.x + 10}, ${pos.y + 53})`}>
                  <rect width="52" height="18" rx="3" fill="#f1f5f9" stroke="#e2e8f0" strokeWidth="0.8" />
                  <text x="26" y="13" textAnchor="middle" fill={isRoot ? "#b91c1c" : "#0369a1"} fontSize="9.5" fontFamily="monospace" fontWeight="600">
                    {p95Val}
                  </text>

                  <rect x="56" width="54" height="18" rx="3" fill="#f1f5f9" stroke="#e2e8f0" strokeWidth="0.8" />
                  <text x="83" y="13" textAnchor="middle" fill="#334155" fontSize="9.5" fontFamily="monospace" fontWeight="600">
                    {rpsVal}
                  </text>

                  <rect x="114" width="46" height="18" rx="3" fill="#f1f5f9" stroke="#e2e8f0" strokeWidth="0.8" />
                  <text x="137" y="13" textAnchor="middle" fill={errVal !== "0%" ? "#b91c1c" : "#047857"} fontSize="9.5" fontFamily="monospace" fontWeight="600">
                    {errVal}
                  </text>
                </g>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

export function ServiceCards({ services, selected, onSelect }) {
  return (
    <div className="topology-cards-strip">
      {services.map((s) => {
        const isSel = selected === s.service;
        return (
          <button
            key={s.service}
            className={`topology-summary-card ${s.status} ${isSel ? "active-sel" : ""}`}
            onClick={() => onSelect(s.service)}
          >
            <div className="summary-card-top">
              <span className="summary-service-name">{friendlySvc(s.service)}</span>
              <span className={`summary-status-pill ${s.status}`}>{s.status.toUpperCase()}</span>
            </div>
            <div className="summary-metrics-grid">
              <div><span>P95</span> <b>{s.p95_ms != null ? `${Math.round(s.p95_ms)}ms` : "-"}</b></div>
              <div><span>RPS</span> <b>{s.rps != null ? s.rps.toFixed(1) : "-"}</b></div>
              <div><span>CPU</span> <b>{s.cpu_pct != null ? `${Math.round(s.cpu_pct)}%` : "-"}</b></div>
              <div><span>ERR</span> <b>{s.err_rate != null ? `${Math.round(s.err_rate * 100)}%` : "0%"}</b></div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
