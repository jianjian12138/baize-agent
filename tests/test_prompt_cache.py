"""Tests for #79 - prompt-cache-friendly prefix + approximate token accounting.

Acceptance: ① cacheable prefix structure; ② token estimator marked approx;
③ zero dependencies.
"""
from __future__ import annotations

import re

from baize import prompt_cache
from baize.llm import LLMClient, _anthropic_request, ModelSpec


def test_estimate_tokens_is_approximate_and_int():
    n = prompt_cache.estimate_tokens("a" * 40)
    assert isinstance(n, int)
    assert n == 10  # 40 // 4
    # the estimator must self-declare as approximate (NO FAKE DONE)
    assert "APPROXIMATE" in (prompt_cache.estimate_tokens.__doc__ or "").upper()
    assert "approx" in (prompt_cache.estimate_tokens.__doc__ or "").lower()


def test_cacheable_prefix_is_deterministic_and_system_first():
    p = prompt_cache.cacheable_prefix("SYS", [{"name": "x"}])
    assert p[0] == {"role": "system", "content": "SYS"}
    # deterministic: identical inputs -> identical structure
    assert p == prompt_cache.cacheable_prefix("SYS", [{"name": "x"}])
    # stable: the prefix does not leak the conversation
    assert len(p) == 1


def test_build_cacheable_messages_pins_system_first():
    convo = [
        {"role": "system", "content": "STALE"},  # should be collapsed
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    out = prompt_cache.build_cacheable_messages("REAL_SYS", None, convo)
    assert out[0] == {"role": "system", "content": "REAL_SYS"}
    assert out[1]["role"] == "user" and out[1]["content"] == "hi"
    assert out[2]["role"] == "assistant"
    # the stale duplicate system message is gone
    assert sum(1 for m in out if m["role"] == "system") == 1


def test_mark_cacheable_anthropic_vs_openai():
    msgs = [{"role": "system", "content": "S"},
            {"role": "user", "content": "u"}]
    anthropic = prompt_cache.mark_cacheable(msgs, "anthropic")
    # last system block gets the cache_control marker
    assert anthropic[0]["cache_control"] == {"type": "ephemeral"}
    # input is never mutated
    assert "cache_control" not in msgs[0]
    # openai/ollama unchanged
    openai = prompt_cache.mark_cacheable(msgs, "openai")
    assert openai == msgs


def test_anthropic_request_honors_cache_control():
    marked = [{"role": "system", "content": "S",
               "cache_control": {"type": "ephemeral"}},
              {"role": "user", "content": "u"}]
    body = _anthropic_request(ModelSpec(name="m", base_url="https://api.anthropic.com",
                                        api_key="k", provider="anthropic"),
                               marked, None, None)
    assert isinstance(body["system"], list)
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    # legacy: without marker, system is a plain string (no behavior change)
    legacy = [{"role": "system", "content": "S"},
              {"role": "user", "content": "u"}]
    body2 = _anthropic_request(ModelSpec(name="m", base_url="https://api.anthropic.com",
                                         api_key="k", provider="anthropic"),
                                legacy, None, None)
    assert body2["system"] == "S"


def test_default_off_does_not_mark():
    captured = {}

    def transport(url, headers, payload):
        captured["payload"] = payload
        return {"content": [{"type": "text", "text": "ok"}]}

    client = LLMClient(
        cfg={"BAIZE_MODEL_BASE_URL": "https://api.anthropic.com",
             "BAIZE_MODEL_NAME": "claude", "BAIZE_MODEL_API_KEY": "k",
             "BAIZE_PROMPT_CACHE": "0"},
        transport=transport)
    client.chat([{"role": "system", "content": "S"},
                 {"role": "user", "content": "u"}])
    # cache off -> system stays a plain string, no cache_control list
    assert isinstance(captured["payload"]["system"], str)


def test_opt_in_attaches_cache_control():
    captured = {}

    def transport(url, headers, payload):
        captured["payload"] = payload
        return {"content": [{"type": "text", "text": "ok"}]}

    client = LLMClient(
        cfg={"BAIZE_MODEL_BASE_URL": "https://api.anthropic.com",
             "BAIZE_MODEL_NAME": "claude", "BAIZE_MODEL_API_KEY": "k",
             "BAIZE_PROMPT_CACHE": "1"},
        transport=transport)
    client.chat([{"role": "system", "content": "S"},
                 {"role": "user", "content": "u"}], tools=[{"name": "x"}])
    # cache on -> system becomes a cacheable block
    assert isinstance(captured["payload"]["system"], list)
    assert captured["payload"]["system"][0]["cache_control"] == \
        {"type": "ephemeral"}


def test_module_zero_third_party_imports():
    src = open(__import__("baize.prompt_cache", fromlist=["x"]).__file__,
               encoding="utf-8").read()
    forbidden = r"^\s*(import|from)\s+(requests|httpx|yaml|tiktoken|litellm|"
    forbidden += r"anthropic|openai)\b"
    assert re.findall(forbidden, src, re.M) == [], "forbidden import"
