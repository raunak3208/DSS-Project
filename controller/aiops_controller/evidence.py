"""Reads the processor's Redis state and assembles the multi-modal evidence packet (metrics + logs + dependencies)."""
import json

from . import config

KEEP = ("cpu_pct", "mem_mb", "rps", "p95_ms", "err_rate", "version", "replicas", "up")


async def active_map(r):
    raw = await r.hgetall("anomalies:active")
    return {svc: json.loads(v) for svc, v in raw.items()}


async def latest_map(r):
    out = {}
    for svc in await r.smembers("services"):
        v = await r.get(f"svc:{svc}:latest")
        if v:
            out[svc] = json.loads(v)
    return out


async def graph_edges(r):
    raw = await r.get("graph")
    dyn = json.loads(raw)["edges"] if raw else []
    known = {(e["src"], e["dst"]) for e in dyn}
    return dyn + [{"src": a, "dst": b, "calls": 0, "err_rate": 0.0, "avg_ms": 0.0}
                  for a, b in config.STATIC_TOPOLOGY if (a, b) not in known]


async def snapshot(r, services):
    latest = await latest_map(r)
    return {s: {**{k: latest[s].get(k) for k in ("cpu_pct", "mem_mb", "p95_ms", "err_rate", "rps", "status")}}
            for s in services if s in latest}


async def collect(r):
    active, latest, edges = await active_map(r), await latest_map(r), await graph_edges(r)
    anomalous = sorted(s for s, lst in active.items() if any(a["severity"] != "low" for a in lst))
    focus = set(anomalous)
    for e in edges:                                   # neighbours (callers/callees) give causal context
        if e["src"] in anomalous:
            focus.add(e["dst"])
        if e["dst"] in anomalous:
            focus.add(e["src"])
    logs = [json.loads(x) for x in await r.lrange("logs:recent", 0, 399)]
    services = {}
    for s in sorted(focus):
        lt = latest.get(s, {})
        err_tpl = await r.hgetall(f"tpl:{s}:ERROR")
        services[s] = {
            "status": lt.get("status", "unknown"),
            "metrics": {k: lt.get(k) for k in KEEP},
            "baseline": lt.get("baseline", {}),
            "active": [{k: a.get(k) for k in ("type", "severity", "detail", "ts", "detector")} for a in active.get(s, [])],
            "error_templates": sorted(err_tpl.items(), key=lambda kv: -int(kv[1]))[:3],
            "error_logs": [l["msg"][:180] for l in logs if l["service"] == s and l.get("level") == "ERROR"][:4],
        }
    pred = await r.get("predictions")
    return {"anomalous": anomalous, "active": active, "services": services,
            "edges": [e for e in edges if e["src"] in focus and e["dst"] in focus],
            "all_edges": edges, "predictions": json.loads(pred)["items"] if pred else []}
