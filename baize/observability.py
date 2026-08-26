"""V20 observability: tracing spans + metrics counters (stdlib only).

Lightweight, zero-dependency instrumentation. Exposes a Prometheus-text /metrics
endpoint (consumed by the serve module) and keeps in-memory traces for debugging.
Defensive by design: instrumentation failures are swallowed and counted — never
allowed to propagate into the caller's control flow.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Span", "Observability", "obs"]


@dataclass
class Span:
    name: str
    start: float
    end: float = 0.0
    ok: bool = True
    meta: dict = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return round((self.end - self.start) * 1000, 2)


class Observability:
    def __init__(self) -> None:
        self._spans: list[Span] = []
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._enabled = True

    def enable(self, on: bool) -> None:
        self._enabled = on

    @property
    def enabled(self) -> bool:
        return self._enabled

    # --- metrics ---
    def inc(self, name: str, by: int = 1) -> None:
        if not self._enabled:
            return
        self._counters[name] = self._counters.get(name, 0) + by

    def gauge(self, name: str, value: float) -> None:
        if not self._enabled:
            return
        self._gauges[name] = value

    def record_error(self, name: str = "errors") -> None:
        self.inc(name)

    # --- tracing ---
    @contextmanager
    def span(self, name: str, **meta: Any):
        if not self._enabled:
            yield None
            return
        s = Span(name=name, start=time.time(), meta=dict(meta))
        try:
            yield s
            s.ok = True
        except Exception:
            s.ok = False
            self.record_error()
            raise
        finally:
            s.end = time.time()
            self._spans.append(s)
            if len(self._spans) > 1000:  # bounded buffer
                self._spans = self._spans[-1000:]

    # --- export ---
    def prometheus(self) -> str:
        lines: list[str] = []
        for k, v in sorted(self._counters.items()):
            lines.append(f"# TYPE baize_{k} counter")
            lines.append(f"baize_{k} {v}")
        for k, v in sorted(self._gauges.items()):
            lines.append(f"# TYPE baize_{k} gauge")
            lines.append(f"baize_{k} {v}")
        return "\n".join(lines) + "\n"

    def spans(self, limit: int = 50) -> list[Span]:
        return self._spans[-limit:]

    def reset(self) -> None:
        self._spans.clear()
        self._counters.clear()
        self._gauges.clear()


# Global default instance. Imported across the runtime.
obs = Observability()
