"""Remediation executors. This is the ONLY code that touches infrastructure, and it is only reachable from the agent's
`execute` node after the safety gate has allowed (or a human has approved) the action. It re-validates defensively."""
import asyncio, time

import httpx

from . import config
from .safety import RISK


class Executor:
    def __init__(self, redis):
        self.r = redis

    async def run(self, action):
        t, target, p = action["type"], action["target"], action.get("params") or {}
        if t not in RISK or target not in config.INVENTORY:           # defence in depth
            return {"ok": False, "detail": f"refused: {t} on {target}", "ts": time.time()}
        try:
            if t in ("restart_pod", "restart_service"):
                detail = await self.restart(target, whole_service=(t == "restart_service"))
            elif t == "scale_deployment":
                detail = await self.scale(target, int(p["replicas"]))
            else:
                detail = await self.rollback(target)
            return {"ok": True, "detail": detail, "ts": time.time()}
        except Exception as e:
            return {"ok": False, "detail": f"{type(e).__name__}: {e}", "ts": time.time()}

    async def _reload(self, target):
        try:                                     # tell the running service to re-read desired version/replicas
            async with httpx.AsyncClient(timeout=3) as c:
                await c.post(f"http://{target}:8000/admin/reload")
        except httpx.HTTPError:
            pass                                 # service is down; it reads Redis on startup

    async def scale(self, target, n):
        await self.r.set(f"replicas:{target}", n)
        await self._reload(target)
        return f"scaled {target} to {n} replicas"

    async def rollback(self, target):
        await self.r.set(f"deploy:{target}", "v1")
        await self._reload(target)
        return f"rolled {target} back to stable release v1"

    async def restart(self, target, whole_service=False):
        raise NotImplementedError

    async def ensure_up(self, target):
        pass


class DockerExecutor(Executor):
    """Compose backend: container name == service name. Needs /var/run/docker.sock mounted into the controller."""

    def _client(self):
        import docker
        return docker.from_env()

    async def restart(self, target, whole_service=False):
        await asyncio.to_thread(lambda: self._client().containers.get(target).restart(timeout=5))
        return f"restarted container {target}"

    async def ensure_up(self, target):
        def go():
            c = self._client().containers.get(target)
            if c.status != "running":
                c.start()
        await asyncio.to_thread(go)


class K8sExecutor(Executor):
    """Kubernetes backend (in-cluster). Deployment and Service names equal the service name, label app=<name>."""

    def __init__(self, redis):
        super().__init__(redis)
        from kubernetes import client, config as kc
        try:
            kc.load_incluster_config()
        except Exception:
            kc.load_kube_config()
        self.core, self.apps, self.ns = client.CoreV1Api(), client.AppsV1Api(), config.K8S_NAMESPACE

    async def restart(self, target, whole_service=False):
        def go():
            if whole_service:       # rolling restart of every replica
                patch = {"spec": {"template": {"metadata": {"annotations": {"aiops/restartedAt": str(time.time())}}}}}
                self.apps.patch_namespaced_deployment(target, self.ns, patch)
                return f"rolling restart of deployment {target}"
            pods = self.core.list_namespaced_pod(self.ns, label_selector=f"app={target}").items
            if not pods:
                raise RuntimeError(f"no pods for {target}")
            worst = max(pods, key=lambda p: sum(cs.restart_count for cs in (p.status.container_statuses or [])))
            self.core.delete_namespaced_pod(worst.metadata.name, self.ns)
            return f"deleted pod {worst.metadata.name} (deployment recreates it)"
        return await asyncio.to_thread(go)

    async def scale(self, target, n):
        await asyncio.to_thread(lambda: self.apps.patch_namespaced_deployment_scale(target, self.ns, {"spec": {"replicas": n}}))
        return await super().scale(target, n)

    async def rollback(self, target):
        # The simulated bad release is a Redis desired-version flag, so rollback flips it and rolls the pods.
        await super().rollback(target)
        return await self.restart(target, whole_service=True) + "; desired version reset to v1"


class SimExecutor(Executor):
    """No infrastructure: records calls. Used by tests."""

    def __init__(self, redis, on_run=None):
        super().__init__(redis)
        self.calls, self.on_run = [], on_run

    async def restart(self, target, whole_service=False):
        return f"[sim] restart {target}"

    async def scale(self, target, n):
        return f"[sim] scale {target}={n}"

    async def rollback(self, target):
        return f"[sim] rollback {target}"

    async def run(self, action):
        self.calls.append(action)
        res = await super().run(action)
        if self.on_run:
            await self.on_run(action)
        return res

    async def _reload(self, target):
        pass


def make_executor(redis):
    if config.BACKEND == "k8s":
        return K8sExecutor(redis)
    if config.BACKEND == "sim":
        return SimExecutor(redis)
    return DockerExecutor(redis)
