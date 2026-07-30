"""V20 chaos engineering - deliberate fault injection to prove resilience.

Why this exists: V19 claimed defensive design but nothing ever verified it.
This module injects real failures (timeouts, malformed responses, disk errors)
so the retry paths, fallbacks and fail-closed gates are exercised for real.

Safety first - chaos is OFF unless explicitly enabled:
  1. BAIZE_CHAOS_ENABLED must be 1
  2. failure rate defaults to 0.0
  3. a fixed BAIZE_CHAOS_SEED makes every run reproducible

    from baize.chaos import Chaos
    chaos = Chaos(cfg)
    transport = chaos.wrap_transport(real_transport)   # may now fail
"""
from __future__ import annotations

import random

from .config import load_config
from .observability import obs

__all__ = ["ChaosError", "Chaos", "FAULTS"]

FAULTS = ("timeout", "http_500", "malformed_json", "empty_response",
          "connection_reset", "slow_response")


class ChaosError(Exception):
    """Raised by an injected fault. Callers must survive this."""


class Chaos:
    """Deterministic fault injector (seeded RNG = reproducible failures)."""

    def __init__(self, cfg: dict | None = None, faults: tuple | None = None):
        cfg = cfg or load_config()
        self.enabled = str(cfg.get("BAIZE_CHAOS_ENABLED", "0")).lower() in (
            "1", "true")
        try:
            self.rate = max(0.0, min(1.0, float(
                cfg.get("BAIZE_CHAOS_FAILURE_RATE", "0.0"))))
        except (TypeError, ValueError):
            self.rate = 0.0
        seed = cfg.get("BAIZE_CHAOS_SEED", "")
        self.rng = random.Random(seed) if seed else random.Random()
        self.faults = faults or FAULTS
        self.injected: list[str] = []

    @property
    def active(self) -> bool:
        return self.enabled and self.rate > 0.0

    def should_fail(self) -> bool:
        return self.active and self.rng.random() < self.rate

    def pick_fault(self) -> str:
        return self.rng.choice(list(self.faults))

    def maybe_fail(self, context: str = "") -> None:
        """Raise ChaosError with probability `rate`. No-op when disabled."""
        if not self.should_fail():
            return
        fault = self.pick_fault()
        self.injected.append(fault)
        obs.inc("chaos_faults_injected")
        obs.inc(f"chaos_fault_{fault}")
        raise ChaosError(f"injected fault '{fault}'"
                         + (f" at {context}" if context else ""))

    # --- wrappers -----------------------------------------------------------

    def wrap_transport(self, transport):
        """Wrap an LLM transport so it fails realistically under chaos."""
        def wrapped(*args, **kwargs):
            if self.should_fail():
                fault = self.pick_fault()
                self.injected.append(fault)
                obs.inc("chaos_faults_injected")
                obs.inc(f"chaos_fault_{fault}")
                if fault == "malformed_json":
                    return "{ this is not valid json"
                if fault == "empty_response":
                    return {}
                raise ChaosError(f"injected transport fault '{fault}'")
            return transport(*args, **kwargs)
        return wrapped

    def wrap_callable(self, fn, context: str = ""):
        """Generic wrapper: inject before delegating."""
        def wrapped(*args, **kwargs):
            self.maybe_fail(context or getattr(fn, "__name__", "call"))
            return fn(*args, **kwargs)
        return wrapped

    def report(self) -> dict:
        counts: dict[str, int] = {}
        for f in self.injected:
            counts[f] = counts.get(f, 0) + 1
        return {"enabled": self.enabled, "rate": self.rate,
                "total_injected": len(self.injected), "by_fault": counts}
