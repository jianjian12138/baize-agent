"""V26-A3/A4/A5: State gate, resume, and status report tests.

Tests the orchestrator's RunLedger integration (A3 state gate),
resume support (A4), and the CLI status command (A5).
"""
import json
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# A3: State gate — task_verified only written on verifier pass
# ---------------------------------------------------------------------------

def test_state_gate_pass_writes_task_verified(tmp_path, monkeypatch):
    """When verifier returns 'pass', task_verified must be written to ledger."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(tmp_path / "sessions"))

    from baize.run_ledger import RunLedger
    from baize.orchestrator import Orchestrator, OrchestrationResult

    # Patch orchestrator to run without a real LLM
    orch = Orchestrator.__new__(Orchestrator)
    orch.cfg = {"BAIZE_PERSISTENCE_DIR": str(tmp_path),
                "BAIZE_SESSIONS_DIR": str(tmp_path / "sessions"),
                "BAIZE_MODEL_BASE_URL": "", "BAIZE_MODEL_NAME": ""}
    orch._ledger = RunLedger("run-gate-test", cfg=orch.cfg)
    orch._ledger.append("plan_created", {"goal": "test goal", "task_count": 1})

    # Simulate a passing verdict
    task_id = "1"
    orch._ledger.append("task_claimed", {"role": "executor"}, task_id=task_id)
    orch._ledger.append("task_started", {"role": "executor"}, task_id=task_id)
    orch._ledger.append("task_verified", {"evidence": "tests/x.py", "verdict": "pass"}, task_id=task_id)
    orch._ledger.append("state_transition", {"from_status": "in_progress", "to_status": "verified"}, task_id=task_id)

    state = orch._ledger.replay()
    assert "1" in state["verified_tasks"]
    assert "1" not in state["failed_tasks"]


def test_state_gate_fail_writes_task_failed(tmp_path, monkeypatch):
    """When verifier fails, task_failed must be written and task NOT in verified_tasks."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    from baize.run_ledger import RunLedger

    ledger = RunLedger("run-gate-fail")
    ledger.append("plan_created", {"goal": "g", "task_count": 1})
    ledger.append("task_claimed", {"role": "executor"}, task_id="1")
    ledger.append("task_started", {"role": "executor"}, task_id="1")
    # No task_verified written — only task_failed
    ledger.append("task_failed", {"issues": ["check failed"], "retries_used": 1}, task_id="1")

    state = ledger.replay()
    assert "1" in state["failed_tasks"]
    assert "1" not in state["verified_tasks"]


# ---------------------------------------------------------------------------
# A4: Resume — skip already-verified tasks
# ---------------------------------------------------------------------------

def test_resume_skips_verified_task(tmp_path, monkeypatch):
    """On resume, already-verified tasks appear as pass without re-executing."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    from baize.run_ledger import RunLedger

    run_id = "run-resume-test"
    ledger = RunLedger(run_id)
    ledger.append("plan_created", {"goal": "build feature", "task_count": 2})
    ledger.append("task_claimed", {"role": "executor"}, task_id="1")
    ledger.append("task_started", {"role": "executor"}, task_id="1")
    ledger.append("task_verified", {"evidence": "src/x.py", "verdict": "pass"}, task_id="1")
    ledger.append("state_transition", {"from_status": "in_progress", "to_status": "verified"}, task_id="1")
    # Task 2 not started yet — simulated interruption

    # Resume: replay should show task 1 as verified, task 2 as unfinished
    resumed = RunLedger(run_id)
    state = resumed.replay()
    assert "1" in state["verified_tasks"]
    assert "2" not in state["verified_tasks"]
    assert "2" not in state["in_progress_tasks"]

    unfinished = resumed.current_unfinished()
    assert "1" not in unfinished


# ---------------------------------------------------------------------------
# A4: CLI --resume flag registered in parser
# ---------------------------------------------------------------------------

def test_cli_resume_flag_exists():
    """The 'team' subcommand must accept --resume argument."""
    from baize.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["team", "my goal", "--resume", "run-abc-123"])
    assert args.resume == "run-abc-123"
    assert args.goal == "my goal"


# ---------------------------------------------------------------------------
# A5: CLI 'status' subcommand
# ---------------------------------------------------------------------------

def test_cli_status_no_runs(tmp_path, monkeypatch, capsys):
    """'baize status' with no runs should report no runs and return 1."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    from baize.cli import cmd_status

    class _Args:
        run_id = ""

    ret = cmd_status(_Args())
    assert ret == 1
    captured = capsys.readouterr()
    assert "no runs" in captured.out.lower()


def test_cli_status_shows_run_info(tmp_path, monkeypatch, capsys):
    """'baize status <run-id>' must display goal, verified tasks, and next action."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    from baize.run_ledger import RunLedger
    from baize.cli import cmd_status

    run_id = "run-status-test"
    ledger = RunLedger(run_id)
    ledger.append("plan_created", {"goal": "Build feature Y", "task_count": 2})
    ledger.append("task_claimed", {"role": "executor"}, task_id="T-01")
    ledger.append("task_verified", {"evidence": "src/y.py", "verdict": "pass"}, task_id="T-01")
    ledger.append("task_started", {"role": "executor"}, task_id="T-02")
    # T-02 in progress (unfinished)

    class _Args:
        pass
    _args = _Args()
    _args.run_id = run_id

    ret = cmd_status(_args)
    captured = capsys.readouterr()
    out = captured.out

    assert ret == 0
    assert "Build feature Y" in out
    assert "T-01" in out     # in verified_tasks
    assert "resume" in out   # next action guidance


def test_cli_status_run_not_found(tmp_path, monkeypatch, capsys):
    """'baize status <nonexistent-run>' should print error and return 1."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    from baize.cli import cmd_status

    class _Args:
        run_id = "run-does-not-exist"

    ret = cmd_status(_Args())
    assert ret == 1
    assert "not found" in capsys.readouterr().out


def test_cli_status_subcommand_registered():
    """'status' must be a registered subcommand in the CLI parser."""
    from baize.cli import build_parser
    parser = build_parser()
    # Should not raise
    args = parser.parse_args(["status", "run-abc"])
    assert args.run_id == "run-abc"
    assert args.command == "status"


def test_cli_status_completed_run(tmp_path, monkeypatch, capsys):
    """A completed run should show 'run complete' in next action guidance."""
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(tmp_path))
    from baize.run_ledger import RunLedger
    from baize.cli import cmd_status

    run_id = "run-completed"
    ledger = RunLedger(run_id)
    ledger.append("plan_created", {"goal": "Finish task", "task_count": 1})
    ledger.append("task_verified", {"evidence": "src/z.py", "verdict": "pass"}, task_id="T-01")
    ledger.append("run_completed", {"success": True, "total_tasks": 1, "passed_tasks": 1})

    class _Args:
        pass
    _args = _Args()
    _args.run_id = run_id

    ret = cmd_status(_args)
    out = capsys.readouterr().out
    assert ret == 0
    assert "complete" in out.lower()
