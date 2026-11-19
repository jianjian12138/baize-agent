"""End-to-end tests for V40.1 zero-501 enterprise HTTP routes & 410 retirements."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from baize.interfaces.serve import Handler, RETIRED_ROUTES, STUB_ROUTES
from baize.interfaces.server.operations import get_imported_tool_registry


def _req(base: str, path: str, *, method: str = "GET", payload: dict | None = None, token: str = "test-v40-ops-tok"):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{base}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class TestV40EnterpriseRoutes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "ws"
        self.pdir = self.root / "persistence"
        self.ws.mkdir(parents=True)
        self.pdir.mkdir(parents=True)
        self._env_backup = {
            k: os.environ.get(k)
            for k in (
                "BAIZE_AUTH_TOKEN",
                "BAIZE_WORKSPACE_DIR",
                "BAIZE_PERSISTENCE_DIR",
                "BAIZE_WEBHOOK_ALLOW_PRIVATE",
                "BAIZE_API_KEY",
                "DEEPSEEK_API_KEY",
                "OPENAI_API_KEY",
            )
        }
        os.environ["BAIZE_AUTH_TOKEN"] = "test-v40-ops-tok"
        os.environ["BAIZE_WORKSPACE_DIR"] = str(self.ws)
        os.environ["BAIZE_PERSISTENCE_DIR"] = str(self.pdir)
        os.environ.pop("BAIZE_WEBHOOK_ALLOW_PRIVATE", None)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def test_zero_501_stubs_and_five_410_retired_routes(self):
        self.assertEqual(STUB_ROUTES, {})
        self.assertEqual(len(RETIRED_ROUTES), 5)
        for path in sorted(RETIRED_ROUTES):
            code, data = _req(self.base, path, method="POST", payload={})
            self.assertEqual(code, 410, f"{path} returned {code}")
            self.assertEqual(data["error"], "gone")
            self.assertEqual(data["status"], "retired")

    def test_webhook_dispatch_ssrf_guard_and_real_signed_delivery(self):
        code, data = _req(self.base, "/api/webhook/dispatch", method="POST", payload={"event": "ping"})
        self.assertEqual(code, 400)
        self.assertEqual(data["error"], "missing_webhook_url")

        received: list[tuple[bytes, dict]] = []

        class _Receiver(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                received.append((raw, dict(self.headers.items())))
                self.send_response(202)
                self.end_headers()
                self.wfile.write(b'{"accepted":true}')

            def log_message(self, *args):
                pass

        rx = ThreadingHTTPServer(("127.0.0.1", 0), _Receiver)
        threading.Thread(target=rx.serve_forever, daemon=True).start()
        rx_url = f"http://127.0.0.1:{rx.server_address[1]}/hook"
        try:
            code, data = _req(
                self.base,
                "/api/webhook/dispatch",
                method="POST",
                payload={"url": rx_url, "event": "build.ok"},
            )
            self.assertEqual(code, 403)
            self.assertEqual(data["error"], "ssrf_blocked")
            self.assertEqual(len(received), 0)

            os.environ["BAIZE_WEBHOOK_ALLOW_PRIVATE"] = "1"
            secret = "my-webhook-secret"
            code, data = _req(
                self.base,
                "/api/webhook/dispatch",
                method="POST",
                payload={"url": rx_url, "event": "build.ok", "payload": {"sha": "abc123"}, "secret": secret},
            )
            self.assertEqual(code, 200)
            self.assertTrue(data["delivered"])
            self.assertEqual(data["http_status"], 202)
            self.assertTrue(data["signed"])
            self.assertEqual(len(received), 1)
            raw_body, hdrs = received[0]
            expected_sig = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            self.assertEqual(hdrs.get("X-Baize-Signature"), expected_sig)
            parsed = json.loads(raw_body.decode("utf-8"))
            self.assertEqual(parsed["event"], "build.ok")
            self.assertEqual(parsed["payload"]["sha"], "abc123")
        finally:
            rx.shutdown()
            rx.server_close()

    def test_rbac_persists_deterministically_and_enforces_precedence(self):
        rules = [
            {"path": "src/**", "perm": "rw"},
            {"path": "deploy/**", "perm": "ro"},
            {"path": ".env", "perm": "deny"},
            {"path": "src/secrets.py", "perm": "deny"},
        ]
        c1, d1 = _req(self.base, "/api/security/rbac", method="POST", payload={"rules": rules})
        c2, d2 = _req(self.base, "/api/security/rbac", method="POST", payload={"rules": rules})
        self.assertEqual(c1, 200)
        self.assertEqual(c2, 200)
        self.assertEqual(d1["policy_digest"], d2["policy_digest"], "digest must be deterministic, not time-based")
        self.assertTrue(d1["persisted"])
        self.assertTrue((self.pdir / "rbac_policy.json").is_file())

        cg, dg = _req(self.base, "/api/security/rbac", method="GET")
        self.assertEqual(cg, 200)
        self.assertEqual(dg["rules_count"], 4)

        ce, de = _req(
            self.base,
            "/api/security/rbac",
            method="POST",
            payload={"evaluate_path": "src/secrets.py", "action": "read"},
        )
        self.assertEqual(ce, 200)
        self.assertFalse(de["evaluation"]["allowed"])
        self.assertEqual(de["evaluation"]["effective_perm"], "deny")

        ce2, de2 = _req(
            self.base,
            "/api/security/rbac",
            method="POST",
            payload={"evaluate_path": "deploy/k8s.yaml", "action": "write"},
        )
        self.assertEqual(ce2, 200)
        self.assertFalse(de2["evaluation"]["allowed"])
        self.assertEqual(de2["evaluation"]["effective_perm"], "ro")

    def test_rbac_rejects_invalid_perm(self):
        code, data = _req(
            self.base,
            "/api/security/rbac",
            method="POST",
            payload={"rules": [{"path": "src/**", "perm": "admin_magic"}]},
        )
        self.assertEqual(code, 400)
        self.assertEqual(data["error"], "invalid_perm")

    def test_tools_import_catalog_registers_and_executes_for_real(self):
        code, data = _req(self.base, "/api/tools/import", method="POST", payload={"name": "json_canonicalizer"})
        self.assertEqual(code, 200)
        self.assertEqual(data["status"], "registered")
        reg = get_imported_tool_registry()
        self.assertIn("json_canonicalizer", reg.names())

        out = reg.execute("json_canonicalizer", {"data": '{"b": 1, "a": 2}'})
        self.assertEqual(out, '{"a":2,"b":1}')

        cg, dg = _req(self.base, "/api/tools/imported", method="GET")
        self.assertEqual(cg, 200)
        self.assertIn("json_canonicalizer", dg["active_runtime_tools"])

    def test_tools_import_workspace_module_and_rejects_escape(self):
        plugin = self.ws / "my_plugin.py"
        plugin.write_text(
            'def double_text(text: str = "") -> str:\n    """Double input text."""\n    return text + text\n',
            encoding="utf-8",
        )
        code, data = _req(
            self.base,
            "/api/tools/import",
            method="POST",
            payload={"name": "double_text", "module_path": "my_plugin.py", "function": "double_text"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(get_imported_tool_registry().execute("double_text", {"text": "ab"}), "abab")

        code2, data2 = _req(
            self.base,
            "/api/tools/import",
            method="POST",
            payload={"name": "evil", "module_path": "../../etc/passwd", "function": "x"},
        )
        self.assertEqual(code2, 403)
        self.assertEqual(data2["error"], "path_outside_workspace")

    def test_ci_autofix_reproduces_passing_and_failing_commands_honestly(self):
        code, data = _req(
            self.base,
            "/api/ci/autofix",
            method="POST",
            payload={"test_command": f"{sys.executable} -c \"print('ok')\""},
        )
        self.assertEqual(code, 200)
        self.assertEqual(data["status"], "already_passing")
        self.assertFalse(data["reproduced"])
        self.assertNotIn("pr_number", data)

        (self.ws / "broken.py").write_text("def bad(:\n    pass\n", encoding="utf-8")
        code2, data2 = _req(
            self.base,
            "/api/ci/autofix",
            method="POST",
            payload={"test_command": f"{sys.executable} -c \"import sys; sys.exit(2)\"", "dry_run": True},
        )
        self.assertEqual(code2, 200)
        self.assertEqual(data2["status"], "diagnosed")
        self.assertTrue(data2["reproduced"])
        self.assertEqual(data2["reproduction"]["returncode"], 2)
        self.assertGreaterEqual(data2["diagnostics"]["errors"], 1)
        self.assertNotIn("pr_number", data2)

    def test_ci_autofix_without_llm_key_answers_503_honestly(self):
        os.environ.pop("DEEPSEEK_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ["BAIZE_API_KEY"] = "sk-your-api-key-here"
        code, data = _req(
            self.base,
            "/api/ci/autofix",
            method="POST",
            payload={"failure_log": "AssertionError: expected 2 got 1"},
        )
        self.assertEqual(code, 503)
        self.assertEqual(data["error"], "llm_not_configured")
        self.assertIsNone(data["job_id"])
        self.assertNotIn("pr_number", data)


if __name__ == "__main__":
    unittest.main()
