"""Threshold validation on REAL service telemetry (slow: `python -m pytest -m slow`).

Runs the five real FastAPI apps in one process (HTTP between them goes through ASGI transports), generates traffic,
and feeds their genuine logs/metrics/spans into the real processor Engine + graph RCA. This checks that detector
thresholds work on real telemetry shapes, not just on the synthetic world used by test_closed_loop.py.
CPU/memory are skipped here because the apps share one OS process.
"""
import asyncio, os, random, sys, time

import fakeredis.aioredis
import httpx
import pytest

os.environ["METRICS_INTERVAL_S"] = "0.5"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "services"))

from aiops_common.app import create_app          # noqa: E402
from aiops_controller import evidence, rca        # noqa: E402
from aiops_processor.engine import Engine         # noqa: E402
from svc.main import ROUTES                       # noqa: E402

pytestmark = pytest.mark.slow
NAMES = list(ROUTES)


class Router(httpx.AsyncBaseTransport):
    def __init__(self, apps):
        self.t = {h: httpx.ASGITransport(app=a) for h, a in apps.items()}

    async def handle_async_request(self, request):
        return await self.t[request.url.host].handle_async_request(request)


async def test_real_telemetry_detects_cascade_and_bad_deploy():
    apps = {n: create_app(n, ROUTES[n]) for n in NAMES}
    router = Router(apps)
    ctxs = {n: a.state.ctx for n, a in apps.items()}
    for c in ctxs.values():
        c.client = httpx.AsyncClient(transport=router)
        await c.tel.start()
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    raised = []

    async def publish(a):
        raised.append((time.time(), a))

    eng = Engine(r, publish)
    gw = httpx.AsyncClient(transport=httpx.ASGITransport(app=apps["gateway"]), base_url="http://gateway:8000", timeout=10)

    async def traffic():
        while True:
            x = random.random()
            if x < 0.6:
                asyncio.create_task(gw.post("/api/checkout", json={"user_id": random.randint(1, 500), "amount": 20}))
            elif x < 0.85:
                asyncio.create_task(gw.get(f"/api/users/{random.randint(1, 500)}"))
            else:
                asyncio.create_task(gw.get(f"/api/orders/{random.randint(1000, 9999)}"))
            await asyncio.sleep(random.expovariate(8))

    async def pump():
        n = 0
        while True:
            for c in ctxs.values():
                while c.tel.sink:
                    topic, m = c.tel.sink.popleft()
                    await {"telemetry.metrics": eng.on_metric, "telemetry.logs": eng.on_log, "telemetry.traces": eng.on_span}[topic](m)
            n += 1
            if n % 5 == 0:
                await eng.tick()
            await asyncio.sleep(0.1)

    tasks = [asyncio.create_task(traffic()), asyncio.create_task(pump())]
    try:
        await asyncio.sleep(40)                                           # baseline learning
        med = [a for _, a in raised if a["severity"] != "low"]
        assert not med, f"false positives during normal operation: {[(a['service'], a['type'], a['detail']) for a in med]}"
        learned = [(n, s.ew["p95_ms"].ready) for n, s in eng.states.items()]
        assert all(ok for _, ok in learned), learned

        # ---- cascading latency from payment-service ------------------------------------------------
        ctxs["payment-service"].chaos.activate("latency", 1500)
        t0 = time.time()
        await asyncio.sleep(18)
        got = {(a["service"], a["type"]) for ts, a in raised if ts >= t0 and a["severity"] != "low"}
        assert ("payment-service", "latency") in got, got
        ev = await evidence.collect(r)
        top = rca.rank(ev)[0]
        assert top["service"] == "payment-service", [(x["service"], x["score"]) for x in rca.rank(ev)]
        assert set(top["explains"]) & {"order-service", "gateway"}
        edge = {(e["src"], e["dst"]) for e in ev["all_edges"] if e["calls"] > 0}
        assert ("order-service", "payment-service") in edge                 # graph learned from real spans
        ctxs["payment-service"].chaos.clear()
        await asyncio.sleep(15)
        active = await evidence.active_map(r)
        assert not [s for s, l in active.items() if any(a["severity"] != "low" for a in l)], active   # recovered and cleared

        # ---- bad deployment ------------------------------------------------------------------------
        ctxs["notification-service"].chaos.version = "v2"
        t1 = time.time()
        await asyncio.sleep(15)
        got = {(a["service"], a["type"]) for ts, a in raised if ts >= t1 and a["severity"] != "low"}
        assert ("notification-service", "errors") in got, got
        top = rca.rank(await evidence.collect(r))[0]
        assert top["service"] == "notification-service"
        assert (await r.hgetall("tpl:notification-service:ERROR")), "error log templates should be mined"
    finally:
        for t in tasks:
            t.cancel()
