"""Unit tests for Baize Interactive REPL / Chat terminal."""
import pytest
from io import StringIO
from unittest.mock import patch, MagicMock

from baize.repl import BaizeREPL, run_repl
from baize.agent import AgentResult, Session


def test_repl_init_and_banner(capsys):
    repl = BaizeREPL(no_color=True, quiet=True)
    assert repl.session is None
    repl._init_agent()
    assert repl.session is not None
    assert repl.session_id == repl.session.id

    repl.print_banner()
    captured = capsys.readouterr()
    assert "Baize Agent Autonomous Engine" in captured.out


def test_repl_slash_help(capsys):
    repl = BaizeREPL(no_color=True, quiet=True)
    repl._init_agent()
    repl.handle_slash("/help")
    out = capsys.readouterr().out
    assert "/reset" in out
    assert "/skills" in out
    assert "/memory" in out


def test_repl_slash_reset(capsys):
    repl = BaizeREPL(no_color=True, quiet=True)
    repl._init_agent()
    old_id = repl.session_id
    repl.handle_slash("/reset")
    out = capsys.readouterr().out
    assert "Started new session" in out
    assert repl.session_id != old_id


def test_repl_slash_status_and_model(capsys):
    repl = BaizeREPL(no_color=True, quiet=True)
    repl._init_agent()
    repl.handle_slash("/status")
    out = capsys.readouterr().out
    assert "Current Session:" in out

    repl.handle_slash("/model")
    out = capsys.readouterr().out
    assert "LLM Configuration:" in out


def test_repl_slash_skills_and_memory(tmp_path, capsys):
    repl = BaizeREPL(no_color=True, quiet=True)
    repl._init_agent()
    repl.handle_slash("/skills")
    out = capsys.readouterr().out
    assert "Available Skills" in out or "No skills" in out

    repl.handle_slash("/memory")
    out = capsys.readouterr().out
    assert "Memory Stats:" in out


def test_repl_slash_history_and_quit(capsys):
    repl = BaizeREPL(no_color=True, quiet=True)
    repl._init_agent()
    repl.handle_slash("/history")
    out = capsys.readouterr().out
    assert "Recent Sessions:" in out or "No previous sessions" in out

    assert repl.running is True
    repl.handle_slash("/quit")
    assert repl.running is False


def test_repl_run_loop_with_mocked_inputs(capsys):
    inputs = ["/help", "/status", "/quit"]
    repl = BaizeREPL(no_color=True, quiet=True)
    with patch("builtins.input", side_effect=inputs):
        code = repl.run()
        assert code == 0
    out = capsys.readouterr().out
    assert "Baize Agent Autonomous Engine" in out


def test_repl_double_ctrl_c_exits(capsys):
    # Simulate pressing Ctrl+C twice in rapid succession
    repl = BaizeREPL(no_color=True, quiet=True)
    with patch("builtins.input", side_effect=[KeyboardInterrupt, KeyboardInterrupt]):
        code = repl.run()
        assert code == 0
    out = capsys.readouterr().out
    assert "Goodbye" in out
