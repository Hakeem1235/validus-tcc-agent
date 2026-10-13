"""Provider-agnostic LLM wrapper. Records model, real token usage and latency on the active trace.

Only three jobs use it: reading attachments/images (S1), extracting fields + classification fallback (S2),
and drafting replies (S7). It never decides an outcome.
"""
from __future__ import annotations

import json
import time
from typing import Any

from app import config
from app.trace import current


class LLMUnavailable(RuntimeError):
    pass


def available() -> bool:
    return config.LLM_PROVIDER not in ("none", "off", "") and bool(config.LLM_API_KEY)


_client = None


def _gemini():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=config.LLM_API_KEY,
                               http_options={"timeout": int(config.LLM_TIMEOUT_S * 1000)})
    return _client


def _record(model: str, usage: Any, purpose: str, ok: bool, t0: float) -> None:
    t = current()
    if t is None:
        return
    inp = getattr(usage, "prompt_token_count", 0) or 0 if usage else 0
    out = (getattr(usage, "candidates_token_count", 0) or 0) + (getattr(usage, "thoughts_token_count", 0) or 0) if usage else 0
    t.model_call(model, inp, out, purpose, ok, int((time.perf_counter() - t0) * 1000))


def generate(prompt: str, *, purpose: str, json_schema: dict | None = None, images: list[tuple[bytes, str]] | None = None,
             system: str | None = None, max_output_tokens: int = 2048) -> str:
    """Return model text (JSON text when json_schema is given). Raises LLMUnavailable on any failure."""
    if not available():
        raise LLMUnavailable("LLM not configured (set LLM_API_KEY)")
    if config.LLM_PROVIDER != "gemini":
        raise LLMUnavailable(f"provider {config.LLM_PROVIDER} not supported")
    from google.genai import types

    parts: list[Any] = []
    for data, mime in images or []:
        parts.append(types.Part.from_bytes(data=data, mime_type=mime))
    parts.append(prompt)
    cfg: dict[str, Any] = {"temperature": 0, "max_output_tokens": max_output_tokens}
    if system:
        cfg["system_instruction"] = system
    if json_schema is not None:
        cfg["response_mime_type"] = "application/json"
        cfg["response_json_schema"] = json_schema
    if config.LLM_MODEL.startswith("gemini-2.5"):
        cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    resp = None
    for attempt in range(config.LLM_RETRIES + 1):
        t0 = time.perf_counter()
        try:
            resp = _gemini().models.generate_content(model=config.LLM_MODEL, contents=parts,
                                                     config=types.GenerateContentConfig(**cfg))
            break
        except Exception as e:  # network, quota, auth, schema
            _record(config.LLM_MODEL, None, purpose, False, t0)
            transient = any(c in str(e) for c in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "504", "DEADLINE"))
            if not transient or attempt == config.LLM_RETRIES:
                raise LLMUnavailable(f"{type(e).__name__}: {str(e)[:300]}") from e
            time.sleep(min(2 ** attempt * 2, 20))
    _record(config.LLM_MODEL, getattr(resp, "usage_metadata", None), purpose, True, t0)
    text = resp.text or ""
    if not text:
        raise LLMUnavailable("empty response")
    return text


def generate_json(prompt: str, *, purpose: str, json_schema: dict, **kw) -> dict:
    text = generate(prompt, purpose=purpose, json_schema=json_schema, **kw)
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1]
    return json.loads(text)
