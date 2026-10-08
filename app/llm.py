"""One chat interface over Groq (hosted) and Ollama (local dev).

Both expose an OpenAI-compatible /chat/completions endpoint, so switching is
just base URL + key + model, picked by LLM_PROVIDER. Responses are cached in
MongoDB keyed by a hash of the full request.
"""

import json
from typing import Any

import httpx

from app.cache import Cache, make_key
from app.config import Settings, get_settings


class LLMError(Exception):
    pass


class LLMRateLimited(LLMError):
    pass


def provider_config(s: Settings) -> tuple[str, dict[str, str], str]:
    """(url, headers, model) for the active provider."""
    if s.llm_provider == "groq":
        if not s.groq_api_key:
            raise LLMError("GROQ_API_KEY is not set")
        return (
            "https://api.groq.com/openai/v1/chat/completions",
            {"Authorization": f"Bearer {s.groq_api_key}"},
            s.groq_model,
        )
    return f"{s.ollama_url.rstrip('/')}/v1/chat/completions", {}, s.ollama_model


REASONING_MODELS = ("gpt-oss", "qwen3", "deepseek-r1")
REASONING_TOKEN_BUDGET = 1500  # extra output tokens a reasoning model may spend thinking


def is_reasoning_model(model: str) -> bool:
    return any(tag in model.lower() for tag in REASONING_MODELS)


class LLM:
    def __init__(self, cache: Cache, settings: Settings | None = None, http: httpx.AsyncClient | None = None):
        self.s = settings or get_settings()
        self.cache = cache
        self.http = http or httpx.AsyncClient(timeout=60)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float = 0.3,
        max_tokens: int = 800,
    ) -> str:
        url, headers, model = provider_config(self.s)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if is_reasoning_model(model):
            # Thinking tokens count against max_tokens; without extra budget a short
            # call (e.g. a 60-token title) can come back empty.
            payload["max_tokens"] = max_tokens + REASONING_TOKEN_BUDGET
            if self.s.llm_provider == "groq" and "gpt-oss" in model.lower():
                payload["reasoning_effort"] = self.s.groq_reasoning_effort

        key = make_key("llm", {"p": self.s.llm_provider, **payload})
        if (hit := await self.cache.get(key)) is not None:
            return hit

        try:
            resp = await self.http.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise LLMError(f"{self.s.llm_provider} unreachable: {e}") from e
        if resp.status_code == 429:
            raise LLMRateLimited(f"{self.s.llm_provider} rate limit reached, try again in a minute")
        if resp.status_code >= 400:
            raise LLMError(f"{self.s.llm_provider} error ({resp.status_code}): {resp.text[:300]}")
        text = (resp.json()["choices"][0]["message"].get("content") or "").strip()
        if not text:
            raise LLMError(f"{model} returned an empty answer (likely ran out of tokens while reasoning)")
        await self.cache.set(key, text, self.s.ttl_llm)
        return text

    async def chat_json(self, messages: list[dict[str, str]], **kw: Any) -> dict:
        text = await self.chat(messages, json_mode=True, **kw)
        try:
            return parse_json(text)
        except ValueError as e:
            raise LLMError(f"model did not return valid JSON: {text[:200]}") from e

    async def aclose(self) -> None:
        await self.http.aclose()


def parse_json(text: str) -> dict:
    """Parse a JSON object, tolerating code fences or chatter around it."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found")
        return json.loads(text[start : end + 1])
