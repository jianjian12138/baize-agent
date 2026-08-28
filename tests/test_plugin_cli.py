"""Unit tests for Baize plugin management CLI (list, install, remove)."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from baize.cli import cmd_plugins


class DummyArgs:
    def __init__(self, action="list", target=""):
        self.action = action
        self.target = target


def test_plugin_list(capsys):
    args = DummyArgs(action="list")
    ret = cmd_plugins(args)
    assert ret == 0
    out = capsys.readouterr().out
    assert "plugin" in out.lower()


def test_plugin_install_bad_url(capsys):
    args = DummyArgs(action="install", target="invalid-url")
    ret = cmd_plugins(args)
    assert ret == 1
    out = capsys.readouterr().out
    assert "invalid github url" in out.lower()


def test_plugin_remove_not_found(tmp_path, capsys):
    with patch.dict("os.environ", {"BAIZE_USER_SKILLS_DIR": str(tmp_path / "user_skills")}):
        args = DummyArgs(action="remove", target="non_existent_plugin")
        ret = cmd_plugins(args)
        assert ret == 1
        out = capsys.readouterr().out
        assert "not found" in out.lower()
