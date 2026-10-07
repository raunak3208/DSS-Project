#!/usr/bin/env python3
"""Run a failure scenario against the live stack and narrate detection -> RCA -> remediation -> verification.

    python scripts/run_scenario.py scenarios/cascading_payment_latency.json            # you approve in the dashboard
    python scripts/run_scenario.py scenarios/cascading_payment_latency.json --auto-approve
Standard library only.
"""
import argparse, json, sys, time, urllib.request


def call(base, path, method="GET", body=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--api", default="http://localhost:8080")
    ap.add_argument("--auto-approve", action="store_true", help="approve pending actions instead of waiting for a human")
    ap.add_argument("--timeout", type=int, default=420)
    a = ap.parse_args()
    sc = json.load(open(a.scenario))
    print(f"== {sc['name']}\n{sc['description']}\n")

    call(a.api, "/api/chaos/reset", "POST")
    print("waiting for baselines to be learned and any earlier incident to clear...")
    while True:
        o = call(a.api, "/api/overview")
        busy = o["incident"] and o["incident"]["status"] not in ("resolved", "escalated")
        if not o["learning"] and not busy and all(s["status"] in ("healthy",) for s in o["services"]):
            break
        time.sleep(3)
    known = {e["id"] for e in o["timeline"]}
    t0 = time.time()
    print(f"[{0:5.0f}s] injecting {sc['inject']}")
    call(a.api, "/api/chaos", "POST", sc["inject"])

    inc, approved = None, set()
    while time.time() - t0 < a.timeout:
        time.sleep(2)
        o = call(a.api, "/api/overview")
        for e in sorted(o["timeline"], key=lambda e: e["id"]):
            if e["id"] not in known:
                known.add(e["id"])
                if e["stage"] != "detect" or e["incident_id"] is None:
                    print(f"[{e['ts'] - (t0):5.0f}s] {e['stage']:<12} {e['summary'][:150]}")
        inc = o["incident"]
        if inc and inc["created"] >= t0 - 2:
            key = (inc["id"], inc["iteration"])
            if inc["status"] == "awaiting_approval" and key not in approved:
                approved.add(key)
                if a.auto_approve:
                    print(f"[{time.time() - t0:5.0f}s] approval    auto-approving (--auto-approve)")
                    call(a.api, f"/api/incidents/{inc['id']}/approval", "POST", {"approved": True, "by": "run_scenario.py"})
                else:
                    print(f"[{time.time() - t0:5.0f}s] approval    waiting for you in the dashboard (http://localhost:3000)")
            if inc["status"] in ("resolved", "escalated"):
                break
    else:
        print("timed out"); return 2

    full = call(a.api, f"/api/incidents/{inc['id']}")
    actions = [h["action"] for h in full["history"]] + ([full["plan"]["type"]] if full["execution"] else [])
    result = {"root_cause": full["root_cause"], "fault_type": full["analysis"]["fault_type"],
              "actions": actions, "final": full["status"], "human_approval": bool(full["approval"])}
    print("\n== result")
    ok = True
    for k, want in sc["expect"].items():
        got = result.get(k)
        good = got == want
        ok &= good
        print(f"  {k:<15} expected={want!s:<40} got={got!s:<40} {'ok' if good else 'DIFFERENT'}")
    print(f"  time to resolution: {(full['resolved_at'] or time.time()) - full['created']:.0f}s, severity {full['severity']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
