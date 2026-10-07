"""LLM output is only a proposal: invalid roots/actions are rejected and the swap-in provider needs no code change."""
import asyncio

from aiops_controller import reasoner
from aiops_controller.llm import LLM


class FakeLLM:
    enabled = True
    def __init__(self, out): self.out = out
    async def complete_json(self, system, user): return self.out


EV = {"services": {"payment-service": {"status": "degraded", "metrics": {"version": "v1", "replicas": 1, "p95_ms": 1600},
      "baseline": {"p95_ms": 60}, "active": [{"type": "latency", "severity": "high"}], "error_templates": [], "error_logs": []}},
      "edges": [], "predictions": []}
RANK = [{"service": "payment-service", "score": 0.9, "explains": [], "path": ["payment-service"], "components": {}}]


def run(out, history=()):
    return asyncio.run(reasoner.reason(FakeLLM(out), EV, RANK, list(history)))


def test_valid_llm_proposal_is_used():
    a, p = run({"root_cause_service": "payment-service", "fault_type": "latency_spike", "explanation": "x", "confidence": 0.8,
                "needs_remediation": True, "proposed_action": {"type": "restart_service", "target": "payment-service", "params": {}}})
    assert a["source"] == "llm" and p["type"] == "restart_service"


def test_hallucinated_target_and_dangerous_action_are_rejected():
    a, p = run({"root_cause_service": "kafka", "fault_type": "latency_spike", "explanation": "x", "confidence": 1.0,
                "proposed_action": {"type": "delete_all_pods", "target": "kafka", "params": {}}})
    assert a["root_cause_service"] == "payment-service" and p["type"] == "restart_pod" and a["validation_notes"]


def test_llm_cannot_repeat_failed_action():
    hist = [{"action": "restart_pod", "target": "payment-service", "iteration": 0, "result": "not_resolved"}]
    a, p = run({"root_cause_service": "payment-service", "fault_type": "latency_spike", "explanation": "x", "confidence": 0.9,
                "proposed_action": {"type": "restart_pod", "target": "payment-service", "params": {}}}, hist)
    assert p["type"] == "restart_service"          # deterministic playbook moves on


def test_llm_failure_falls_back_to_rules():
    class Boom(FakeLLM):
        async def complete_json(self, s, u): raise RuntimeError("429 rate limited")
    a, p = asyncio.run(reasoner.reason(Boom({}), EV, RANK, []))
    assert a["source"] == "heuristic" and "llm_error" in a and p["type"] == "restart_pod"


def test_provider_swap_is_configuration_only(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "mistral")
    assert not LLM().enabled                         # no key -> rules only
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    assert LLM().enabled and LLM().base.startswith("https://api.mistral.ai")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    l = LLM()
    assert l.enabled and "11434" in l.base and l.model == "llama3.2"
