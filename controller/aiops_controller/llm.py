"""Provider-agnostic LLM client. Everything speaks the OpenAI-style /chat/completions protocol, so swapping
Mistral for Ollama (or any compatible server) is an environment change, not a code change.

    LLM_PROVIDER=mistral        MISTRAL_API_KEY=...            (default when a key is present)
    LLM_PROVIDER=ollama         LLM_MODEL=llama3.2             (Ollama's OpenAI-compatible endpoint)
    LLM_PROVIDER=openai_compat  LLM_BASE_URL=... LLM_API_KEY=...
    LLM_PROVIDER=heuristic      (no LLM; deterministic reasoner only)
"""
import json, os, re

import httpx

DEFAULTS = {"mistral": ("https://api.mistral.ai/v1", "mistral-small-latest"),
            "ollama": ("http://host.docker.internal:11434/v1", "llama3.2"),
            "openai_compat": ("http://localhost:8000/v1", "local-model")}


class LLM:
    def __init__(self):
        key = os.getenv("MISTRAL_API_KEY", "")
        self.provider = os.getenv("LLM_PROVIDER") or ("mistral" if key else "heuristic")
        base, model = DEFAULTS.get(self.provider, (None, None))
        self.base = os.getenv("LLM_BASE_URL") or base
        self.model = os.getenv("LLM_MODEL") or model
        self.key = os.getenv("LLM_API_KEY") or key
        self.timeout = float(os.getenv("LLM_TIMEOUT_S", "60"))

    @property
    def enabled(self):
        needs_key = self.provider == "mistral"          # hosted provider: no key means no LLM, fall back to rules
        return self.provider != "heuristic" and bool(self.base) and (bool(self.key) or not needs_key)

    def info(self):
        return {"provider": self.provider, "model": self.model if self.enabled else None, "enabled": self.enabled}

    async def complete_json(self, system, user):
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        body = {"model": self.model, "temperature": 0.1, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self.base}/chat/completions", json=body, headers=headers)
            r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                raise ValueError("LLM did not return JSON")
            return json.loads(m.group(0))
