"""Route-level tests for baize/serve.py.

These were written to raise serve.py coverage, and in the process they found
four more endpoints that reported success they had not achieved
(/api/tools/import, /api/security/rbac, /api/chaos/simulate, /v30/speculative).
That is the point of testing routes you have not tested: the audit's list of
fabricated endpoints was a sample, not a census, and nothing in the code made
the difference visible.

No mocks. A real ThreadingHTTPServer on an ephemeral port, driven with urllib,
against a server that has a token configured and is sent it.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from baize.serve import STUB_ROUTES, Handler  # noqa: E402

TEST_TOKEN = "route-tests-token-not-a-secret"


def _start(monkeypatch, tmp_path: Path, **env):
    """Start a real server whose sessions dir is an isolated temp dir."""
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(sessions))
    monkeypatch.setenv("BAIZE_AUTH_TOKEN", TEST_TOKEN)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}", sessions


@pytest.fixture
def server(monkeypatch, tmp_path):
    httpd, base, sessions = _start(monkeypatch, tmp_path)
    yield base, sessions
    httpd.shutdown()
    httpd.server_close()


def _call(url, method="GET", payload=None, token=TEST_TOKEN):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _json(body: str) -> dict:
    return json.loads(body)


# --------------------------------------------------------------- DELETE ----


def test_delete_all_sessions_reports_the_real_count(server):
    base, sessions = server
    for i in range(3):
        (sessions / f"s{i}.jsonl").write_text("{}\n", encoding="utf-8")

    status, body = _call(f"{base}/sessions", method="DELETE")
    assert status == 200
    payload = _json(body)
    assert payload["deleted_count"] == 3
    assert list(sessions.glob("*.jsonl")) == []


def test_delete_all_sessions_on_an_empty_dir_is_zero_not_an_error(server):
    base, _sessions = server
    status, body = _call(f"{base}/sessions/all", method="DELETE")
    assert status == 200
    assert _json(body)["deleted_count"] == 0


def test_delete_one_session(server):
    base, sessions = server
    (sessions / "abc.jsonl").write_text("{}\n", encoding="utf-8")

    status, body = _call(f"{base}/sessions/abc", method="DELETE")
    assert status == 200
    assert _json(body)["deleted"] == "abc"
    assert not (sessions / "abc.jsonl").exists()


def test_delete_missing_session_is_404(server):
    base, _sessions = server
    status, body = _call(f"{base}/sessions/nope", method="DELETE")
    assert status == 404
    assert "not found" in _json(body)["error"]


def test_delete_unknown_path_is_404(server):
    base, _sessions = server
    status, _body = _call(f"{base}/definitely/not/a/route", method="DELETE")
    assert status == 404


def test_delete_requires_a_token(server):
    base, sessions = server
    (sessions / "keep.jsonl").write_text("{}\n", encoding="utf-8")
    status, _body = _call(f"{base}/sessions", method="DELETE", token=None)
    assert status == 401
    # ...and it really did not delete anything.
    assert (sessions / "keep.jsonl").exists()


# ----------------------------------------------------- second-pass stubs ---


@pytest.mark.parametrize("path", [
    "/api/tools/import",
    "/api/security/rbac",
    "/api/chaos/simulate",
    "/v30/speculative",
])
def test_second_pass_stub_routes_answer_501(server, path):
    base, _sessions = server
    status, body = _call(f"{base}{path}", method="POST", payload={"goal": "x"})
    assert status == 501
    payload = _json(body)
    assert payload["error"] == "not_implemented"
    assert payload["path"] == path
    assert payload["reason"] == STUB_ROUTES[path]


def test_tools_import_does_not_claim_to_have_loaded_a_tool(server):
    base, _sessions = server
    status, body = _call(f"{base}/api/tools/import", method="POST",
                         payload={"name": "my_tool"})
    payload = _json(body)
    assert status == 501
    # Assert on the parsed field, not on a substring: the stub's own `reason`
    # text quotes the old "status 'imported'" value, so a substring scan of the
    # body would match the explanation of the bug and cry wolf.
    assert payload["status"] == "not_implemented"
    assert "name" not in payload, "the handler used to echo the caller's name back"


def test_speculative_points_callers_at_the_real_endpoint(server):
    """/v30/speculative and /v30/swarm/speculate look interchangeable and are
    not; the stub body must not leave that ambiguity to the reader."""
    base, _sessions = server
    _status, body = _call(f"{base}/v30/speculative", method="POST",
                          payload={"goal": "x"})
    assert "timeline" in _json(body)["reason"]


# ------------------------------------------- overclaims fixed in place -----


def test_model_route_classifies_and_says_it_did_not_route(server):
    base, _sessions = server
    status, body = _call(f"{base}/api/models/route", method="POST",
                         payload={"prompt": "请重构这段 AST 推演逻辑"})
    assert status == 200
    payload = _json(body)
    assert payload["complexity"] == "HIGH"
    assert payload["suggested_model"] == "deepseek-reasoner"
    assert payload["routed"] is False
    # The two fields that were invented are gone.
    assert "routed_model" not in payload
    assert "saved_cost_ratio" not in payload


def test_model_route_reports_no_match_honestly(server):
    base, _sessions = server
    _status, body = _call(f"{base}/api/models/route", method="POST",
                          payload={"prompt": "hello"})
    payload = _json(body)
    assert payload["complexity"] == "FAST"
    assert "no complexity keyword matched" in payload["basis"]


def test_active_model_is_not_reported_as_persisted(server):
    base, _sessions = server
    status, body = _call(f"{base}/api/models/active", method="POST",
                         payload={"model": "deepseek-reasoner"})
    assert status == 200
    payload = _json(body)
    assert payload["active_model"] == "deepseek-reasoner"
    assert payload["status"] == "stored_in_process_env"
    assert payload["persisted"] is False


def test_active_model_without_a_name_is_400(server):
    base, _sessions = server
    status, _body = _call(f"{base}/api/models/active", method="POST",
                          payload={})
    assert status == 400


def test_memory_search_reports_substring_matches_not_scores(server):
    base, sessions = server
    (sessions / "s1.jsonl").write_text(
        json.dumps({"text": "the needle is here, needle again"}) + "\n",
        encoding="utf-8")

    status, body = _call(f"{base}/api/memory/search", method="POST",
                         payload={"query": "needle"})
    assert status == 200
    payload = _json(body)
    assert payload["match"] == "substring"
    assert len(payload["results"]) == 1
    hit = payload["results"][0]
    assert hit["source"] == "session:s1"
    assert hit["occurrences"] == 2
    assert "relevance" not in hit


def test_memory_search_with_no_match_invents_nothing(server):
    """The old version answered every miss with a fabricated `knowledge_base`
    result at relevance 0.75, claiming a semantic match had happened."""
    base, _sessions = server
    _status, body = _call(f"{base}/api/memory/search", method="POST",
                          payload={"query": "zzz-not-present-zzz"})
    payload = _json(body)
    assert payload["results"] == []
    assert "knowledge_base" not in body


def test_memory_search_without_a_query_returns_no_results(server):
    base, _sessions = server
    _status, body = _call(f"{base}/api/memory/search", method="POST",
                          payload={"query": "   "})
    assert _json(body)["results"] == []


# --------------------------------------------------- code-exec endpoints ---


def test_synthesis_endpoint_is_501_without_the_explicit_opt_in(server):
    base, _sessions = server
    status, body = _call(f"{base}/v30/synthesize", method="POST",
                         payload={"name": "t", "code": "def t(): return 1"})
    assert status == 501
    assert "BAIZE_ENABLE_SYNTHESIS_API" in _json(body)["error"]


def test_synthesis_endpoint_rejects_missing_fields_when_enabled(monkeypatch,
                                                                tmp_path):
    httpd, base, _sessions = _start(
        monkeypatch, tmp_path, BAIZE_ENABLE_SYNTHESIS_API="1")
    try:
        status, body = _call(f"{base}/v30/synthesize", method="POST",
                             payload={"name": "", "code": ""})
        assert status == 400
        assert "missing" in _json(body)["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_code_exec_endpoint_403s_when_the_only_auth_is_allow_no_auth(
        monkeypatch, tmp_path):
    """BAIZE_ALLOW_NO_AUTH=1 unlocks ordinary writes. It must not unlock the
    endpoints that exec caller-supplied code."""
    monkeypatch.setenv("BAIZE_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("BAIZE_AUTH_TOKEN", "")
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(sessions))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        # An ordinary write is allowed under this flag...
        ok, _ = _call(f"{base}/api/config", method="POST",
                      payload={"autonomy_level": 2}, token=None)
        assert ok == 200
        # ...but the code-executing endpoint is not.
        status, body = _call(f"{base}/v30/synthesize", method="POST",
                             payload={"name": "t", "code": "x"},
                             token=None)
        assert status == 403
        assert "BAIZE_ALLOW_NO_AUTH" in _json(body)["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_adversarial_endpoint_rejects_missing_blue_code(monkeypatch, tmp_path):
    httpd, base, _sessions = _start(
        monkeypatch, tmp_path, BAIZE_ENABLE_SYNTHESIS_API="1")
    try:
        status, body = _call(f"{base}/v30/adversarial", method="POST",
                             payload={"blue_code": ""})
        assert status == 400
        assert "blue_code" in _json(body)["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()


# ----------------------------------------------------------- /run paths ----


def test_run_rejects_a_missing_goal(server):
    base, _sessions = server
    status, body = _call(f"{base}/run", method="POST", payload={"goal": "  "})
    assert status == 400
    assert "goal" in _json(body)["error"]


def test_run_stream_rejects_a_missing_goal(server):
    base, _sessions = server
    status, body = _call(f"{base}/run/stream", method="POST", payload={})
    assert status == 400
    assert "goal" in _json(body)["error"]


def test_run_stream_422s_when_the_model_is_not_configured(server, monkeypatch):
    monkeypatch.setenv("BAIZE_MODEL_BASE_URL", "")
    monkeypatch.setenv("BAIZE_MODEL_API_KEY", "")
    base, _sessions = server
    status, body = _call(f"{base}/run/stream", method="POST",
                         payload={"goal": "do something"})
    assert status == 422
    assert "configured" in _json(body)["error"]


# ------------------------------------------------------------ /api/config --


def test_config_without_a_field_is_400(server):
    base, _sessions = server
    status, _body = _call(f"{base}/api/config", method="POST", payload={})
    assert status == 400


def test_unknown_post_route_is_404(server):
    base, _sessions = server
    status, _body = _call(f"{base}/api/nope", method="POST", payload={})
    assert status == 404


def test_post_without_a_token_is_401(server):
    base, _sessions = server
    status, _body = _call(f"{base}/api/config", method="POST",
                          payload={"autonomy_level": 1}, token=None)
    assert status == 401


# ------------------------------------------------------------ /v30/causal --


def test_causal_slice_works_and_reports_that_nothing_was_executed(server):
    """This route used to import a name that does not exist (CausalDebugger), so
    every request raised ImportError. Now that it runs, it must also not imply
    the generated mutation cases were applied - they are descriptors."""
    base, _sessions = server
    status, body = _call(
        f"{base}/v30/causal", method="POST",
        payload={"code": "def divide(a, b):\n    return a / b",
                 "target_function": "divide"},
    )
    assert status == 200, body
    data = _json(body)
    assert data["target_function"] == "divide"
    assert data["ast_node_type"] == "FunctionDef"
    assert set(data["culprit_variables"]) == {"a", "b"}
    assert data["mutations_executed"] is False
    assert data["mutations_note"]
    assert data["mutations"], "the fuzzer should produce case descriptors"
    for case in data["mutations"]:
        assert set(case) == {"name", "type", "desc", "payload"}
    # The payload is rendered, not shipped as an opaque object().
    assert all(isinstance(v, str) for case in data["mutations"]
               for v in case["payload"].values())


def test_causal_slice_reports_an_unknown_function_honestly(server):
    base, _sessions = server
    status, body = _call(
        f"{base}/v30/causal", method="POST",
        payload={"code": "def other(x):\n    return x", "target_function": "missing"},
    )
    assert status == 200
    data = _json(body)
    assert data["target_function"] == "missing"
    # ASTCausalTracker falls back to a whole-file slice and says so via the node
    # type, rather than inventing a function it did not find.
    assert data["ast_node_type"] == "Unknown"
    assert data["culprit_variables"] == []


# ------------------------------------------------ /v30/causal/persist_test --


def test_persist_test_refuses_a_non_identifier_name(server):
    """`target_function` was interpolated into a filename and into Python source
    written to disk, so a name with a newline could inject code into a file that
    pytest collects."""
    base, _sessions = server
    status, body = _call(
        f"{base}/v30/causal/persist_test", method="POST",
        payload={"target_function": "f(a): pass\nimport os", "code": "def f(): pass"},
    )
    assert status == 400
    assert "identifier" in _json(body)["error"]


def test_persist_test_requires_the_source_it_claims_to_derive_from(server):
    base, _sessions = server
    status, body = _call(
        f"{base}/v30/causal/persist_test", method="POST",
        payload={"target_function": "divide"},
    )
    assert status == 400
    assert "code is required" in _json(body)["error"]


def test_persist_test_writes_the_generated_guardrail_not_a_template(server, tmp_path,
                                                                   monkeypatch):
    base, _sessions = server
    # The route writes to `tests/generated` relative to the CWD. Chdir into the
    # temp dir so the test cannot leave a file inside the repository.
    monkeypatch.chdir(tmp_path)
    code = "def check_score(s):\n    return True if s > 60 else False"
    status, body = _call(
        f"{base}/v30/causal/persist_test", method="POST",
        payload={"target_function": "check_score", "code": code},
    )
    assert status == 200, body
    data = _json(body)
    assert data["status"] == "persisted"
    assert data["tracked_by_git"] is False
    written = Path(data["path"])
    assert written.exists()
    assert tmp_path in written.parents, "the route must not write outside the CWD"
    text = written.read_text(encoding="utf-8")
    # The file has to be the arena's output for THIS source, not a fixed divide()
    # template with the function name substituted.
    assert code in text
    assert "assert check_score(" in text
    assert "assert True" not in text
    assert "def divide(" not in text
    assert data["bytes_written"] == len(text.encode("utf-8"))
    # No CRLF: the byte count in the response has to match what a reader computes.
    assert b"\r\n" not in written.read_bytes()


def test_persist_test_writes_nothing_when_it_refuses(server, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base, _sessions = server
    _call(f"{base}/v30/causal/persist_test", method="POST",
          payload={"target_function": "not an identifier", "code": "def f(): pass"})
    assert not (tmp_path / "tests" / "generated").exists()


def test_persist_test_reports_when_no_test_can_be_generated(server):
    base, _sessions = server
    status, body = _call(
        f"{base}/v30/causal/persist_test", method="POST",
        payload={"target_function": "plain", "code": "def plain(x):\n    return x"},
    )
    assert status == 422
    assert _json(body)["arena_status"] == "no_mutation_sites"
