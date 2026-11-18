"""Runtime Performance Profiler & Bottleneck Diagnostics (pure Python stdlib).

Runs real, non-destructive measurements over workspace indexing, PageRank
skeleton generation, RAG/skill lookup, memory recall, and registry construction,
and gathers live process cache + HTTP connection pool telemetry.
"""
from __future__ import annotations

import cProfile
import io
import pstats
import time
from pathlib import Path
from typing import Any, Callable

from .arch_cache import get_arch_cache_stats, get_cached_symbol_graph
from .config import ROOT, load_config
from .llm import get_http_pool_stats
from .memory import recall as memory_recall
from .rag import build_corpus, retrieve
from .repo_map import RepoMapGenerator
from .skill_index import load_index, search as skill_search
from .tools import default_registry

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
