"""End-to-end HTTP tests for V42 Studio REST API routes and Helios Console HTML."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from baize import __version__
from baize.core.sessions import Session, record_checkpoint_node
from baize.execution.bg_proc import get_bg_manager
from baize.interfaces.approval import ApprovalRequest, get_approval_queue
from baize.interfaces.desktop import render_desktop_studio
from baize.interfaces.serve import Handler


class TestV42StudioRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.ws = self.root / "ws"
        self.ws.mkdir()
        (self.ws / "sample.py").write_text("def helios_marker():\n    return 42\n", encoding="utf-8")

        self._env_backup = {}
        overrides = {
            "BAIZE_AUTH_TOKEN": "v42-test-token",
            "BAIZE_ALLOW_NO_AUTH": "0",
            "BAIZE_PERSISTENCE_DIR": str(self.root / "persist"),
            "BAIZE_SESSIONS_DIR": str(self.root / "sessions"),
            "BAIZE_WORKSPACE_DIR": str(self.ws),
            "BAIZE_HYBRID_INDEX_PATH": str(self.root / "hybrid.sqlite3"),
            "BAIZE_EMBEDDING_BASE_URL": "",
        }
        for k, v in overrides.items():
            self._env_backup[k] = os.environ.get(k)
            os.environ[k] = v

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        for k, old in self._env_backup.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        self._td.cleanup()

    def _req(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer v42-test-token"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_v42_routes_require_auth(self):
        for ep in ("/api/budget", "/api/approvals", "/api/worktrees", "/api/sessions/tree", "/api/memory/bounded", "/api/bg-procs"):
            code, _ = self._req("GET", ep, auth=False)
            self.assertEqual(code, 401, f"{ep} should require auth")

    def test_budget_and_config_roundtrip(self):
        code, d = self._req("GET", "/api/budget")
        self.assertEqual(code, 200)
        self.assertIn("summary", d)
        code, d2 = self._req("POST", "/api/budget/config", {
            "max_session_usd": 2.5,
            "max_session_tokens": 50000,
            "warn_ratio": 0.75,
        })
        self.assertEqual(code, 200)
        self.assertAlmostEqual(d2["config"]["max_session_usd"], 2.5, places=2)
        self.assertEqual(d2["config"]["max_session_tokens"], 50000)

    def test_approval_queue_endpoints(self):
        q = get_approval_queue()
        item = q.enqueue_nonblocking(ApprovalRequest(
            tool_name="write_file",
            arguments={"path": "foo.py"},
            risk="write",
            preview="+print(1)",
        ))
        req_id = item["request_id"]
        code, d = self._req("GET", "/api/approvals")
        self.assertEqual(code, 200)
        self.assertTrue(any(p["request_id"] == req_id for p in d["pending"]))

        code, res = self._req("POST", f"/api/approvals/{req_id}/resolve", {
            "approved": True,
            "scope": "once",
            "reason": "verified",
        })
        self.assertEqual(code, 200)
        self.assertTrue(res["ok"])

    def test_bg_procs_and_stop_endpoint(self):
        mgr = get_bg_manager()
        started = mgr.start(f"{sys.executable} -c \"import time; print('hi-bg', flush=True); time.sleep(3)\"", cwd=str(self.ws))
        pid = started["proc_id"]
        try:
            code, d = self._req("GET", f"/api/bg-procs?id={pid}&tail=20")
            self.assertEqual(code, 200)
            self.assertTrue(any(p["proc_id"] == pid for p in d["procs"]))
            self.assertIn("output", d)
        finally:
            code, stopped = self._req("POST", f"/api/bg-procs/{pid}/stop", {})
            self.assertEqual(code, 200)
            self.assertTrue(stopped["ok"])

    def test_bounded_memory_and_hybrid_search_endpoints(self):
        code, d = self._req("POST", "/api/memory/bounded", {
            "slot": "memory",
            "action": "add",
            "content": "Helios V42 prefers zero runtime dependencies.",
        })
        self.assertEqual(code, 200)
        self.assertIn("Helios V42", d["memory"])

        code, d2 = self._req("GET", "/api/memory/bounded")
        self.assertEqual(code, 200)
        self.assertIn("Helios V42", d2["memory"])

        code, sr = self._req("POST", "/api/search/hybrid", {
            "query": "helios_marker",
            "mode": "hybrid",
            "reindex": True,
        })
        self.assertEqual(code, 200)
        self.assertTrue(sr["hits"])
        self.assertIn("sample.py", sr["hits"][0]["doc_id"])

    def test_session_tree_rewind_and_worktrees_endpoints(self):
        s = Session(session_id="v42-tree-sess")
        s.append({"role": "user", "content": "hello"})
        s.append({"role": "assistant", "content": "world"})
        record_checkpoint_node("v42-tree-sess", turn_index=1, summary="init turn")
        code, d = self._req("GET", "/api/sessions/tree")
        self.assertEqual(code, 200)
        self.assertIn("v42-tree-sess", d["formatted"])

        code, wt = self._req("GET", "/api/worktrees")
        self.assertEqual(code, 200)
        self.assertIn("worktrees", wt)

        code, cl = self._req("POST", "/api/worktrees/cleanup", {})
        self.assertEqual(code, 200)

    def test_studio_html_contains_v42_helios_console(self):
        html = render_desktop_studio(__version__)
        for marker in (
            "tab-helios",
            "helios-cost",
            "helios-ops",
            "helios-worktrees",
            "helios-rag",
            "helios-tree",
            "runHeliosHybridSearch",
            "saveHeliosBudgetConfig",
            "resolveHeliosApproval",
        ):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
