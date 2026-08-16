"""Tests for V21 P2-1 Plan Mode + autonomy slider."""
import json

from baize import autonomy as autonomy_mod
from baize.agent import Agent
from baize.config import load_config
from baize.llm import LLMClient

AutonomyPolicy = autonomy_mod.AutonomyPolicy


def _cfg(tmp_path, monkeypatch):
    cfg = load_config()
    for k, v in {
        "BAIZE_PERSISTENCE_DIR": str(tmp_path / "persistence"),
        "BAIZE_SESSIONS_DIR": str(tmp_path / "sessions"),
        "BAIZE_WORKSPACE_DIR": str(tmp_path / "workspace"),
        "BAIZE_ASSETS_DIR": str(tmp_path / "assets"),
        "BAIZE_INDEX_FILE": str(tmp_path / "skill_index.json"),
        "BAIZE_TEAM_MEMORY_BACKEND": "local",
        "BAIZE_MODEL_BASE_URL": "http://127.0.0.1:1/v1",
        "BAIZE_MODEL_NAME": "test-model",
        "BAIZE_MODEL_API_KEY": "test-key",
    }.items():
        monkeypatch.setenv(k, v)
        cfg[k] = v
    return cfg


def scripted_client(cfg, replies):
    queue = list(replies)

    def transport(url, headers, payload):
        return {"choices": [{"message": queue.pop(0)}]}
    return LLMClient(cfg=cfg, transport=transport)


# --- AutonomyPolicy unit ----------------------------------------------------

def test_supervised_allows_readonly_only():
    p = AutonomyPolicy(level="supervised")
    assert p.allow("read_file", {})[0] is True
    assert p.allow("write_file", {})[0] is False
    assert p.allow("bash", {})[0] is False


def test_balanced_blocks_dangerous_but_allows_write():
    p = AutonomyPolicy(level="balanced")
    assert p.allow("write_file", {})[0] is True
    assert p.allow("run_skill", {})[0] is False
    ok, _ = p.allow("bash", {"command": "rm -rf /"})
    assert ok is False
    ok, _ = p.allow("bash", {"command": "echo hi"})
    assert ok is True


def test_autonomous_allows_everything():
    p = AutonomyPolicy(level="autonomous")
    assert p.allow("bash", {"command": "rm -rf /"})[0] is True
    assert p.allow("run_skill", {})[0] is True


def test_cost_cap_forces_downgrade():
    p = AutonomyPolicy(level="autonomous", cost_cap=10)
    assert p.allow("write_file", {})[0] is True
    p.record_cost(100)  # exceed the tiny cap
    assert p.downgraded is True
    assert p.level == "supervised"
    # now even write_file is denied
    assert p.allow("write_file", {})[0] is False


def test_supervised_approver_can_grant():
    p = AutonomyPolicy(level="supervised", approver=lambda t, a: t == "write_file")
    assert p.allow("write_file", {})[0] is True
    assert p.allow("bash", {})[0] is False


# --- Plan Mode in the Agent loop --------------------------------------------

def test_plan_mode_blocks_write_tool(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    # scripted: first call write_file (should be blocked), then answer
    replies = [
        {"content": "", "tool_calls": [{"id": "1", "function": {
            "name": "write_file",
            "arguments": json.dumps({"path": "x.txt", "content": "y"})}}]},
        {"content": "Here is my plan: write the file after approval."},
    ]
    agent = Agent(role="executor", cfg=cfg, client=scripted_client(cfg, replies),
                  plan_mode=True)
    res = agent.run("draft a plan")
    transcript = res.transcript
    blocked = any("blocked by policy: plan mode" in str(m.get("content", ""))
                  for m in transcript if m.get("role") == "tool")
    assert blocked
    assert res.stopped_reason == "final"


def test_plan_mode_allows_read_tool(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "a.txt").write_text("hello", encoding="utf-8")
    replies = [
        {"content": "", "tool_calls": [{"id": "1", "function": {
            "name": "read_file",
            "arguments": json.dumps({"path": "a.txt"})}}]},
        {"content": "I read the file."},
    ]
    agent = Agent(role="executor", cfg=cfg, client=scripted_client(cfg, replies),
                  plan_mode=True)
    res = agent.run("explore")
    contents = [str(m.get("content", "")) for m in res.transcript
                if m.get("role") == "tool"]
    assert any("hello" in c for c in contents)


def test_agent_autonomy_supervised_blocks_bash(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    replies = [
        {"content": "", "tool_calls": [{"id": "1", "function": {
            "name": "bash",
            "arguments": json.dumps({"command": "echo hi"})}}]},
        {"content": "done"},
    ]
    agent = Agent(role="executor", cfg=cfg, client=scripted_client(cfg, replies),
                  autonomy="supervised")
    res = agent.run("run a command")
    blocked = any("blocked by policy" in str(m.get("content", ""))
                  for m in res.transcript if m.get("role") == "tool")
    assert blocked


def test_autonomy_module_is_stdlib_only():
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "baize" / "autonomy.py"
    assert "import httpx" not in src.read_text(encoding="utf-8")
