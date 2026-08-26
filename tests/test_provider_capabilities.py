"""W2 F5 — provider capability truthfulness, max_tokens, DeepSeek reasoning.

F5 removes the prior "always return {stream:True, tools:True}" fake-green by
keeping the capability map honest (anthropic streaming is now a real SSE; only
capabilities the adapters genuinely implement are reported) and surfaces
DeepSeek ``reasoning_content`` instead of discarding it.
"""
from __future__ import annotations

from baize.llm import LLMClient, ModelSpec, _openai_parse


def _cap(client, provider):
    # provider_capabilities is a staticmethod; build an instance without cfg.
    return client.provider_capabilities(provider)


def test_provider_capabilities_truthful():
    c = LLMClient.__new__(LLMClient)
    openai = _cap(c, "openai")
    assert openai["stream"] is True and openai["tools"] is True
    anthropic = _cap(c, "anthropic")
    assert anthropic["stream"] is True and anthropic["tools"] is True
    deepseek = _cap(c, "deepseek")
    assert deepseek.get("reasoning") is True
    # case-insensitive / substring match for deepseek variants
    assert _cap(c, "DeepSeek-Chat").get("reasoning") is True


def test_max_tokens_parameterized():
    assert ModelSpec(name="a", base_url="http://h").max_tokens == 4096
    assert ModelSpec(name="a", base_url="http://h",
                     max_tokens=2048).max_tokens == 2048


def test_openai_parse_surfaces_reasoning_content():
    raw = {"choices": [{"message": {"content": "answer",
                                    "reasoning_content": "let me think"}}]}
    out = _openai_parse(raw)
    assert out["content"] == "answer"
    assert out["reasoning_content"] == "let me think"


def test_openai_parse_omits_reasoning_when_absent():
    raw = {"choices": [{"message": {"content": "answer"}}]}
    out = _openai_parse(raw)
    assert out["content"] == "answer"
    assert "reasoning_content" not in out
