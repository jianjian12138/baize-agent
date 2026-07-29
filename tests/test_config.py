"""Tests for config loader — real .env file parsing."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baize.config import _parse_env_file, load_config, skill_library_paths  # noqa: E402


def test_parse_env_file_handles_comments_and_quotes(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        '# a comment\n'
        'KEY1=value1\n'
        'KEY2="quoted value"\n'
        "KEY3='single quoted'\n"
        '\n'
        'EMPTY=\n',
        encoding="utf-8",
    )
    data = _parse_env_file(env)
    assert data["KEY1"] == "value1"
    assert data["KEY2"] == "quoted value"
    assert data["KEY3"] == "single quoted"
    assert data["EMPTY"] == ""


def test_parse_env_file_missing_returns_empty(tmp_path):
    assert _parse_env_file(tmp_path / "nonexistent.env") == {}


def test_load_config_merges_defaults_and_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SKILL_LIBRARY_PATHS=D:/lib1,D:/lib2\n", encoding="utf-8")
    cfg = load_config(env)
    assert "D:/lib1" in cfg["SKILL_LIBRARY_PATHS"]
    assert "D:/lib2" in cfg["SKILL_LIBRARY_PATHS"]
    # defaults still present
    assert cfg["TEST_COVERAGE_THRESHOLD"] == "85"


def test_skill_library_paths_parses_comma_list(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SKILL_LIBRARY_PATHS=D:/a, D:/b ,, D:/c\n", encoding="utf-8")
    cfg = load_config(env)
    paths = skill_library_paths(cfg)
    assert len(paths) == 3
    assert paths[0] == Path("D:/a")
    assert paths[2] == Path("D:/c")


def test_skill_library_paths_empty_when_unset():
    cfg = load_config(Path("nonexistent.env"))
    assert skill_library_paths(cfg) == []
