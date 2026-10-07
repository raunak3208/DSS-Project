import { useEffect, useState } from "react";

async function call(path, method = "GET", body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.json();
}

export const api = {
  overview: () => call("/api/overview"),
  approve: (id, approved, note) => call(`/api/incidents/${id}/approval`, "POST", { approved, note, by: "dashboard operator" }),
  chaos: (service, type, intensity) => call("/api/chaos", "POST", { service, type, ...(intensity ? { intensity } : {}) }),
  reset: () => call("/api/chaos/reset", "POST"),
  setMode: (mode) => call("/api/mode", "POST", { mode }),
};

/** Poll the controller every `ms` milliseconds. */
export function useOverview(ms = 2000) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    const load = () =>
      api.overview().then((d) => live && (setData(d), setError(null))).catch((e) => live && setError(e.message));
    load();
    const t = setInterval(load, ms);
    return () => { live = false; clearInterval(t); };
  }, [ms, tick]);
  return { data, error, refresh: () => setTick((n) => n + 1) };
}

export const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
export const short = (s) => (s || "").replace("-service", "");
