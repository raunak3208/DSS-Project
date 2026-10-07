"""End-to-end test of detection -> correlation/RCA -> agent -> safety gate -> remediation -> verification.

A synthetic world generates telemetry for the five services (no Kafka/Docker needed). The real processor Engine detects
anomalies, the real LangGraph agent + safety gate decide, and a SimExecutor changes the world so verification can pass/fail.
"""
import asyncio, random, time

import fakeredis.aioredis
import pytest

from aiops_controller import config
from aiops_controller.agent import build_agent
from aiops_controller.executor import SimExecutor
from aiops_controller.llm import LLM
from aiops_controller.manager import Manager
from aiops_controller.runtime import Runtime
from aiops_controller.store import Store
from aiops_processor import engine as engine_mod
from aiops_processor.engine import Engine

BASE = {"gateway": 120, "user-service": 25, "order-service": 110, "payment-service": 70, "notification-service": 25}
CALLS = [("gateway", "user-service"), ("gateway", "order-service"), ("order-service", "user-service"),
         ("order-service", "payment-service"), ("order-service", "notification-service")]
ORDER = ["payment-service", "notification-service", "user-service", "order-service", "gateway"]


class World:
    def __init__(self):
        self.faults, self.replicas = {}, {n: 1 for n in BASE}

    def eff(self, svc):
        f, rep = self.faults.get(svc), self.replicas[svc]
        e = {"down": f == "crash", "cpu": 8.0, "mem": 62.0, "lat": 0.0, "err": 0.0, "ver": "v1"}
        if f == "cpu":
            e.update(cpu=95.0 / rep, lat=600.0 / rep)
        elif f == "latency":
            e.update(lat=1500.0)
        elif f == "bad_deploy":
            e.update(err=0.4, lat=150.0, ver="v2")
        for a, b in CALLS:
            if a == svc and b != "notification-service":
                c = self.eff(b)
                if c["down"] or c["lat"] > 1000:
                    e["err"], e["lat"] = max(e["err"], 0.3), max(e["lat"], 2500.0 if c["down"] else c["lat"])
                else:
                    e["lat"] = max(e["lat"], c["lat"])
        return e

    def batch(self):
        now, out, spans, logs = time.time(), [], [], []
        for svc in ORDER:
            e = self.eff(svc)
            if not e["down"]:
                g = random.gauss
                out.append({"service": svc, "ts": now, "cpu_pct": max(0, g(e["cpu"], 1.2)), "mem_mb": g(e["mem"], 0.8),
                            "rps": 5.0, "p50_ms": BASE[svc], "p95_ms": max(1, g(BASE[svc] + e["lat"], BASE[svc] * 0.04)),
                            "err_rate": max(0.0, g(e["err"], 0.003)) if e["err"] else 0.0, "inflight": 1,
                            "version": e["ver"], "replicas": self.replicas[svc], "up": 1})
                if e["err"]:
                    logs.append({"service": svc, "ts": now, "level": "ERROR", "msg":
                                 "POST /orders failed status=500 reason=upstream call to payment-service failed status=599"
                                 if svc == "order-service" else
                                 f"GET /x failed status=500 reason=NullReferenceError in handler (release {e['ver']})"})
        for a, b in CALLS:
            bad = self.eff(b)["down"] or self.eff(b)["err"] > 0.2
            spans.append({"service": a, "peer": b, "ts": now, "dur_ms": 50, "status": 599 if bad else 200, "trace_id": "t"})
        return out, spans, logs

    async def apply(self, action):
        t, svc = action["type"], action["target"]
        if t in ("restart_pod", "restart_service") and self.faults.get(svc) != "bad_deploy":
            self.faults.pop(svc, None)
        elif t == "scale_deployment":
            self.replicas[svc] = action["params"]["replicas"]
        elif t == "rollback_deployment" and self.faults.get(svc) == "bad_deploy":
            del self.faults[svc]


@pytest.fixture
async def env(monkeypatch):
    for k, v in dict(DEBOUNCE_S=0.4, VERIFY_SETTLE_S=0.3, VERIFY_POLL_S=0.1, VERIFY_TIMEOUT_S=3.0, COOLDOWN_S=0.1,
                     APPROVAL_TIMEOUT_S=20.0).items():
        monkeypatch.setattr(config, k, v)
    monkeypatch.setattr(engine_mod, "SILENCE_S", 0.6)
    monkeypatch.setattr(engine_mod, "LOG_QUIET_S", 0.3)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    world = World()
    ex = SimExecutor(r, on_run=world.apply)
    rt = Runtime(r, Store(":memory:"), LLM(), ex)
    engine = Engine(r)
    mgr = Manager(rt, build_agent(rt))
    engine.publish = mgr.on_anomaly                      # replaces the Kafka hop for this test

    async def pump():
        n = 0
        while True:
            metrics, spans, logs = world.batch()
            for m in metrics:
                await engine.on_metric(m)
            for s in spans:
                await engine.on_span(s)
            for l in logs:
                await engine.on_log(l)
            n += 1
            if n % 5 == 0:
                await engine.tick()
            await asyncio.sleep(0.02)

    task = asyncio.create_task(pump())
    await asyncio.sleep(1.6)                             # learn baselines (EWMA warm-up + Isolation Forest fit)
    yield world, rt, mgr, ex
    task.cancel()


async def wait_for(pred, timeout=40.0):
    end = time.time() + timeout
    while time.time() < end:
        if (v := pred()):
            return v
        await asyncio.sleep(0.05)
    raise AssertionError("timed out")


async def settle(rt, mgr):
    await wait_for(lambda: mgr.current and rt.incidents[mgr.current]["status"] in ("resolved", "escalated"))
    return rt.incidents[mgr.current]


async def test_no_incident_during_normal_operation(env):
    world, rt, mgr, ex = env
    await asyncio.sleep(1.0)
    assert mgr.current is None and not rt.incidents


async def test_cpu_saturation_scale_fails_then_agent_reinvestigates_and_restarts(env):
    world, rt, mgr, ex = env
    world.faults["order-service"] = "cpu"
    inc = await settle(rt, mgr)
    assert inc["status"] == "resolved", inc["history"]
    assert inc["root_cause"] == "order-service" and inc["analysis"]["fault_type"] == "cpu_saturation"
    assert [c["type"] for c in ex.calls] == ["scale_deployment", "restart_pod"]      # no blind repeat
    assert inc["history"][0]["result"] == "not_resolved" and inc["gate"]["decision"] == "ALLOW_AUTO"
    assert inc["severity"] != "critical" and inc["verification"]["resolved"]


async def test_cascading_latency_is_critical_needs_approval_then_resolves(env):
    world, rt, mgr, ex = env
    world.faults["payment-service"] = "latency"
    await wait_for(lambda: mgr.current and rt.incidents[mgr.current]["status"] == "awaiting_approval")
    inc = rt.incidents[mgr.current]
    assert inc["root_cause"] == "payment-service" and inc["severity"] == "critical"
    assert inc["gate"]["decision"] == "REQUIRE_APPROVAL" and not ex.calls           # nothing ran before approval
    rt.approvals[inc["id"]].set_result({"approved": True, "by": "tester", "note": "ok"})
    inc = await settle(rt, mgr)
    assert inc["status"] == "resolved" and ex.calls[0]["target"] == "payment-service"
    assert set(inc["services"]) >= {"payment-service", "order-service", "gateway"}
    assert inc["approval"]["status"] == "approved"


async def test_rejected_rollback_is_never_executed(env):
    world, rt, mgr, ex = env
    world.faults["notification-service"] = "bad_deploy"
    await wait_for(lambda: mgr.current and rt.incidents[mgr.current]["status"] == "awaiting_approval")
    inc = rt.incidents[mgr.current]
    assert inc["analysis"]["fault_type"] == "bad_deploy" and inc["plan"]["type"] == "rollback_deployment"
    rt.approvals[inc["id"]].set_result({"approved": False, "by": "tester", "note": "hold on"})
    inc = await settle(rt, mgr)
    assert inc["status"] == "escalated" and ex.calls == [] and inc["approval"]["status"] == "rejected"


async def test_approved_rollback_fixes_bad_deploy(env):
    world, rt, mgr, ex = env
    world.faults["notification-service"] = "bad_deploy"
    await wait_for(lambda: mgr.current and rt.incidents[mgr.current]["status"] == "awaiting_approval")
    rt.approvals[mgr.current].set_result({"approved": True, "by": "tester", "note": ""})
    inc = await settle(rt, mgr)
    assert inc["status"] == "resolved" and [c["type"] for c in ex.calls] == ["rollback_deployment"]


async def test_crashed_critical_service_restart_requires_approval(env):
    world, rt, mgr, ex = env
    world.faults["payment-service"] = "crash"
    await wait_for(lambda: mgr.current and rt.incidents[mgr.current]["status"] == "awaiting_approval")
    inc = rt.incidents[mgr.current]
    assert inc["root_cause"] == "payment-service" and inc["plan"]["type"] == "restart_service"
    rt.approvals[inc["id"]].set_result({"approved": True, "by": "tester", "note": ""})
    assert (await settle(rt, mgr))["status"] == "resolved"


async def test_approve_all_mode_forces_human_for_low_risk_actions(env):
    world, rt, mgr, ex = env
    rt.mode = "approve_all"
    world.faults["order-service"] = "cpu"
    await wait_for(lambda: mgr.current and rt.incidents[mgr.current]["status"] == "awaiting_approval")
    assert rt.incidents[mgr.current]["gate"]["decision"] == "REQUIRE_APPROVAL" and not ex.calls
    rt.approvals[mgr.current].set_result({"approved": False, "by": "tester", "note": ""})
    assert (await settle(rt, mgr))["status"] == "escalated"
