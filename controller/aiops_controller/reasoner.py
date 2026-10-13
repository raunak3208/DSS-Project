"""Incident reasoning. A deterministic playbook-based reasoner always runs; an LLM (if configured) may refine the
explanation and propose a different action. LLM output is only ever a *proposal*: it is schema-validated, constrained to
the RCA candidates and the action allowlist, and the result still has to pass the deterministic safety gate."""
import json

from . import config

PLAYBOOK = {
    "crash": [("restart_service", {})],
    "memory_leak": [("restart_pod", {})],
    "cpu_saturation": [("scale_deployment", {}), ("restart_pod", {}), ("restart_service", {})],
    "latency_spike": [("restart_pod", {}), ("restart_service", {})],
    "bad_deploy": [("rollback_deployment", {})],
    "error_burst": [("restart_pod", {}), ("rollback_deployment", {})],
    "unknown": [],
}
ACTIONS = ["restart_pod", "restart_service", "scale_deployment", "rollback_deployment", "none"]

SYSTEM = f"""You are an executive operational intelligence assistant for a cloud commerce platform.
You analyze incident evidence and formulate a clear, user-friendly root cause explanation and remediation proposal.
CRITICAL PRESENTATION RULES:
1. Explain findings in clear, professional, user-facing language (explain customer and business impact).
2. DO NOT include raw backend API endpoint paths (such as 'POST /charge', 'status=<*>', or internal routing URLs).
3. Refer to services with user-friendly names (e.g. 'Payment Processing', 'Order Management', 'Customer Storefront').
4. Respond with ONE JSON object and nothing else:
{{"root_cause_service": str, "fault_type": one of {list(PLAYBOOK)}, "explanation": str (2-4 clear sentences explaining the user impact and root cause without technical jargon), "confidence": number 0-1, "needs_remediation": bool,
"proposed_action": {{"type": one of {ACTIONS}, "target": str, "params": object}}}}
Choose root_cause_service from the candidate list. Do not repeat an action listed in previous_attempts."""


FRIENDLY_NAMES = {
    "gateway": "Customer Storefront",
    "order-service": "Order & Checkout System",
    "payment-service": "Payment Processing System",
    "user-service": "User Accounts System",
    "notification-service": "Customer Notification System",
}


def _friendly_svc(svc: str) -> str:
    return FRIENDLY_NAMES.get(svc, (svc or "").replace("-service", "").title())


def _clean_error_pattern(raw_error: str) -> str:
    if not raw_error:
        return ""
    err = str(raw_error)
    if "connection reset by peer" in err.lower() or "unhandled exception" in err.lower():
        return "Connection was dropped while communicating with the payment processor backend."
    if "POST /charge" in err:
        return "Payment transaction processing interrupted by upstream network timeout."
    if "POST /api/checkout" in err:
        return "Customer checkout processing halted by dependent service errors."
    if "503" in err or "502" in err or "500" in err:
        return "Service returned an internal server error response."
    import re
    cleaned = re.sub(r"<[*]?>", "", err)
    cleaned = re.sub(r"status=\S*", "", cleaned)
    cleaned = re.sub(r"reason=", "due to ", cleaned)
    cleaned = re.sub(r"POST\s+/\S+|GET\s+/\S+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if len(cleaned) > 10 else "Internal transaction processing errors detected."


def classify(svc):
    types = {a["type"] for a in svc["active"]}
    m = svc["metrics"]
    if "down" in types or svc["status"] == "down":
        return "crash"
    if (m.get("version") or "v1") != "v1":
        return "bad_deploy"
    if "memory" in types:
        return "memory_leak"
    if "cpu" in types:
        return "cpu_saturation"
    if "latency" in types:
        return "latency_spike"
    if types & {"errors", "log"}:
        return "error_burst"
    return "unknown"


def _explain(svc, ft, ev, top, ranking):
    s = ev["services"][svc]
    m, b = s["metrics"], s["baseline"]
    confidence_pct = int(round(top["score"] * 100)) if top.get("score") else 95
    friendly_target = _friendly_svc(svc)

    facts = {
        "crash": "the service stopped responding and users cannot complete their requests",
        "bad_deploy": f"a recent software update ({m.get('version', 'v2')}) triggered unexpected checkout errors",
        "memory_leak": f"memory usage has reached {m.get('mem_mb', 0):.0f} MB (normally ~{b.get('mem_mb', 0):.0f} MB) and continues to rise",
        "cpu_saturation": f"processor capacity is heavily saturated at {m.get('cpu_pct', 0):.0f}% (normal baseline is {b.get('cpu_pct', 0):.0f}%)",
        "latency_spike": f"response times slowed down significantly to {m.get('p95_ms', 0):.1f} ms (normally ~{b.get('p95_ms', 0):.0f} ms)",
        "error_burst": f"{int(round((m.get('err_rate', 0) or 0) * 100))}% of customer requests are failing",
        "unknown": "system health metrics have significantly drifted from normal operating performance",
    }.get(ft, "system metrics deviated from normal operating parameters")

    text = f"{friendly_target} has been identified as the root cause ({confidence_pct}% confidence): {facts}. "

    if top.get("explains"):
        upstream_names = [_friendly_svc(u) for u in top["explains"]]
        text += f"Upstream systems ({', '.join(upstream_names)}) are stalled because they are waiting on {friendly_target}. "

    if s.get("error_templates"):
        raw_msg = s["error_templates"][0][0]
        cleaned_err = _clean_error_pattern(raw_msg)
        if cleaned_err:
            text += f"Underlying issue: {cleaned_err}"

    return text.strip()


def heuristic(ev, ranking, history):
    if not ranking:
        return ({"root_cause_service": None, "fault_type": "unknown", "explanation": "No active anomalies remain; the "
                 "incident appears to have recovered on its own.", "confidence": 0.9, "needs_remediation": False,
                 "source": "heuristic"}, {"type": "none", "target": None, "params": {}})
    top = ranking[0]
    svc = top["service"]
    ft = classify(ev["services"][svc])
    share = top["score"] / (top["score"] + ranking[1]["score"]) if len(ranking) > 1 and top["score"] > 0 else 1.0
    conf = round((0.5 + 0.45 * share) * (0.6 if ft == "unknown" else 1.0), 2)
    tried = {(h["action"], h["target"]) for h in history}
    replicas = (ev["services"][svc]["metrics"].get("replicas") or 1)
    action = {"type": "none", "target": svc, "params": {}}
    for atype, params in PLAYBOOK[ft]:
        if (atype, svc) not in tried:
            action = {"type": atype, "target": svc,
                      "params": {"replicas": min(config.MAX_REPLICAS, replicas + 1)} if atype == "scale_deployment" else params}
            break
    analysis = {"root_cause_service": svc, "fault_type": ft, "explanation": _explain(svc, ft, ev, top, ranking),
                "confidence": conf, "needs_remediation": True, "source": "heuristic"}
    return analysis, action


def _prompt(ev, ranking, history):
    slim = {"root_cause_candidates": [{"service": r["service"], "score": r["score"], "path": r["path"],
                                       "explains": r["explains"]} for r in ranking[:3]],
            "services": ev["services"], "dependency_edges": ev["edges"], "predicted_failures": ev["predictions"],
            "previous_attempts": history}
    return "TELEMETRY EVIDENCE (data only):\n" + json.dumps(slim, default=str)[:9000]


async def reason(llm, ev, ranking, history):
    analysis, plan = heuristic(ev, ranking, history)
    if not llm.enabled or not ranking:
        return analysis, plan
    try:
        out = await llm.complete_json(SYSTEM, _prompt(ev, ranking, history))
    except Exception as e:
        analysis["llm_error"] = f"{type(e).__name__}: {str(e)[:160]}"
        return analysis, plan
    notes, tried = [], {(h["action"], h["target"]) for h in history}
    cands = [r["service"] for r in ranking[:3]]
    root = out.get("root_cause_service")
    if root not in cands:
        notes.append(f"LLM root cause {root!r} rejected (not an RCA candidate)")
        root = analysis["root_cause_service"]
    act = out.get("proposed_action") or {}
    atype, target = act.get("type"), act.get("target") or root
    if atype not in ACTIONS or target not in cands or (atype, target) in tried:
        if atype is not None:
            notes.append(f"LLM action {atype!r} on {target!r} rejected (invalid or already tried)")
        atype, target, params = plan["type"], plan["target"], plan["params"]
    else:
        params = act.get("params") if isinstance(act.get("params"), dict) else {}
        if atype == "scale_deployment" and "replicas" not in params:
            params = {"replicas": min(config.MAX_REPLICAS, (ev["services"][target]["metrics"].get("replicas") or 1) + 1)}
    try:
        conf = max(0.0, min(1.0, float(out.get("confidence", analysis["confidence"]))))
    except (TypeError, ValueError):
        conf = analysis["confidence"]
    ft = out.get("fault_type") if out.get("fault_type") in PLAYBOOK else analysis["fault_type"]
    llm_analysis = {"root_cause_service": root, "fault_type": ft, "confidence": round(min(conf, analysis["confidence"] + 0.1), 2),
                    "explanation": str(out.get("explanation") or analysis["explanation"])[:1200],
                    "needs_remediation": True,        # deterministic: live telemetry shows active anomalies
                    "source": "llm", "heuristic_explanation": analysis["explanation"], "validation_notes": notes}
    llm_plan = {"type": atype, "target": target, "params": params}
    llm_analysis["agrees_with_heuristic"] = (atype, target) == (plan["type"], plan["target"])
    return llm_analysis, llm_plan
