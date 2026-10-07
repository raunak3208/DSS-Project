"""Turns the anomaly stream into incidents and runs one agent workflow per incident."""
import asyncio, json, sys, time

from . import config, evidence


class Manager:
    def __init__(self, rt, graph):
        self.rt, self.graph = rt, graph
        self.current, self.task = None, None
        self.pending, self.opening, self.cooldown_until = [], False, 0.0

    @property
    def busy(self):
        return bool(self.task and not self.task.done())

    async def on_anomaly(self, a):
        self.rt.event(None, "detect", f"{a['service']}: {a['detail']}", {k: a[k] for k in ("type", "severity", "detector", "service")})
        if self.busy:                                   # fold cascading symptoms into the running incident
            inc = self.rt.incidents[self.current]
            inc["anomalies"].append(a)
            if a["severity"] != "low" and a["service"] not in inc["services"]:
                self.rt.patch(self.current, services=sorted(inc["services"] + [a["service"]]))
            return
        if a["severity"] == "low" or time.time() < self.cooldown_until:
            return
        self.pending.append(a)
        if not self.opening:
            self.opening = True
            asyncio.create_task(self._open_later())

    async def _open_later(self):
        await asyncio.sleep(config.DEBOUNCE_S)         # gather correlated anomalies before analysing
        self.opening, anomalies, self.pending = False, self.pending, []
        if not self.busy:
            self.open(anomalies)

    def open(self, anomalies=None, trigger="auto"):
        inc = self.rt.new_incident(anomalies or [], trigger)
        self.current = inc["id"]
        self.task = asyncio.create_task(self._run(inc["id"]))
        return inc

    async def trigger_manual(self):
        act = await evidence.active_map(self.rt.r)
        anomalies = [a for lst in act.values() for a in lst if a["severity"] != "low"]
        return None if not anomalies or self.busy else self.open(anomalies, "manual")

    async def _run(self, iid):
        try:
            await self.graph.ainvoke({"incident_id": iid, "iteration": 0, "history": []}, {"recursion_limit": 100})
        except Exception as e:
            print(f"[agent] error {e!r}", file=sys.stderr, flush=True)
            self.rt.patch(iid, status="escalated", stage="done")
            self.rt.event(iid, "escalated", f"Agent error, escalated to human: {type(e).__name__}: {e}")
        finally:
            self.cooldown_until = time.time() + 15

    async def consume(self):
        from aiokafka import AIOKafkaConsumer
        while True:
            try:
                c = AIOKafkaConsumer("aiops.anomalies", bootstrap_servers=config.KAFKA_BOOTSTRAP, group_id="aiops-controller",
                                     auto_offset_reset="latest", value_deserializer=lambda b: json.loads(b))
                await c.start()
                print("[controller] consuming aiops.anomalies", flush=True)
                async for msg in c:
                    await self.on_anomaly(msg.value)
            except Exception as e:
                print(f"[controller] kafka consumer error {e!r}; retrying", file=sys.stderr, flush=True)
                await asyncio.sleep(3)
