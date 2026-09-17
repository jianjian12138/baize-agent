"""Tests for the NO FAKE DONE gate and the V23.6 quality dimension."""
from __future__ import annotations

from baize import gate
from baize.gate import check_composition, check_coverage, check_manifest


def test_check_manifest_missing_file(tmp_path):
    ok, problems = check_manifest(str(tmp_path / "nope.manifest.json"))
    assert ok is False
    assert any("not found" in p for p in problems)


def test_check_coverage_reports_unknown_without_pkg():
    rep = check_coverage("__does_not_exist__.coverage")
    assert rep["status"] == "unknown"


# ------------------------------------------------- coverage data freshness
#
# `check_coverage` used to read `.coverage` whatever its age and report the
# number as a verdict about the current tree. Observed: 83.5% FAILED from an
# hour-old file while the same tree measured 86.6% PASS. A stale file is now
# `unknown`, which is a different and honest thing from `fail`.


def _stale_data_file(tmp_path, name="old.coverage"):
    """A data file with an mtime an hour in the past. No coverage needed: the
    freshness check runs before the file is ever loaded."""
    import os
    import time

    p = tmp_path / name
    p.write_bytes(b"not really coverage data")
    old = time.time() - 3600
    os.utime(p, (old, old))
    return p


def test_calibration_the_stale_probe_sees_a_stale_file(tmp_path):
    """Without this, every refusal test below would pass on a probe that
    silently sees nothing."""
    from baize.gate import coverage_data_is_stale

    reason = coverage_data_is_stale(_stale_data_file(tmp_path))
    assert reason is not None, "probe failed to notice a 1h-old data file"
    assert "older tree" in reason


def test_a_stale_data_file_is_unknown_not_fail(tmp_path):
    rep = check_coverage(str(_stale_data_file(tmp_path)))
    assert rep["status"] == "unknown", (
        "a stale measurement must not be reported as a verdict")
    assert "cannot verify" in rep["reason"]
    assert "total" not in rep, "no percentage may be reported from a stale file"


def test_coverage_file_env_var_is_honoured(tmp_path, monkeypatch):
    """`coverage run` honours COVERAGE_FILE, so the gate must too - otherwise it
    measures a different, older file than the run it is checking."""
    stale = _stale_data_file(tmp_path, "redirected.coverage")
    monkeypatch.setenv("COVERAGE_FILE", str(stale))

    rep = check_coverage()
    assert rep["status"] == "unknown"
    assert "redirected.coverage" in rep["reason"]


def test_explicit_argument_beats_the_env_var(tmp_path, monkeypatch):
    from baize.gate import resolve_coverage_data_file

    monkeypatch.setenv("COVERAGE_FILE", "from-env.coverage")
    assert resolve_coverage_data_file("explicit.coverage") == "explicit.coverage"
    assert resolve_coverage_data_file() == "from-env.coverage"
    assert resolve_coverage_data_file(
        None, {"BAIZE_COVERAGE_DATA": "from-cfg.coverage"}) == "from-env.coverage"
    monkeypatch.delenv("COVERAGE_FILE")
    assert resolve_coverage_data_file(
        None, {"BAIZE_COVERAGE_DATA": "from-cfg.coverage"}) == "from-cfg.coverage"
    assert resolve_coverage_data_file(None, {}) == ".coverage"


def test_check_composition_assembles():
    rep = check_composition()
    assert rep["status"] == "pass"


def test_check_quality_dimensions_and_bounds():
    q = gate.check_quality()
    dims = q["dimensions"]
    assert set(dims) == {"runnable", "coverage_clarity", "composition",
                         "loop_integrity", "locatability", "maintainability"}
    assert 0.0 <= q["score"] <= 1.0
    assert isinstance(q["pass"], bool)
    assert q["threshold"] > 0


def test_run_gate_includes_quality():
    rep = gate.run_gate()
    assert "quality" in rep
    assert rep["quality"]["score"] >= 0
    assert rep["quality"]["threshold"] > 0


# ------------------------------------------------- manifest evidence freshness
#
# `check_manifest` judged every evidence file by `now - mtime`. Git rewrites the
# mtime of tracked files on checkout, so for tracked evidence that number is the
# age of the checkout, not of the file. Observed: the same commit reported
# `manifest : FAIL - V70: evidence STALE (28d old): baize/subagent.py` in a
# long-lived working copy, and `manifest : PASS` in a fresh clone of the same
# bytes. All 173 evidence entries in this repo are tracked, so the rule could
# only fire where it was wrong - and never in CI, where it would be vacuous.


def _old_file(path, days=30):
    import os
    import time

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("evidence\n", encoding="utf-8")
    old = time.time() - days * 86400
    os.utime(path, (old, old))
    return path


def _manifest(tmp_path, evidence, pid="V1"):
    import json

    # project/version/phases are all required by validate_manifest, which
    # check_manifest runs first - a manifest missing them is rejected before the
    # per-file checks are reached.
    p = tmp_path / "baize.manifest.json"
    p.write_text(json.dumps({
        "project": "t", "version": "0.0.1",
        "phases": [{"id": pid, "name": "n", "status": "done",
                    "evidence": evidence}]}), encoding="utf-8")
    return str(p)


def _git(tmp_path, *args):
    import subprocess

    return subprocess.run(["git", "-C", str(tmp_path), *args],
                          capture_output=True, timeout=60)


def _init_repo(tmp_path):
    import pytest

    if _git(tmp_path, "init").returncode != 0:
        pytest.skip("git unavailable")


def test_calibration_a_stale_untracked_evidence_file_is_still_stale(tmp_path):
    """The rule must still fire where mtime is trustworthy, or the tests below
    would pass for a check that had simply been deleted."""
    _init_repo(tmp_path)
    _old_file(tmp_path / "artifacts" / "run.log")
    notes: list[str] = []
    ok, problems = check_manifest(_manifest(tmp_path, ["artifacts/run.log"]),
                                  notes=notes)
    assert ok is False
    assert any("STALE" in p for p in problems)
    assert notes == [], "a judged file must not also be reported as not judged"


def test_a_tracked_evidence_file_is_not_called_stale(tmp_path):
    """`baize/subagent.py` is the *implementation* of phase V70. Its age is the
    age of the checkout, so calling it stale is a claim about nothing."""
    _init_repo(tmp_path)
    _old_file(tmp_path / "baize" / "thing.py")
    assert _git(tmp_path, "add", "baize/thing.py").returncode == 0
    notes: list[str] = []
    ok, problems = check_manifest(_manifest(tmp_path, ["baize/thing.py"]),
                                  notes=notes)
    assert ok is True, problems
    assert not any("STALE" in p for p in problems)
    assert len(notes) == 1
    assert "tracked" in notes[0]


def test_a_fresh_file_produces_no_note(tmp_path):
    """Calibration: the note reports a real condition, it is not unconditional."""
    _old_file(tmp_path / "baize" / "thing.py", days=0)
    notes: list[str] = []
    ok, problems = check_manifest(_manifest(tmp_path, ["baize/thing.py"]),
                                  notes=notes)
    assert ok is True, problems
    assert notes == []


def test_git_unavailable_is_not_a_stale_verdict(tmp_path, monkeypatch):
    """"Cannot judge" must not be reported as a defect - the same rule the
    coverage freshness check follows."""
    _old_file(tmp_path / "baize" / "thing.py")
    monkeypatch.setattr(gate.shutil, "which", lambda name: None)
    notes: list[str] = []
    ok, problems = check_manifest(_manifest(tmp_path, ["baize/thing.py"]),
                                  notes=notes)
    assert ok is True, problems
    assert len(notes) == 1
    assert "git is unavailable" in notes[0]


def test_missing_evidence_is_still_a_hard_failure(tmp_path):
    """Existence stays a hard failure. That check was always sound.

    `validate_manifest` runs first inside `check_manifest` and already rejects a
    missing evidence file, so the per-file MISSING branch below it is defensive
    rather than the one that fires. Either way the verdict is a failure, which is
    the property that matters.
    """
    ok, problems = check_manifest(_manifest(tmp_path, ["baize/gone.py"]))
    assert ok is False
    assert any("missing" in p.lower() for p in problems)


def test_old_tracked_evidence_is_summarised_not_repeated(tmp_path):
    """173 evidence entries must not produce 173 note lines."""
    _init_repo(tmp_path)
    evidence = []
    for i in range(3):
        name = f"baize/m{i}.py"
        _old_file(tmp_path / name)
        assert _git(tmp_path, "add", name).returncode == 0
        evidence.append(name)
    notes: list[str] = []
    ok, _ = check_manifest(_manifest(tmp_path, evidence), notes=notes)
    assert ok is True
    assert len(notes) == 1
    assert "3 evidence file(s)" in notes[0]


def test_tracked_paths_reports_cannot_judge_outside_a_repo(tmp_path):
    """Not a repository -> None, never an empty set that reads like "nothing is
    tracked"."""
    assert gate.tracked_paths(tmp_path) is None


def test_tracked_paths_lists_the_repo(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert _git(tmp_path, "add", "a.py").returncode == 0
    tracked = gate.tracked_paths(tmp_path)
    assert tracked is not None
    assert "a.py" in tracked
