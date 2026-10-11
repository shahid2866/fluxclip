"""Tiny, dependency-free LLM client for Claude, OpenAI(-compatible) and Ollama.

Provider selection (``provider="auto"``):
  1. ANTHROPIC_API_KEY set  -> anthropic
  2. OPENAI_API_KEY set     -> openai   (honours OPENAI_BASE_URL: Groq, OpenRouter, LM Studio…)
  3. Ollama reachable       -> ollama
  4. otherwise              -> heuristic (no LLM, offline scoring)

Override models with FLUXCLIP_MODEL or the ``model`` argument.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .utils import FluxClipError, log

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.1",
}

PROVIDERS = ("auto", "anthropic", "openai", "ollama", "heuristic")


def _ollama_url() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def _ollama_up() -> bool:
    try:
        urllib.request.urlopen(_ollama_url() + "/api/tags", timeout=1.5)
        return True
    except Exception:
        return False


def resolve_provider(provider: str = "auto") -> str:
    provider = (provider or "auto").lower()
    if provider not in PROVIDERS:
        raise FluxClipError(f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}")
    if provider != "auto":
        return provider
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if _ollama_up():
        return "ollama"
    return "heuristic"


def _post(url: str, payload: dict, headers: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise FluxClipError(f"LLM request failed ({e.code}): {detail}") from e


def complete(system: str, user: str, provider: str = "auto", model: str | None = None,
             max_tokens: int = 4000) -> str:
    """Send one prompt and return the text reply."""
    provider = resolve_provider(provider)
    model = model or os.environ.get("FLUXCLIP_MODEL") or DEFAULT_MODELS.get(provider)
    log.info("Asking %s (%s) to find highlights…", provider, model)

    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise FluxClipError("ANTHROPIC_API_KEY is not set.")
        base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
        data = _post(f"{base}/v1/messages", {
            "model": model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}],
        }, {"x-api-key": key, "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in data.get("content", []))

    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        data = _post(f"{base}/chat/completions", {
            "model": model, "max_tokens": max_tokens, "temperature": 0.4,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }, {"Authorization": f"Bearer {key}"} if key else {})
        return data["choices"][0]["message"]["content"]

    if provider == "ollama":
        data = _post(f"{_ollama_url()}/api/chat", {
            "model": model, "stream": False, "format": "json",
            "options": {"temperature": 0.4, "num_ctx": 16384},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }, {}, timeout=900)
        return data["message"]["content"]

    raise FluxClipError("The heuristic provider does not call an LLM.")


def extract_json(text: str):
    """Pull the first JSON object/array out of a model reply (tolerates ```json fences)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("[", "]"), ("{", "}")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise FluxClipError("Could not parse JSON from the model's reply:\n" + text[:400])
