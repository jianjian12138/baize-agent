"""Tests for baize.llm - request building, retry, response parsing.

The transport is injected, so every code path in LLMClient runs for real;
nothing is mocked away with MagicMock.
"""
from __future__ import annotations

import urllib.error

import pytest

from baize.llm import LLMClient, LLMError


def make_client(transport, **cfg_extra):
    cfg = {"BAIZE_MODEL_BASE_URL": "http://fake.local/v1",
           "BAIZE_MODEL_API_KEY": "sk-test",
           "BAIZE_MODEL_NAME": "test-model",
           "BAIZE_LLM_MAX_RETRIES": "1",
           **cfg_extra}
    return LLMClient(cfg=cfg, transport=transport)


def test_unconfigured_raises():
    client = LLMClient(cfg={"BAIZE_MODEL_BASE_URL": "", "BAIZE_MODEL_NAME": ""},
                       transport=lambda *a: {})
    assert not client.configured
    with pytest.raises(LLMError, match="not configured"):
        client.chat([{"role": "user", "content": "hi"}])


def test_chat_builds_request_and_parses():
    captured = {}

    def transport(url, headers, payload):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "hello"}}]}

    client = make_client(transport)
    msg = client.chat([{"role": "user", "content": "hi"}],
                      tools=[{"type": "function"}], temperature=0.2)
    assert msg == {"role": "assistant", "content": "hello"}
    assert captured["url"] == "http://fake.local/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["payload"]["model"] == "test-model"
    assert captured["payload"]["tools"] == [{"type": "function"}]
    assert captured["payload"]["temperature"] == 0.2


def test_tool_calls_passthrough():
    call = {"id": "c1", "function": {"name": "bash", "arguments": "{}"}}

    def transport(url, headers, payload):
        return {"choices": [{"message": {"content": None,
                                         "tool_calls": [call]}}]}

    msg = make_client(transport).chat([{"role": "user", "content": "x"}])
    assert msg["tool_calls"] == [call]


def test_retry_then_success(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    attempts = {"n": 0}

    def transport(url, headers, payload):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise urllib.error.URLError("boom")
        return {"choices": [{"message": {"content": "ok"}}]}

    msg = make_client(transport).chat([{"role": "user", "content": "x"}])
    assert msg["content"] == "ok"
    assert attempts["n"] == 2


def test_retries_exhausted(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)

    def transport(url, headers, payload):
        raise urllib.error.URLError("down")

    with pytest.raises(LLMError, match="model call failed after 2 attempts"):
        make_client(transport).chat([{"role": "user", "content": "x"}])


def test_arbitrary_transport_exception_is_retried_not_leaked(monkeypatch):
    """Regression: a non-URLError exception used to escape and kill the run."""
    monkeypatch.setattr("time.sleep", lambda *_: None)
    attempts = {"n": 0}

    class WeirdError(Exception):
        pass

    def transport(url, headers, payload):
        attempts["n"] += 1
        raise WeirdError("ssl handshake exploded")

    with pytest.raises(LLMError, match="WeirdError"):
        make_client(transport).chat([{"role": "user", "content": "x"}])
    assert attempts["n"] == 2          # retried, not leaked on first failure


def test_malformed_response():
    def transport(url, headers, payload):
        return {"unexpected": True}

    with pytest.raises(LLMError, match="malformed"):
        make_client(transport, BAIZE_LLM_MAX_RETRIES="0").chat(
            [{"role": "user", "content": "x"}])
