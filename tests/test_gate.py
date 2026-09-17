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
