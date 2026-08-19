"""Tests for baize.tools - registry, sandbox confinement, deny-list gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from baize.tools import (ToolRegistry, command_allowed, default_registry,
                         _resolve_in_workspace)


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Point every runtime dir at tmp_path via environment overrides."""
    persistence = tmp_path / "persistence"
    assets = tmp_path / "assets"
    (assets / "skills").mkdir(parents=True)
    persistence.mkdir()
    monkeypatch.setenv("BAIZE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(persistence))
    monkeypatch.setenv("BAIZE_ASSETS_DIR", str(assets))
    monkeypatch.setenv("BAIZE_INDEX_FILE", str(persistence / "skill_index.json"))
    monkeypatch.setenv("BAIZE_USER_SKILLS_DIR", str(tmp_path / "user_skills"))
    monkeypatch.setenv("SKILL_LIBRARY_PATHS", "")
    monkeypatch.setenv("BAIZE_ALLOW_OUTSIDE_WORKSPACE", "0")
    return tmp_path


# -- registry ---------------------------------------------------------------


def test_register_and_execute():
    reg = ToolRegistry()
    reg.register("echo", "echo back", {"type": "object", "properties": {
        "text": {"type": "string"}}, "required": ["text"]},
        lambda text: f"echo:{text}")
    assert reg.names() == ["echo"]
    assert reg.execute("echo", {"text": "hi"}) == "echo:hi"


def test_unknown_tool_and_bad_args():
    reg = ToolRegistry()
    reg.register("f", "d", {"type": "object", "properties": {}},
                 lambda x: x)  # requires x
    assert reg.execute("nope", {}).startswith("ERROR: unknown tool")
    assert reg.execute("f", {}).startswith("ERROR: bad arguments")


def test_tool_exception_becomes_observation():
    reg = ToolRegistry()

    def boom() -> str:
        raise ValueError("kaput")

    reg.register("boom", "d", {"type": "object", "properties": {}}, boom)
    out = reg.execute("boom", {})
    assert out.startswith("ERROR: tool 'boom' failed") and "kaput" in out


def test_schemas_are_openai_shape():
    schemas = default_registry().schemas()
    assert all(s["type"] == "function" for s in schemas)
    names = {s["function"]["name"] for s in schemas}
    assert {"read_file", "write_file", "bash", "search_skills",
            "load_skill", "memory_recall", "memory_log",
            "save_skill"} <= names


# -- sandbox ----------------------------------------------------------------


def test_path_confined_to_workspace(sandbox):
    inside = _resolve_in_workspace("sub/file.txt")
    assert str(inside).startswith(str(sandbox))
    with pytest.raises(PermissionError, match="outside workspace"):
        _resolve_in_workspace(str(sandbox.parent / "escape.txt"))


def test_outside_allowed_when_enabled(sandbox, monkeypatch):
    monkeypatch.setenv("BAIZE_ALLOW_OUTSIDE_WORKSPACE", "1")
    p = _resolve_in_workspace(str(sandbox.parent / "escape.txt"))
    assert p.name == "escape.txt"


def test_deny_list_blocks_destructive_commands():
    for bad in ("rm -rf /", "rm -rf C:", "mkfs.ext4 /dev/sda",
                "shutdown -h now", "dd if=/dev/zero of=/dev/sda"):
        ok, reason = command_allowed(bad)
        assert not ok and "deny pattern" in reason
    ok, _ = command_allowed("ls -la && echo hi")
    assert ok


# -- built-in tools ---------------------------------------------------------


def test_file_tools_roundtrip(sandbox):
    reg = default_registry()
    out = reg.execute("write_file", {"path": "notes/a.txt", "content": "hello"})
    assert "wrote 5 chars" in out
    assert reg.execute("read_file", {"path": "notes/a.txt"}) == "hello"
    listing = reg.execute("list_dir", {"path": "notes"})
    assert "[f] a.txt" in listing


def test_bash_tool_runs_and_blocks(sandbox):
    reg = default_registry()
    out = reg.execute("bash", {"command": "echo baize-ok"})
    assert out.startswith("exit=0") and "baize-ok" in out
    blocked = reg.execute("bash", {"command": "rm -rf /"})
    assert blocked.startswith("ERROR: command rejected")


def test_save_skill_persists_and_indexes(sandbox):
    reg = default_registry()
    out = reg.execute("save_skill", {
        "name": "Deploy Checklist!",
        "description": "steps to deploy safely",
        "body_markdown": "1. test\n2. backup\n3. deploy"})
    assert "skill saved and indexed" in out
    skill_file = (sandbox / "user_skills" / "deploy-checklist" / "SKILL.md")
    assert skill_file.is_file()
    idx = json.loads((sandbox / "persistence" / "skill_index.json")
                     .read_text(encoding="utf-8"))
    assert any(s["name"] == "deploy-checklist" for s in idx["skills"])


def test_memory_tools(sandbox):
    reg = default_registry()
    assert "logged ->" in reg.execute(
        "memory_log", {"text": "unit event alpha", "tags": "unit"})
    out = reg.execute("memory_recall", {"keyword": "alpha", "tags": "unit"})
    assert "unit event alpha" in out
