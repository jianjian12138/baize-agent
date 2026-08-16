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

import json
import shutil
import tempfile
import time
from pathlib import Path

from .config import load_config

__all__ = ["register", "run_all", "CASES"]

CASES: dict = {}

# Fixed epoch for deterministic scheduling benchmarks.
NOW = 1_600_000_000.0


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


# --- P1-P3 end-to-end capability benchmarks (real execution, real asserts) ---


@register("subagent_isolation")
def _bench_subagent(cfg: dict) -> str:
    """A sub-agent's scoped tool registry must not leak disallowed tools."""
    from .subagent import load_subagent
    d = Path(tempfile.mkdtemp())
    (d / "research.agent").write_text(
        "---\nname: research\n"
        "tools:\n  - read_file\n  - list_dir\n"
        "disallowedTools:\n  - bash\n"
        "model: test\n---\nDo research.\n", encoding="utf-8")
    defn = load_subagent(d / "research.agent")
    eff = defn.effective_tools()
    assert "read_file" in eff and "list_dir" in eff, eff
    reg = defn.registry()
    assert "bash" not in reg.names(), "scoped registry leaked disallowed tool"
    return f"scoped tools={eff}, registry size={len(reg.names())}"


@register("skill_self_evolve")
def _bench_skill(cfg: dict) -> str:
    """The honest rubric must accept a valid draft and reject a dependency-
    hiding one (no fake green)."""
    from .skill_runner import verify_skill_draft
    good = {"name": "demo_skill",
            "steps": [{"tool": "read_file", "args": {"path": "x"}}],
            "dependencies": []}
    ok, reasons = verify_skill_draft(good)
    assert ok, f"valid draft rejected: {reasons}"
    bad = {"name": "bad", "steps": [{"tool": "read_file", "args": {}}]}
    ok2, _ = verify_skill_draft(bad)
    assert not ok2, "draft missing dependencies wrongly accepted"
    return "verify accepted valid, rejected missing-dependency draft"


@register("automation_fire")
def _bench_automation(cfg: dict) -> str:
    """A recurring interval task must become due and actually fire."""
    from . import automations as a
    d = Path(tempfile.mkdtemp()) / "a.json"
    store = a.AutomationStore(d)
    store.save(a.AutomationSpec(id="t", schedule_type="recurring",
                                rrule="interval:5",
                                created_at=a._to_iso(NOW - 100)))
    sched = a.AutomationScheduler(store=store, clock=lambda: NOW)
    assert [s.id for s in sched.due_now()] == ["t"]
    fired: list[str] = []
    sched.runner = lambda spec: fired.append(spec.id) or {"ok": True}
    sched.tick()
    assert "t" in fired, "scheduled task did not fire"
    return f"interval task fired (last_run={store.get('t').last_run})"


@register("session_fork_compress")
def _bench_session(cfg: dict) -> str:
    """Fork a session and extractively compress it, asserting real token math."""
    from .agent import Session
    from . import sessions as s_mod
    d = Path(tempfile.mkdtemp()) / "sessions"
    s = Session(cfg={"BAIZE_SESSIONS_DIR": str(d)})
    s.append({"role": "user", "content": "goal"})
    s.append({"role": "assistant", "content": "x" * 500})
    new = s_mod.fork_session(s.id, 1, cfg={"BAIZE_SESSIONS_DIR": str(d)})
    rep = s_mod.compress_session(s.id, cfg={"BAIZE_SESSIONS_DIR": str(d)})
    assert rep["after_tokens"] <= rep["before_tokens"]
    assert rep["summary"]["total_messages"] == 2
    return (f"fork={new[:8]}, compressed "
            f"{rep['before_tokens']}->{rep['after_tokens']} tokens")


@register("multi_provider_parse")
def _bench_providers(cfg: dict) -> str:
    """Provider detection + endpoint routing must be correct for all three."""
    from .llm import _infer_provider, _endpoint, ModelSpec
    assert _infer_provider("http://localhost:11434") == "ollama"
    assert _infer_provider("https://api.anthropic.com") == "anthropic"
    assert _infer_provider("http://x/v1") == "openai"
    spec = ModelSpec(name="m", base_url="http://x/v1", api_key="k")
    assert _endpoint(spec) == "http://x/v1/chat/completions"
    return "provider inference + endpoint routing verified (openai/anthropic/ollama)"


@register("plan_mode_block")
def _bench_plan(cfg: dict) -> str:
    """Supervised autonomy must block dangerous tools, allow read-only."""
    from .autonomy import AutonomyPolicy
    pol = AutonomyPolicy(level="supervised")
    ok_bash, _ = pol.allow("bash", {"command": "rm -rf /"})
    assert not ok_bash, "supervised must block bash"
    ok_read, _ = pol.allow("read_file", {"path": "x"})
    assert ok_read, "supervised allows read-only"
    return "supervised blocks bash, allows read-only"


@register("manifest_gate")
def _bench_manifest(cfg: dict) -> str:
    """NO FAKE DONE: a done phase WITH evidence validates; a done phase
    WITHOUT evidence is rejected (the gate must be real, not cosmetic)."""
    from .manifest import validate_manifest
    d = Path(tempfile.mkdtemp())
    (d / "main.py").write_text("print('hello')\n", encoding="utf-8")
    good = d / "good.manifest.json"
    good.write_text(json.dumps({
        "project": "demo", "version": "1.0.0",
        "phases": [{"id": "P1", "name": "build", "status": "done",
                    "evidence": ["main.py"]}]}), encoding="utf-8")
    res_ok = validate_manifest(good)
    assert res_ok.ok, f"valid manifest rejected: {res_ok.errors}"

    bad = d / "bad.manifest.json"
    bad.write_text(json.dumps({
        "project": "demo", "version": "1.0.0",
        "phases": [{"id": "P1", "name": "build", "status": "done",
                    "evidence": []}]}), encoding="utf-8")
    res_bad = validate_manifest(bad)
    assert not res_bad.ok, "done-without-evidence must be rejected"
    return f"gate accepts valid, rejects done-without-evidence ({len(res_ok.warnings)} warnings)"


@register("memory_compress")
def _bench_memcompress(cfg: dict) -> str:
    """Old daily logs must be distilled into notes.md (real file ops)."""
    from . import memory as mem
    d = Path(tempfile.mkdtemp())
    ccfg = {"BAIZE_PERSISTENCE_DIR": str(d)}
    logs = d / "logs"
    logs.mkdir()
    (logs / "2020-01-01.jsonl").write_text(
        json.dumps({"ts": "2020-01-01T00:00:00", "text": "old event",
                    "tags": ["x"]}) + "\n", encoding="utf-8")
    rep = mem.compress(days=30, cfg=ccfg)
    assert rep["compressed_files"] >= 1, "expected a compressed file"
    assert rep["events_distilled"] >= 1
    return f"compressed {rep['compressed_files']} file(s), {rep['events_distilled']} events"


@register("public_benchmarks")
def _bench_public(cfg: dict) -> str:
    """Honest coverage map: every entry must carry a valid status and we must
    NOT falsely claim a score on benchmarks baize does not run."""
    from . import bench_public as bp
    rep = bp.coverage_report()
    assert rep["benchmarks"], "no benchmark entries"
    for b in rep["benchmarks"]:
        assert b["status"] in bp.VALID_STATUSES, f"bad status: {b}"
    c = rep["counts"]
    return (f"{c['covered']} covered / {c['partial']} partial / "
            f"{c['not_run']} not_run (honest)")


@register("composition_kernel")
def _bench_composition(cfg: dict) -> str:
    """V22 #95: the composition kernel must assemble all 9 default components,
    each satisfying its per-kind Protocol, and an explicit override must
    actually swap the resolved instance (no fake green)."""
    from .component import (CompositionKernel, Kind, Component,
                            _KIND_PROTOCOLS)

    rt = CompositionKernel(cfg).assemble()
    for k in Kind:
        inst = rt.get(k)
        assert inst is not None, f"missing default component {k.value}"
        assert isinstance(inst, _KIND_PROTOCOLS[k]), \
            f"{k.value} fails {_KIND_PROTOCOLS[k].__name__}"

    # explicit override really swaps the resolved instance
    class _Sentinel:
        def run(self, *a, **k):
            return "sentinel"

    k2 = CompositionKernel(cfg)
    k2.components[Kind.SANDBOX] = Component(
        Kind.SANDBOX, "override", lambda c: _Sentinel(), explicit=True)
    assert isinstance(k2.assemble().get(Kind.SANDBOX), _Sentinel)
    return (f"all {len(list(Kind))} kinds assembled + protocol-checked; "
            f"explicit override swap verified")


@register("mode_switch")
def _bench_mode(cfg: dict) -> str:
    """V22 #97: named modes resolve to distinct, authoritative bundles."""
    from .modes import VALID_MODES, resolve_mode
    bundles = {m: resolve_mode({"BAIZE_MODE": m}) for m in VALID_MODES}
    assert bundles["eval"]["loop"] == "programmatic"
    assert bundles["safe-review"]["plan_mode"] is True
    # scalar slider fallback when no mode is selected
    fb = resolve_mode({"BAIZE_AUTONOMY": "autonomous", "BAIZE_PLAN_MODE": "0"})
    assert fb["autonomy"] == "autonomous"
    # BAIZE_MODE authority overrides the scalar sliders
    auth = resolve_mode({"BAIZE_MODE": "safe-review",
                         "BAIZE_AUTONOMY": "autonomous"})
    assert auth["autonomy"] == "supervised"
    return (f"{len(VALID_MODES)} modes resolved (eval->programmatic, "
            f"safe-review->plan); authority verified")


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
