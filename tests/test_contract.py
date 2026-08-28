"""V26-A1: ProjectContract schema tests (written before implementation).

All tests here MUST fail until baize/contract.py is implemented.
Test coverage maps exactly to openspec/specs/baize-agent/v26-contract.md §8.
"""
import json
import pytest
from pathlib import Path

# This import will fail until baize/contract.py is created — that is expected.
from baize.contract import (
    AtomicTask,
    ProjectContract,
    ValidationResult,
    load_contract,
    save_contract,
    validate_contract,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_valid_task(**kwargs) -> dict:
    base = {
        "id": "T-01",
        "goal": "Implement feature X",
        "prerequisites": [],
        "allowed_roles": ["executor"],
        "allowed_tools": ["read_file", "write_file"],
        "workspace_scope": "src/",
        "expected_artifacts": [{"description": "main module", "path": "src/main.py"}],
        "evidence_paths": ["src/main.py"],
        "checks": [
            {"type": "file_exists", "path": "src/main.py"},
        ],
        "verifier_criterion": "src/main.py exists and passes linting",
        "failure_reasons": [],
        "max_retries": 1,
        "skill_candidate_condition": "",
        "status": "pending",
    }
    base.update(kwargs)
    return base


def _make_valid_contract(tasks=None) -> dict:
    return {
        "run_id": "run-2026-001",
        "project": "baize-agent",
        "goal": "Implement V26 core contract",
        "created_at": "2026-08-26T10:00:00",
        "tasks": tasks or [_make_valid_task()],
    }


# ---------------------------------------------------------------------------
# A1-1: 有效 schema 加载 / 序列化往返
# ---------------------------------------------------------------------------

def test_valid_contract_roundtrip(tmp_path):
    """A valid contract survives a save-load roundtrip unchanged."""
    data = _make_valid_contract()
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    contract = load_contract(path)
    assert isinstance(contract, ProjectContract)
    assert contract.run_id == "run-2026-001"
    assert contract.project == "baize-agent"
    assert len(contract.tasks) == 1
    assert isinstance(contract.tasks[0], AtomicTask)
    assert contract.tasks[0].id == "T-01"
    assert contract.tasks[0].goal == "Implement feature X"
    assert contract.tasks[0].max_retries == 1
    assert contract.tasks[0].status == "pending"

    # save and reload
    out = tmp_path / "out.json"
    save_contract(contract, out)
    contract2 = load_contract(out)
    assert contract2.run_id == contract.run_id
    assert contract2.tasks[0].id == contract.tasks[0].id


# ---------------------------------------------------------------------------
# A1-2: validate_contract 返回 ValidationResult
# ---------------------------------------------------------------------------

def test_validate_valid_contract():
    """A fully valid contract produces no errors and no warnings."""
    data = _make_valid_contract()
    path_data = json.dumps(data)
    import io
    from baize.contract import ProjectContract, AtomicTask
    # Build directly from dicts
    tasks = [AtomicTask(**t) for t in data["tasks"]]
    contract = ProjectContract(
        run_id=data["run_id"],
        project=data["project"],
        goal=data["goal"],
        created_at=data["created_at"],
        tasks=tasks,
    )
    result = validate_contract(contract)
    assert isinstance(result, ValidationResult)
    assert result.ok, f"Expected no errors, got: {result.errors}"
    assert result.errors == []


# ---------------------------------------------------------------------------
# A1-3: 缺失必填字段 → ERROR
# ---------------------------------------------------------------------------

def test_invalid_missing_goal():
    """An AtomicTask with an empty goal must produce an ERROR."""
    task_data = _make_valid_task(goal="")
    tasks = [AtomicTask(**task_data)]
    contract = ProjectContract(
        run_id="run-001", project="p", goal="overall goal",
        created_at="2026-01-01T00:00:00", tasks=tasks,
    )
    result = validate_contract(contract)
    assert not result.ok
    assert any("goal" in e.lower() for e in result.errors), result.errors


def test_invalid_missing_verifier_criterion():
    """An AtomicTask with empty verifier_criterion must produce an ERROR."""
    task_data = _make_valid_task(verifier_criterion="")
    tasks = [AtomicTask(**task_data)]
    contract = ProjectContract(
        run_id="run-001", project="p", goal="overall goal",
        created_at="2026-01-01T00:00:00", tasks=tasks,
    )
    result = validate_contract(contract)
    assert not result.ok
    assert any("verifier" in e.lower() for e in result.errors), result.errors


def test_invalid_empty_tasks():
    """A contract with no tasks must produce an ERROR."""
    contract = ProjectContract(
        run_id="run-001", project="p", goal="overall goal",
        created_at="2026-01-01T00:00:00", tasks=[],
    )
    result = validate_contract(contract)
    assert not result.ok
    assert any("task" in e.lower() for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# A1-4: task id 重复 → ERROR
# ---------------------------------------------------------------------------

def test_duplicate_task_id():
    """Two tasks with the same id must produce an ERROR."""
    t1 = AtomicTask(**_make_valid_task(id="T-01"))
    t2 = AtomicTask(**_make_valid_task(id="T-01", goal="Another goal"))
    contract = ProjectContract(
        run_id="run-001", project="p", goal="overall goal",
        created_at="2026-01-01T00:00:00", tasks=[t1, t2],
    )
    result = validate_contract(contract)
    assert not result.ok
    assert any("duplicate" in e.lower() or "T-01" in e for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# A1-5: check type 非法 → ERROR (fail-closed)
# ---------------------------------------------------------------------------

def test_invalid_check_type():
    """An unknown check type must produce an ERROR (fail-closed)."""
    task_data = _make_valid_task(checks=[{"type": "unknown_type", "path": "x"}])
    tasks = [AtomicTask(**task_data)]
    contract = ProjectContract(
        run_id="run-001", project="p", goal="overall goal",
        created_at="2026-01-01T00:00:00", tasks=tasks,
    )
    result = validate_contract(contract)
    assert not result.ok
    assert any("check" in e.lower() or "type" in e.lower() for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# A1-6: file_contains 缺 text → ERROR
# ---------------------------------------------------------------------------

def test_file_contains_missing_text():
    """A file_contains check without 'text' field must produce an ERROR."""
    task_data = _make_valid_task(checks=[{"type": "file_contains", "path": "x.py"}])
    tasks = [AtomicTask(**task_data)]
    contract = ProjectContract(
        run_id="run-001", project="p", goal="overall goal",
        created_at="2026-01-01T00:00:00", tasks=tasks,
    )
    result = validate_contract(contract)
    assert not result.ok
    assert any("text" in e.lower() or "file_contains" in e.lower() for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# A1-7: prerequisites 悬空 id → ERROR
# ---------------------------------------------------------------------------

def test_dangling_prerequisite():
    """A prerequisite id that doesn't match any task must produce an ERROR."""
    task_data = _make_valid_task(id="T-01", prerequisites=["T-99"])
    tasks = [AtomicTask(**task_data)]
    contract = ProjectContract(
        run_id="run-001", project="p", goal="overall goal",
        created_at="2026-01-01T00:00:00", tasks=tasks,
    )
    result = validate_contract(contract)
    assert not result.ok
    assert any("T-99" in e or "prerequisite" in e.lower() for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# A1-8: evidence_paths 空但 status=done → WARNING
# ---------------------------------------------------------------------------

def test_done_without_evidence_warning():
    """A task with status='done' but no evidence_paths must produce a WARNING."""
    task_data = _make_valid_task(status="done", evidence_paths=[])
    tasks = [AtomicTask(**task_data)]
    contract = ProjectContract(
        run_id="run-001", project="p", goal="overall goal",
        created_at="2026-01-01T00:00:00", tasks=tasks,
    )
    result = validate_contract(contract)
    assert any("evidence" in w.lower() for w in result.warnings), result.warnings


# ---------------------------------------------------------------------------
# A1-9: max_retries 负数 → ERROR
# ---------------------------------------------------------------------------

def test_negative_max_retries():
    """max_retries < 0 must produce an ERROR."""
    task_data = _make_valid_task(max_retries=-1)
    tasks = [AtomicTask(**task_data)]
    contract = ProjectContract(
        run_id="run-001", project="p", goal="overall goal",
        created_at="2026-01-01T00:00:00", tasks=tasks,
    )
    result = validate_contract(contract)
    assert not result.ok
    assert any("retries" in e.lower() or "max_retries" in e.lower() for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# A1-10: 未知字段静默忽略（向前兼容）
# ---------------------------------------------------------------------------

def test_unknown_fields_ignored(tmp_path):
    """Unknown JSON fields in the contract must be silently ignored."""
    data = _make_valid_contract()
    data["unknown_future_field"] = "some_value"
    data["tasks"][0]["another_future_field"] = 42
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    # Should not raise
    contract = load_contract(path)
    assert contract.run_id == "run-2026-001"


# ---------------------------------------------------------------------------
# A1-11: 文件不存在 → FileNotFoundError
# ---------------------------------------------------------------------------

def test_load_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_contract(tmp_path / "nonexistent.json")


# ---------------------------------------------------------------------------
# A1-12: JSON 非法 → ValueError
# ---------------------------------------------------------------------------

def test_load_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("NOT JSON {{", encoding="utf-8")
    with pytest.raises(ValueError):
        load_contract(path)


# ---------------------------------------------------------------------------
# A1-13: status 非法值 → ERROR
# ---------------------------------------------------------------------------

def test_invalid_status():
    """An AtomicTask with an invalid status must produce an ERROR."""
    task_data = _make_valid_task(status="finished")  # not in valid set
    tasks = [AtomicTask(**task_data)]
    contract = ProjectContract(
        run_id="run-001", project="p", goal="overall goal",
        created_at="2026-01-01T00:00:00", tasks=tasks,
    )
    result = validate_contract(contract)
    assert not result.ok
    assert any("status" in e.lower() for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# A1-14: cmd_ok check 缺 cmd 字段 → ERROR
# ---------------------------------------------------------------------------

def test_cmd_ok_missing_cmd():
    """A cmd_ok check without 'cmd' field must produce an ERROR."""
    task_data = _make_valid_task(checks=[{"type": "cmd_ok"}])
    tasks = [AtomicTask(**task_data)]
    contract = ProjectContract(
        run_id="run-001", project="p", goal="overall goal",
        created_at="2026-01-01T00:00:00", tasks=tasks,
    )
    result = validate_contract(contract)
    assert not result.ok
    assert any("cmd" in e.lower() or "cmd_ok" in e.lower() for e in result.errors), result.errors
