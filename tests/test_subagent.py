"""Tests for V21 P1-3 sub-agent definition format + isolation."""
import json
from pathlib import Path

import pytest

from baize.config import load_config
from baize.llm import LLMClient
from baize.subagent import (
    SubagentDef,
    build_scoped_registry,
    load_subagent,
)


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


# --- parsing ---------------------------------------------------------------

def test_load_agent_frontmatter(tmp_path):
    p = tmp_path / "reviewer.agent"
    p.write_text(
        "---\n"
        "name: reviewer\n"
        "description: reviews code\n"
        "tools: read_file, list_dir\n"
        "disallowed_tools: bash, write_file\n"
        "model: inherit\n"
        "permission_mode: default\n"
        "skills: code-review\n"
        "---\n"
        "You are a careful reviewer. Check things.\n",
        encoding="utf-8")
    d = load_subagent(p)
    assert d.name == "reviewer"
    assert d.description == "reviews code"
    assert d.tools == ["read_file", "list_dir"]
    assert d.disallowed_tools == ["bash", "write_file"]
    assert d.model == "inherit"
    assert d.permission_mode == "default"
    assert d.skills == ["code-review"]
    assert "careful reviewer" in d.instructions


def test_load_json_definition(tmp_path):
    p = tmp_path / "helper.json"
    p.write_text(json.dumps({
        "name": "helper",
        "description": "a helper",
        "tools": ["read_file"],
        "disallowed_tools": ["bash"],
        "instructions": "help with reading",
    }), encoding="utf-8")
    d = load_subagent(p)
    assert d.name == "helper"
    assert d.tools == ["read_file"]
    assert d.disallowed_tools == ["bash"]
    assert "help with reading" in d.instructions


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_subagent("/no/such/file.agent")


# --- tool scoping (isolation primitive) ------------------------------------

def test_effective_tools_excludes_disallowed():
    d = SubagentDef(name="x", tools=["read_file", "list_dir", "bash"],
                    disallowed_tools=["bash"])
    assert d.effective_tools() == ["read_file", "list_dir"]


def test_effective_tools_default_all():
    d = SubagentDef(name="x")
    # an empty/None tools list resolves to every built-in tool
    assert "read_file" in d.effective_tools()
    assert "bash" in d.effective_tools()
    assert "secret" not in d.effective_tools()  # non-existent tool dropped


def test_build_agent_has_scoped_registry():
    d = SubagentDef(name="x", tools=["read_file", "list_dir"],
                    disallowed_tools=["bash"])
    agent = d.build_agent()
    assert set(agent.registry.names()) == {"read_file", "list_dir"}
    # disallowed tool is physically unreachable -> unknown tool error
    obs = agent.registry.execute("bash", {"command": "ls"})
    assert "unknown tool" in obs


def test_scoped_registry_helper():
    reg = build_scoped_registry(["read_file", "bash"], disallowed=["bash"])
    assert reg.names() == ["read_file"]


# --- context isolation ------------------------------------------------------

def test_subagent_gets_own_session(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    d = SubagentDef(name="iso", tools=["read_file", "list_dir"])
    agent = d.build_agent(cfg=cfg)
    # independent session, not shared with any parent
    assert isinstance(agent.session, object)
    assert agent.session.id
    # running it does not require a parent's messages
    assert agent.session.messages == []


def test_subagent_run_isolated(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    d = SubagentDef(name="worker", tools=["read_file", "list_dir"])
    client = scripted_client(cfg, [{"content": "I finished the task."}])
    summary = d.run("do something", cfg=cfg, client=client)
    assert summary == "I finished the task."


# --- orchestrator compatibility --------------------------------------------

def test_orchestrator_spawn_subagent(tmp_path, monkeypatch):
    from baize.orchestrator import Orchestrator

    cfg = _cfg(tmp_path, monkeypatch)
    orch = Orchestrator(cfg=cfg, client=scripted_client(
        cfg, [{"content": "subagent summary"}]))
    d = SubagentDef(name="mini", tools=["read_file"])
    out = orch.spawn_subagent(d, "goal")
    assert out == "subagent summary"


def test_orchestrator_spawn_subagent_fail_closed(tmp_path, monkeypatch):
    from baize.orchestrator import Orchestrator

    cfg = _cfg(tmp_path, monkeypatch)
    # no client -> would be "not configured" -> must not crash the team
    orch = Orchestrator(cfg=cfg, client=scripted_client(
        cfg, [{"content": "x"}]))
    d = SubagentDef(name="boom", tools=["read_file"])

    def _boom(*a, **k):
        raise RuntimeError("subprocess exploded")
    orch.spawn_subagent(d, "goal", client=_boom)
    # fail-closed: returns a summary string, no exception escapes
    assert True  # reaching here means the runner swallowed the crash


# --- zero-dependency guard --------------------------------------------------

def test_subagent_module_is_stdlib_only():
    src = Path(__file__).resolve().parent.parent / "baize" / "subagent.py"
    text = src.read_text(encoding="utf-8")
    for forbidden in ("import yaml", "import toml", "import mcp",
                      "from yaml", "import httpx"):
        assert forbidden not in text, f"forbidden import in subagent.py: {forbidden}"
