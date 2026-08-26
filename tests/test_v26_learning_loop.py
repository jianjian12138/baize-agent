"""V26-C1-C5: Learning loop, memory layering, skill governance, and gate integrity.

Tests written before implementation.
Maps to openspec/specs/baize-agent/v26-learning-loop.md §3.
"""
import pytest
from pathlib import Path

from baize.config import load_config
from baize.memory import log_event, recall
from baize.skill_index import verify_skill_draft, record_usage, skill_stats
from baize.gate import check_loop_integrity


def test_c1_memory_layered_lineage(tmp_path, monkeypatch):
    """Memory events support layering (fact, decision, lesson) and preserve source lineage."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    cfg = load_config()
    cfg["BAIZE_PERSISTENCE_DIR"] = str(tmp_path)

    log_event("Discovered bug in parser", tags=["bug"], category="lesson",
              run_id="run-001", task_id="T-01", evidence="tests/parser_err.log", cfg=cfg)
    log_event("Adopted json over yaml", tags=["arch"], category="decision",
              run_id="run-001", task_id="T-02", cfg=cfg)

    # Recall by category
    hits = recall("bug", cfg=cfg, category="lesson")
    assert len(hits) == 1
    h = hits[0]
    assert h["category"] == "lesson"
    assert h["run_id"] == "run-001"
    assert h["task_id"] == "T-01"
    assert h["evidence"] == "tests/parser_err.log"

    # Category filter exclusion
    assert len(recall("bug", cfg=cfg, category="decision")) == 0


def test_c2_skill_candidate_requires_evidence(tmp_path):
    """RunLedger skill_candidate contains task_id and verified evidence."""
    from baize.run_ledger import RunLedger
    ledger = RunLedger("run-candidate-test", cfg={"BAIZE_PERSISTENCE_DIR": str(tmp_path)})
    ledger.append("skill_candidate", {
        "task_id": "T-10",
        "candidate_description": "Reusable git workflow",
        "evidence": "src/git_helper.py"
    }, task_id="T-10")

    state = ledger.replay()
    assert len(state["skill_candidates"]) == 1
    cand = state["skill_candidates"][0]
    assert cand["task_id"] == "T-10"
    assert cand["evidence"] == "src/git_helper.py"


def test_c3_verify_skill_draft_rejects_missing_evidence():
    """Skill draft without evidence or verification command is rejected."""
    # Valid draft
    valid_draft = {
        "name": "auto-tester",
        "description": "Automated pytest runner",
        "source_run": "run-2026-01",
        "source_task": "T-05",
        "evidence": "tests/test_auto.py",
        "verification_cmd": "pytest tests/test_auto.py",
        "dependencies": ["pytest"],
        "scope": "python projects",
    }
    ok, reason = verify_skill_draft(valid_draft)
    assert ok, f"Expected valid draft to pass, got: {reason}"

    # Invalid draft (missing evidence)
    invalid_draft = dict(valid_draft)
    invalid_draft["evidence"] = ""
    ok, reason = verify_skill_draft(invalid_draft)
    assert not ok
    assert "evidence" in reason.lower()

    # Invalid draft (missing source_run)
    invalid_draft2 = dict(valid_draft)
    invalid_draft2["source_run"] = ""
    ok, reason = verify_skill_draft(invalid_draft2)
    assert not ok
    assert "source" in reason.lower() or "run" in reason.lower()


def test_c4_skill_feedback_and_stats(tmp_path, monkeypatch):
    """Recording skill usage tracks successes/failures and calculates stats."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    cfg = load_config()
    cfg["BAIZE_PERSISTENCE_DIR"] = str(tmp_path)

    record_usage("auto-tester", success=True, cfg=cfg)
    record_usage("auto-tester", success=True, cfg=cfg)
    record_usage("auto-tester", success=False, reason="syntax error in skill", cfg=cfg)

    stats = skill_stats(cfg=cfg)
    assert "auto-tester" in stats
    s = stats["auto-tester"]
    assert s["uses"] == 3
    assert s["successes"] == 2
    assert s["failures"] == 1
    assert s["success_rate"] == round(2 / 3, 2)


def test_c5_gate_loop_integrity(tmp_path, monkeypatch):
    """Quality gate loop_integrity checks run ledgers and reports valid status."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    cfg = load_config()
    cfg["BAIZE_PERSISTENCE_DIR"] = str(tmp_path)

    # Empty runs -> pass with note
    res = check_loop_integrity(cfg=cfg)
    assert "status" in res
    assert res["status"] in ("pass", "unknown")
