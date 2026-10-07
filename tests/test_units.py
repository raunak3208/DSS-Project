import time

import pytest

from aiops_controller import config, rca, safety
from aiops_processor.detectors import Ewma, forecast
from aiops_processor.drain import Drain


def test_drain_merges_variable_parts_and_separates_levels():
    d = Drain()
    a = d.add("INFO", "GET /users/42 200 12ms")
    b = d.add("INFO", "GET /users/977 200 31ms")
    assert a[0] == b[0] and a[1] == "GET /users/<*> <*> <*>ms"
    e = d.add("ERROR", "GET /users/42 failed status=500 reason=MemoryError: heap at 93% of limit")
    assert e[2] and e[0] != a[0]


def test_ewma_flags_spike_and_freezes_baseline():
    e = Ewma(floor=1.0)
    for i in range(40):
        e.update(10 + (i % 3) * 0.2)
    assert e.ready and e.z(10.2) < 2 and e.z(40) > 4


def test_forecast_memory_trend():
    pts = [{"ts": i * 2.0, "mem_mb": 60 + 3 * i} for i in range(20)]
    f = forecast(pts, "mem_mb", 235, 0.3)
    assert f and 70 < f["eta_s"] < 90 and f["confidence"] > 0.95
    assert forecast([{"ts": i * 2.0, "mem_mb": 60} for i in range(20)], "mem_mb", 235, 0.3) is None


def _ev(active):
    now = time.time()
    act = {s: [{"type": t, "severity": sev, "ts": now + off, "detail": ""}] for s, (t, sev, off) in active.items()}
    return {"active": act, "all_edges": [{"src": a, "dst": b} for a, b in config.STATIC_TOPOLOGY]}


def test_rca_blames_deepest_callee_in_cascade():
    ranked = rca.rank(_ev({"payment-service": ("latency", "high", 0), "order-service": ("latency", "high", 3),
                           "gateway": ("errors", "high", 5)}))
    assert ranked[0]["service"] == "payment-service"
    assert set(ranked[0]["explains"]) == {"order-service", "gateway"}
    assert ranked[0]["path"] == ["gateway", "order-service", "payment-service"]


def _gate(atype, target, sev="medium", conf=0.9, params=None, recent=None, mode="auto", cands=None):
    plan = {"type": atype, "target": target, "params": params or {}}
    st = {"candidates": cands or [target], "edges": [], "recent": recent or [], "mode": mode}
    return safety.evaluate(plan, {"confidence": conf}, sev, st)["decision"]


def test_gate_policies():
    assert _gate("restart_pod", "user-service") == "ALLOW_AUTO"
    assert _gate("scale_deployment", "order-service", params={"replicas": 2}) == "ALLOW_AUTO"
    assert _gate("scale_deployment", "order-service", params={"replicas": 99}) == "DENY"
    assert _gate("restart_service", "order-service") == "ALLOW_AUTO"
    assert _gate("restart_service", "payment-service") == "REQUIRE_APPROVAL"        # critical service
    assert _gate("rollback_deployment", "notification-service") == "REQUIRE_APPROVAL"  # high risk
    assert _gate("restart_pod", "user-service", sev="critical") == "REQUIRE_APPROVAL"
    assert _gate("restart_pod", "user-service", conf=0.4) == "REQUIRE_APPROVAL"
    assert _gate("restart_pod", "user-service", mode="approve_all") == "REQUIRE_APPROVAL"
    assert _gate("drop_database", "user-service") == "DENY"                         # not allowlisted
    assert _gate("restart_pod", "kafka", cands=["kafka"]) == "DENY"                 # not a managed service
    assert _gate("restart_pod", "user-service", cands=["order-service"]) == "DENY"  # LLM target not in RCA set
    recent = [{"ts": time.time(), "type": "restart_pod", "target": "user-service", "auto": True}]
    assert _gate("restart_pod", "user-service", recent=recent) == "DENY"            # cooldown
