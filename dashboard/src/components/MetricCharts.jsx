import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtTime } from "../api.js";

const CHARTS = [["cpu_pct", "CPU (%)"], ["mem_mb", "Memory (MB)"], ["p95_ms", "p95 latency (ms)"], ["err_rate", "Error rate"]];

export default function MetricCharts({ service }) {
  const bad = service.status === "degraded" || service.status === "down";
  const color = bad ? "#c8372d" : "#4b49c8";
  return (
    <div className="panel">
      <h2>Live metrics for {service.service} <span className={`badge ${bad ? "bad" : "ok"}`}>{service.status}</span></h2>
      <div className="chart-grid">
        {CHARTS.map(([key, title]) => (
          <div key={key}>
            <div className="chart-title">{title}</div>
            <ResponsiveContainer width="100%" height={130}>
              <LineChart data={service.series} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
                <CartesianGrid stroke="#edf0f3" vertical={false} />
                <XAxis dataKey="ts" hide />
                <YAxis tick={{ fontSize: 10 }} width={44} domain={key === "err_rate" ? [0, 1] : ["auto", "auto"]} />
                <Tooltip labelFormatter={fmtTime} formatter={(v) => [v, title]} contentStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey={key} stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ))}
      </div>
    </div>
  );
}
