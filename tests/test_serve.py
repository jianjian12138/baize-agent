"""Real HTTP tests for the V20 service: a real server on a real socket.

No mocks: the ThreadingHTTPServer is started on an ephemeral port and driven
with urllib. Guards the two content-type bugs found during V20 integration:
  - /metrics must be Prometheus plain text, never JSON-encoded
  - explicit --host/--port must win over config defaults
"""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from baize import __version__  # noqa: E402
from baize.observability import obs  # noqa: E402
from baize.serve import Handler  # noqa: E402


@pytest.fixture
def server():
    obs.inc("test_probe")                      # ensure metrics are non-empty
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def get(url: str):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read().decode()


def test_health_returns_json_with_version(server):
    status, ctype, body = get(f"{server}/health")
    assert status == 200
    assert ctype.startswith("application/json")
    assert json.loads(body) == {"status": "ok", "version": __version__}


def test_metrics_is_plain_prometheus_not_json(server):
    status, ctype, body = get(f"{server}/metrics")
    assert status == 200
    assert ctype.startswith("text/plain")
    assert "version=0.0.4" in ctype
    # the regression: JSON encoding would wrap it in quotes with \n escapes
    assert not body.startswith('"')
    assert "\\n" not in body
    assert body.startswith("# TYPE baize_")


def test_dashboard_served_as_html(server):
    for path in ("/", "/dashboard", "/index.html"):
        status, ctype, body = get(f"{server}{path}")
        assert status == 200, path
        assert ctype.startswith("text/html")
        assert body.startswith("<!DOCTYPE html>")
        assert "Baize Engine" in body


def test_sessions_endpoint_returns_list(server):
    status, ctype, body = get(f"{server}/sessions")
    assert status == 200
    assert isinstance(json.loads(body)["sessions"], list)


def test_unknown_path_404(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(f"{server}/nope")
    assert e.value.code == 404


def test_head_is_supported(server):
    req = urllib.request.Request(f"{server}/health", method="HEAD")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 200
        assert r.headers.get("Content-Type", "").startswith("application/json")


def test_run_fails_closed_without_model(server, monkeypatch):
    """No model configured -> 422, never a fake success."""
    monkeypatch.setenv("BAIZE_MODEL_BASE_URL", "")
    monkeypatch.setenv("BAIZE_MODEL_NAME", "")
    req = urllib.request.Request(
        f"{server}/run", data=json.dumps({"goal": "x"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 422


def test_run_rejects_missing_goal(server):
    req = urllib.request.Request(
        f"{server}/run", data=b"{}",
        headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 400


def test_invalid_json_rejected(server):
    req = urllib.request.Request(
        f"{server}/run", data=b"{not json",
        headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 400


def test_explicit_port_wins_over_config(monkeypatch):
    """Regression: config default used to silently override --port."""
    captured = {}

    class FakeServer:
        def __init__(self, addr, handler):
            captured["addr"] = addr

        def serve_forever(self):
            raise KeyboardInterrupt      # exit immediately

        def server_close(self):
            pass

    import baize.serve as serve_mod
    monkeypatch.setattr(serve_mod, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setenv("BAIZE_SERVE_PORT", "8787")

    serve_mod.serve(host="127.0.0.1", port=9999)
    assert captured["addr"] == ("127.0.0.1", 9999)   # CLI arg wins

    serve_mod.serve()                                 # falls back to config
    assert captured["addr"] == ("127.0.0.1", 8787)
