"""API smoke test: controller endpoints with an in-memory runtime (no Kafka/Docker)."""
import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from aiops_controller import main as m
from aiops_controller.agent import build_agent
from aiops_controller.executor import SimExecutor
from aiops_controller.llm import LLM
from aiops_controller.manager import Manager
from aiops_controller.runtime import Runtime
from aiops_controller.store import Store


@pytest.fixture
def client():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    rt = Runtime(r, Store(":memory:"), LLM(), SimExecutor(r))
    m.app.state.rt, m.app.state.mgr = rt, Manager(rt, build_agent(rt))
    return TestClient(m.app)          # no context manager: lifespan (Kafka consumer) is not started


def test_overview_and_config(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    cfg = client.get("/api/config").json()
    assert cfg["llm"]["provider"] == "heuristic" and cfg["mode"] == "auto"
    o = client.get("/api/overview").json()
    assert len(o["services"]) == 5 and o["learning"] is True and o["incident"] is None


def test_mode_validation_and_guards(client):
    assert client.post("/api/mode", json={"mode": "approve_all"}).json() == {"mode": "approve_all"}
    assert client.post("/api/mode", json={"mode": "yolo"}).status_code == 400
    assert client.post("/api/incidents/INC-NONE/approval", json={"approved": True}).status_code == 404
    assert client.post("/api/chaos", json={"service": "kafka", "type": "cpu"}).status_code == 400
    assert client.post("/api/incidents/trigger").status_code == 409


def test_openapi_documents_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/overview", "/api/incidents/{iid}/approval", "/api/chaos", "/api/mode"):
        assert p in paths
