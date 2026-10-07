"""FastAPI app factory shared by all microservices: telemetry middleware, tracing, chaos + admin endpoints."""
import asyncio, os, random, time, uuid
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from .chaos import DEFAULTS, STABLE_VERSION, Chaos
from .telemetry import Telemetry

OPS_PREFIXES = ("/health", "/metrics", "/chaos", "/admin")


class UpstreamError(Exception):
    def __init__(self, peer, status):
        self.peer, self.status = peer, status


class Ctx:
    def __init__(self, service):
        self.service = service
        self.tel = Telemetry(service)
        self.chaos = Chaos(service)
        self.tel.state = self.chaos
        self.redis = None
        self.client = None
        self.timeout = float(os.getenv("UPSTREAM_TIMEOUT_S", "2.5"))
        self.peer_base = os.getenv("PEER_BASE", "http://{peer}:8000")

    async def reload(self):
        """Re-read desired version / replica count (written by the remediation executor)."""
        if not self.redis:
            return
        try:
            self.chaos.version = await self.redis.get(f"deploy:{self.service}") or STABLE_VERSION
            self.chaos.replicas = int(await self.redis.get(f"replicas:{self.service}") or 1)
        except Exception:
            pass

    async def call(self, request, peer, method, path, json=None):
        trace, parent = request.state.trace
        sid, status, t0 = uuid.uuid4().hex[:8], 0, time.perf_counter()
        try:
            base = os.getenv("PEER_URL_" + peer.upper().replace("-", "_")) or self.peer_base.format(peer=peer)
            r = await self.client.request(method, base + path, json=json,
                                          headers={"x-trace-id": trace, "x-span-id": sid}, timeout=self.timeout)
            status = r.status_code
            if status >= 500:
                raise UpstreamError(peer, status)
            return r.json()
        except httpx.HTTPError:
            status = 599
            raise UpstreamError(peer, 599)
        finally:
            self.tel.span(trace, sid, parent, f"{method} {path}", (time.perf_counter() - t0) * 1000, status, peer=peer)


def create_app(service, register):
    ctx = Ctx(service)
    reg = CollectorRegistry()
    REQ = Counter("app_requests_total", "HTTP requests", ["service", "status"], registry=reg)
    LAT = Histogram("app_request_duration_seconds", "Request latency", ["service"], registry=reg,
                    buckets=(.01, .025, .05, .1, .25, .5, 1, 2.5, 5))
    CPU = Gauge("app_cpu_percent", "Process CPU %", ["service"], registry=reg)
    MEM = Gauge("app_memory_mb", "Process RSS MB", ["service"], registry=reg)
    ctx.tel.on_metric = lambda m: (CPU.labels(service).set(m["cpu_pct"]), MEM.labels(service).set(m["mem_mb"]))

    @asynccontextmanager
    async def lifespan(app):
        if os.getenv("REDIS_URL"):
            ctx.redis = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        ctx.client = httpx.AsyncClient()
        await ctx.reload()
        await ctx.tel.start()
        ctx.tel.log("INFO", f"service started version={ctx.chaos.version} replicas={ctx.chaos.replicas}")
        yield
        await ctx.client.aclose()

    app = FastAPI(title=service, lifespan=lifespan)
    app.state.ctx = ctx

    @app.exception_handler(UpstreamError)
    async def upstream_handler(request: Request, exc: UpstreamError):
        request.state.reason = f"upstream call to {exc.peer} failed status={exc.status}"
        return JSONResponse({"error": request.state.reason}, status_code=502)

    @app.middleware("http")
    async def telemetry_mw(request: Request, call_next):
        path = request.url.path
        if path.startswith(OPS_PREFIXES):
            return await call_next(request)
        trace = request.headers.get("x-trace-id") or uuid.uuid4().hex[:16]
        parent, sid = request.headers.get("x-span-id"), uuid.uuid4().hex[:8]
        request.state.trace = (trace, sid)
        t0, status, reason = time.perf_counter(), 500, None
        ctx.tel.inflight += 1
        try:
            delay = ctx.chaos.latency_ms()
            if delay:
                await asyncio.sleep(delay / 1000)
            if random.random() < ctx.chaos.error_rate():
                status, reason = 500, ctx.chaos.error_message()
                return JSONResponse({"error": reason}, status_code=500)
            resp = await call_next(request)
            status, reason = resp.status_code, getattr(request.state, "reason", None)
            return resp
        except Exception as e:
            status, reason = 500, f"unhandled {type(e).__name__}"
            return JSONResponse({"error": "internal"}, status_code=500)
        finally:
            dur = (time.perf_counter() - t0) * 1000
            ctx.tel.inflight -= 1
            ctx.tel.record_request(dur, status < 500)
            REQ.labels(service, str(status)).inc()
            LAT.labels(service).observe(dur / 1000)
            ctx.tel.span(trace, sid, parent, f"{request.method} {path}", dur, status)
            level = "INFO" if status < 400 else "WARN" if status < 500 else "ERROR"
            text = (f"{request.method} {path} failed status={status} reason={reason}" if reason
                    else f"{request.method} {path} {status} {dur:.0f}ms")
            ctx.tel.log(level, text, trace)

    # ---- ops endpoints ---------------------------------------------------------------------
    @app.get("/health")
    async def health():
        return {"status": "ok", "service": service, "version": ctx.chaos.version}

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(reg), media_type=CONTENT_TYPE_LATEST)

    @app.post("/chaos")
    async def chaos_set(body: dict):
        ftype = body["type"]
        if ftype not in DEFAULTS:
            return JSONResponse({"error": f"type must be one of {list(DEFAULTS)}"}, status_code=400)
        if ftype == "bad_deploy":
            if ctx.redis:
                await ctx.redis.set(f"deploy:{service}", "v2")
            ctx.chaos.version = "v2"
        else:
            ctx.chaos.activate(ftype, body.get("intensity"), float(body.get("duration_s", 0)))
        print(f"[chaos] activated {ftype} {body}", flush=True)   # stdout only: ground truth never enters telemetry
        return {"ok": True, "active": list(ctx.chaos.faults) + (["bad_deploy"] if ctx.chaos.version != STABLE_VERSION else [])}

    @app.delete("/chaos")
    async def chaos_clear():
        ctx.chaos.clear()
        if ctx.redis:
            await ctx.redis.delete(f"deploy:{service}", f"replicas:{service}")
        ctx.chaos.version, ctx.chaos.replicas = STABLE_VERSION, 1
        return {"ok": True}

    @app.post("/admin/reload")
    async def admin_reload():
        await ctx.reload()
        return {"version": ctx.chaos.version, "replicas": ctx.chaos.replicas}

    @app.get("/admin/state")
    async def admin_state():
        return {"version": ctx.chaos.version, "replicas": ctx.chaos.replicas, "faults": list(ctx.chaos.faults)}

    register(app, ctx)
    return app
