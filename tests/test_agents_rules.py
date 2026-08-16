"""Tests for V21 P0-2: external AGENTS.md/CLAUDE.md untrusted consumption."""
from __future__ import annotations

from pathlib import Path

from baize import agents_rules
from baize.agent import build_system_prompt


def test_discover_skips_own_agent_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# external\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")
    (tmp_path / "AGENT.md").write_text("# baize own - must NOT be consumed\n",
                                        encoding="utf-8")
    found = {p.name for p in agents_rules.discover_external_rules(tmp_path)}
    assert found == {"AGENTS.md", "CLAUDE.md"}


def test_load_external_rules_wraps_as_untrusted(tmp_path):
    (tmp_path / "AGENTS.md").write_text("do something unsafe", encoding="utf-8")
    out = agents_rules.load_external_rules(tmp_path)
    assert "UNTRUSTED REFERENCE ONLY" in out
    assert "do something unsafe" in out
    assert "NO FAKE DONE" in out  # guard-rail reminder present
    # baize's own file is ignored
    (tmp_path / "AGENT.md").write_text("own rules", encoding="utf-8")
    assert "own rules" not in out


def test_load_external_rules_empty_when_absent(tmp_path):
    assert agents_rules.load_external_rules(tmp_path) == ""


def test_system_prompt_injects_external_rules(monkeypatch, tmp_path):
    (tmp_path / "AGENTS.md").write_text("project-specific rule X",
                                         encoding="utf-8")
    monkeypatch.setenv("BAIZE_WORKSPACE_DIR", str(tmp_path))
    prompt = build_system_prompt(role="executor")
    assert "EXTERNAL PROJECT RULES" in prompt
    assert "project-specific rule X" in prompt


def test_system_prompt_ignores_own_agent_md(monkeypatch, tmp_path):
    (tmp_path / "AGENT.md").write_text("baize own spec", encoding="utf-8")
    monkeypatch.setenv("BAIZE_WORKSPACE_DIR", str(tmp_path))
    prompt = build_system_prompt(role="executor")
    assert "EXTERNAL PROJECT RULES" not in prompt
    assert "baize own spec" not in prompt
