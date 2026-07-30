"""V20 benchmark harness - deterministic self-checks over core subsystems.

Runs real micro-benchmarks with zero network access:
  - vector: index+search latency over a synthetic corpus
  - rag: corpus build + retrieval round-trip
  - memory: log/recall throughput
  - graph: triple add/query round-trip

Each case returns {name, ok, ms, detail}. `run_all()` aggregates a report.
This is the reserved seat for future agent-task benchmarks (SWE-bench style
harness can plug in via register()) - the runner interface is final.
"""
from __future__ import annotations

import shutil
import tempfile
import time

from .config import load_config

__all__ = ["register", "run_all", "CASES"]

CASES: dict = {}


def register(name: str):
    """Decorator: register a benchmark case (name -> fn(cfg) -> detail str)."""
    def deco(fn):
        CASES[name] = fn
        return fn
    return deco


@register("vector")
def _bench_vector(cfg: dict) -> str:
    from .vector import TfidfIndex
    idx = TfidfIndex()
    for i in range(200):
        idx.add(f"d{i}", f"document {i} about topic{i % 20} and deploy plan")
    idx.build()
    hits = idx.search("deploy plan topic3", top_k=5)
    assert hits, "vector search returned no hits"
    return f"200 docs indexed, top hit {hits[0]['id']} ({hits[0]['score']})"


@register("rag")
def _bench_rag(cfg: dict) -> str:
    from . import rag
    corpus = rag.build_corpus(cfg)
    hits = rag.retrieve("skill", cfg=cfg, corpus=corpus)
    return f"corpus={len(corpus)} docs, retrieve('skill') -> {len(hits)} hits"


@register("memory")
def _bench_memory(cfg: dict) -> str:
    from . import memory as memory_mod
    for i in range(20):
        memory_mod.log_event(f"bench event {i}", tags=["bench"], cfg=cfg)
    hits = memory_mod.recall("bench event", cfg=cfg, limit=50)
    assert len(hits) >= 20, f"expected >=20 recalls, got {len(hits)}"
    return f"20 events logged, {len(hits)} recalled"


@register("graph")
def _bench_graph(cfg: dict) -> str:
    from . import graph
    graph.add("baize", "version", "20", cfg=cfg)
    graph.add("baize", "depends_on", "stdlib-only", cfg=cfg)
    hits = graph.query(subject="baize", cfg=cfg)
    assert len(hits) >= 2, f"expected >=2 triples, got {len(hits)}"
    return f"{len(hits)} triples for node 'baize'"


def run_all(cfg: dict | None = None) -> dict:
    """Run every registered case; never raises - failures are reported.

    Side-effect free by design: unless the caller injects a cfg, benchmarks
    run against an ephemeral persistence dir that is deleted afterwards -
    a benchmark must never pollute the user's real memory or graph.
    """
    tmp = None
    if cfg is None:
        cfg = dict(load_config())
        tmp = tempfile.mkdtemp(prefix="baize_bench_")
        cfg["BAIZE_PERSISTENCE_DIR"] = tmp
    results = []
    for name, fn in CASES.items():
        t0 = time.perf_counter()
        try:
            detail = fn(cfg)
            ok = True
        except Exception as exc:  # defensive: report, don't crash the run
            detail = f"{type(exc).__name__}: {exc}"
            ok = False
        results.append({"name": name, "ok": ok,
                        "ms": round((time.perf_counter() - t0) * 1000, 1),
                        "detail": detail})
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(1 for r in results if r["ok"])
    return {"total": len(results), "passed": passed,
            "all_ok": passed == len(results), "cases": results}
