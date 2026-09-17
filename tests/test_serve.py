"""Real HTTP tests for the V20 service: a real server on a real socket.

No mocks: the ThreadingHTTPServer is started on an ephemeral port and driven
with urllib. Guards the two content-type bugs found during V20 integration:
  - /metrics must be Prometheus plain text, never JSON-encoded
  - explicit --host/--port must win over config defaults

Since V37.1 the service is fail-closed: writes need a configured bearer token.
These tests therefore run against a server that HAS a token, and send it, so they
exercise the real authorised path rather than a bypass. The unauthenticated paths
are pinned separately by TestAuthPosture below.
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
from baize.serve import STUB_ROUTES, Handler  # noqa: E402


#: Token the fixture server is configured with. Not a secret - it exists only
#: inside this process, and the point is that the tests go through the real
#: authorisation path instead of relying on the old fail-open default.
TEST_TOKEN = "test-token-not-a-secret"


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("BAIZE_AUTH_TOKEN", TEST_TOKEN)
    obs.inc("test_probe")                      # ensure metrics are non-empty
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def get(url: str, token: str | None = TEST_TOKEN):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read().decode()


def post(server: str, path: str, payload, token: str | None = TEST_TOKEN):
    """POST JSON. Returns (status, body); never raises on an HTTP error code."""
    req = urllib.request.Request(
        f"{server}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def get_status(url: str, token: str | None = TEST_TOKEN):
    """GET, returning (status, body) for both 2xx and error codes.

    `get()` above raises on 4xx/5xx because most tests there assert success;
    these tests assert the failure contract, so they need the error code.
    """
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_health_returns_json_with_version(server):
    status, ctype, body = get(f"{server}/health")
    assert status == 200
    assert ctype.startswith("application/json")
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert payload["version"] == __version__
    assert set(payload) == {"status", "version", "execution_boundary"}


def test_health_discloses_the_execution_boundary(server):
    """"status: ok" must not be readable without the caveat attached."""
    status, _ctype, body = get(f"{server}/health")
    assert status == 200
    boundary = json.loads(body)["execution_boundary"]
    # The one claim that matters: it says out loud that it is not a boundary.
    assert boundary["security_boundary"] is False
    assert boundary["control"] == "DENY_PATTERNS"
    assert boundary["pattern_count"] > 0
    assert "blocked" in boundary["measured_coverage"]
    assert boundary["enforced_by"]


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
    status, _ = post(server, "/run", {"goal": "x"})
    assert status == 422


def test_run_rejects_missing_goal(server):
    status, _ = post(server, "/run", {})
    assert status == 400


def test_invalid_json_rejected(server):
    req = urllib.request.Request(
        f"{server}/run", data=b"{not json",
        headers={"Content-Type": "application/json"}, method="POST")
    req.add_header("Authorization", f"Bearer {TEST_TOKEN}")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 400


# ---------------------------------------------------------------------------
# Auth posture (V37.1) - the service used to authenticate everyone whenever
# BAIZE_AUTH_TOKEN was unset, which made the /v30 code-execution endpoints
# reachable from any web page the user visited. These pin the new contract.
# ---------------------------------------------------------------------------


class TestAuthPosture:
    def test_read_only_routes_stay_open_without_a_token(self, server):
        """Probes and the dashboard shell must not require credentials."""
        for path in ("/health", "/metrics", "/"):
            status, _, _ = get(f"{server}{path}", token=None)
            assert status == 200, path

    def test_session_transcripts_require_a_token(self, server):
        """Session data is user content - it must not be world-readable."""
        with pytest.raises(urllib.error.HTTPError) as e:
            get(f"{server}/sessions", token=None)
        assert e.value.code == 401

    def test_write_without_token_is_rejected(self, server):
        status, body = post(server, "/run", {"goal": "x"}, token=None)
        assert status == 401
        assert "unauthorized" in body

    def test_every_write_method_checks_authorisation(self):
        """Structural invariant, not a behavioural spot-check.

        do_DELETE shipped with no auth call at all while the module docstring
        claimed "every write (POST/PUT/DELETE) requires a configured
        BAIZE_AUTH_TOKEN". Behavioural tests missed it for as long as nobody
        issued a DELETE. This test reads the source and asserts that every
        do_<write-method> body calls _is_authorized, so adding a new write
        method without auth fails immediately instead of silently.
        """
        import ast
        from pathlib import Path as _P

        src = (_P(__file__).resolve().parent.parent
               / "baize" / "serve.py").read_text(encoding="utf-8")
        tree = ast.parse(src)

        write_methods = {"do_POST", "do_PUT", "do_PATCH", "do_DELETE"}
        checked = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name not in write_methods:
                continue
            checked.append(node.name)
            calls = {n.func.attr for n in ast.walk(node)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
            assert "_is_authorized" in calls, (
                f"{node.name} handles a state-changing request but never calls "
                f"_is_authorized - every write must be authenticated"
            )

        assert checked, "no write methods found - the parse is wrong, not the code"

    def test_write_with_wrong_token_is_rejected(self, server):
        status, _ = post(server, "/run", {"goal": "x"}, token="wrong-token")
        assert status == 401

    def test_write_with_correct_token_is_not_401(self, server):
        status, _ = post(server, "/run", {"goal": "x"})
        assert status != 401

    def test_query_string_token_is_accepted(self, server):
        req = urllib.request.Request(
            f"{server}/sessions?token={TEST_TOKEN}")
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200

    def test_no_token_and_no_optout_denies_writes(self, monkeypatch):
        """The core regression: absent config must deny, not allow."""
        monkeypatch.delenv("BAIZE_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("BAIZE_ALLOW_NO_AUTH", raising=False)
        handler = Handler.__new__(Handler)
        handler.headers = {}
        handler.path = "/run"
        assert handler._is_authorized() is False

    def test_explicit_optout_allows_writes(self, monkeypatch):
        monkeypatch.delenv("BAIZE_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("BAIZE_ALLOW_NO_AUTH", "1")
        handler = Handler.__new__(Handler)
        handler.headers = {}
        handler.path = "/run"
        assert handler._is_authorized() is True

    def test_optout_does_not_unlock_code_execution(self, monkeypatch):
        """BAIZE_ALLOW_NO_AUTH is a localhost convenience, not a licence to
        execute caller-supplied code."""
        monkeypatch.delenv("BAIZE_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("BAIZE_ALLOW_NO_AUTH", "1")
        handler = Handler.__new__(Handler)
        handler.headers = {}
        handler.path = "/v30/synthesize"
        assert handler._is_authorized(require_token=True) is False


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


class TestCors:
    """CORS is opt-in and never a wildcard.

    A `*` here is not cosmetic: it lets any page the user visits drive their
    loopback server, which is how the unauthenticated RCE was reachable from a
    browser in the first place.
    """

    @staticmethod
    def _get_headers(server: str, path: str, origin: str) -> dict:
        req = urllib.request.Request(f"{server}{path}")
        req.add_header("Authorization", f"Bearer {TEST_TOKEN}")
        req.add_header("Origin", origin)
        with urllib.request.urlopen(req, timeout=5) as r:
            return dict(r.headers)

    @staticmethod
    def _options_headers(server: str, path: str, origin: str) -> dict:
        req = urllib.request.Request(f"{server}{path}", method="OPTIONS")
        req.add_header("Origin", origin)
        req.add_header("Access-Control-Request-Method", "POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return dict(r.headers)

    def test_no_allowlist_means_no_cors_header(self, server, monkeypatch):
        monkeypatch.setenv("BAIZE_CORS_ORIGINS", "")
        headers = self._get_headers(server, "/health", "https://evil.example")
        assert "Access-Control-Allow-Origin" not in headers

    def test_allowlisted_origin_is_echoed(self, server, monkeypatch):
        monkeypatch.setenv("BAIZE_CORS_ORIGINS", "https://app.example")
        headers = self._get_headers(server, "/health", "https://app.example")
        assert headers.get("Access-Control-Allow-Origin") == "https://app.example"
        assert headers.get("Vary") == "Origin"

    def test_non_allowlisted_origin_is_refused(self, server, monkeypatch):
        monkeypatch.setenv("BAIZE_CORS_ORIGINS", "https://app.example")
        headers = self._get_headers(server, "/health", "https://evil.example")
        assert "Access-Control-Allow-Origin" not in headers

    def test_preflight_refused_for_unknown_origin(self, server, monkeypatch):
        monkeypatch.setenv("BAIZE_CORS_ORIGINS", "https://app.example")
        headers = self._options_headers(server, "/run", "https://evil.example")
        assert "Access-Control-Allow-Origin" not in headers
        assert "Access-Control-Allow-Methods" not in headers

    def test_preflight_allows_known_origin(self, server, monkeypatch):
        monkeypatch.setenv("BAIZE_CORS_ORIGINS", "https://app.example")
        headers = self._options_headers(server, "/run", "https://app.example")
        assert headers.get("Access-Control-Allow-Origin") == "https://app.example"
        assert "POST" in headers.get("Access-Control-Allow-Methods", "")

    def test_no_wildcard_anywhere_in_the_package(self):
        """Source-level guard.

        The wildcard was removed from two of three emission sites and the SSE
        stream kept sending `*`; the behavioural tests above cannot reach that
        branch (it needs a live model endpoint), so assert on the source.
        """
        pkg = Path(__file__).resolve().parent.parent / "baize"
        offenders = [
            f"{p.relative_to(pkg.parent)}:{i}"
            for p in pkg.rglob("*.py")
            for i, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
            if 'Access-Control-Allow-Origin", "*"' in line
        ]
        assert offenders == [], f"wildcard CORS still emitted at: {offenders}"


class TestStubRoutes:
    """Stub endpoints must answer 501, never a fabricated 200.

    Each route below used to return HTTP 200 with a hardcoded success payload
    ("PR #43 opened", "4/4 checks green", "hunk merged") while doing no work. The
    only way to keep that from creeping back is to assert the 501 contract.
    """

    @pytest.mark.parametrize("path", sorted(STUB_ROUTES))
    def test_stub_route_returns_501(self, server, path):
        status, body = post(server, path, {})
        assert status == 501, f"{path} answered {status}, expected 501"
        payload = json.loads(body)
        assert payload["error"] == "not_implemented"
        assert payload["path"] == path
        # `reason` must say what is missing, and `message` must be present so a
        # caller reading only `message` sees something truthful.
        assert payload["reason"]
        assert "尚未实现" in payload["message"]

    @pytest.mark.parametrize("path", sorted(STUB_ROUTES))
    def test_stub_route_reports_no_fabricated_success(self, server, path):
        """The old bodies carried fake artefacts ("pr_number": 43,
        "tests_passed": 4, "executed_nodes": [...]). Pin the key set exactly, so
        no fabricated field can be added back alongside the 501."""
        _, body = post(server, path, {})
        payload = json.loads(body)
        assert set(payload) == {"error", "status", "path", "reason", "message"}, (
            f"{path} stub body has unexpected keys: "
            f"{sorted(set(payload) - {'error', 'status', 'path', 'reason', 'message'})}"
        )

    def test_real_route_still_works(self, server):
        """The stub gate must not swallow neighbouring real routes."""
        status, body = post(server, "/api/context/slice",
                            {"code": "def f():\n    return 1", "focus_symbol": "f"})
        assert status == 200
        assert "sliced_code" in json.loads(body)


class TestGitEndpoints:
    """/api/git/status and /api/git/diff must not fabricate a clean tree.

    Both used to hardcode the git executable to one developer's PortableGit
    install and, on any failure, answer HTTP 200 - with /api/git/status reporting
    "clean": True. "Could not check" was indistinguishable from "all clear".
    """

    def test_git_is_resolved_not_hardcoded(self):
        import baize.serve as serve_mod
        src = Path(serve_mod.__file__).read_text(encoding="utf-8")
        # The defect was a raw Windows path literal assigned to git_exe. Check
        # for that shape rather than for the word "PortableGit", which legitimately
        # appears in the comment explaining the fix.
        assert 'r"C:\\' not in src, "a hardcoded Windows path literal is back in serve.py"
        assert "shutil.which" in src, "_resolve_git must search PATH"
        exe = serve_mod._resolve_git()
        if exe:
            assert Path(exe).exists()

    def test_missing_git_answers_503_not_a_clean_tree(self, server, monkeypatch):
        import baize.serve as serve_mod
        monkeypatch.setattr(serve_mod, "_resolve_git", lambda: None)
        status, body = get_status(f"{server}/api/git/status")
        assert status == 503
        payload = json.loads(body)
        assert payload["git_available"] is False
        # The fabricated field must be absent, not merely false.
        assert "clean" not in payload
        assert "branch" not in payload

    def test_status_reports_real_state(self, server):
        status, body = get_status(f"{server}/api/git/status")
        assert status in (200, 503)      # 503 when the runner has no git
        if status == 200:
            payload = json.loads(body)
            assert payload["git_available"] is True
            assert isinstance(payload["clean"], bool)
            # A real branch name comes from git; the old code invented "v30-dev"
            # as a fallback, so the key must be present.
            assert "branch" in payload

    def test_diff_has_no_error_key_on_success(self, server):
        status, body = get_status(f"{server}/api/git/diff")
        assert status in (200, 503)
        payload = json.loads(body)
        assert payload.get("git_available") in (True, False)
        if status == 200:
            assert "diff" in payload


class TestInertSettings:
    """The autonomy slider must announce that it does nothing.

    BAIZE_AUTONOMY_LEVEL / BAIZE_YOLO_MODE are written and echoed by
    /api/config but read by no other code path. Reporting them without that
    caveat is how a control panel ends up lying to its user.
    """

    def test_get_config_declares_the_settings_inert(self, server):
        status, _, body = get(f"{server}/api/config")
        assert status == 200
        payload = json.loads(body)
        assert payload["effective"] == {"autonomy_level": False, "yolo_mode": False}
        assert "no code path reads them" in payload["note"]

    def test_post_config_does_not_claim_to_have_changed_behaviour(self, server):
        status, body = post(server, "/api/config", {"autonomy_level": 3})
        assert status == 200
        payload = json.loads(body)
        assert payload["effective"] is False
        assert payload["persisted"] is False
        assert payload["status"] == "stored_in_process_env"
        # The old wording was "updated", which reads as "it took effect".
        assert payload["status"] != "updated"

    def test_these_settings_have_no_consumer_in_the_package(self):
        """Source-level guard: if someone wires one up, this test must fail so the
        inert labels above get removed rather than left stale.

        Matches string CONSTANTS via the AST rather than raw text, so a mention
        in a comment or in prose does not count as a consumer.
        """
        import ast

        pkg = Path(__file__).resolve().parent.parent / "baize"
        for key in ("BAIZE_AUTONOMY_LEVEL", "BAIZE_YOLO_MODE"):
            referencing = set()
            for p in pkg.rglob("*.py"):
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and node.value == key:
                        referencing.add(p.name)
                        break
            assert sorted(referencing) == ["config.py", "config_schema.py", "serve.py"], (
                f"{key} is now referenced in code by {sorted(referencing)} - it may "
                f"no longer be inert; update /api/config and the Studio slider label"
            )



