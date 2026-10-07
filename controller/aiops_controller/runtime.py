"""Shared runtime state: dependencies, incident cache, pending approvals, executed-action history."""
import time, uuid

from . import config


class Runtime:
    def __init__(self, redis, store, llm, executor):
        self.r, self.store, self.llm, self.executor = redis, store, llm, executor
        self.mode = config.REMEDIATION_MODE
        self.recent = []                  # executed actions: {ts, type, target, auto}
        self.approvals = {}               # incident_id -> asyncio.Future
        self.incidents = {i["id"]: i for i in reversed(store.incidents(50))}

    def event(self, incident_id, stage, summary, data=None):
        return self.store.add_event(incident_id, stage, summary, data)

    def patch(self, incident_id, **fields):
        inc = self.incidents[incident_id]
        inc.update(fields)
        inc["updated"] = time.time()
        self.store.save_incident(inc)
        return inc

    def new_incident(self, anomalies, trigger="auto"):
        iid = "INC-" + uuid.uuid4().hex[:6].upper()
        inc = {"id": iid, "created": time.time(), "updated": time.time(), "trigger": trigger, "status": "analyzing",
               "stage": "detect", "severity": "medium", "iteration": 0, "anomalies": list(anomalies),
               "services": sorted({a["service"] for a in anomalies}), "root_cause": None, "rca": [], "analysis": None,
               "plan": None, "gate": None, "approval": None, "execution": None, "verification": None,
               "before": None, "after": None, "history": [], "resolved_at": None}
        self.incidents[iid] = inc
        self.store.save_incident(inc)
        self.event(iid, "detect", f"Incident {iid} opened from {len(anomalies)} anomaly signal(s)",
                   {"services": inc["services"]})
        return inc
