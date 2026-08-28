"""Unit tests for Autonomous Skill Harvester (V31 closed-loop learning)."""
import pytest
from pathlib import Path
from baize.agent import AgentResult
from baize.skill_harvester import SkillHarvester, _slugify


def test_slugify():
    assert _slugify("Write Unit Tests for Auth Module!") == "write-unit-tests-for-auth-module"
    assert _slugify("  ") != ""


def test_harvester_should_harvest_heuristics():
    harvester = SkillHarvester()

    # Fail: not final
    r_error = AgentResult("s1", "error msg", 5, 3, "error", [])
    assert harvester.should_harvest(r_error) is False

    # Fail: empty output
    r_empty = AgentResult("s2", "   ", 5, 3, "final", [])
    assert harvester.should_harvest(r_empty) is False

    # Fail: 0 tool calls
    r_no_tools = AgentResult("s3", "Valid final text explanation", 2, 0, "final", [
        {"role": "assistant", "content": "Just talking"}
    ])
    assert harvester.should_harvest(r_no_tools) is False

    # Success: non-trivial task with tool calls and final text
    r_good = AgentResult("s4", "Successfully implemented and verified tests in test_auth.py", 4, 3, "final", [
        {"role": "user", "content": "TASK: Write comprehensive unit tests for auth"},
        {"role": "assistant", "tool_calls": [{"function": {"name": "read_file", "arguments": '{"path": "auth.py"}'}}]},
        {"role": "tool", "content": "def authenticate(): pass"},
        {"role": "assistant", "tool_calls": [{"function": {"name": "write_file", "arguments": '{"path": "test_auth.py"}'}}]},
        {"role": "tool", "content": "wrote 200 bytes"},
        {"role": "assistant", "content": "Successfully implemented and verified tests in test_auth.py"},
    ])
    assert harvester.should_harvest(r_good) is True


def test_harvester_extraction_and_harvest(tmp_path):
    cfg = {"BAIZE_USER_SKILLS_DIR": str(tmp_path / "user_skills")}
    harvester = SkillHarvester(cfg=cfg)

    r = AgentResult("s5", "Refactored user database migration script with zero data loss.", 5, 2, "final", [
        {"role": "user", "content": "TASK: Refactor DB Migration"},
        {"role": "assistant", "tool_calls": [{"function": {"name": "read_file", "arguments": '{"path": "mig.py"}'}}]},
        {"role": "tool", "content": "db code"},
        {"role": "assistant", "tool_calls": [{"function": {"name": "bash", "arguments": '{"command": "pytest"}'}}]},
        {"role": "tool", "content": "2 passed"},
        {"role": "assistant", "content": "Refactored user database migration script with zero data loss."},
    ])

    spec = harvester.extract_skill_spec(r, goal="Refactor DB Migration")
    assert "name" in spec
    assert "agentskills" not in spec["content"] # standard YAML frontmatter tags present
    assert "harnesses: [baize, hermes, codex]" in spec["content"]

    skill_path = harvester.harvest(r, goal="Refactor DB Migration")
    assert skill_path is not None
    assert skill_path.exists()
    content = skill_path.read_text(encoding="utf-8")
    assert "auto-refactor-db-migration" in content
    assert "read_file, bash" in content
