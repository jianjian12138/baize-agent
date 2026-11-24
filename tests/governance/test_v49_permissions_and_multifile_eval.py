"""V49.0.0 Zenith tests: three-state permission rules engine, Agent gate integration, multi-file benchmark, and HTTP API."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from baize.core.agent import Agent
from baize.core.config import load_config
from baize.core.llm import LLMClient
from baize.governance.eval_harness import MULTI_FILE_BENCH_TASKS, run_multi_file_benchmark
from baize.governance.permissions import (
    evaluate_tool_permission,
    load_permissions,
    parse_permission_rule,
)
from baize.interfaces.serve import Handler


class _FakeLLM:
    build_messages = staticmethod(LLMClient.build_messages)

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.configured = True
        self.calls = 0

    def chat(self, messages, tools=None, temperature=None, stream=False):
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return self._responses[idx]


class TestV49PermissionsAndMultifileEval(unittest.TestCase):
    def test_permission_rule_parsing_and_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d).resolve()
            perm_dir = ws / ".baize"
            perm_dir.mkdir(parents=True)
            (perm_dir / "permissions.json").write_text(
                json.dumps({
                    "allow": ["Bash(pytest:*)", "Edit(src/**)", "Read(*)"],
                    "ask": ["Bash(git push:*)", "Edit(src/prod/**)"],
                    "deny": ["Bash(rm -rf:*)", "Bash(pytest --dangerous:*)", "Read(.env*)"],
                }),
                encoding="utf-8",
            )

            rs = load_permissions(ws, {})
            self.assertEqual(len(rs.allow), 3)
            self.assertEqual(len(rs.ask), 2)
            self.assertEqual(len(rs.deny), 3)

            self.assertEqual(evaluate_tool_permission("bash", {"command": "pytest -q tests/"}, workspace=ws, cfg={}).action, "allow")
            self.assertEqual(evaluate_tool_permission("bash", {"command": "pytest --dangerous all"}, workspace=ws, cfg={}).action, "deny")
            self.assertEqual(evaluate_tool_permission("bash", {"command": "rm -rf /tmp/foo"}, workspace=ws, cfg={}).action, "deny")
            self.assertEqual(evaluate_tool_permission("write_file", {"path": "src/prod/secrets.py"}, workspace=ws, cfg={}).action, "ask")
            self.assertEqual(evaluate_tool_permission("patch_file", {"path": "src/utils/math.py"}, workspace=ws, cfg={}).action, "allow")
            self.assertEqual(evaluate_tool_permission("read_file", {"path": ".env.local"}, workspace=ws, cfg={}).action, "deny")
            self.assertEqual(evaluate_tool_permission("bash", {"command": "ls -la"}, workspace=ws, cfg={}).action, "default")

            rule = parse_permission_rule("Bg(*)", "allow")
            self.assertIsNotNone(rule)
            self.assertTrue(rule.matches_tool("bash_bg_send_input"))

    def test_agent_enforces_deny_and_allow_permission_rules(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d).resolve()
            (ws / ".baize").mkdir()
            (ws / ".baize" / "permissions.json").write_text(
                json.dumps({
                    "allow": ["Write(allowed.txt)"],
                    "deny": ["Bash(rm -rf:*)"],
                    "ask": [],
                }),
                encoding="utf-8",
            )
            llm = _FakeLLM([
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_deny_1",
                            "type": "function",
                            "function": {
                                "name": "bash",
                                "arguments": json.dumps({"command": "rm -rf /tmp/never"}),
                            },
                        },
                        {
                            "id": "call_allow_2",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps({"path": "allowed.txt", "content": "ok-by-rule"}),
                            },
                        },
                    ],
                },
                {"role": "assistant", "content": "done"},
            ])
            cfg = dict(load_config())
            cfg.update({
                "BAIZE_WORKSPACE_DIR": str(ws),
                "BAIZE_SESSIONS_DIR": str(ws / ".sessions"),
                "BAIZE_AUTONOMY": "balanced",
                "BAIZE_MAX_STEPS": "4",
                "BAIZE_AUTO_COMPACT": "0",
                "BAIZE_SPEC_MODE": "off",
            })
            approver_calls: list[str] = []

            def approver(req):
                approver_calls.append(getattr(req, "tool_name", str(req)))
                return mock.MagicMock(approved=False, reason="denied in test")

            agent = Agent(client=llm, cfg=cfg, approval_callback=approver)
            res = agent.run("test permissions")
            self.assertEqual(res.final_text, "done")
            self.assertEqual(approver_calls, [])
            self.assertEqual((ws / "allowed.txt").read_text(encoding="utf-8"), "ok-by-rule")
            tool_msgs = [m.get("content", "") for m in agent.session.messages if m.get("role") == "tool"]
            self.assertTrue(any("PERMISSION_DENIED" in msg for msg in tool_msgs))

    def test_multi_file_benchmark_offline_oracle_passes_all_tasks(self) -> None:
        self.assertGreaterEqual(len(MULTI_FILE_BENCH_TASKS), 3)
        report = run_multi_file_benchmark(mode="offline", cfg={}, persist_history=False)
        self.assertEqual(report["suite"], "multi_file_v49")
        self.assertEqual(report["total_tasks"], len(MULTI_FILE_BENCH_TASKS))
        self.assertEqual(report["passed_tasks"], len(MULTI_FILE_BENCH_TASKS))
        self.assertEqual(report["pass_rate"], 1.0)
        for task in report["tasks"]:
            self.assertTrue(task["passed"], f"Task failed: {task}")

    def test_permissions_http_endpoints_auth_and_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d).resolve()
            (ws / ".baize").mkdir()
            (ws / ".baize" / "permissions.json").write_text(
                json.dumps({"allow": ["Bash(echo:*)"], "ask": [], "deny": ["Read(.env*)"]}),
                encoding="utf-8",
            )
            token = "v49-test-secret-token"
            env_patch = {"BAIZE_WORKSPACE_DIR": str(ws), "BAIZE_AUTH_TOKEN": token}
            with mock.patch.dict(os.environ, env_patch):
                srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                port = srv.server_address[1]
                th = threading.Thread(target=srv.serve_forever, daemon=True)
                th.start()
                try:
                    base = f"http://127.0.0.1:{port}"
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen(f"{base}/api/permissions", timeout=5)
                    self.assertEqual(ctx.exception.code, 401)

                    req = urllib.request.Request(f"{base}/api/permissions", headers={"Authorization": f"Bearer {token}"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        self.assertEqual(resp.status, 200)
                        body = json.loads(resp.read().decode("utf-8"))
                        self.assertEqual(body["allow"], ["Bash(echo:*)"])
                        self.assertEqual(body["deny"], ["Read(.env*)"])

                    req_post = urllib.request.Request(
                        f"{base}/api/permissions/check",
                        data=json.dumps({"tool": "read_file", "target": ".env"}).encode("utf-8"),
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req_post, timeout=5) as resp:
                        self.assertEqual(resp.status, 200)
                        dec = json.loads(resp.read().decode("utf-8"))
                        self.assertEqual(dec["action"], "deny")
                finally:
                    srv.shutdown()
                    srv.server_close()


if __name__ == "__main__":
    unittest.main()
