import { short } from "../api.js";

const POS = {
  "gateway": [290, 42], "order-service": [150, 150], "user-service": [430, 150],
  "payment-service": [70, 258], "notification-service": [260, 258],
};
const COLOR = { healthy: "#1f8a70", degraded: "#d98e04", down: "#c8372d", learning: "#8a96a3", unknown: "#8a96a3" };

export default function ServiceGraph({ services, edges, rootCause, selected, onSelect }) {
  const by = Object.fromEntries(services.map((s) => [s.service, s]));
  return (
    <div>
      <svg className="graph" viewBox="0 0 520 300" role="img" aria-label="Service dependency graph">
        <defs>
          {["#aab4c0", "#c8372d", "#d98e04"].map((c, i) => (
            <marker key={i} id={`arr${i}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0 0L10 5L0 10z" fill={c} />
            </marker>
          ))}
        </defs>
        {edges.map((e) => {
          const a = POS[e.src], b = POS[e.dst];
          if (!a || !b) return null;
          const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy);
          const [x1, y1, x2, y2] = [a[0] + (dx / len) * 34, a[1] + (dy / len) * 22, b[0] - (dx / len) * 38, b[1] - (dy / len) * 26];
          const k = e.err_rate > 0.15 ? 1 : e.avg_ms > 800 ? 2 : 0;
          return (
            <g key={e.src + e.dst}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={["#aab4c0", "#c8372d", "#d98e04"][k]}
                strokeWidth={k ? 2.5 : 1.5} strokeDasharray={e.calls ? "" : "4 4"} markerEnd={`url(#arr${k})`} />
              {e.calls > 0 && <text x={(x1 + x2) / 2 + 6} y={(y1 + y2) / 2} fontSize="10" fill="#66748a">{Math.round(e.avg_ms)}ms</text>}
            </g>
          );
        })}
        {Object.entries(POS).map(([name, [x, y]]) => {
          const s = by[name] || {};
          const isRoot = rootCause === name;
          return (
            <g key={name} onClick={() => onSelect(name)} style={{ cursor: "pointer" }} tabIndex={0}
               onKeyDown={(ev) => ev.key === "Enter" && onSelect(name)} role="button" aria-label={`${name} ${s.status || "unknown"}`}>
              {isRoot && <rect x={x - 46} y={y - 30} width="92" height="60" rx="10" fill="none" stroke="#4b49c8" strokeWidth="3" strokeDasharray="5 3" />}
              <rect x={x - 40} y={y - 24} width="80" height="48" rx="7" fill="#fff" stroke={COLOR[s.status] || COLOR.unknown} strokeWidth={selected === name ? 4 : 2.5} />
              <text x={x} y={y - 4} textAnchor="middle" fontSize="12.5" fontWeight="650" fill="#1c2733">{short(name) || name}</text>
              <text x={x} y={y + 13} textAnchor="middle" fontSize="10.5" fill="#66748a">{s.status || "unknown"}</text>
              {isRoot && <text x={x} y={y - 34} textAnchor="middle" fontSize="10.5" fontWeight="650" fill="#4b49c8">probable root cause</text>}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function ServiceCards({ services, selected, onSelect }) {
  return (
    <div className="cards">
      {services.map((s) => (
        <button key={s.service} className={`card ${s.status} ${selected === s.service ? "sel" : ""}`} onClick={() => onSelect(s.service)}>
          <div className="row"><span className="name">{s.service}</span><span className="muted">{s.version || ""}</span></div>
          <div className="kv">
            <span>CPU <b>{s.cpu_pct ?? "-"}%</b></span><span>Mem <b>{s.mem_mb ?? "-"}</b></span>
            <span>p95 <b>{s.p95_ms ?? "-"}</b></span><span>Err <b>{s.err_rate != null ? Math.round(s.err_rate * 100) + "%" : "-"}</b></span>
          </div>
        </button>
      ))}
    </div>
  );
}
