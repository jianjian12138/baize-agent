"""NO FAKE DONE gate, productized (P3-3). Zero runtime dependencies.

This is the single source of truth for "is this project honestly done":

* Manifest gate - every phase marked ``done`` must list evidence files that
  actually EXIST, are NON-EMPTY, and are NOT STALE (mtime within
  ``MANIFEST_STALE_SECONDS``). This closes risk #5 / #6: a phase cannot claim
  completion on a missing, empty, or ancient file (no stale fake green).
* Coverage gate - if the ``coverage`` dev package is installed we measure the
  REAL TOTAL and compare to ``TEST_COVERAGE_THRESHOLD``; otherwise we report
  ``unknown`` rather than pretending green.

All checks are fail-closed: any uncertainty is surfaced, never hidden.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import load_config

# Evidence older than this is treated as stale (a "done" claim on a week-old
# file is suspect - the work may have regressed since).
MANIFEST_STALE_SECONDS = 60 * 60 * 24 * 7

__all__ = ["check_manifest", "check_coverage", "run_gate",
           "MANIFEST_STALE_SECONDS"]


def check_manifest(manifest_path: str,
                   max_stale_seconds: int = MANIFEST_STALE_SECONDS,
                   now: float | None = None) -> tuple[bool, list[str]]:
    """Return (ok, problems). A 'done' phase's evidence must exist, be
    non-empty, and be fresh."""
    from .manifest import validate_manifest
    now = now if now is not None else time.time()
    path = Path(manifest_path)
    if not path.exists():
        return False, [f"manifest not found: {path}"]
    res = validate_manifest(path)
    if not res.ok:
        return False, [f"manifest invalid: {e}" for e in res.errors]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, [f"manifest unreadable: {exc}"]
    problems: list[str] = []
    base = path.parent
    for ph in data.get("phases", []):
        if ph.get("status") != "done":
            continue
        for ev in ph.get("evidence", []) or []:
            fp = Path(ev)
            if not fp.is_absolute():
                fp = base / ev
            if not fp.exists():
                problems.append(f"{ph['id']}: evidence MISSING: {ev}")
                continue
            if fp.stat().st_size == 0:
                problems.append(f"{ph['id']}: evidence EMPTY: {ev}")
                continue
            age = now - fp.stat().st_mtime
            if age > max_stale_seconds:
                problems.append(
                    f"{ph['id']}: evidence STALE "
                    f"({int(age // 86400)}d old): {ev}")
    return (not problems), problems


def check_coverage(data_file: str = ".coverage") -> dict:
    """Measure real coverage if possible; otherwise report unknown."""
    try:
        import coverage  # dev dependency only; never imported on the runtime
    except ImportError:
        return {"status": "unknown",
                "reason": "coverage package not installed"}
    if not Path(data_file).exists():
        return {"status": "unknown", "reason": f"no data file {data_file}"}
    try:
        threshold = int(load_config().get("TEST_COVERAGE_THRESHOLD", 85))
        cov = coverage.Coverage(data_file=data_file)
        cov.load()
        total = cov.report()
    except Exception as exc:  # defensive: measurement must never fake green
        return {"status": "unknown", "reason": str(exc)}
    ok = total >= threshold
    return {"status": "pass" if ok else "fail",
            "total": round(total, 1), "threshold": threshold}


def check_composition(cfg: dict | None = None) -> dict:
    """V22 honest check: the composition kernel and named modes must actually
    work - assemble the default runtime, validate every per-kind Protocol, and
    verify a mode bundle. This closes the "component swap + mode switch" path
    from the V22 plan with REAL execution (fail-closed)."""
    from .component import (
        CompositionKernel, Kind, Component, _KIND_PROTOCOLS, LoopStrategyProto)
    from .modes import VALID_MODES, resolve_mode
    try:
        rt = CompositionKernel(cfg).assemble()
        for k in Kind:
            inst = rt.get(k)
            if inst is None:
                return {"status": "fail", "detail": f"missing {k.value}"}
            if not isinstance(inst, _KIND_PROTOCOLS[k]):
                return {"status": "fail",
                        "detail": f"{k.value} fails {_KIND_PROTOCOLS[k].__name__}"}
        for m in VALID_MODES:
            b = resolve_mode({"BAIZE_MODE": m})
            assert b["autonomy"] and "loop" in b and "plan_mode" in b, m
            # F3: the mode's loop strategy must actually instantiate and
            # conform to LoopStrategyProto. A mode pointing at an unresolved or
            # non-conforming loop class must fail the gate (was fail-open).
            loop_name = b["loop"]
            from .agent import LOOP_STRATEGIES, get_loop_strategy
            if loop_name not in LOOP_STRATEGIES:
                return {"status": "fail",
                        "detail": f"mode {m} loop {loop_name!r} unknown"}
            try:
                loop_inst = get_loop_strategy(loop_name)
            except Exception as exc:
                return {"status": "fail",
                        "detail": f"mode {m} loop {loop_name!r} failed to "
                                  f"build: {exc}"}
            if not isinstance(loop_inst, LoopStrategyProto):
                return {"status": "fail",
                        "detail": f"mode {m} loop {loop_name!r} fails "
                                  f"{LoopStrategyProto.__name__}"}
        return {"status": "pass",
                "detail": f"{len(list(Kind))} kinds + {len(VALID_MODES)} modes"}
    except Exception as exc:  # defensive: never fake green
        return {"status": "fail", "detail": f"{type(exc).__name__}: {exc}"}


def run_gate(manifest_path: str = "baize.manifest.json",
             data_file: str = ".coverage",
             now: float | None = None) -> dict:
    man_ok, man_problems = check_manifest(manifest_path, now=now)
    cov = check_coverage(data_file)
    comp = check_composition()
    if not man_ok or cov["status"] == "fail" or comp["status"] == "fail":
        status = "fail"
    elif cov["status"] == "unknown":
        status = "unknown"
    else:
        status = "pass"
    return {
        "manifest_ok": man_ok,
        "manifest_problems": man_problems,
        "coverage": cov,
        "composition": comp,
        "overall": (man_ok and cov["status"] == "pass"
                    and comp["status"] == "pass"),
        "status": status,
    }
