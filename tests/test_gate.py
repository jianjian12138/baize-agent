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


def test_check_composition_assembles():
    rep = check_composition()
    assert rep["status"] == "pass"


def test_check_quality_dimensions_and_bounds():
    q = gate.check_quality()
    dims = q["dimensions"]
    assert set(dims) == {"runnable", "coverage_clarity", "composition",
                         "locatability", "maintainability"}
    assert 0.0 <= q["score"] <= 1.0
    assert isinstance(q["pass"], bool)
    assert q["threshold"] > 0


def test_run_gate_includes_quality():
    rep = gate.run_gate()
    assert "quality" in rep
    assert rep["quality"]["score"] >= 0
    assert rep["quality"]["threshold"] > 0
