"""NO FAKE DONE gate, productized (P3-3, V26-C5). Zero runtime dependencies.

This is the single source of truth for "is this project honestly done":

* Manifest gate - every phase marked ``done`` must list evidence files that
  actually EXIST and are NON-EMPTY. Age is checked only where age means
  something: an evidence file that git tracks has its mtime rewritten by every
  checkout, so ``now - mtime`` measures the checkout, not the file. Tracked
  evidence is therefore reported as "freshness not judged" instead of being
  judged. (It used to be judged, which produced ``evidence STALE (28d old):
  baize/subagent.py`` - the *implementation* of the phase - on a healthy tree,
  while a fresh clone passed the same check vacuously. All 173 evidence entries
  in this repo are tracked, so the rule could only ever fire where it was wrong.)
  Existence and non-emptiness stay hard failures; those are sound.
* Coverage gate - if the ``coverage`` dev package is installed we measure the
  REAL TOTAL and compare to ``TEST_COVERAGE_THRESHOLD``; otherwise we report
  ``unknown`` rather than pretending green.
* Loop Integrity gate (V26-C5) - verifies that run ledgers exist and match
  manifest claims; unverified tasks and unhandled failures block fake completion.

All checks are fail-closed: any uncertainty is surfaced, never hidden.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from .config import load_config, ROOT

# Evidence older than this is treated as stale - but only for evidence git does
# not track. For a tracked file the mtime is written by checkout, so this
# threshold is never consulted; see `check_manifest`. A "done" claim on a
# week-old *artifact* is still suspect; a week-old *source file* is normal.
MANIFEST_STALE_SECONDS = 60 * 60 * 24 * 7

# The sources a coverage percentage claims to describe. Kept here, next to the
# staleness rule itself, so the CLI gate and scripts/coverage_gate.py cannot
# drift apart on what "the tree" means.
COVERAGE_SOURCE_DIRS = ("baize", "tests")

__all__ = ["check_manifest", "check_coverage", "check_loop_integrity",
           "run_gate", "MANIFEST_STALE_SECONDS", "COVERAGE_SOURCE_DIRS",
           "newest_source", "newest_source_mtime", "coverage_data_is_stale",
           "resolve_coverage_data_file", "tracked_paths"]


def newest_source(root: Path | None = None) -> tuple[float, Path | None]:
    """``(newest mtime, which file)`` over ``COVERAGE_SOURCE_DIRS``.

    The decision and the message must come from the same scan, or a caller can
    name a file it did not actually compare against.
    """
    root = ROOT if root is None else Path(root)
    newest, which = 0.0, None
    for sub in COVERAGE_SOURCE_DIRS:
        d = root / sub
        if not d.is_dir():
            continue
        for path in d.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                m = path.stat().st_mtime
            except OSError:
                continue
            if m > newest:
                newest, which = m, path
    return newest, which


def newest_source_mtime(root: Path | None = None) -> float:
    """Newest mtime among the sources a coverage number claims to describe.

    ``0.0`` means "nothing to compare against", which callers must read as
    *cannot judge* rather than *everything is fresh*.
    """
    return newest_source(root)[0]


def coverage_data_is_stale(data_file: Path | str,
                           root: Path | None = None) -> str | None:
    """Why ``data_file`` cannot describe the tree at ``root``, or ``None``.

    A data file older than the newest source file was measured against a tree
    that no longer exists, so the percentage it holds is not a statement about
    the current code. Equal timestamps pass: coverage writes its data after the
    sources are read, and coarse filesystem clocks make a same-second write
    normal.

    This rule lives here, not in each caller, because it was independently
    rediscovered twice: scripts/coverage_gate.py learned it after reporting
    83.6% FAILED from an hour-old file, and ``check_coverage`` was still reading
    a stale ``.coverage`` to report 83.5% FAILED against a tree that measured
    86.6% PASS.
    """
    data_file = Path(data_file)
    root = ROOT if root is None else Path(root)
    newest, which = newest_source(root)
    if newest == 0.0:
        return None  # nothing to compare against - cannot judge, so do not block
    try:
        written = data_file.stat().st_mtime
    except OSError as exc:
        return f"cannot stat data file {str(data_file)!r}: {exc}"
    if written >= newest:
        return None
    behind = newest - written
    newest_name = str(which.relative_to(root)) if which else "?"
    return (
        f"data file {str(data_file)!r} was written {behind:.0f}s before the "
        f"newest source file ({newest_name}); it describes an older tree"
    )


def resolve_coverage_data_file(explicit: str | None = None,
                               cfg: dict | None = None) -> str:
    """Explicit argument > ``COVERAGE_FILE`` > ``BAIZE_COVERAGE_DATA`` > default.

    Honouring ``COVERAGE_FILE`` is not a nicety: ``coverage run`` honours it, so
    a gate that does not will happily measure a different, older file than the
    run it is supposed to be checking.
    """
    if explicit:
        return explicit
    from_env = os.environ.get("COVERAGE_FILE")
    if from_env:
        return from_env
    return (cfg or {}).get("BAIZE_COVERAGE_DATA") or ".coverage"


def tracked_paths(root: Path | str | None = None) -> set[str] | None:
    """Repo-relative paths tracked by git, or ``None`` when that cannot be known.

    This exists so a caller can ask whether a file's mtime means anything. Git
    rewrites the mtime of every tracked file on checkout, so for a tracked file
    ``now - mtime`` measures *when you cloned*, not when the file was produced.
    A check built on that number therefore reports the checkout age and calls it
    the file's age - green in a fresh clone (where CI runs) and red in a
    long-lived working copy, which is the opposite of useful.

    Returns ``None`` when git is unavailable, the path is not a repository, or
    git fails - "cannot judge", never "assume stale".
    """
    git = shutil.which("git")
    if git is None:
        return None
    base = ROOT if root is None else Path(root)
    # Routed through proc.run, not subprocess.run: on a timeout the whole process
    # tree has to be killed, and `subprocess.run(timeout=)` only kills the direct
    # child. tests/test_proc_timeout.py caught this file doing it the direct way
    # - the repo's own gate, working on a change I made.
    from .proc import run as _proc_run
    try:
        res = _proc_run([git, "-c", "core.quotepath=false", "ls-files", "-z"],
                        timeout=60, cwd=str(base))
    except OSError:
        # Popen raises when cwd is unusable or the binary vanished between the
        # `which` call and here. Cannot judge, so say so rather than assume.
        return None
    if res.timed_out or res.returncode != 0:
        return None
    # -z plus quotepath=false: a plain `read` would split on the quotes git adds
    # around non-ASCII paths, silently dropping exactly those files.
    return {p for p in res.stdout.split("\0") if p}


def check_manifest(manifest_path: str,
                   max_stale_seconds: int = MANIFEST_STALE_SECONDS,
                   now: float | None = None,
                   notes: list[str] | None = None) -> tuple[bool, list[str]]:
    """Return (ok, problems). A 'done' phase's evidence must exist, be
    non-empty, and - when its age can be trusted - be fresh.

    The freshness dimension only applies to evidence git does *not* track. For
    tracked evidence the mtime is written by checkout, so it says nothing about
    the file; measuring it produced a confident "evidence STALE (28d old)" for
    `baize/subagent.py`, the *implementation* of the phase, on a tree that was
    perfectly healthy. All 173 evidence entries in this repo are tracked, so
    that rule could only ever fire where it was wrong and never where CI runs.
    Tracked evidence is recorded in ``notes`` instead of being judged.
    """
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
    tracked = tracked_paths(base)
    unjudged_tracked: list[str] = []
    unjudged_no_git: list[str] = []
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
            if age <= max_stale_seconds:
                continue
            rel = _repo_relative(fp, base)
            if tracked is None:
                unjudged_no_git.append(ev)
                continue
            if rel is not None and rel in tracked:
                unjudged_tracked.append(ev)
                continue
            problems.append(
                f"{ph['id']}: evidence STALE "
                f"({int(age // 86400)}d old): {ev}")
    if notes is not None:
        # Aggregate: one line per reason, not one per file. 173 evidence entries
        # would otherwise bury the verdict they are a footnote to.
        if unjudged_tracked:
            notes.append(
                f"{len(unjudged_tracked)} evidence file(s) are older than "
                f"{int(max_stale_seconds // 86400)}d AND tracked by git, so their mtime "
                f"records the checkout rather than the file - freshness not judged "
                f"(e.g. {unjudged_tracked[0]})")
        if unjudged_no_git:
            notes.append(
                f"{len(unjudged_no_git)} evidence file(s) could not be judged: git is "
                f"unavailable, so their mtime cannot be trusted as an age")
    return (not problems), problems


def _repo_relative(fp: Path, base: Path) -> str | None:
    """``fp`` relative to ``base`` in git's slash form, or None if outside."""
    try:
        rel = fp.resolve().relative_to(base.resolve())
    except (ValueError, OSError):
        return None
    return str(rel).replace("\\", "/")


def check_coverage(data_file: str | None = None,
                   cfg: dict | None = None) -> dict:
    """Measure real coverage if possible; otherwise report unknown.

    A *stale* data file is ``unknown``, not ``fail``: reporting a percentage
    from an older tree as a verdict is the same lie as reporting green from one.
    """
    try:
        import coverage  # dev dependency only; never imported on the runtime
    except ImportError:
        return {"status": "unknown",
                "reason": "coverage package not installed"}
    data_file = resolve_coverage_data_file(data_file, cfg)
    if not Path(data_file).exists():
        return {"status": "unknown", "reason": f"no data file {data_file}"}
    stale = coverage_data_is_stale(data_file)
    if stale is not None:
        return {"status": "unknown",
                "reason": f"cannot verify - {stale}",
                "data_file": data_file}
    try:
        threshold = int(load_config().get("TEST_COVERAGE_THRESHOLD", 85))
        cov = coverage.Coverage(data_file=data_file)
        cov.load()
        total = cov.report()
    except Exception as exc:  # defensive: measurement must never fake green
        return {"status": "unknown", "reason": str(exc)}
    ok = total >= threshold
    return {"status": "pass" if ok else "fail",
        "total": round(total, 1), "threshold": threshold,
        "data_file": data_file}


def check_composition(cfg: dict | None = None) -> dict:
    """V22 honest check: the composition kernel and named modes must actually
    work - assemble the default runtime, validate every per-kind Protocol, and
    verify a mode bundle. This closes the "component swap + mode switch" path
    from the V22 plan with REAL execution (fail-closed)."""
    from .component import (
        CompositionKernel, Kind, _KIND_PROTOCOLS, LoopStrategyProto)
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


def check_loop_integrity(manifest_path: str = "baize.manifest.json",
                         cfg: dict | None = None) -> dict:
    """V26-C5: Check run ledgers and manifest loop integrity.

    Verifies:
    - Runs in persistence/runs/ have valid events without unresolved crashes.
    - Verified tasks have evidence and transitions recorded in ledgers.
    """
    from .run_ledger import list_runs, RunLedger
    runs = list_runs(cfg=cfg)
    if not runs:
        return {"status": "pass", "detail": "0 runs recorded (clean state)",
                "runs_checked": 0}

    problems: list[str] = []
    for rid in runs:
        ledger = RunLedger(rid, cfg=cfg)
        state = ledger.replay()
        # Unfinished tasks left hanging without completion marker
        if state["in_progress_tasks"] and not state["completed"]:
            problems.append(f"run {rid}: {len(state['in_progress_tasks'])} task(s) unverified/in_progress")

    if problems:
        return {"status": "fail", "detail": "; ".join(problems[:5]),
                "runs_checked": len(runs), "problems": problems}

    return {"status": "pass", "detail": f"{len(runs)} run(s) verified",
            "runs_checked": len(runs)}


def check_quality(cfg: dict | None = None,
                  manifest_path: str | None = None,
                  data_file: str | None = None,
                  now: float | None = None) -> dict:
    """V23.6 / V26-C5 multi-dimensional quality gate.

    Aggregates existing honest signals into six dimensions:
      - runnable         : manifest evidence is real (check_manifest)
      - coverage_clarity : real coverage measured (check_coverage)
      - composition      : composition kernel + modes assemble (check_composition)
      - loop_integrity   : run ledgers integrity (check_loop_integrity)
      - locatability     : skill index hygiene (missing-description rate)
      - maintainability  : has tests/ + README (static repo hygiene)
    Below ``BAIZE_QUALITY_THRESHOLD`` the overall gate FAILS (intercept).

    ``manifest_path``, ``data_file`` and ``now`` are forwarded to the two checks
    this function *re-runs*. Without them it silently fell back to the defaults,
    so ``run_gate`` could report two different subjects in one output. Observed:

        $ python -m baize gate --manifest bogus.json
        manifest : FAIL
          - manifest invalid: V1: evidence missing on disk: ...
        quality  : 1.0 PASS
          - runnable: 1.0          <- documented as "manifest evidence is real"

        $ python -m baize gate --coverage-data D:/tmp/NOPE.coverage
        coverage : UNKNOWN (no data file D:/tmp/NOPE.coverage)
        quality  : 1.0 PASS
          - coverage_clarity: 1.0  <- documented as "real coverage measured"

    A dimension named after a check must be that check's answer about the *same*
    subject.
    """
    cfg = cfg or load_config()
    notes: list[str] = []
    # 1. runnable — manifest evidence actually exists / non-empty / fresh.
    man_ok, _ = check_manifest(
        manifest_path or cfg.get("BAIZE_MANIFEST", "baize.manifest.json"),
        now=now, notes=notes)
    # 2. coverage clarity — real coverage measured, not faked.
    cov = check_coverage(data_file, cfg=cfg)
    cov_score = {"pass": 1.0, "unknown": 0.5, "fail": 0.0}.get(
        cov.get("status"), 0.0)
    # 3. composition — kernel + modes actually assemble.
    comp = check_composition(cfg)
    comp_score = 1.0 if comp.get("status") == "pass" else 0.0
    # 4. loop_integrity (V26-C5)
    loop = check_loop_integrity(cfg=cfg)
    loop_score = 1.0 if loop.get("status") == "pass" else 0.0
    # 5. locatability — skill index hygiene (missing-description rate).
    try:
        from . import skill_index
        au = skill_index.audit_index(cfg)
        total = au.get("count") or 1
        miss = len(au.get("missing_description", []))
        locatability = max(0.0, 1.0 - miss / total)
    except Exception:
        locatability = 0.5
    # 6. maintainability — static repo hygiene.
    root = Path(cfg.get("BAIZE_WORKSPACE_DIR", str(ROOT)))
    has_tests = (root / "tests").is_dir()
    has_readme = any((root / f).exists()
                     for f in ("README.md", "README", "readme.md"))
    maintainability = (0.5 if has_tests else 0.0) + (0.5 if has_readme else 0.0)
    dims = {
        "runnable": 1.0 if man_ok else 0.0,
        "coverage_clarity": cov_score,
        "composition": comp_score,
        "loop_integrity": loop_score,
        "locatability": round(locatability, 3),
        "maintainability": maintainability,
    }
    weights = {"runnable": 0.25, "coverage_clarity": 0.2, "composition": 0.15,
               "loop_integrity": 0.15, "locatability": 0.15, "maintainability": 0.1}
    score = round(sum(dims[k] * w for k, w in weights.items()), 3)
    threshold = float(cfg.get("BAIZE_QUALITY_THRESHOLD", "0.8"))
    return {"dimensions": dims, "score": score,
            "threshold": threshold, "pass": score >= threshold,
            "notes": notes}


def run_gate(manifest_path: str = "baize.manifest.json",
             data_file: str | None = None,
             now: float | None = None,
             cfg: dict | None = None) -> dict:
    """Run every check and aggregate. Each input is threaded to *every* check
    that evaluates it, so no reported number describes a different subject than
    the line above it (see ``check_quality``)."""
    cfg = cfg or load_config()
    manifest_notes: list[str] = []
    man_ok, man_problems = check_manifest(manifest_path, now=now,
                                          notes=manifest_notes)
    cov = check_coverage(data_file, cfg=cfg)
    comp = check_composition()
    quality = check_quality(cfg, manifest_path=manifest_path,
                            data_file=data_file, now=now)
    loop = check_loop_integrity()
    if (not man_ok or cov["status"] == "fail" or comp["status"] == "fail"
            or not quality["pass"] or loop["status"] == "fail"):
        status = "fail"
    elif cov["status"] == "unknown":
        status = "unknown"
    else:
        status = "pass"
    return {
        "manifest_ok": man_ok,
        "manifest_problems": man_problems,
        "manifest_notes": manifest_notes,
        "coverage": cov,
        "composition": comp,
        "quality": quality,
        "loop_integrity": loop,
        "overall": (man_ok and cov["status"] == "pass"
                    and comp["status"] == "pass" and quality["pass"]
                    and loop["status"] == "pass"),
        "status": status,
    }
