"""Dependency-graph RCA.

Symptoms propagate caller <- callee, so a personalised PageRank that walks caller -> callee (seeded at anomalous
services) concentrates score on the deepest anomalous dependency. It is combined with three further signals:
earliest onset, severity, and how many anomalous callers the candidate would explain; a candidate whose own callees are
anomalous is penalised (blame should move deeper)."""
import networkx as nx

SEV = {"low": 0.2, "medium": 0.6, "high": 1.0}


def rank(evidence):
    active = {s: [a for a in lst if a["severity"] != "low"] for s, lst in evidence["active"].items()}
    active = {s: lst for s, lst in active.items() if lst}
    if not active:
        return []
    sev = {s: max(SEV[a["severity"]] for a in lst) + (0.3 if any(a["type"] == "down" for a in lst) else 0)
           for s, lst in active.items()}
    onset = {s: min(a["ts"] for a in lst) for s, lst in active.items()}
    g = nx.DiGraph()
    for e in evidence["all_edges"]:
        g.add_edge(e["src"], e["dst"], weight=1.0 + sev.get(e["dst"], 0))
    for s in active:
        g.add_node(s)
    pr = nx.pagerank(g, alpha=0.85, personalization={n: sev.get(n, 0) + 0.01 for n in g}, weight="weight")
    pr_max = max(pr[s] for s in active)
    t0, span = min(onset.values()), max(max(onset.values()) - min(onset.values()), 10.0)
    ranked = []
    for s in active:
        callers = nx.ancestors(g, s) & set(active)
        callees = nx.descendants(g, s) & set(active)
        comp = {"pagerank": round(pr[s] / pr_max, 3),
                "earliest": round(1 - (onset[s] - t0) / span, 3),
                "severity": round(sev[s] / 1.3, 3),
                "explains": round(len(callers) / max(len(active) - 1, 1), 3) if len(active) > 1 else 0.0,
                "deeper_anomalous_callee_penalty": 0.25 if callees else 0.0}
        score = (0.40 * comp["pagerank"] + 0.25 * comp["earliest"] + 0.20 * comp["severity"]
                 + 0.15 * comp["explains"] - comp["deeper_anomalous_callee_penalty"])
        roots = [c for c in callers if not (nx.ancestors(g, c) & set(active))]
        path = []
        if roots:
            try:
                path = nx.shortest_path(g, sorted(roots)[0], s)
            except nx.NetworkXNoPath:
                path = []
        ranked.append({"service": s, "score": round(score, 3), "components": comp,
                       "explains": sorted(callers), "path": path or [s], "onset": onset[s]})
    return sorted(ranked, key=lambda x: -x["score"])
