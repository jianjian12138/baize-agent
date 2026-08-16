"""Tests for baize.sessions - fork + extractive compression (P2-4).

Zero-dependency. We build real Session transcripts on disk (via the public
Session API) and assert fork isolation + compression evidence preservation.
UI renderers (dashboard HTML + ui.py text) are asserted for real content.
"""
from __future__ import annotations

import re

from baize import sessions as S
from baize.agent import Session
from baize import ui
from baize import dashboard


def _build(tmp_path, msgs):
    """Create a session under tmp_path with the given message dicts."""
    cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions")}
    s = Session(cfg=cfg)
    for m in msgs:
        s.append(m)
    return s


def test_fork_creates_independent_session(tmp_path):
    s = _build(tmp_path, [
        {"role": "user", "content": "goal A"},
        {"role": "assistant", "content": "step 1"},
        {"role": "user", "content": "goal B"},
        {"role": "assistant", "content": "step 2"},
    ])
    new_id = S.fork_session(s.id, 2, cfg={"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions")})
    assert new_id != s.id
    child = Session(session_id=new_id,
                    cfg={"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions")})
    assert len(child.messages) == 2
    assert child.messages[0]["content"] == "goal A"
    assert child.messages[1]["content"] == "step 1"


def test_fork_does_not_mutate_parent(tmp_path):
    cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions")}
    s = _build(tmp_path, [{"role": "user", "content": "p1"},
                          {"role": "assistant", "content": "p2"}])
    before = len(s.messages)
    S.fork_session(s.id, 1, cfg=cfg)
    assert len(Session(session_id=s.id, cfg=cfg).messages) == before


def test_fork_records_lineage(tmp_path):
    cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions")}
    s = _build(tmp_path, [{"role": "user", "content": "x"}])
    new_id = S.fork_session(s.id, 1, cfg=cfg)
    lineage = S.list_lineage(cfg=cfg)
    assert new_id in lineage
    assert lineage[new_id]["parent"] == s.id
    assert lineage[new_id]["at_index"] == 1


def test_fork_at_index_clamped(tmp_path):
    cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions")}
    s = _build(tmp_path, [{"role": "user", "content": "x"},
                          {"role": "assistant", "content": "y"}])
    # at_index beyond length -> clamps to full length, no crash
    new_id = S.fork_session(s.id, 999, cfg=cfg)
    child = Session(session_id=new_id, cfg=cfg)
    assert len(child.messages) == 2


def test_fork_unknown_parent_raises(tmp_path):
    cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions")}
    try:
        S.fork_session("does-not-exist", 0, cfg=cfg)
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def _evidence_session(tmp_path):
    cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions")}
    s = Session(cfg=cfg)
    s.append({"role": "user", "content": "build the feature"})
    # a long middle that should be compressible
    for i in range(20):
        s.append({"role": "assistant", "content": f"intermediate thinking {i}" * 5})
    # verifier evidence at the tail
    s.append({"role": "user", "content": "verify"})
    s.append({"role": "assistant", "content":
              '{"verdict":"pass","evidence":"tests green"}'})
    return s, cfg


def test_compress_preserves_evidence_and_counts_tokens(tmp_path):
    s, cfg = _evidence_session(tmp_path)
    rep = S.compress_session(s.id, cfg=cfg)
    assert rep["before_tokens"] > 0
    assert rep["after_tokens"] <= rep["before_tokens"]
    assert rep["saved_tokens"] == rep["before_tokens"] - rep["after_tokens"]
    summ = rep["summary"]
    assert summ["total_messages"] == len(s.messages)
    # evidence preserved
    assert any("build the feature" in g for g in summ["goals"])
    assert any("verdict" in v.lower() for v in summ["verdicts"])
    assert summ["roles"].get("user") == 2
    # retained messages = head + tail only
    assert summ["retained_messages"] == (4 + 8)


def test_compress_unknown_session_raises(tmp_path):
    cfg = {"BAIZE_SESSIONS_DIR": str(tmp_path / "sessions")}
    try:
        S.compress_session("nope", cfg=cfg)
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_ui_fork_tree_renders():
    lineage = {
        "a": {"parent": None, "at_index": None, "created_at": "t"},
        "b": {"parent": "a", "at_index": 2, "created_at": "t"},
        "c": {"parent": "a", "at_index": 5, "created_at": "t"},
    }
    txt = ui.render_fork_tree(lineage)
    assert "a" in txt and "b" in txt and "c" in txt
    assert "fork @#2" in txt
    assert "会话分叉树" in txt


def test_ui_compress_report_renders():
    rep = {
        "session_id": "x", "before_tokens": 1000, "after_tokens": 200,
        "saved_tokens": 800, "compression_ratio": 0.2,
        "retained_messages": 12,
        "summary": {"total_messages": 30, "roles": {"user": 3},
                    "goals": ["build"], "tool_calls": ["bash"],
                    "verdicts": ['{"verdict":"pass"}'], "errors": 1},
    }
    txt = ui.render_compress_report(rep)
    assert "1000" in txt and "200" in txt and "800" in txt
    assert "build" in txt and "bash" in txt and "pass" in txt


def test_dashboard_contains_fork_and_compress_controls():
    html = dashboard.render("20.0.0")
    assert "会话分支" in html
    assert 'id="forkform"' in html
    assert 'id="compressform"' in html
    assert "/sessions/fork" in html
    assert "/sessions/compress" in html
    # JS handlers wired
    assert "forkform" in html and "compressform" in html


def test_stdlib_only_no_third_party_imports():
    src = open(__import__("baize.sessions", fromlist=["x"]).__file__,
               encoding="utf-8").read()
    forbidden = r"^\s*(import|from)\s+(requests|httpx|yaml|tiktoken|litellm|"
    forbidden += r"anthropic|openai)\b"
    assert re.findall(forbidden, src, re.M) == [], "forbidden import"
