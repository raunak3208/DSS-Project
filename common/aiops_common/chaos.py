"""In-process fault injection. State lives in memory, so a container restart clears most faults,
but a bad deployment is persisted in Redis (desired version) and only a rollback removes it."""
import asyncio, os, threading, time

import psutil

MEM_LIMIT_MB = float(os.getenv("MEM_LIMIT_MB", "256"))
STABLE_VERSION = "v1"
DEFAULTS = {"latency": 1500, "errors": 0.5, "cpu": 0.9, "memory": 3, "crash": 1, "bad_deploy": 1}


class Chaos:
    def __init__(self, service):
        self.service = service
        self.version = STABLE_VERSION
        self.replicas = 1
        self.faults = {}
        self._burn_stop = None
        self._leak = []
        self._leak_task = None
        self._proc = psutil.Process()

    # ---- lifecycle -------------------------------------------------------------------------
    def activate(self, ftype, intensity=None, duration_s=0):
        intensity = DEFAULTS[ftype] if intensity is None else float(intensity)
        self.clear(ftype)
        self.faults[ftype] = {"intensity": intensity, "until": time.time() + duration_s if duration_s else 0}
        if ftype == "cpu":
            self._start_burn(min(1.0, intensity))
        elif ftype == "memory":
            self._leak_task = asyncio.create_task(self._leak_loop(intensity))
        elif ftype == "crash":
            asyncio.get_running_loop().call_later(1.0, os._exit, 1)

    def clear(self, ftype=None):
        for t in ([ftype] if ftype else list(self.faults)):
            self.faults.pop(t, None)
            if t == "cpu" and self._burn_stop:
                self._burn_stop.set()
            if t == "memory":
                if self._leak_task:
                    self._leak_task.cancel()
                self._leak = []

    def _alive(self, t):
        f = self.faults.get(t)
        if f and f["until"] and time.time() > f["until"]:
            self.clear(t)
            return None
        return f

    # ---- effects ---------------------------------------------------------------------------
    def latency_ms(self):
        ms = 0.0
        if (f := self._alive("latency")):
            ms += f["intensity"]
        if (f := self._alive("cpu")):
            ms += 600 * f["intensity"] / max(1, self.replicas)      # scaling out spreads the saturation
        if self.version != STABLE_VERSION:
            ms += 150
        if self.memory_pressure():
            ms += 300
        return ms

    def error_rate(self):
        r = 0.0
        if (f := self._alive("errors")):
            r = max(r, f["intensity"])
        if self.version != STABLE_VERSION:
            r = max(r, 0.4)
        if self.memory_pressure():
            r = max(r, 0.5)
        return r

    def error_message(self):
        if self.version != STABLE_VERSION:
            return f"NullReferenceError in handler (release {self.version}): unexpected field 'currency'"
        if self.memory_pressure():
            pct = 100 * self._proc.memory_info().rss / 1048576 / MEM_LIMIT_MB
            return f"MemoryError: allocation failed, heap at {pct:.0f}% of limit"
        return "Unhandled exception: connection reset by peer while reading from backend"

    def memory_pressure(self):
        return bool(self._leak) and self._proc.memory_info().rss / 1048576 > 0.9 * MEM_LIMIT_MB

    # ---- fault workers ---------------------------------------------------------------------
    def _start_burn(self, duty):
        stop = self._burn_stop = threading.Event()

        def run():
            while not stop.is_set():
                t = time.perf_counter()
                while time.perf_counter() - t < 0.1 * duty:
                    sum(i * i for i in range(500))
                time.sleep(0.1 * (1 - duty) + 0.001)
        threading.Thread(target=run, daemon=True).start()

    async def _leak_loop(self, mb_per_s):
        while self._proc.memory_info().rss / 1048576 < 0.93 * MEM_LIMIT_MB:
            self._leak.append(bytearray(b"x") * int(mb_per_s * 1048576))
            await asyncio.sleep(1)
        while True:                      # hold at the ceiling (service is now degraded)
            await asyncio.sleep(5)
