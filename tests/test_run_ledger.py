"""V26-A2: RunLedger tests (written before implementation).

All tests here MUST fail until baize/run_ledger.py is implemented.
Test coverage maps exactly to openspec/specs/baize-agent/v26-ledger.md §7.
"""
import json
import pytest
from pathlib import Path

# This import will fail until baize/run_ledger.py is created.
from baize.run_ledger import RunLedger, get_ledger, list_runs


# ---------------------------------------------------------------------------
# A2-1: append + events 读取
# ---------------------------------------------------------------------------

def test_append_and_read_events(tmp_path, monkeypatch):
    """Appended events must be readable via .events()."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    ledger = RunLedger("run-test-001")

    ledger.append("plan_created", {"goal": "Build feature X", "task_count": 2})
    ledger.append("task_started", {"role": "executor"}, task_id="T-01")

    events = ledger.events()
    assert len(events) == 2

    e0 = events[0]
    assert e0["event"] == "plan_created"
    assert e0["run_id"] == "run-test-001"
    assert e0["payload"]["goal"] == "Build feature X"
    assert "ts" in e0

    e1 = events[1]
    assert e1["event"] == "task_started"
    assert e1["task_id"] == "T-01"


# ---------------------------------------------------------------------------
# A2-2: replay 状态重建
# ---------------------------------------------------------------------------

def test_replay_state(tmp_path, monkeypatch):
    """replay() must correctly rebuild verified/failed/in_progress task sets."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    ledger = RunLedger("run-test-002")

    ledger.append("plan_created", {"goal": "Test goal", "task_count": 3})
    ledger.append("task_claimed", {"role": "executor"}, task_id="T-01")
    ledger.append("task_started", {"role": "executor"}, task_id="T-01")
    ledger.append("task_verified", {"evidence": "src/x.py", "verdict": "pass"}, task_id="T-01")
    ledger.append("state_transition", {"from_status": "in_progress", "to_status": "verified"}, task_id="T-01")

    ledger.append("task_claimed", {"role": "executor"}, task_id="T-02")
    ledger.append("task_started", {"role": "executor"}, task_id="T-02")
    ledger.append("task_failed", {"issues": ["test failed"], "retries_used": 1}, task_id="T-02")

    ledger.append("task_claimed", {"role": "executor"}, task_id="T-03")
    ledger.append("task_started", {"role": "executor"}, task_id="T-03")

    state = ledger.replay()

    assert state["run_id"] == "run-test-002"
    assert state["goal"] == "Test goal"
    assert "T-01" in state["verified_tasks"]
    assert "T-02" in state["failed_tasks"]
    assert "T-03" in state["in_progress_tasks"]
    assert "T-01" not in state["in_progress_tasks"]
    assert "T-02" not in state["in_progress_tasks"]


# ---------------------------------------------------------------------------
# A2-3: current_unfinished
# ---------------------------------------------------------------------------

def test_current_unfinished(tmp_path, monkeypatch):
    """current_unfinished() must return only tasks not yet verified or failed."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    ledger = RunLedger("run-test-003")

    ledger.append("task_started", {"role": "executor"}, task_id="T-01")
    ledger.append("task_verified", {"evidence": "x", "verdict": "pass"}, task_id="T-01")
    ledger.append("task_started", {"role": "executor"}, task_id="T-02")
    # T-02 is in progress but not finished

    unfinished = ledger.current_unfinished()
    assert "T-01" not in unfinished
    assert "T-02" in unfinished


# ---------------------------------------------------------------------------
# A2-4: is_task_claimed / is_task_verified flags
# ---------------------------------------------------------------------------

def test_claim_and_verify_flags(tmp_path, monkeypatch):
    """is_task_claimed() and is_task_verified() must reflect ledger state."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    ledger = RunLedger("run-test-004")

    assert not ledger.is_task_claimed("T-01")
    assert not ledger.is_task_verified("T-01")

    ledger.append("task_claimed", {"role": "executor"}, task_id="T-01")
    assert ledger.is_task_claimed("T-01")
    assert not ledger.is_task_verified("T-01")

    ledger.append("task_verified", {"evidence": "x", "verdict": "pass"}, task_id="T-01")
    assert ledger.is_task_verified("T-01")


# ---------------------------------------------------------------------------
# A2-5: 损坏 JSONL 行跳过不崩溃
# ---------------------------------------------------------------------------

def test_corrupt_line_skipped(tmp_path, monkeypatch):
    """Corrupt JSONL lines must be skipped during replay(), not crash."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    ledger = RunLedger("run-test-005")
    ledger.append("plan_created", {"goal": "test", "task_count": 1})

    # Manually inject a corrupt line
    ledger.path.open("a", encoding="utf-8").write("NOT JSON {{{BAD\n")

    ledger.append("task_started", {"role": "executor"}, task_id="T-01")

    # Must not raise
    events = ledger.events()
    state = ledger.replay()
    assert state["goal"] == "test"
    # corrupt line should be skipped, valid lines should be present
    assert len(events) >= 2  # plan_created and task_started


# ---------------------------------------------------------------------------
# A2-6: list_runs
# ---------------------------------------------------------------------------

def test_list_runs(tmp_path, monkeypatch):
    """list_runs() must return all run_ids found in persistence/runs/."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))

    RunLedger("run-alpha").append("plan_created", {"goal": "a", "task_count": 1})
    RunLedger("run-beta").append("plan_created", {"goal": "b", "task_count": 1})

    runs = list_runs()
    assert "run-alpha" in runs
    assert "run-beta" in runs


# ---------------------------------------------------------------------------
# A2-7: resume 跳过已 verified 任务
# ---------------------------------------------------------------------------

def test_resume_skips_verified(tmp_path, monkeypatch):
    """After resume, verified tasks must not appear in current_unfinished()."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    ledger = RunLedger("run-test-007")

    ledger.append("task_started", {"role": "executor"}, task_id="T-01")
    ledger.append("task_verified", {"evidence": "x", "verdict": "pass"}, task_id="T-01")
    ledger.append("task_started", {"role": "executor"}, task_id="T-02")
    # Simulate interruption — T-02 not finished

    # On resume, recreate ledger from same run_id (simulates resume)
    resumed = RunLedger("run-test-007")
    state = resumed.replay()

    assert "T-01" in state["verified_tasks"]
    assert "T-02" not in state["verified_tasks"]
    unfinished = resumed.current_unfinished()
    assert "T-01" not in unfinished
    assert "T-02" in unfinished


# ---------------------------------------------------------------------------
# A2-8: get_ledger factory
# ---------------------------------------------------------------------------

def test_get_ledger_factory(tmp_path, monkeypatch):
    """get_ledger() must return a RunLedger for the given run_id."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    ledger = get_ledger("run-factory-001")
    assert isinstance(ledger, RunLedger)
    assert ledger.path.parent.name == "runs"


# ---------------------------------------------------------------------------
# A2-9: 账本文件路径
# ---------------------------------------------------------------------------

def test_ledger_path(tmp_path, monkeypatch):
    """Ledger files must be stored at persistence/runs/<run-id>.jsonl."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    ledger = RunLedger("run-path-check")
    assert ledger.path.name == "run-path-check.jsonl"
    assert ledger.path.parent.name == "runs"


# ---------------------------------------------------------------------------
# A2-10: append is truly append-only (file grows)
# ---------------------------------------------------------------------------

def test_append_only_grows(tmp_path, monkeypatch):
    """Each append must increase the file size (truly append-only)."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    ledger = RunLedger("run-grow")
    ledger.append("plan_created", {"goal": "g", "task_count": 1})
    size1 = ledger.path.stat().st_size
    ledger.append("task_started", {"role": "executor"}, task_id="T-01")
    size2 = ledger.path.stat().st_size
    assert size2 > size1
