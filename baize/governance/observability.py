"""Prometheus-compatible metrics, structured tracing, and performance profiling."""

from __future__ import annotations

# ===========================================================================
# Section: observability.py
# ===========================================================================

import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Span", "Observability", "obs"]

_PROM_NAME_RE = re.compile(r"[^a-zA-Z0-9_:]")


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
        self._lock = threading.RLock()
        self._spans: list[Span] = []
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._enabled = True

    def enable(self, on: bool) -> None:
        with self._lock:
            self._enabled = on

    @property
    def enabled(self) -> bool:
        return self._enabled

    # --- metrics ---
    def inc(self, name: str, by: int = 1) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + by

    def counter(self, name: str, default: int = 0) -> int:
        with self._lock:
            return self._counters.get(name, default)

    def gauge(self, name: str, value: float) -> None:
        if not self._enabled:
            return
        with self._lock:
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
            with self._lock:
                self._spans.append(s)
                if len(self._spans) > 1000:  # bounded buffer
                    self._spans = self._spans[-1000:]

    # --- export ---
    def prometheus(self) -> str:
        with self._lock:
            counters = sorted(self._counters.items())
            gauges = sorted(self._gauges.items())
        lines: list[str] = []
        for k, v in counters:
            metric = _PROM_NAME_RE.sub("_", f"baize_{k}")
            lines.append(f"# TYPE {metric} counter")
            lines.append(f"{metric} {v}")
        for k, v in gauges:
            metric = _PROM_NAME_RE.sub("_", f"baize_{k}")
            lines.append(f"# TYPE {metric} gauge")
            lines.append(f"{metric} {v}")
        return "\n".join(lines) + "\n"

    def spans(self, limit: int = 50) -> list[Span]:
        with self._lock:
            return list(self._spans[-limit:])

    def reset(self) -> None:
        with self._lock:
            self._spans.clear()
            self._counters.clear()
            self._gauges.clear()


# Global default instance. Imported across the runtime.
obs = Observability()

# ===========================================================================
# Section: perf.py
# ===========================================================================

import cProfile
import io
import pstats
import time
from pathlib import Path
from typing import Any, Callable

from ..codebase.arch_cache import get_arch_cache_stats, get_cached_symbol_graph
from ..core.config import ROOT, load_config
from ..core.llm import get_http_pool_stats
from ..knowledge.memory import recall as memory_recall
from ..knowledge.rag import build_corpus, retrieve
from ..codebase.repo_map import RepoMapGenerator
from ..knowledge.skills import load_index, search as skill_search
from ..execution.tools import default_registry

__all__ = [
    "measure_step",
    "profile_workspace",
]


def measure_step(name: str, fn: Callable[[], Any], repeat: int = 1) -> dict[str, Any]:
    """Execute ``fn`` ``repeat`` times and return honest wall-clock latency stats."""
    runs = max(1, int(repeat))
    t0 = time.perf_counter()
    for _ in range(runs):
        fn()
    total_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "name": name,
        "runs": runs,
        "total_ms": round(total_ms, 3),
        "avg_ms": round(total_ms / runs, 3),
    }


def profile_workspace(
    root_dir: str | Path | None = None,
    *,
    include_cprofile: bool = False,
) -> dict[str, Any]:
    """Profile core Baize subsystems on the target workspace and rank bottlenecks."""
    cfg = load_config()
    root = str(Path(root_dir or cfg.get("BAIZE_WORKSPACE_DIR", str(ROOT))).resolve())

    t_start = time.perf_counter()
    timings: list[dict[str, Any]] = []

    graph = get_cached_symbol_graph(root_dir=root, cfg=cfg)
    timings.append(measure_step("arch_cache.warm_lookup", lambda: get_cached_symbol_graph(root_dir=root, cfg=cfg), repeat=5))
    timings.append(measure_step("repo_map.pagerank_and_render", lambda: RepoMapGenerator(graph).generate_repo_map(max_symbols=40), repeat=3))
    timings.append(measure_step("rag.build_corpus_and_retrieve", lambda: retrieve("agent mcp tool", corpus=build_corpus(cfg=cfg)), repeat=3))
    timings.append(measure_step("skill_index.load_and_search", lambda: (load_index(cfg), skill_search("python", cfg=cfg)), repeat=3))
    timings.append(measure_step("memory.recall", lambda: memory_recall("agent", cfg=cfg, limit=20), repeat=5))
    timings.append(measure_step("tools.default_registry", default_registry, repeat=10))

    ranked = sorted(timings, key=lambda item: item["avg_ms"], reverse=True)
    result: dict[str, Any] = {
        "workspace": root,
        "files_indexed": graph.total_files_indexed,
        "unique_symbols": len(graph.symbols),
        "total_profile_ms": round((time.perf_counter() - t_start) * 1000.0, 3),
        "timings": timings,
        "top_bottlenecks": ranked[:3],
        "cache_stats": get_arch_cache_stats(),
        "http_pool_stats": get_http_pool_stats(),
    }

    if include_cprofile:
        pr = cProfile.Profile()
        pr.enable()
        RepoMapGenerator(graph).generate_repo_map(max_symbols=40)
        pr.disable()
        buf = io.StringIO()
        pstats.Stats(pr, stream=buf).sort_stats("cumtime").print_stats(12)
        result["cprofile_top"] = buf.getvalue()

    return result
