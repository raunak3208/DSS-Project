"""Provider-agnostic LLM client. Everything speaks the OpenAI-style /chat/completions protocol, so swapping
Mistral for Ollama (or any compatible server) is an environment change, not a code change.

    LLM_PROVIDER=mistral        MISTRAL_API_KEY=...            (default when a key is present)
    LLM_PROVIDER=ollama         LLM_MODEL=llama3.2             (Ollama's OpenAI-compatible endpoint)
    LLM_PROVIDER=openai_compat  LLM_BASE_URL=... LLM_API_KEY=...
    LLM_PROVIDER=heuristic      (no LLM; deterministic reasoner only)
"""
import json, os, re
import httpx

DEFAULTS = {
    "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest"),
    "ollama": ("http://host.docker.internal:11434/v1", "llama3.2"),
    "openai_compat": ("http://localhost:8000/v1", "local-model"),
    "heuristic": ("", ""),
}


def _clean_env(val: str | None, default: str = "") -> str:
    if not val:
        return default
    # Remove any trailing inline comments (e.g. 'val # comment')
    clean = val.split("#")[0].strip()
    if (clean.startswith('"') and clean.endswith('"')) or (clean.startswith("'") and clean.endswith("'")):
        clean = clean[1:-1].strip()
    return clean if clean else default


class LLM:
    def __init__(self):
        raw_key = _clean_env(os.getenv("MISTRAL_API_KEY"))
        provider_env = _clean_env(os.getenv("LLM_PROVIDER"))

        # If provider is mistral but no API key was supplied, use heuristic rules
        if provider_env == "mistral" and not raw_key:
            self.provider = "heuristic"
        else:
            self.provider = provider_env or ("mistral" if raw_key else "heuristic")

        base_default, model_default = DEFAULTS.get(self.provider, ("", ""))
        self.base = _clean_env(os.getenv("LLM_BASE_URL")) or base_default
        self.model = _clean_env(os.getenv("LLM_MODEL")) or model_default
        self.key = _clean_env(os.getenv("LLM_API_KEY")) or raw_key

        try:
            self.timeout = float(_clean_env(os.getenv("LLM_TIMEOUT_S"), "60"))
        except (ValueError, TypeError):
            self.timeout = 60.0

    @property
    def enabled(self):
        if self.provider == "heuristic":
            return False
        if not self.base or not str(self.base).startswith(("http://", "https://")):
            return False
        if self.provider == "mistral" and not self.key:
            return False
        return True

    def info(self):
        return {
            "provider": self.provider if self.enabled else "heuristic",
            "model": self.model if self.enabled else None,
            "enabled": self.enabled,
        }

    async def complete_json(self, system, user):
        if not self.enabled:
            raise ValueError("LLM is not enabled; using rule-based reasoning.")
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        body = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
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
