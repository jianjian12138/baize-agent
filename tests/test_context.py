"""Tests for #77 - evidence-preserving context compression + tiered memory.

The core regression guard: compression must KEEP Verifier evidence (verdict /
error signal), never blindly discard it (risk #3).
"""
from __future__ import annotations

from baize import context
from baize.agent import compress_context

KEEP = 8


def _tool_msgs(n, content):
    return [{"role": "tool", "content": content} for _ in range(n)]


def test_compress_context_preserves_verdict():
    long = "x" * 600 + ' {"verdict":"pass","evidence":"tests green"} tail'
    msgs = _tool_msgs(20, long)
    n = compress_context(msgs, keep_recent=KEEP)
    assert n == 12, f"expected 12 compressed, got {n}"
    # the OLD (compressed) message still carries the verdict signal
    assert "verdict=pass" in msgs[0]["content"]
    assert "compressed old observation" in msgs[0]["content"]
    # recent messages are untouched
    assert msgs[15]["content"].startswith("x" * 10)


def test_compress_context_detects_errors():
    long = "z" * 600 + " Traceback (most recent call last): something failed"
    msgs = _tool_msgs(10, long)
    compress_context(msgs, keep_recent=KEEP)
    assert "errors=yes" in msgs[0]["content"]


def test_compress_context_keeps_recent_verbatim():
    # when total <= keep_recent nothing is compressed
    msgs = _tool_msgs(5, "y" * 600 + " verdict fail")
    n = compress_context(msgs, keep_recent=KEEP)
    assert n == 0
    assert msgs[0]["content"] == "y" * 600 + " verdict fail"  # untouched, full text


def test_extract_evidence_finds_verdict_and_error():
    msgs = [
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": '{"verdict":"pass","evidence":"ok"}'},
        {"role": "tool", "content": "ERROR: boom"},
    ]
    ev = context.extract_evidence(msgs)
    assert any("verdict" in v.lower() for v in ev["verdicts"])
    assert ev["errors"] >= 1
    assert ev["goals"] == ["do the thing"]


def test_tiered_memory_hot_warm_cold():
    tm = context.TieredMemory(hot_limit=3)
    for i in range(10):
        tm.push({"role": "user", "content": f"goal {i} " * 4})
    # hot is capped
    assert len(tm.hot) == 3
    # demoted messages produced structured evidence and/or warm summaries
    assert tm.cold["goals"] or tm.warm
    snap = tm.snapshot()
    # hot verbatim survives in the snapshot
    assert any(m.get("content", "").startswith("goal 9") for m in tm.hot)
    # snapshot carries a system note (warm summary or cold evidence)
    assert any(m["role"] == "system" for m in snap)


def test_tiered_memory_persist_load(tmp_path):
    p = tmp_path / "cold.json"
    tm = context.TieredMemory(hot_limit=2, path=str(p))
    tm.push({"role": "assistant",
             "content": "result summary verdict pass evidence ok"})
    for i in range(6):
        tm.push({"role": "user", "content": f"goal {i}"})
    tm.persist()
    assert p.exists()
    tm2 = context.TieredMemory(hot_limit=2, path=str(p))
    assert any("pass" in v.lower() for v in tm2.cold["verdicts"]), tm2.cold


def test_module_zero_third_party_imports():
    import re
    src = open(__import__("baize.context", fromlist=["x"]).__file__,
               encoding="utf-8").read()
    forbidden = r"^\s*(import|from)\s+(requests|httpx|yaml|tiktoken|litellm|"
    forbidden += r"anthropic|openai)\b"
    assert re.findall(forbidden, src, re.M) == [], "forbidden import"
