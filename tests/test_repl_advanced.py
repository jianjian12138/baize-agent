"""Unit tests for Baize V32 Advanced REPL Features (@file ingestion, /cost, /model, /fork, /rewind, multiline)."""
import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from baize.repl import BaizeREPL, _extract_at_files, _format_user_friendly_error
from baize.agent import Session


def test_extract_at_files(tmp_path):
    f1 = tmp_path / "hello.py"
    f1.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")

    text = "Please check @hello.py:2-4 and also @hello.py:1"
    cleaned, attached = _extract_at_files(text, tmp_path)

    assert len(attached) == 2
    att = attached[0]
    assert "lines 2-4" in att["header"]
    assert "line2\nline3\nline4" in att["snippet"]


def test_format_user_friendly_error():
    err1 = "ValueError: unknown url type: '1/chat/completions'"
    msg1 = _format_user_friendly_error(err1)
    assert "接口 Base URL 格式无效" in msg1
    assert "http://" in msg1

    err2 = "HTTP Error 401: Unauthorized"
    msg2 = _format_user_friendly_error(err2)
    assert "身份认证失败" in msg2


def test_repl_cost_dashboard(capsys):
    repl = BaizeREPL(no_color=True, quiet=True)
    repl._init_agent()
    repl.session.append({"role": "user", "content": "hello world"})
    repl.session.append({"role": "assistant", "content": "hi there!"})

    repl.handle_slash("/cost")
    out = capsys.readouterr().out
    assert "Session Resource & Cost Dashboard" in out
    assert "Est. Total Tokens" in out


def test_repl_model_hot_switch(capsys):
    repl = BaizeREPL(no_color=True, quiet=True)
    repl._init_agent()

    repl.handle_slash("/model deepseek-reasoner")
    out = capsys.readouterr().out
    assert "Switched active model to: deepseek-reasoner" in out
    assert os.environ.get("BAIZE_MODEL_NAME") == "deepseek-reasoner"


def test_repl_fork_and_rewind(tmp_path, capsys):
    repl = BaizeREPL(no_color=True, quiet=True)
    repl._init_agent()

    # Add 2 turns
    repl.session.append({"role": "user", "content": "turn 1"})
    repl.session.append({"role": "assistant", "content": "ans 1"})
    repl.session.append({"role": "user", "content": "turn 2"})
    repl.session.append({"role": "assistant", "content": "ans 2"})

    assert len(repl.session.messages) == 4

    # Test Fork
    repl.handle_slash("/fork branch_exp")
    out = capsys.readouterr().out
    assert "Parallel session forked: branch_exp" in out
    assert repl.session.id == "branch_exp"
    assert len(repl.session.messages) == 4

    # Test Rewind 1 turn
    repl.handle_slash("/rewind 1")
    out = capsys.readouterr().out
    assert "Rewound 1 turn(s)" in out
    assert len(repl.session.messages) == 2
    assert repl.session.messages[-1]["content"] == "ans 1"


def test_repl_paste_mode(capsys):
    repl = BaizeREPL(no_color=True, quiet=True)
    repl._init_agent()

    with patch("baize.repl.input", side_effect=["def foo():", "    return 42", "/end"]):
        repl.handle_slash("/paste")

    # If client is not configured, it emits tip
    out = capsys.readouterr().out
    assert "Multi-line Paste Mode" in out
