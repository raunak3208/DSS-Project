import { useEffect, useState } from "react";

const TOKEN_KEY = "aiops_auth_token";

export function getAuthToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setAuthToken(token) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function clearAuthToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(message, status, data = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

async function call(path, method = "GET", body) {
  const token = getAuthToken();
  const headers = {};
  if (body) {
    headers["content-type"] = "application/json";
  }
  if (token) {
    headers["authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(path, {
    method,
    headers: Object.keys(headers).length > 0 ? headers : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch (e) {
    json = null;
  }

  if (!res.ok) {
    const errorMsg = json?.detail || text || res.statusText;
    throw new ApiError(errorMsg, res.status, json);
  }

  return json;
}

export const api = {
  // Auth endpoints
  login: (username, password) => call("/api/auth/login", "POST", { username, password }),
  logout: () => call("/api/auth/logout", "POST"),
  me: () => call("/api/auth/me"),
  authStatus: (username = "") => call(`/api/auth/status${username ? `?username=${encodeURIComponent(username)}` : ""}`),

  // Operational endpoints
  overview: () => call("/api/overview"),
  approve: (id, approved, note) => call(`/api/incidents/${id}/approval`, "POST", { approved, note, by: "dashboard operator" }),
  chaos: (service, type, intensity) => call("/api/chaos", "POST", { service, type, ...(intensity ? { intensity } : {}) }),
  reset: () => call("/api/chaos/reset", "POST"),
  setMode: (mode) => call("/api/mode", "POST", { mode }),
};

/** Poll the controller every `ms` milliseconds if authenticated. */
export function useOverview(ms = 2000, enabled = true) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    const load = () =>
      api.overview()
        .then((d) => {
          if (live) {
            setData(d);
            setError(null);
          }
        })
        .catch((e) => {
          if (live) setError(e.message);
        });

    load();
    const t = setInterval(load, ms);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [ms, tick, enabled]);

  return { data, error, refresh: () => setTick((n) => n + 1) };
}

export const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
export const short = (s) => (s || "").replace("-service", "");
