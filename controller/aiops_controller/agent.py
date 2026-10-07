"""LangGraph workflow for one incident.

 gather -> rca -> reason -> gate --ALLOW_AUTO--------------> execute -> verify --resolved--> finish
                              |  \\--REQUIRE_APPROVAL -> approval --approved--^     |
                              |                                                  not resolved
                              \\--DENY / rejected / timeout / no action--> escalate     |
                                                       next_iteration (re-investigate, never repeat) <--/

The LLM (inside `reason`) only proposes. `gate` is deterministic. `execute` is the only node that touches infrastructure.
"""
import asyncio, time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from . import config, evidence, rca, reasoner, safety

ORDER = {"medium": 0, "high": 1, "critical": 2}


class AgentState(TypedDict, total=False):
    incident_id: str
    iteration: int
    evidence: dict
    ranking: list
    analysis: dict
    plan: dict
    gate: dict
    approval: str
    exec_ok: bool
    resolved: bool
    history: list
    reason: str


def incident_severity(ev):
    act, an = ev["active"], ev["anomalous"]
    crit_down = any(config.INVENTORY.get(s, {}).get("critical") and any(a["type"] == "down" for a in act[s]) for s in an)
    gw_err = (ev["services"].get("gateway", {}).get("metrics", {}).get("err_rate")) or 0
    if len(an) >= 3 or crit_down or gw_err >= 0.25:
        return "critical"
    if any(a["severity"] == "high" for s in an for a in act[s]):
        return "high"
    return "medium"


def build_agent(rt):
    def ev_(s, stage, summary, data=None):
        return rt.event(s["incident_id"], stage, summary, data)

    async def gather(s):
        iid = s["incident_id"]
        rt.patch(iid, status="analyzing", stage="correlate", iteration=s["iteration"])
        ev = await evidence.collect(rt.r)
        inc = rt.incidents[iid]
        sev = max(inc["severity"], incident_severity(ev), key=ORDER.get)
        rt.patch(iid, severity=sev, services=sorted(set(inc["services"]) | set(ev["anomalous"])))
        ev_(s, "correlate", f"Correlated metrics, logs and call graph for {len(ev['services'])} services; "
            f"anomalous: {', '.join(ev['anomalous']) or 'none'}; incident severity {sev}")
        return {"evidence": ev}

    async def rca_node(s):
        ranking = rca.rank(s["evidence"])
        top = ranking[0] if ranking else None
        rt.patch(s["incident_id"], rca=ranking, root_cause=top["service"] if top else None)
        ev_(s, "rca", (f"Dependency-graph RCA ranks {top['service']} first (score {top['score']}), path "
                       f"{' -> '.join(top['path'])}") if top else "No anomalous services remain")
        return {"ranking": ranking}

    async def reason_node(s):
        iid = s["incident_id"]
        rt.patch(iid, stage="agent")
        analysis, plan = await reasoner.reason(rt.llm, s["evidence"], s["ranking"], s["history"])
        plan["rationale"] = f"{analysis['fault_type']} on {plan['target']}"
        rt.patch(iid, analysis=analysis, plan=plan)
        ev_(s, "agent", f"[{analysis['source']}] fault={analysis['fault_type']} confidence={analysis['confidence']} "
            f"proposal={plan['type']}({plan['target']})", {"explanation": analysis["explanation"]})
        return {"analysis": analysis, "plan": plan}

    async def gate_node(s):
        iid = s["incident_id"]
        rt.patch(iid, stage="gate")
        st = {"candidates": [r["service"] for r in s["ranking"][:3]], "edges": s["evidence"]["all_edges"],
              "recent": rt.recent, "mode": rt.mode}
        gate = safety.evaluate(s["plan"], s["analysis"], rt.incidents[iid]["severity"], st)
        rt.patch(iid, gate=gate)
        ev_(s, "gate", f"Safety gate: {gate['decision']} (risk {gate['risk']})"
            + (f" - {'; '.join(gate['reasons'])}" if gate["reasons"] else " - all checks passed"), gate)
        return {"gate": gate}

    async def approval_node(s):
        iid = s["incident_id"]
        rt.patch(iid, status="awaiting_approval", stage="approval", approval={"status": "pending", "requested": time.time()})
        ev_(s, "approval", f"Human approval required for {s['plan']['type']}({s['plan']['target']})")
        fut = asyncio.get_running_loop().create_future()
        rt.approvals[iid] = fut
        try:
            res = await asyncio.wait_for(fut, config.APPROVAL_TIMEOUT_S)
        except asyncio.TimeoutError:
            res = {"approved": False, "by": "system", "note": "approval timed out"}
        finally:
            rt.approvals.pop(iid, None)
        status = "approved" if res["approved"] else ("timeout" if res["by"] == "system" else "rejected")
        rt.patch(iid, status="analyzing", approval={"status": status, "by": res["by"], "note": res.get("note", ""), "ts": time.time()})
        ev_(s, "approval", f"Action {status} by {res['by']}" + (f": {res['note']}" if res.get("note") else ""))
        return {"approval": status}

    async def execute_node(s):
        iid, plan = s["incident_id"], s["plan"]
        services = rt.incidents[iid]["services"]
        before = await evidence.snapshot(rt.r, set(services) | {plan["target"]})
        rt.patch(iid, status="remediating", stage="remediate", before=before)
        res = await rt.executor.run(plan)
        rt.recent.append({"ts": time.time(), "type": plan["type"], "target": plan["target"],
                          "auto": s["gate"]["decision"] == "ALLOW_AUTO"})
        rt.patch(iid, execution=res)
        ev_(s, "remediation", f"{'Executed' if res['ok'] else 'FAILED'} {plan['type']}({plan['target']}): {res['detail']}", res)
        return {"exec_ok": res["ok"]}

    async def verify_node(s):
        iid, plan = s["incident_id"], s["plan"]
        rt.patch(iid, status="verifying", stage="verify")
        services = set(rt.incidents[iid]["services"]) | {plan["target"]}
        ev_(s, "verification", f"Re-checking telemetry for {', '.join(sorted(services))} after remediation")
        await asyncio.sleep(config.VERIFY_SETTLE_S)
        deadline, streak, bad = time.time() + config.VERIFY_TIMEOUT_S, 0, []
        while True:
            act, latest = await evidence.active_map(rt.r), await evidence.latest_map(rt.r)
            bad = []
            for svc in services:
                live = [a["type"] for a in act.get(svc, []) if a["severity"] != "low"]
                if live:
                    bad.append(f"{svc}: still anomalous ({', '.join(live)})")
                elif latest.get(svc, {}).get("status") in ("down", "degraded"):
                    bad.append(f"{svc}: status {latest[svc]['status']}")
            streak = streak + 1 if not bad else 0
            if streak >= config.VERIFY_STREAK or time.time() > deadline:
                break
            await asyncio.sleep(config.VERIFY_POLL_S)
        resolved = streak >= config.VERIFY_STREAK
        after = await evidence.snapshot(rt.r, services)
        ver = {"resolved": resolved, "remaining": bad, "ts": time.time()}
        rt.patch(iid, verification=ver, after=after)
        ev_(s, "verification", "Verified: telemetry back to normal" if resolved else f"Not fixed: {'; '.join(bad)}", ver)
        return {"resolved": resolved}

    async def next_iteration(s):
        h = s["history"] + [{"iteration": s["iteration"], "action": s["plan"]["type"], "target": s["plan"]["target"],
                             "result": "not_resolved"}]
        rt.patch(s["incident_id"], history=h, iteration=s["iteration"] + 1, approval=None)
        ev_(s, "agent", f"Remediation did not fix the issue; re-investigating (attempt {s['iteration'] + 2}) "
            f"without repeating {s['plan']['type']}({s['plan']['target']})")
        return {"history": h, "iteration": s["iteration"] + 1}

    async def finish(s):
        iid = s["incident_id"]
        rt.patch(iid, status="resolved", stage="done", resolved_at=time.time())
        mttr = time.time() - rt.incidents[iid]["created"]
        ev_(s, "resolved", f"Incident resolved in {mttr:.0f}s after {s['iteration'] + 1} attempt(s)")
        return {}

    async def finish_noop(s):
        iid = s["incident_id"]
        rt.patch(iid, status="resolved", stage="done", resolved_at=time.time())
        ev_(s, "resolved", "Anomalies cleared without intervention; no action taken")
        return {}

    async def escalate(s):
        iid = s["incident_id"]
        why = s.get("reason") or ("safety gate denied the action" if s.get("gate", {}).get("decision") == "DENY"
                                  else f"approval {s.get('approval')}" if s.get("approval") in ("rejected", "timeout")
                                  else "remediation not verified" if s.get("exec_ok") else "no safe automatic action available")
        rt.patch(iid, status="escalated", stage="done")
        ev_(s, "escalated", f"Escalated to on-call human: {why}")
        return {}

    # ---- routing (deterministic) ---------------------------------------------------------------
    def after_reason(s):
        if not s["analysis"]["needs_remediation"]:
            return "noop"
        return "gate" if s["plan"]["type"] != "none" else "escalate"

    def after_gate(s):
        return {"ALLOW_AUTO": "execute", "REQUIRE_APPROVAL": "approval"}.get(s["gate"]["decision"], "escalate")

    def after_verify(s):
        if s["resolved"]:
            return "resolved"
        return "retry" if s["iteration"] + 1 < config.MAX_ITERATIONS else "escalate"

    g = StateGraph(AgentState)
    for name, fn in [("gather", gather), ("rca", rca_node), ("reason", reason_node), ("gate", gate_node),
                     ("approval", approval_node), ("execute", execute_node), ("verify", verify_node),
                     ("next_iteration", next_iteration), ("finish", finish), ("finish_noop", finish_noop),
                     ("escalate", escalate)]:
        g.add_node(name, fn)
    g.set_entry_point("gather")
    g.add_edge("gather", "rca")
    g.add_edge("rca", "reason")
    g.add_conditional_edges("reason", after_reason, {"gate": "gate", "noop": "finish_noop", "escalate": "escalate"})
    g.add_conditional_edges("gate", after_gate, {"execute": "execute", "approval": "approval", "escalate": "escalate"})
    g.add_conditional_edges("approval", lambda s: "execute" if s["approval"] == "approved" else "escalate",
                            {"execute": "execute", "escalate": "escalate"})
    g.add_conditional_edges("execute", lambda s: "verify" if s["exec_ok"] else "escalate",
                            {"verify": "verify", "escalate": "escalate"})
    g.add_conditional_edges("verify", after_verify, {"resolved": "finish", "retry": "next_iteration", "escalate": "escalate"})
    g.add_edge("next_iteration", "gather")
    for n in ("finish", "finish_noop", "escalate"):
        g.add_edge(n, END)
    return g.compile()
