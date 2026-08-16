"""Tests for V21 P1-4 honest skill self-evolution."""
import json

from baize import rag
from baize.config import load_config
from baize.skill_runner import SkillRunner, verify_skill_draft
from baize.tools import default_registry


def _cfg(tmp_path, monkeypatch):
    cfg = load_config()
    for k, v in {
        "BAIZE_PERSISTENCE_DIR": str(tmp_path / "persistence"),
        "BAIZE_SESSIONS_DIR": str(tmp_path / "sessions"),
        "BAIZE_WORKSPACE_DIR": str(tmp_path / "workspace"),
        "BAIZE_ASSETS_DIR": str(tmp_path / "assets"),
        "BAIZE_INDEX_FILE": str(tmp_path / "skill_index.json"),
        "BAIZE_TEAM_MEMORY_BACKEND": "local",
    }.items():
        monkeypatch.setenv(k, v)
        cfg[k] = v
    return cfg


# --- rubric gate ------------------------------------------------------------

def test_verify_rejects_missing_name():
    ok, reasons = verify_skill_draft({"steps": [{"tool": "read_file"}],
                                      "dependencies": []})
    assert not ok
    assert any("name" in r for r in reasons)


def test_verify_rejects_path_in_name():
    ok, reasons = verify_skill_draft({"name": "../evil", "steps": [],
                                      "dependencies": []})
    assert not ok


def test_verify_rejects_unknown_tool():
    ok, reasons = verify_skill_draft({
        "name": "bad", "steps": [{"tool": "no_such_tool"}],
        "dependencies": []})
    assert not ok
    assert any("unknown tool" in r for r in reasons)


def test_verify_rejects_missing_dependencies():
    ok, reasons = verify_skill_draft({"name": "x", "steps": [{"tool": "read_file"}]})
    assert not ok
    assert any("dependencies" in r for r in reasons)


def test_verify_accepts_valid_draft():
    ok, reasons = verify_skill_draft({
        "name": "reader", "steps": [{"tool": "read_file", "args": {"path": "a.txt"}}],
        "dependencies": []})
    assert ok, reasons


# --- real execution path + record_skill_outcome call site -------------------

def test_run_records_outcome_on_success(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    reg = default_registry()
    runner = SkillRunner(cfg=cfg, registry=reg)
    draft = {
        "name": "make-and-check",
        "steps": [{"tool": "write_file",
                   "args": {"path": "hello.txt", "content": "hi"}}],
        "verify": [{"type": "file_exists", "path": "hello.txt"}],
        "dependencies": [],
    }
    res = runner.run(draft)
    assert res["success"] is True
    scores = rag.skill_scores(cfg=cfg)
    assert scores["make-and-check"]["uses"] == 1
    assert scores["make-and-check"]["successes"] == 1
    assert scores["make-and-check"]["success_rate"] == 1.0


def test_run_records_outcome_on_failure(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    runner = SkillRunner(cfg=cfg)
    draft = {
        "name": "fails-check",
        "steps": [{"tool": "write_file",
                   "args": {"path": "real.txt", "content": "x"}}],
        "verify": [{"type": "file_exists", "path": "does-not-exist.txt"}],
        "dependencies": [],
    }
    res = runner.run(draft)
    assert res["success"] is False
    scores = rag.skill_scores(cfg=cfg)
    # honest: recorded as a use with 0 successes
    assert scores["fails-check"]["uses"] == 1
    assert scores["fails-check"]["success_rate"] == 0.0


def test_run_no_verify_is_fail_closed(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    runner = SkillRunner(cfg=cfg)
    draft = {"name": "blind", "steps": [{"tool": "read_file",
                                         "args": {"path": "a.txt"}}],
             "dependencies": []}
    res = runner.run(draft)
    assert res["success"] is False
    assert "no verification" in res["evidence"]


def test_run_skill_tool_is_real_call_site(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    reg = default_registry()
    draft = {
        "name": "via-tool",
        "steps": [{"tool": "write_file",
                   "args": {"path": "via.txt", "content": "v"}}],
        "verify": [{"type": "file_contains", "path": "via.txt", "text": "v"}],
        "dependencies": [],
    }
    out = reg.execute("run_skill", {
        "name": "via-tool",
        "steps_json": json.dumps(draft["steps"]),
        "verify_json": json.dumps(draft["verify"]),
        "dependencies_json": json.dumps(draft["dependencies"]),
    })
    assert "success=True" in out
    scores = rag.skill_scores(cfg=cfg)
    assert scores["via-tool"]["uses"] == 1


def test_run_skill_tool_rejects_bad_draft(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    reg = default_registry()
    out = reg.execute("run_skill", {"name": "x"})  # missing steps + dependencies
    assert "rejected" in out


# --- zero-dependency guard --------------------------------------------------

def test_skill_runner_is_stdlib_only():
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "baize" / "skill_runner.py"
    text = src.read_text(encoding="utf-8")
    assert "import yaml" not in text
    assert "import httpx" not in text
