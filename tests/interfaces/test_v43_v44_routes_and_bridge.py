"""End-to-end tests for V43+V44 Agent<->ApprovalQueue bridge, multi-tenant routes, probes & Studio Helios governance UI."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from baize.core.agent import Agent
from baize.core.llm import LLMClient
from baize.governance.dlp import AuditLedger
from baize.interfaces.approval import ApprovalQueue, ApprovalRequest, get_approval_queue
from baize.interfaces.desktop import render_desktop_studio
from baize.interfaces.serve import Handler, set_shutting_down


def _make_stub_llm() -> LLMClient:
    calls = {"n": 0}

    def _transport(url, headers, payload):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_write_1",
                                    "type": "function",
                                    "function": {
                                        "name": "write_file",
                                        "arguments": json.dumps({"path": "bridged.txt", "content": "approved-by-queue"}),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "bridge done"}}]}

    return LLMClient(
        cfg={
            "BAIZE_MODEL_BASE_URL": "http://127.0.0.1:9999/v1",
            "BAIZE_MODEL_NAME": "stub-model",
            "BAIZE_MODEL_API_KEY": "stub-key",
        },
        transport=_transport,
    )


class TestV43V44RoutesAndBridge(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.ws = self.root / "ws"
        self.ws.mkdir()
        (self.ws / "hello.py").write_text("print('atlas')\n", encoding="utf-8")
        self._env_backup = {}
        overrides = {
            "BAIZE_AUTH_TOKEN": "admin-master-tok",
            "BAIZE_TENANT_TOKENS": "team-a:tok-team-a:operator,team-b:tok-team-b:viewer",
            "BAIZE_ALLOW_NO_AUTH": "0",
            "BAIZE_PERSISTENCE_DIR": str(self.root / "persist"),
            "BAIZE_SESSIONS_DIR": str(self.root / "sessions"),
            "BAIZE_WORKSPACE_DIR": str(self.ws),
            "BAIZE_HYBRID_INDEX_PATH": str(self.root / "hybrid.sqlite3"),
            "BAIZE_EMBEDDING_BASE_URL": "",
            "BAIZE_APPROVAL_MODE": "tiered",
            "BAIZE_APPROVAL_BRIDGE": "queue",
            "BAIZE_APPROVAL_TIMEOUT": "10",
            "BAIZE_AUTO_DIAGNOSE_ON_EDIT": "0",
        }
        for k, v in overrides.items():
            self._env_backup[k] = os.environ.get(k)
            os.environ[k] = v
        set_shutting_down(False)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self) -> None:
        set_shutting_down(False)
        self.srv.shutdown()
        self.srv.server_close()
        for k, old in self._env_backup.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        self._td.cleanup()

    def _req(self, path: str, *, method: str = "GET", body: dict | None = None, token: str | None = "tok-team-a"):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(f"{self.base}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8")), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"raw": raw}
            return exc.code, parsed, dict(exc.headers)

    def test_agent_approval_queue_bridge_and_sqlite_persistence(self) -> None:
        db_path = self.root / "persist" / "approvals_standalone.sqlite3"
        q1 = ApprovalQueue(db_path=db_path)
        enq = q1.enqueue_nonblocking(
            ApprovalRequest(tool_name="write_file", arguments={"path": "x.txt"}, preview="write x.txt", risk="medium")
        )
        q2 = ApprovalQueue(db_path=db_path)
        pending_ids = [p["request_id"] for p in q2.list_pending()]
        self.assertIn(enq["request_id"], pending_ids)

        agent = Agent(client=_make_stub_llm())
        result_box: dict[str, object] = {}

        def _run_agent():
            result_box["out"] = agent.run("write bridged.txt")

        t = threading.Thread(target=_run_agent, daemon=True)
        t.start()

        q = get_approval_queue()
        req_id = ""
        deadline = time.time() + 5.0
        while time.time() < deadline:
            for item in q.list_pending():
                if item.get("tool_name") == "write_file":
                    req_id = item["request_id"]
                    break
            if req_id:
                break
            time.sleep(0.05)

        self.assertTrue(req_id, "Expected pending write_file approval in ApprovalQueue")
        res = q.resolve(req_id, approved=True, scope="once", reason="unit-test-ok")
        self.assertTrue(res["ok"])
        t.join(timeout=5.0)
        self.assertFalse(t.is_alive())
        self.assertEqual((self.ws / "bridged.txt").read_text(encoding="utf-8"), "approved-by-queue")

        ledger = AuditLedger()
        entries = ledger.list_entries(limit=20)
        event_types = {e["event_type"] for e in entries}
        self.assertIn("approval_resolved", event_types)

    def test_multi_tenant_auth_probes_audit_traces_eval_and_studio_ui(self) -> None:
        st, data, hdrs = self._req("/livez", token=None)
        self.assertEqual(st, 200)
        self.assertEqual(data["status"], "alive")
        self.assertIn("traceparent", {k.lower() for k in hdrs})

        st, data, _ = self._req("/readyz", token=None)
        self.assertEqual(st, 200)
        self.assertEqual(data["status"], "ready")

        set_shutting_down(True)
        st, data, _ = self._req("/readyz", token=None)
        self.assertEqual(st, 503)
        self.assertEqual(data["status"], "draining")
        set_shutting_down(False)

        st, _, _ = self._req("/api/audit", token="wrong-token")
        self.assertEqual(st, 401)

        st, bdata, _ = self._req(
            "/api/budget/config",
            method="POST",
            body={"max_session_usd": 4.25, "warn_ratio": 0.75},
            token="tok-team-a",
        )
        self.assertEqual(st, 200)
        self.assertTrue(bdata.get("persisted"))

        st, edata, _ = self._req("/api/eval/run", method="POST", body={"mode": "offline"}, token="tok-team-a")
        self.assertEqual(st, 200)
        self.assertEqual(edata["passed_tasks"], 4)

        st, hdata, _ = self._req("/api/eval/history", token="tok-team-b")
        self.assertEqual(st, 200)
        self.assertGreaterEqual(len(hdata["runs"]), 1)

        st, adata, _ = self._req("/api/audit?verify=1", token="tok-team-a")
        self.assertEqual(st, 200)
        self.assertTrue(adata["integrity"]["ok"])

        st, tdata, _ = self._req("/api/traces", token="tok-team-a")
        self.assertEqual(st, 200)
        self.assertIn("traces", tdata)

        html = render_desktop_studio()
        self.assertIn("helios-gov", html)
        self.assertIn("runHeliosOfflineEval", html)
        self.assertIn("loadHeliosAudit", html)
        self.assertIn("loadHeliosTraces", html)


if __name__ == "__main__":
    unittest.main()
