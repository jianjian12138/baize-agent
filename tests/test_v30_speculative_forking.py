"""Tests for V30 Speculative Time-Travel Forking Engine."""
import pathlib
import pytest
from baize.orchestration.forking import (
    VirtualWorkspace, SpeculativeTimeline, SpeculativeEngine
)


def test_virtual_workspace_isolation(tmp_path):
    """Virtual workspace creates an isolated shadow copy without modifying original files."""
    test_file = tmp_path / "hello.py"
    test_file.write_text("print('original')\n", encoding="utf-8")

    vw = VirtualWorkspace(str(tmp_path))
    shadow_root = pathlib.Path(vw.path)

    # Modify in shadow
    shadow_file = shadow_root / "hello.py"
    assert shadow_file.exists()
    assert shadow_file.read_text(encoding="utf-8") == "print('original')\n"

    shadow_file.write_text("print('modified in shadow')\n", encoding="utf-8")

    # Verify original is untouched
    assert test_file.read_text(encoding="utf-8") == "print('original')\n"

    # Clean up shadow
    vw.cleanup()
    assert not shadow_root.exists()


def test_speculative_timeline_scoring():
    """Timelines are scored based on checks passed, simplicity, and low churn."""
    t1 = SpeculativeTimeline(
        timeline_id="t1",
        strategy="minimal_patch",
        status="verified",
        checks_passed=3,
        total_checks=3,
        churn_lines=5,
        duration_ms=120,
        modified_files={"main.py": "x = 1\n"}
    )
    t2 = SpeculativeTimeline(
        timeline_id="t2",
        strategy="modular_refactor",
        status="verified",
        checks_passed=3,
        total_checks=3,
        churn_lines=80,
        duration_ms=450,
        modified_files={"main.py": "x = 1\n" * 20}
    )

    engine = SpeculativeEngine()
    score1 = engine.evaluate_timeline(t1)
    score2 = engine.evaluate_timeline(t2)

    assert score1 > score2  # t1 wins due to minimal churn
    assert 0.0 <= score1 <= 1.0


def test_speculative_engine_merge_winner(tmp_path):
    """SpeculativeEngine selects the best timeline and atomically applies diff to real workspace."""
    f = tmp_path / "calc.py"
    f.write_text("def add(a, b): return a - b\n", encoding="utf-8")

    engine = SpeculativeEngine(workspace=str(tmp_path))

    # Candidate 1: Fixed
    t1 = SpeculativeTimeline(
        timeline_id="t_win",
        strategy="minimal_patch",
        status="verified",
        checks_passed=2,
        total_checks=2,
        churn_lines=2,
        duration_ms=100,
        modified_files={"calc.py": "def add(a, b): return a + b\n"}
    )
    # Candidate 2: Failed
    t2 = SpeculativeTimeline(
        timeline_id="t_fail",
        strategy="modular_refactor",
        status="failed",
        checks_passed=0,
        total_checks=2,
        churn_lines=50,
        duration_ms=300,
        modified_files={"calc.py": "broken code\n"}
    )

    winner = engine.select_and_merge([t1, t2])
    assert winner.timeline_id == "t_win"
    assert f.read_text(encoding="utf-8") == "def add(a, b): return a + b\n"
