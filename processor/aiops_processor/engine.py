"""Stream-processing engine. Pure logic + Redis writes; Kafka plumbing lives in main.py so it is easy to test."""
import collections, json, time, uuid

from .detectors import Ewma, MultiVariate, forecast
from .drain import Drain

# metric -> (anomaly type, EWMA std floor, minimum absolute deviation from baseline)
CHARTS = {"cpu_pct": ("cpu", 4.0, 25.0), "mem_mb": ("memory", 8.0, 25.0),
          "p95_ms": ("latency", 25.0, 150.0), "err_rate": ("errors", 0.02, 0.08)}
FEATURES = ["cpu_pct", "mem_mb", "p95_ms", "err_rate", "rps"]
Z, CONSEC, CLEAR_AFTER, SILENCE_S, LOG_QUIET_S = 4.0, 2, 5, 6, 10


def severity(typ, x, mem_limit):
    if typ == "cpu":
        return "high" if x >= 85 else "medium"
    if typ == "memory":
        return "high" if x >= 0.85 * mem_limit else "medium"
    if typ == "latency":
        return "high" if x >= 1000 else "medium"
    if typ == "errors":
        return "high" if x >= 0.3 else "medium"
    return "medium"


class SvcState:
    def __init__(self):
        self.ew = {k: Ewma(floor=v[1]) for k, v in CHARTS.items()}
        self.mv = MultiVariate()
        self.points = collections.deque(maxlen=240)
        self.consec = collections.Counter()
        self.active = {}            # anomaly type -> anomaly dict (+ "last")
        self.normal = 0
        self.mv_consec = 0
        self.last_seen = None
        self.log_hit = 0.0
        self.latest = None


class Engine:
    def __init__(self, redis, publish=None, mem_limit=256.0, now=time.time):
        self.r, self.publish, self.mem_limit, self.now = redis, publish, mem_limit, now
        self.states = collections.defaultdict(SvcState)
        self.drain = Drain()
        self.edges = collections.defaultdict(collections.deque)
        self.err_hits = collections.defaultdict(collections.deque)

    # ---- anomaly helpers -----------------------------------------------------------------------
    async def _raise(self, name, typ, sev, detector, metric, value, base, score, detail, ts=None):
        s = self.states[name]
        now = self.now()
        if typ in s.active:
            s.active[typ]["last"] = now
            if sev == "high":
                s.active[typ]["severity"] = "high"
            return
        a = {"id": uuid.uuid4().hex[:8], "ts": ts or now, "service": name, "type": typ, "severity": sev,
             "detector": detector, "metric": metric, "value": value, "baseline": base,
             "score": round(score, 2), "detail": detail}
        s.active[typ] = {**a, "last": now}
        await self.r.lpush("anomalies:recent", json.dumps(a))
        await self.r.ltrim("anomalies:recent", 0, 199)
        if self.publish:
            await self.publish(a)

    def _status(self, s, now):
        if s.last_seen is None:
            return "unknown"
        if now - s.last_seen > SILENCE_S or "down" in s.active:
            return "down"
        if not s.ew["p95_ms"].ready:
            return "learning"
        if any(a["severity"] != "low" for a in s.active.values()):
            return "degraded"
        return "healthy"

    async def _flush(self, name):
        s, now = self.states[name], self.now()
        latest = dict(s.latest or {"service": name, "up": 0})
        if s.latest and now - s.last_seen > SILENCE_S:
            latest["up"] = 0
        latest.update(status=self._status(s, now), last_seen=s.last_seen,
                      baseline={k: round(e.mean, 3) for k, e in s.ew.items()})
        pipe = self.r.pipeline()
        pipe.sadd("services", name)
        pipe.set(f"svc:{name}:latest", json.dumps(latest), ex=300)
        if s.active:
            pipe.hset("anomalies:active", name, json.dumps(list(s.active.values())))
        else:
            pipe.hdel("anomalies:active", name)
        await pipe.execute()

    # ---- inputs --------------------------------------------------------------------------------
    async def on_metric(self, m):
        name, now = m["service"], self.now()
        s = self.states[name]
        s.last_seen, s.latest = now, m
        s.points.append(m)
        hits = {}
        for key, (typ, _floor, min_delta) in CHARTS.items():
            ew, x = s.ew[key], m[key]
            z = ew.z(x)
            if ew.ready and z > Z and x - ew.mean >= min_delta:
                hits[typ] = (key, x, ew.mean, z)
            if z < 2.5:
                ew.update(x)                      # freeze the baseline while the metric is anomalous
        if m["err_rate"] >= 0.15 and m["rps"] >= 0.5 and "errors" not in hits:
            hits["errors"] = ("err_rate", m["err_rate"], s.ew["err_rate"].mean, 9.9)
        for typ in list(s.consec):
            if typ not in hits:
                s.consec[typ] = 0
        for typ, (key, x, base, z) in hits.items():
            s.consec[typ] += 1
            if s.consec[typ] >= CONSEC:
                await self._raise(name, typ, severity(typ, x, self.mem_limit), "ewma_control_chart", key,
                                  x, round(base, 3), z, f"{key} {x:.1f} vs baseline {base:.1f} (z={z:.1f})", m["ts"])
        # multivariate Isolation Forest (low severity, corroborating signal)
        vec = [m[k] for k in FEATURES]
        mv_flag = False
        if not hits and not s.active:
            s.mv.observe_normal(vec)
        sc = s.mv.score(vec)
        s.mv_consec = s.mv_consec + 1 if sc is not None and sc < -0.12 else 0
        if s.mv_consec >= 3:
            mv_flag = True
            await self._raise(name, "multivariate", "low", "isolation_forest", "multivariate", sc, 0,
                              -sc, f"unusual combination of metrics (isolation score {sc:.2f})", m["ts"])
        quiet = not hits and not mv_flag and now - s.log_hit > LOG_QUIET_S
        s.normal = s.normal + 1 if quiet else 0
        if s.active and s.normal >= CLEAR_AFTER:
            s.active.clear()
        for typ in [t for t, a in s.active.items() if a["severity"] == "low" and now - a["last"] > 20]:
            del s.active[typ]
        pipe = self.r.pipeline()
        pipe.lpush(f"svc:{name}:series", json.dumps(m))
        pipe.ltrim(f"svc:{name}:series", 0, 239)
        await pipe.execute()
        await self._flush(name)

    async def on_log(self, m):
        name, lvl, now = m["service"], m.get("level", "INFO"), self.now()
        tid, tpl, _new = self.drain.add(lvl, m["msg"])
        pipe = self.r.pipeline()
        pipe.lpush("logs:recent", json.dumps({**m, "template": tpl}))
        pipe.ltrim("logs:recent", 0, 499)
        if lvl in ("ERROR", "WARN"):
            pipe.hincrby(f"tpl:{name}:{lvl}", tpl, 1)
            pipe.expire(f"tpl:{name}:{lvl}", 900)
        await pipe.execute()
        if lvl == "ERROR":                       # error-template burst: same error template >=3 times in 20s
            dq = self.err_hits[(name, tid)]
            dq.append(now)
            while dq and now - dq[0] > 20:
                dq.popleft()
            s = self.states[name]
            if len(dq) >= 3 and s.ew["p95_ms"].ready:
                s.log_hit = now
                await self._raise(name, "log", "medium", "drain_log_parser", "log_template", len(dq), 0, len(dq),
                                  f"error template repeating: {tpl[:140]}", m["ts"])
                await self._flush(name)

    async def on_span(self, m):
        if m.get("peer"):
            self.edges[(m["service"], m["peer"])].append((self.now(), m["dur_ms"], m["status"] >= 500))
        pipe = self.r.pipeline()
        pipe.lpush("traces:recent", json.dumps(m))
        pipe.ltrim("traces:recent", 0, 599)
        await pipe.execute()

    # ---- periodic ------------------------------------------------------------------------------
    async def tick(self):
        now = self.now()
        preds = []
        for name, s in list(self.states.items()):
            if s.last_seen and now - s.last_seen > SILENCE_S and "down" not in s.active:
                await self._raise(name, "down", "high", "heartbeat", "up", 0, 1, 10.0,
                                  f"no telemetry for {now - s.last_seen:.0f}s")
            pts = list(s.points)
            for key, limit, slope, kind in (("mem_mb", 0.92 * self.mem_limit, 0.3, "memory_exhaustion"),
                                            ("p95_ms", 800.0, 8.0, "latency_slo_breach"),
                                            ("cpu_pct", 95.0, 1.0, "cpu_saturation")):
                f = forecast(pts, key, limit, slope)
                if f and f["eta_s"] < 600:
                    preds.append({"service": name, "kind": kind, **f})
            await self._flush(name)
        edges = []
        for (a, b), dq in list(self.edges.items()):
            while dq and now - dq[0][0] > 60:
                dq.popleft()
            if dq:
                n = len(dq)
                edges.append({"src": a, "dst": b, "calls": n, "err_rate": round(sum(e for *_, e in dq) / n, 3),
                              "avg_ms": round(sum(d for _, d, _ in dq) / n, 1)})
        pipe = self.r.pipeline()
        pipe.set("graph", json.dumps({"ts": now, "edges": edges}), ex=120)
        pipe.set("predictions", json.dumps({"ts": now, "items": preds}), ex=60)
        await pipe.execute()
