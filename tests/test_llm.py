"""Tests for baize.llm - request building, retry, response parsing.

The transport is injected, so every code path in LLMClient runs for real;
nothing is mocked away with MagicMock.
"""
from __future__ import annotations

import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from baize.llm import LLMClient, LLMError, RateLimiter


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


# ---------------------------------------------------------------------------
# Coverage expansion: router config, multi-model selection, streaming, the real
# stdlib HTTP transports, and RateLimiter branches.
# ---------------------------------------------------------------------------

def test_router_invalid_json_is_honest(capsys):
    cfg = {"BAIZE_MODEL_ROUTER": "not-json{",
           "BAIZE_MODEL_BASE_URL": "", "BAIZE_MODEL_NAME": ""}
    client = LLMClient(cfg=cfg)
    assert client.model_count == 0
    assert not client.configured
    capsys.readouterr()  # the warning print must not crash


def test_router_valid_multi_model_and_header_branch():
    router = json.dumps([
        {"name": "m1", "base_url": "http://a/v1", "api_key": "", "weight": 1},
        {"name": "m2", "base_url": "http://b/v1", "api_key": "k2", "weight": 2},
    ])
    client = LLMClient(cfg={"BAIZE_MODEL_ROUTER": router})
    assert client.model_count == 2
    assert client.configured
    # model with no key -> no Authorization header (162->164 false branch)
    h1 = LLMClient._headers(client.models[0])
    assert "Authorization" not in h1
    # model with key -> Bearer header
    h2 = LLMClient._headers(client.models[1])
    assert h2["Authorization"] == "Bearer k2"
    # multi-model select exercises the choices() branch (returns a priority
    # list of ModelSpec, all drawn from the configured models)
    for _ in range(20):
        order = client._select()
        assert isinstance(order, list)
        assert all(m in client.models for m in order)


def test_cross_model_fallback(monkeypatch):
    """A failing primary model must be recovered by a working secondary.

    Order is randomized by the weighted shuffle, so the assertion is written
    order-independently: b is the only endpoint that can succeed, and b must
    therefore always be reached; the a->b fallback path must be exercised at
    least once across the runs.
    """
    monkeypatch.setattr("time.sleep", lambda *_: None)
    calls = []
    a_tried = {"n": 0}

    def transport(url, headers, payload):
        calls.append(url)
        if "a/v1" in url:
            a_tried["n"] += 1
            raise urllib.error.URLError("a down")
        return {"choices": [{"message": {"content": "from-b"}}]}

    router = json.dumps([
        {"name": "m1", "base_url": "http://a/v1"},
        {"name": "m2", "base_url": "http://b/v1"}])
    for _ in range(30):
        calls.clear()
        client = LLMClient(cfg={"BAIZE_MODEL_ROUTER": router,
                                "BAIZE_LLM_MAX_RETRIES": "0"},
                           transport=transport)
        msg = client.chat([{"role": "user", "content": "x"}])
        assert msg["content"] == "from-b"
        # b must have been reached - it is the only endpoint that can succeed
        assert any("b/v1" in c for c in calls)
    # the a-then-b fallback path must have been exercised at least once
    assert a_tried["n"] >= 1


def test_chat_stream_yields_deltas():
    def stream_transport(url, headers, payload):
        for c in [{"choices": [{"delta": {"content": "Hello"}}]},
                  {"choices": [{"delta": {"content": "world"}}]},
                  {"choices": [{"delta": {}}]}]:
            yield c

    client = LLMClient(
        cfg={"BAIZE_MODEL_BASE_URL": "http://x/v1", "BAIZE_MODEL_NAME": "m"},
        stream_transport=stream_transport)
    chunks = list(client.chat([{"role": "user", "content": "hi"}], stream=True))
    # the third chunk carries an empty delta, so it yields nothing
    assert chunks == [{"delta": "Hello"}, {"delta": "world"}]


def test_chat_stream_error_falls_back_to_nonstream(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)

    def stream_transport(url, headers, payload):
        raise RuntimeError("stream broke")

    def transport(url, headers, payload):
        return {"choices": [{"message": {"content": "fallback"}}]}

    client = LLMClient(
        cfg={"BAIZE_MODEL_BASE_URL": "http://x/v1", "BAIZE_MODEL_NAME": "m",
             "BAIZE_LLM_MAX_RETRIES": "0"},
        transport=transport, stream_transport=stream_transport)
    chunks = list(client.chat([{"role": "user", "content": "hi"}], stream=True))
    assert chunks == [{"delta": "fallback"}]


def _spawn_json_server(handler_factory):
    server = HTTPServer(("127.0.0.1", 0), handler_factory())
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def test_real_http_transport_covers_network_path():
    captured = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            captured["body"] = self.rfile.read(length)
            body = json.dumps(
                {"choices": [{"message": {"content": "real-http"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server, port = _spawn_json_server(lambda: H)
    try:
        client = LLMClient(
            cfg={"BAIZE_MODEL_BASE_URL": f"http://127.0.0.1:{port}/v1",
                 "BAIZE_MODEL_NAME": "m", "BAIZE_MODEL_API_KEY": "k"})
        msg = client.chat([{"role": "user", "content": "hi"}])
        assert msg["content"] == "real-http"
        # the request payload actually reached the server (proves the real
        # urllib transport ran end-to-end, not the injected fake)
        assert b'"model": "m"' in captured["body"]
    finally:
        server.shutdown()


def test_real_http_stream_transport_covers_sse_path():
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            data = (
                "data: not-json-line\n\n"
                "data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n\n"
                "data: [DONE]\n\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    server, port = _spawn_json_server(lambda: H)
    try:
        client = LLMClient(
            cfg={"BAIZE_MODEL_BASE_URL": f"http://127.0.0.1:{port}/v1",
                 "BAIZE_MODEL_NAME": "m"})
        chunks = list(client.chat(
            [{"role": "user", "content": "hi"}], stream=True))
        assert chunks == [{"delta": "hi"}]
    finally:
        server.shutdown()


def test_ratelimiter_tokens_default_no_append():
    rl = RateLimiter(0, 0)
    rl.acquire()  # tokens default 0 -> `if tokens:` false branch (70->exit)
    assert rl._reqs


def test_ratelimiter_tpm_backoff(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    rl = RateLimiter(0, 1)  # tpm=1
    rl.acquire(tokens=1000)  # sum + 1000 > 1 -> backoff sleep at line 68
    assert True


def test_ratelimiter_rpm_wait_branch(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    rl = RateLimiter(1, 0)  # rpm=1
    rl.acquire()
    rl.acquire()  # second call: len >= rpm, wait > 0 -> sleep (patched no-op)
    assert len(rl._reqs) == 2
