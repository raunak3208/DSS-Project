"""Telemetry emitter: logs, metrics and spans go to Kafka, or to an in-memory sink when KAFKA_BOOTSTRAP is empty."""
import asyncio, collections, json, os, sys, time

import psutil

TOPICS = {"log": "telemetry.logs", "metric": "telemetry.metrics", "span": "telemetry.traces"}


class Telemetry:
    def __init__(self, service, bootstrap=None):
        self.service = service
        self.bootstrap = os.getenv("KAFKA_BOOTSTRAP", "") if bootstrap is None else bootstrap
        self.q = asyncio.Queue(maxsize=5000)
        self.producer = None
        self.sink = collections.deque(maxlen=2000)      # used when Kafka is not configured (tests/dev)
        self.window = collections.deque()                # (ts, dur_ms, is_error)
        self.inflight = 0
        self.state = None                                # object with .version / .replicas (Chaos)
        self.on_metric = None                            # optional callback (Prometheus gauges)
        self.interval = float(os.getenv("METRICS_INTERVAL_S", "2"))   # metric window cadence (tests shorten it)

    # ---- emit API -------------------------------------------------------------------------
    def emit(self, kind, msg):
        msg.setdefault("ts", time.time())
        msg["service"] = self.service
        try:
            self.q.put_nowait((TOPICS[kind], msg))
        except asyncio.QueueFull:
            pass

    def log(self, level, text, trace_id=None, **fields):
        print(json.dumps({"ts": round(time.time(), 3), "service": self.service, "level": level, "msg": text}), flush=True)
        self.emit("log", {"level": level, "msg": text, "trace_id": trace_id, "fields": fields})

    def span(self, trace_id, span_id, parent_id, name, dur_ms, status, peer=None):
        self.emit("span", {"trace_id": trace_id, "span_id": span_id, "parent_id": parent_id, "name": name,
                           "dur_ms": round(dur_ms, 1), "status": status, "peer": peer})

    def record_request(self, dur_ms, ok):
        self.window.append((time.time(), dur_ms, not ok))

    # ---- background tasks -----------------------------------------------------------------
    async def start(self):
        asyncio.create_task(self._pump())
        asyncio.create_task(self._metrics_loop())

    async def _pump(self):
        if self.bootstrap:
            from aiokafka import AIOKafkaProducer
            while self.producer is None:
                try:
                    p = AIOKafkaProducer(bootstrap_servers=self.bootstrap, linger_ms=50,
                                         value_serializer=lambda v: json.dumps(v).encode())
                    await p.start()
                    self.producer = p
                except Exception as e:  # Kafka not ready yet
                    print(f"[telemetry] waiting for kafka: {e!r}", file=sys.stderr, flush=True)
                    await asyncio.sleep(3)
        while True:
            topic, msg = await self.q.get()
            if self.producer:
                try:
                    await self.producer.send(topic, msg)
                except Exception:
                    pass
            else:
                self.sink.append((topic, msg))

    async def _metrics_loop(self):
        proc = psutil.Process()
        proc.cpu_percent(None)
        while True:
            await asyncio.sleep(self.interval)
            now = time.time()
            while self.window and now - self.window[0][0] > 4:
                self.window.popleft()
            durs = sorted(d for _, d, _ in self.window)
            n = len(durs)
            errs = sum(1 for _, _, e in self.window if e)
            pct = lambda q: durs[min(n - 1, int(q * n))] if n else 0.0
            rep = max(1, getattr(self.state, "replicas", 1))
            m = {"cpu_pct": round(min(100.0, proc.cpu_percent(None) / rep), 1),
                 "mem_mb": round(proc.memory_info().rss / 1048576, 1),
                 "rps": round(n / 4, 2), "p50_ms": round(pct(0.5), 1), "p95_ms": round(pct(0.95), 1),
                 "err_rate": round(errs / n, 3) if n else 0.0, "inflight": self.inflight,
                 "version": getattr(self.state, "version", "v1"), "replicas": rep, "up": 1}
            self.emit("metric", m)
            if self.on_metric:
                self.on_metric(m)
