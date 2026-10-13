"""Per-request trace collector (S8). Bound to a contextvar so tools record themselves."""
from __future__ import annotations

import contextvars
import functools
import time
from typing import Any, Callable

from app.config import price_for

_current: contextvars.ContextVar["TraceCollector | None"] = contextvars.ContextVar("trace", default=None)


class TraceCollector:
    def __init__(self) -> None:
        self.model_calls: list[dict] = []
        self.tools_called: list[str] = []
        self.tool_log: list[dict] = []
        self.documents_used: list[dict] = []
        self.started = time.perf_counter()

    # --- binding
    def __enter__(self) -> "TraceCollector":
        self._token = _current.set(self)
        return self

    def __exit__(self, *exc) -> None:
        _current.reset(self._token)

    # --- recording
    def model_call(self, model: str, input_tokens: int, output_tokens: int, purpose: str, ok: bool = True,
                   latency_ms: int | None = None) -> None:
        self.model_calls.append({"model": model, "input_tokens": int(input_tokens or 0),
                                 "output_tokens": int(output_tokens or 0), "purpose": purpose, "ok": ok,
                                 "latency_ms": latency_ms})

    def tool(self, name: str, args: dict | None = None, hit: Any = None) -> None:
        if name not in self.tools_called:
            self.tools_called.append(name)
        self.tool_log.append({"tool": name, "args": args or {}, "found": hit})

    def document(self, document: str, version: str) -> None:
        d = {"document": document, "version": version}
        if d not in self.documents_used:
            self.documents_used.append(d)

    def cost_usd(self) -> float:
        total = 0.0
        for c in self.model_calls:
            pin, pout = price_for(c["model"])
            total += c["input_tokens"] / 1e6 * pin + c["output_tokens"] / 1e6 * pout
        return round(total, 6)

    def to_contract(self) -> dict:
        return {
            "model_calls": [{"model": c["model"], "input_tokens": c["input_tokens"], "output_tokens": c["output_tokens"],
                             "purpose": c["purpose"]} for c in self.model_calls],
            "tools_called": list(self.tools_called),
            "documents_used": list(self.documents_used),
            "cost_usd": self.cost_usd(),
            "latency_ms": int((time.perf_counter() - self.started) * 1000),
            "tool_calls": self.tool_log,
        }


def current() -> TraceCollector | None:
    return _current.get()


def tool(name: str) -> Callable:
    """Decorator: record a tool invocation (name, args, whether it returned data) on the active trace."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            out = fn(*args, **kwargs)
            t = current()
            if t is not None:
                shown = {k: v for k, v in kwargs.items()}
                if args:
                    shown["args"] = [a for a in args if isinstance(a, (str, int, float))]
                t.tool(name, shown, bool(out) if not isinstance(out, (int, float)) else out)
            return out

        return wrapper

    return deco
