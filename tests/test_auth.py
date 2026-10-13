"""Tests for authentication, 40 req/s rate limiting, and 5-attempt/2-minute lockout protection."""
import time
import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from aiops_controller import main as m, auth
from aiops_controller.agent import build_agent
from aiops_controller.executor import SimExecutor
from aiops_controller.llm import LLM
from aiops_controller.manager import Manager
from aiops_controller.runtime import Runtime
from aiops_controller.store import Store


@pytest.fixture(autouse=True)
def clean_state():
    """Reset auth state and rate limiter between tests."""
    auth._active_sessions.clear()
    auth._lockout_tracker.clear()
    auth._rate_limit_tracker.clear()


@pytest.fixture
def client():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    rt = Runtime(r, Store(":memory:"), LLM(), SimExecutor(r))
    m.app.state.rt, m.app.state.mgr = rt, Manager(rt, build_agent(rt))
    return TestClient(m.app)


def test_successful_login_and_auth_me(client):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert data["user"]["username"] == "admin"
    assert data["user"]["role"] == "admin"

    token = data["token"]

    # Verify session with /api/auth/me
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["authenticated"] is True
    assert me_res.json()["user"]["username"] == "admin"


def test_failed_login_increments_attempts(client):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "wrongpassword"})
    assert res.status_code == 401
    data = res.json()
    assert data["locked"] is False
    assert data["failed_attempts"] == 1
    assert data["remaining_attempts"] == 4


def test_lockout_after_5_failed_attempts(client):
    # Perform 4 failed attempts
    for i in range(1, 5):
        res = client.post("/api/auth/login", json={"username": "admin", "password": f"wrong_{i}"})
        assert res.status_code == 401
        assert res.json()["failed_attempts"] == i
        assert res.json()["remaining_attempts"] == 5 - i

    # 5th failed attempt triggers 2-minute lockout
    res5 = client.post("/api/auth/login", json={"username": "admin", "password": "wrong_5"})
    assert res5.status_code == 423
    data5 = res5.json()
    assert data5["locked"] is True
    assert data5["failed_attempts"] == 5
    assert data5["remaining_attempts"] == 0
    assert data5["remaining_seconds"] <= 120 and data5["remaining_seconds"] >= 115

    # Any subsequent attempt during lockout (even with correct password) is rejected
    res_blocked = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert res_blocked.status_code == 423
    assert res_blocked.json()["locked"] is True
    assert "Account locked" in res_blocked.json()["detail"]


def test_lockout_expires_after_2_minutes(client):
    # Lock out user
    for i in range(5):
        client.post("/api/auth/login", json={"username": "operator", "password": "bad"})

    status_locked = client.get("/api/auth/status?username=operator").json()
    assert status_locked["locked"] is True

    # Fast forward time beyond 120 seconds in lockout tracker for both user and client IP
    now_past = time.time() - 1
    auth._lockout_tracker["operator"]["locked_until"] = now_past
    auth._lockout_tracker["testclient"]["locked_until"] = now_past

    # Now login should succeed with correct credentials
    res = client.post("/api/auth/login", json={"username": "operator", "password": "operator123"})
    assert res.status_code == 200
    assert res.json()["user"]["username"] == "operator"

    # Status should no longer be locked
    status_unlocked = client.get("/api/auth/status?username=operator").json()
    assert status_unlocked["locked"] is False
    assert status_unlocked["failed_attempts"] == 0


def test_rate_limiting_40_req_per_second(client):
    # Perform 40 requests rapidly
    responses = [client.get("/api/health") for _ in range(40)]
    for r in responses:
        assert r.status_code == 200
        assert r.headers.get("X-RateLimit-Limit") == "40"

    # 41st request within the 1-second window MUST be rejected with HTTP 429
    res_41 = client.get("/api/health")
    assert res_41.status_code == 429
    assert res_41.json()["retry_after"] == 1
    assert "Rate limit exceeded" in res_41.json()["detail"]


def test_logout(client):
    login_res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login_res.json()["token"]

    # Logout
    logout_res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_res.status_code == 200
    assert logout_res.json()["ok"] is True

    # Token is now revoked
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 401
