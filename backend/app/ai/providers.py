# -*- coding: utf-8 -*-
"""One request to one provider, returning JSON text and token counts. Nothing here decides anything.

Anthropic is called through its official SDK. OpenAI, xAI, DeepSeek and custom endpoints use the OpenAI-style
chat completions API; Gemini uses its own. Keys are passed in headers only and never appear in errors or logs.
"""
from __future__ import annotations

import json
import time

TIMEOUT = 45.0
# Models that can re-run a declined request on another model inside the same call (server-side fallbacks).
_FALLBACKS = {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
# Models that take `effort` (the current generation); a model typed in by hand is called without it.
_EFFORT = _FALLBACKS | {"claude-haiku-5-5", "claude-sonnet-5", "claude-opus-4-8", "claude-opus-4-7"}


class ProviderError(Exception):
    def __init__(self, message: str, retry: bool = False):
        super().__init__(message)
        self.message, self.retry = message, retry


def _b64(data: bytes) -> str:
    import base64
    return base64.standard_b64encode(data).decode("ascii")


def _anthropic(key, model, system, user, schema, timeout, image=None):
    import anthropic
    client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=1)
    content = user if image is None else [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(image)}},
        {"type": "text", "text": user}]
    kw = {"model": model, "max_tokens": 4096, "system": system, "messages": [{"role": "user", "content": content}],
          "output_config": {"format": {"type": "json_schema", "schema": schema}}}
    if model in _EFFORT:
        kw["output_config"]["effort"] = "low"          # a short, constrained judgement: low effort is enough
    try:
        if model in _FALLBACKS:
            r = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        else:
            r = client.messages.create(**kw)
    except anthropic.AuthenticationError:
        raise ProviderError("the key was refused")
    except anthropic.PermissionDeniedError:
        raise ProviderError("the key may not use this model")
    except anthropic.NotFoundError:
        raise ProviderError("unknown model")
    except anthropic.RateLimitError:
        raise ProviderError("rate limited by the provider", retry=True)
    except anthropic.BadRequestError as e:
        raise ProviderError(f"request refused: {str(getattr(e, 'message', e))[:160]}")
    except anthropic.APIStatusError as e:
        raise ProviderError(f"provider error {e.status_code}", retry=e.status_code >= 500)
    except anthropic.APIConnectionError:
        raise ProviderError("cannot reach the provider", retry=True)
    if r.stop_reason == "refusal":
        raise ProviderError("the model declined to answer")
    text = next((b.text for b in r.content if b.type == "text"), "")
    return text, r.usage.input_tokens or 0, r.usage.output_tokens or 0


def _http(url, headers, body, timeout):
    import httpx
    try:
        r = httpx.post(url, headers=headers, json=body, timeout=timeout)
    except httpx.TimeoutException:
        raise ProviderError("the provider did not answer in time", retry=True)
    except httpx.HTTPError:
        raise ProviderError("cannot reach the provider", retry=True)
    if r.status_code in (401, 403):
        raise ProviderError("the key was refused")
    if r.status_code == 404:
        raise ProviderError("unknown model or address")
    if r.status_code == 429:
        raise ProviderError("rate limited by the provider", retry=True)
    if r.status_code >= 400:
        raise ProviderError(f"provider error {r.status_code}", retry=r.status_code >= 500)
    try:
        return r.json()
    except ValueError:
        raise ProviderError("the provider sent something that is not JSON")


def _openai_style(base, key, model, system, user, timeout, image=None):
    content = user if image is None else [{"type": "text", "text": user},
                                          {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _b64(image)}}]
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "response_format": {"type": "json_object"}}
    d = _http(base.rstrip("/") + "/chat/completions", {"Authorization": f"Bearer {key}"}, body, timeout)
    try:
        text = d["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise ProviderError("unexpected answer from the provider")
    u = d.get("usage") or {}
    return text, u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def _gemini(base, key, model, system, user, timeout, image=None):
    parts = [{"text": user}] if image is None else [{"inline_data": {"mime_type": "image/png", "data": _b64(image)}}, {"text": user}]
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json"}}
    d = _http(f"{base.rstrip('/')}/models/{model}:generateContent", {"x-goog-api-key": key}, body, timeout)
    try:
        text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        raise ProviderError("unexpected answer from the provider")
    u = d.get("usageMetadata") or {}
    return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)


def call(p: dict, key: str, model: str, system: str, user: str, schema: dict, timeout: float = TIMEOUT,
         image: bytes | None = None) -> dict:
    """{text, tokens_in, tokens_out, seconds}. `image`: a PNG to look at (a small crop, never a whole page).
    Raises ProviderError."""
    t = time.time()
    hint = "\n\nReply with JSON matching: " + json.dumps(schema)
    if p["kind"] == "anthropic":
        text, a, b = _anthropic(key, model, system, user, schema, timeout, image)
    elif p["kind"] == "gemini":
        text, a, b = _gemini(p["base_url"], key, model, system, user + hint, timeout, image)
    else:
        text, a, b = _openai_style(p["base_url"], key, model, system, user + hint, timeout, image)
    return {"text": text, "tokens_in": a, "tokens_out": b, "seconds": round(time.time() - t, 2)}


def cost(p: dict, model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimated cost in USD from the prices entered for this provider (0 when unknown)."""
    price = (p.get("prices") or {}).get(model)
    if not price:
        return 0.0
    return round(tokens_in / 1e6 * price[0] + tokens_out / 1e6 * price[1], 6)


def test(p: dict, key: str, model: str) -> dict:
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    out = call(p, key, model, "You check that a connection works.", 'Answer {"ok": true}.', schema, timeout=30)
    try:
        ok = json.loads(out["text"]).get("ok") is True
    except (ValueError, AttributeError):
        ok = False
    return {"ok": ok, "seconds": out["seconds"]}
