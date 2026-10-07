"""Controller API: dashboard data, human approvals, chaos proxy. The agent runs in the background (see manager.py)."""
import asyncio, json
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import config, evidence
from .agent import build_agent
from .executor import make_executor
from .llm import LLM
from .manager import Manager
from .runtime import Runtime
from .store import Store

SERIES_KEYS = ("ts", "cpu_pct", "mem_mb", "p95_ms", "err_rate", "rps")


class ChaosReq(BaseModel):
    service: str
    type: str                      # cpu | latency | memory | errors | crash | bad_deploy
    intensity: float | None = None
    duration_s: float = 0


class ApprovalReq(BaseModel):
    approved: bool
    by: str = "operator"
    note: str = ""


class ModeReq(BaseModel):
    mode: str                      # auto | approve_all


@asynccontextmanager
async def lifespan(app):
    r = aioredis.from_url(config.REDIS_URL, decode_responses=True)
    rt = Runtime(r, Store(config.DB_PATH), LLM(), make_executor(r))
    app.state.rt, app.state.mgr = rt, Manager(rt, build_agent(rt))
    task = asyncio.create_task(app.state.mgr.consume())
    yield
    task.cancel()


app = FastAPI(title="AIOps Controller API", version="1.0", lifespan=lifespan,
              description="Operational-intelligence controller: telemetry views, incidents, human approvals and chaos injection.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _brief(i):
    return {k: i[k] for k in ("id", "created", "status", "severity", "root_cause", "services", "stage", "resolved_at")}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config")
async def get_config():
    rt = app.state.rt
    return {"llm": rt.llm.info(), "mode": rt.mode, "backend": config.BACKEND,
            "policy": {"auto_max_risk": config.AUTO_MAX_RISK, "min_confidence": config.MIN_CONFIDENCE,
                       "cooldown_s": config.COOLDOWN_S, "max_replicas": config.MAX_REPLICAS,
                       "max_iterations": config.MAX_ITERATIONS, "approval_timeout_s": config.APPROVAL_TIMEOUT_S},
            "inventory": config.INVENTORY}


@app.get("/api/overview", summary="Everything the dashboard needs in one call")
async def overview():
    rt, r = app.state.rt, app.state.rt.r
    latest = await evidence.latest_map(r)
    services = []
    for name in config.INVENTORY:
        pts = [json.loads(x) for x in await r.lrange(f"svc:{name}:series", 0, 89)]
        services.append({**latest.get(name, {"service": name, "status": "unknown"}),
                         "series": [{k: p.get(k) for k in SERIES_KEYS} for p in reversed(pts)]})
    graph = await evidence.graph_edges(r)
    pred = await r.get("predictions")
    incs = sorted(rt.incidents.values(), key=lambda i: -i["created"])
    mgr = app.state.mgr
    current = rt.incidents.get(mgr.current) if mgr.current else None
    return {
        "mode": rt.mode, "llm": rt.llm.info(),
        "learning": all(s.get("status") in ("learning", "unknown") for s in services),
        "services": services, "edges": graph,
        "anomalies": [json.loads(x) for x in await r.lrange("anomalies:recent", 0, 29)],
        "predictions": json.loads(pred)["items"] if pred else [],
        "incident": current or (incs[0] if incs else None),
        "incidents": [_brief(i) for i in incs[:15]],
        "timeline": rt.store.events(limit=80),
        "logs": [json.loads(x) for x in await r.lrange("logs:recent", 0, 119)],
    }


@app.get("/api/incidents")
async def incidents():
    return [_brief(i) for i in sorted(app.state.rt.incidents.values(), key=lambda i: -i["created"])]


@app.get("/api/incidents/{iid}")
async def incident(iid: str):
    rt = app.state.rt
    if iid not in rt.incidents:
        raise HTTPException(404, "unknown incident")
    return {**rt.incidents[iid], "events": list(reversed(rt.store.events(iid, limit=200)))}


@app.post("/api/incidents/{iid}/approval", summary="Human-in-the-loop decision on a pending remediation")
async def approve(iid: str, body: ApprovalReq):
    fut = app.state.rt.approvals.get(iid)
    if not fut or fut.done():
        raise HTTPException(404, "no pending approval for this incident")
    fut.set_result({"approved": body.approved, "by": body.by, "note": body.note})
    return {"ok": True}


@app.post("/api/incidents/trigger", summary="Open an incident from currently active anomalies")
async def trigger():
    inc = await app.state.mgr.trigger_manual()
    if not inc:
        raise HTTPException(409, "no active anomalies, or an incident is already running")
    return _brief(inc)


@app.post("/api/mode", summary="auto = low-risk actions run automatically; approve_all = every action needs a human")
async def set_mode(body: ModeReq):
    if body.mode not in ("auto", "approve_all"):
        raise HTTPException(400, "mode must be auto or approve_all")
    app.state.rt.mode = body.mode
    return {"mode": body.mode}


@app.get("/api/anomalies")
async def anomalies(limit: int = 50):
    return [json.loads(x) for x in await app.state.rt.r.lrange("anomalies:recent", 0, limit - 1)]


@app.get("/api/logs")
async def logs(service: str | None = None, level: str | None = None, limit: int = 100):
    out = [json.loads(x) for x in await app.state.rt.r.lrange("logs:recent", 0, 499)]
    return [l for l in out if (not service or l["service"] == service) and (not level or l["level"] == level)][:limit]


@app.get("/api/graph")
async def graph():
    return await evidence.graph_edges(app.state.rt.r)


@app.get("/api/traces/{trace_id}")
async def trace(trace_id: str):
    spans = [json.loads(x) for x in await app.state.rt.r.lrange("traces:recent", 0, 599)]
    return sorted([s for s in spans if s["trace_id"] == trace_id], key=lambda s: s["ts"])


@app.post("/api/chaos", summary="Inject a failure into a service (demo/testing)")
async def chaos(body: ChaosReq):
    if body.service not in config.INVENTORY:
        raise HTTPException(400, f"unknown service; choose from {list(config.INVENTORY)}")
    async with httpx.AsyncClient(timeout=5) as c:
        try:
            r = await c.post(f"http://{body.service}:8000/chaos", json=body.model_dump(exclude={"service"}, exclude_none=True))
        except httpx.HTTPError as e:
            raise HTTPException(502, f"service unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.post("/api/chaos/reset", summary="Clear injected faults on every service (restarts crashed containers)")
async def chaos_reset():
    ex = app.state.rt.executor
    async with httpx.AsyncClient(timeout=3) as c:
        for s in config.INVENTORY:
            try:
                await ex.ensure_up(s)
            except Exception:
                pass
            try:
                await c.delete(f"http://{s}:8000/chaos")
            except httpx.HTTPError:
                pass
    return {"ok": True}
