"""Thin OpenAI client wrapper: chat completions, structured JSON, embeddings."""
from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from . import config

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def chat(
    *,
    system: str,
    user: str,
    history: list[dict[str, str]] | None = None,
    model: str | None = None,
    json_mode: bool = False,
    max_tokens: int | None = None,
    temperature: float = 0.2,
) -> str:
    """One-shot chat completion. Returns the assistant message content as a string."""
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user})

    kwargs: dict[str, Any] = {
        "model": model or config.OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    resp = client().chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def chat_json(**kwargs: Any) -> dict[str, Any]:
    """Convenience: chat() with json_mode=True, parsed into a dict."""
    kwargs["json_mode"] = True
    raw = chat(**kwargs)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw, "_parse_error": True}


def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Return embeddings for a list of input strings."""
    if not texts:
        return []
    resp = client().embeddings.create(
        model=model or config.OPENAI_EMBED_MODEL,
        input=texts,
    )
    return [d.embedding for d in resp.data]
