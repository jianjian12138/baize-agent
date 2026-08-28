"""V26-B2-B5: Controlled execution, machine-first verification, failure feedback, and security.

Tests written before implementation.
Maps to openspec/specs/baize-agent/v26-controlled-roles.md §3.
"""
import pytest
from pathlib import Path

from baize.orchestrator import Orchestrator, SubtaskReport
from baize.run_ledger import RunLedger
from baize.tools import default_registry, ToolRegistry
from baize.team import Role, TeamConfig


from baize.config import load_config


def _make_dummy_orch(tmp_path):
    orch = Orchestrator.__new__(Orchestrator)
    cfg = load_config()
    cfg.update({
        "BAIZE_SESSIONS_DIR": str(tmp_path / "sessions"),
        "BAIZE_PERSISTENCE_DIR": str(tmp_path),
        "BAIZE_WORKSPACE_DIR": str(tmp_path / "workspace"),
        "BAIZE_AGENT_MAX_STEPS": "2",
        "BAIZE_MODEL_BASE_URL": "",
        "BAIZE_MODEL_NAME": "",
    })
    orch.cfg = cfg
    (tmp_path / "workspace").mkdir(parents=True, exist_ok=True)
    orch.registry = default_registry()
    from baize.hooks import HookRegistry
    orch.hooks = HookRegistry()
    orch.client = None
    orch.on_event = lambda *_: None
    orch.team_memory = None
    orch.verify_hooks = []
    orch.max_retries = 1
    orch._ledger = RunLedger("run-b-test", cfg=orch.cfg)
    return orch


def test_b2_role_not_allowed_rejected(tmp_path):
    """If a subtask specifies allowed_roles and 'executor' is not in it, execute_subtask fails."""
    orch = _make_dummy_orch(tmp_path)
    sub = {
        "id": "T-01",
        "task": "Do restricted task",
        "verify": "check",
        "allowed_roles": ["security_officer"],  # executor not allowed
    }
    summary, sid = orch.execute_subtask(sub)
    assert "not allowed" in summary.lower() or "unauthorized" in summary.lower() or "role" in summary.lower()


def test_b3_machine_checks_fail_blocks_verifier(tmp_path):
    """When machine checks fail, verify_subtask returns fail without invoking Verifier LLM."""
    orch = _make_dummy_orch(tmp_path)
    sub = {
        "id": "T-01",
        "task": "Create foo.txt",
        "verify": "foo.txt exists",
        "checks": [{"type": "file_exists", "path": "non_existent_file.txt"}],
    }
    # No LLM client configured, so if it attempted to call Verifier LLM, it would error or fail
    res = orch.verify_subtask(sub, "I created foo.txt (claiming false success)")
    assert res["verdict"] == "fail"
    assert any("non_existent_file.txt" in str(i) or "file_exists" in str(i) for i in res["issues"])
    assert res["session_id"] == ""  # LLM verifier was NOT spawned


def test_b3_missing_evidence_paths_rejected(tmp_path):
    """When evidence_paths are declared but missing/empty, verify_subtask returns fail."""
    orch = _make_dummy_orch(tmp_path)
    sub = {
        "id": "T-02",
        "task": "Create artifact",
        "verify": "artifact exists",
        "evidence_paths": ["missing_artifact.json"],
        "checks": [],
    }
    res = orch.verify_subtask(sub, "I claim artifact is created")
    assert res["verdict"] == "fail"
    assert any("evidence" in str(i).lower() or "missing_artifact" in str(i) for i in res["issues"])


def test_b4_retry_feedback_and_exhaustion(tmp_path, monkeypatch):
    """Failed subtask records task_failed event with issues when retries are exhausted."""
    orch = _make_dummy_orch(tmp_path)
    ledger = orch._ledger

    # Mock execute_subtask and verify_subtask to always fail
    monkeypatch.setattr(orch, "execute_subtask", lambda s: ("executed", "sid-1"))
    monkeypatch.setattr(orch, "verify_subtask", lambda s, summary: {
        "verdict": "fail", "evidence": "no evidence", "issues": ["unit tests failed"],
        "session_id": "sid-2", "checks": []
    })
    monkeypatch.setattr(orch, "plan", lambda g: ([{"id": "1", "task": "subtask 1", "verify": "v1"}], "sid-0"))

    res = orch.run("Test Goal")
    assert not res.success
    assert res.reports[0].verdict == "fail"
    assert res.reports[0].retried is True

    # Check ledger events
    ledger = RunLedger(res.run_id, cfg=orch.cfg)
    evs = ledger.events()
    failed_evs = [e for e in evs if e["event"] == "task_failed"]
    assert len(failed_evs) == 1
    assert failed_evs[0]["task_id"] == "1"
    assert "unit tests failed" in failed_evs[0]["payload"]["issues"]


def test_b5_unauthorized_tool_blocked(tmp_path):
    """When a role only allows read_file, calling bash is not possible in its registry."""
    orch = _make_dummy_orch(tmp_path)
    role = Role(name="executor", allow_tools=["read_file"])
    orch.team_config = TeamConfig(roles=[role])

    agent = orch._spawn("executor")
    assert "read_file" in agent.registry.names()
    assert "bash" not in agent.registry.names()
    # Executing bash fails with unknown tool
    res = agent.registry.execute("bash", {"command": "echo hacked"})
    assert "unknown tool" in res.lower() or "error" in res.lower()

