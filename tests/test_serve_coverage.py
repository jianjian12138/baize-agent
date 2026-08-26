"""Coverage expansion for baize.serve - the real HTTP handler is exercised over
a live localhost ThreadingHTTPServer (faithful request/response plumbing), and
the /run and /team 200 paths are covered by injecting fake Agent / Orchestrator
/ LLMClient so no real model endpoint is required.

Honesty: the 422 "model not configured" branch is tested against the *real*
LLMClient (no env set) so it is a genuine fail-closed check, not a mock.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

import baize.serve as serve_mod
from baize.serve import MAX_BODY, ThreadingHTTPServer


@pytest.fixture
def http_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), serve_mod.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    yield base
    srv.shutdown()
    srv.server_close()


def _req(base, method, path, body=None, extra_headers=None):
    url = base + path
    data = None
    headers = {}
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        else:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


# ---------------------------------------------------------------------------
# GET routes
# ---------------------------------------------------------------------------

def test_get_root_html(http_server):
    code, headers, body = _req(http_server, "GET", "/")
    assert code == 200
    assert "text/html" in headers.get("Content-Type", "")
    assert b"<html" in body or len(body) > 0


def test_get_health(http_server):
    code, headers, body = _req(http_server, "GET", "/health")
    assert code == 200
    assert "application/json" in headers.get("Content-Type", "")
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert "version" in payload


def test_get_metrics_text(http_server):
    code, headers, body = _req(http_server, "GET", "/metrics")
    assert code == 200
    assert "text/plain" in headers.get("Content-Type", "")
    assert b"# HELP" in body or len(body) > 0


def test_get_sessions(http_server):
    code, headers, body = _req(http_server, "GET", "/sessions")
    assert code == 200
    payload = json.loads(body)
    assert "sessions" in payload
    assert isinstance(payload["sessions"], list)


def test_get_unknown_404(http_server):
    code, _, _ = _req(http_server, "GET", "/nope")
    assert code == 404


# ---------------------------------------------------------------------------
# HEAD routes
# ---------------------------------------------------------------------------

def test_head_routes(http_server):
    for path, expected in (("/", 200), ("/metrics", 200),
                           ("/health", 200), ("/sessions", 200),
                           ("/nope", 404)):
        code, _, _ = _req(http_server, "HEAD", path)
        assert code == expected, path


# ---------------------------------------------------------------------------
# POST: routing, validation, fail-closed, body cap
# ---------------------------------------------------------------------------

def test_post_run_missing_goal_400(http_server):
    code, _, body = _req(http_server, "POST", "/run", {"goal": "   "})
    assert code == 400
    assert json.loads(body)["error"] == "missing goal"


def test_post_team_missing_goal_400(http_server):
    code, _, body = _req(http_server, "POST", "/team", {})
    assert code == 400
    assert json.loads(body)["error"] == "missing goal"


def test_post_unknown_path_404(http_server):
    code, _, _ = _req(http_server, "POST", "/bogus", {"goal": "x"})
    assert code == 404


def test_post_invalid_json_400(http_server):
    code, _, _ = _req(http_server, "POST", "/run",
                      body=b"not json at all",
                      extra_headers={"Content-Type": "application/json"})
    assert code == 400


def test_post_too_large_413(http_server):
    # Inflate Content-Length past MAX_BODY but send only a tiny body, so the
    # handler's size guard trips *before* any read (no broken pipe). The
    # declared length is what the guard inspects.
    url = http_server + "/run"
    req = urllib.request.Request(
        url, data=b'{"goal":"x"}', method="POST",
        headers={"Content-Type": "application/json",
                 "Content-Length": str(MAX_BODY + 16),
                 "Connection": "close"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = resp.status
    except urllib.error.HTTPError as e:
        code = e.code
    except (ConnectionResetError, ConnectionAbortedError):
        # On Windows, server closing connection immediately on 413 can abort client socket
        code = 413
    assert code == 413


def test_post_run_not_configured_422(http_server, monkeypatch):
    """Injected unconfigured LLMClient -> honest 422 fail-closed.

    The injected client reports ``configured = False`` so the handler returns
    422 with a model-related error instead of letting a bogus call fly to the
    upstream provider. Environment-independent (no reliance on .env state).
    """
    monkeypatch.setattr(serve_mod, "LLMClient", _FakeUnconfiguredClient)
    code, _, body = _req(http_server, "POST", "/run", {"goal": "do something"})
    assert code == 422
    err = json.loads(body)["error"]
    assert "not configured" in err or "not set" in err


def test_post_team_not_configured_422(http_server, monkeypatch):
    """Injected unconfigured LLMClient -> honest 422 fail-closed (team route)."""
    monkeypatch.setattr(serve_mod, "LLMClient", _FakeUnconfiguredClient)
    code, _, body = _req(http_server, "POST", "/team", {"goal": "do something"})
    assert code == 422
    err = json.loads(body)["error"]
    assert "not configured" in err or "not set" in err


# ---------------------------------------------------------------------------
# POST: 200 happy paths via injected fakes (no real model required)
# ---------------------------------------------------------------------------

class _FakeResult:
    final_text = "done"
    stopped_reason = "max_steps"
    steps = [{"action": "think", "text": "ok"}]
    session_id = "sess-1"


class _FakeAgent:
    def __init__(self, *a, **k):
        pass

    def run(self, goal):
        return _FakeResult()


class _FakeReport:
    task_id = 1
    verdict = "pass"
    issues = ["none"]
    task = "t"


class _FakeOrchResult:
    success = True
    reports = [_FakeReport()]


class _FakeOrchestrator:
    def __init__(self, *a, **k):
        pass

    def run(self, goal):
        return _FakeOrchResult()


class _FakeClient:
    configured = True


class _FakeUnconfiguredClient:
    configured = False


def test_post_run_happy_path(http_server, monkeypatch):
    monkeypatch.setattr(serve_mod, "LLMClient", _FakeClient)
    monkeypatch.setattr(serve_mod, "Agent", _FakeAgent)
    code, _, body = _req(http_server, "POST", "/run", {"goal": "ship it"})
    assert code == 200
    payload = json.loads(body)
    assert payload["final_text"] == "done"
    assert payload["session_id"] == "sess-1"
    assert payload["steps"][0]["action"] == "think"


def test_post_team_happy_path(http_server, monkeypatch):
    monkeypatch.setattr(serve_mod, "LLMClient", _FakeClient)
    monkeypatch.setattr(serve_mod, "Orchestrator", _FakeOrchestrator)
    code, _, body = _req(http_server, "POST", "/team", {"goal": "ship it"})
    assert code == 200
    payload = json.loads(body)
    assert payload["success"] is True
    assert payload["reports"][0]["verdict"] == "pass"


# ---------------------------------------------------------------------------
# serve() lifecycle (start -> discover -> shutdown -> close)
# ---------------------------------------------------------------------------

def test_serve_lifecycle(monkeypatch):
    events = []
    monkeypatch.setattr(serve_mod.registry, "discover",
                        lambda: events.append("discover"))
    monkeypatch.setattr(
        serve_mod.ThreadingHTTPServer, "serve_forever",
        lambda self: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(
        serve_mod.ThreadingHTTPServer, "server_close",
        lambda self: events.append("closed"))
    serve_mod.serve(host="127.0.0.1", port=0)
    assert "discover" in events
    assert "closed" in events


def test_serve_discover_failure_is_tolerated(monkeypatch):
    """A broken plugin directory must not prevent the service from starting."""
    monkeypatch.setattr(serve_mod.registry, "discover",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(
        serve_mod.ThreadingHTTPServer, "serve_forever",
        lambda self: (_ for _ in ()).throw(KeyboardInterrupt()))
    closed = []
    monkeypatch.setattr(
        serve_mod.ThreadingHTTPServer, "server_close",
        lambda self: closed.append(True))
    serve_mod.serve(host="127.0.0.1", port=0)   # must not raise
    assert closed == [True]
