"""Deterministic safety gate. Pure function, no LLM, no I/O: every proposed remediation is evaluated against explicit
policies. Result is ALLOW_AUTO, REQUIRE_APPROVAL (human in the loop) or DENY, with a per-check audit trail."""
import time

import networkx as nx

from . import config

RISK = {"restart_pod": 1, "scale_deployment": 1, "restart_service": 2, "rollback_deployment": 3}
RISK_NAME = {1: "low", 2: "medium", 3: "high"}


def blast_radius(target, edges):
    g = nx.DiGraph([(e["src"], e["dst"]) for e in edges] + config.STATIC_TOPOLOGY)
    return len(nx.ancestors(g, target)) if target in g else 0


def evaluate(plan, analysis, severity, st):
    """st = {candidates, edges, recent:[{ts,type,target,auto}], mode}"""
    atype, target, params = plan["type"], plan["target"], plan.get("params") or {}
    now, checks = time.time(), []

    def chk(name, passed, effect, note):
        checks.append({"check": name, "passed": bool(passed), "effect": effect, "note": note})

    risk = RISK.get(atype, 9)
    chk("action_allowlisted", atype in RISK, "deny", f"{atype} {'is' if atype in RISK else 'is NOT'} an allowed action")
    chk("target_in_inventory", target in config.INVENTORY, "deny", f"{target} is a managed application service")
    chk("target_matches_rca", target in st["candidates"], "deny", "target must be a graph-RCA candidate")
    if atype == "scale_deployment":
        n = params.get("replicas")
        ok = isinstance(n, int) and 1 <= n <= config.MAX_REPLICAS
        chk("params_valid", ok, "deny", f"replicas={n} must be an integer in 1..{config.MAX_REPLICAS}")
    else:
        chk("params_valid", not params, "deny", "action takes no parameters")
    chk("risk_level", risk <= config.AUTO_MAX_RISK, "approve",
        f"risk {RISK_NAME.get(risk, 'unknown')} (auto-execution up to {RISK_NAME[config.AUTO_MAX_RISK]})")
    chk("confidence", analysis["confidence"] >= config.MIN_CONFIDENCE, "approve",
        f"confidence {analysis['confidence']:.2f} (minimum {config.MIN_CONFIDENCE})")
    chk("incident_severity", severity != "critical", "approve", f"incident severity is {severity}; critical needs a human")
    crit = config.INVENTORY.get(target, {}).get("critical", False)
    chk("critical_service", not (crit and risk >= 2), "approve", f"{target} {'is' if crit else 'is not'} a critical service")
    br = blast_radius(target, st["edges"])
    chk("blast_radius", not (risk >= 2 and br >= 2), "approve", f"{br} upstream service(s) depend on {target}")
    cool = [r for r in st["recent"] if r["type"] == atype and r["target"] == target and now - r["ts"] < config.COOLDOWN_S]
    chk("cooldown", not cool, "deny", f"same action on same target within {config.COOLDOWN_S:.0f}s")
    auto = [r for r in st["recent"] if r["auto"] and now - r["ts"] < 600]
    chk("rate_limit", len(auto) < config.MAX_AUTO_PER_10MIN, "approve", f"{len(auto)} auto-actions in last 10 min")
    chk("mode", st["mode"] == "auto", "approve", f"remediation mode is '{st['mode']}'")

    failed = [c for c in checks if not c["passed"]]
    if any(c["effect"] == "deny" for c in failed):
        decision = "DENY"
    elif failed:
        decision = "REQUIRE_APPROVAL"
    else:
        decision = "ALLOW_AUTO"
    return {"decision": decision, "risk": RISK_NAME.get(risk, "unknown"), "checks": checks,
            "reasons": [f"{c['check']}: {c['note']}" for c in failed]}
