"""Regression tests for P0/P1 codebase optimizations."""
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
from unittest.mock import patch

from baize.execution import tools as tools_mod
from baize.core.agent import Agent, Session
from baize.codebase.arch_cache import ArchCacheManager
from baize.core.autonomy import build_policy, resolve_autonomy_level
from baize.core.config import load_config
from baize.interfaces.desktop_ui import read_studio_asset, render_desktop_studio
from baize.knowledge.doc_crawler import DocHTMLToMarkdownParser, validate_public_http_url
from baize.core.llm import LLMClient, LLMError, ModelSpec, _anthropic_request
from baize.ext.mcp.dispatcher import call_mcp_tool
from baize.governance.observability import Observability
from baize.orchestration.orchestrator import Orchestrator
from baize.interfaces.serve import Handler
from baize.core.sessions import _read_records


class TestPatchFileDiffPreservation(unittest.TestCase):
    def test_diff_mode_preserves_unmodified_surrounding_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "module.py"
            original = (
                "line1\n"
                "line2\n"
                "def target():\n"
                "    return 1\n"
                "line5\n"
                "line6\n"
            )
            p.write_text(original, encoding="utf-8")
            diff = (
                "--- a/module.py\n"
                "+++ b/module.py\n"
                "@@ -3,2 +3,2 @@\n"
                " def target():\n"
                "-    return 1\n"
                "+    return 42\n"
            )
            with patch.object(tools_mod, "_resolve_in_workspace", return_value=p):
                res = tools_mod._tool_patch_file(str(p), "", diff, mode="diff")
            self.assertIn("patched", res)
            self.assertEqual(
                p.read_text(encoding="utf-8"),
                "line1\nline2\ndef target():\n    return 42\nline5\nline6\n",
            )

    def test_diff_mode_rejects_mismatched_hunk_without_corrupting_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "module.py"
            original = "alpha\nbeta\ngamma\n"
            p.write_text(original, encoding="utf-8")
            diff = "@@ -1,2 +1,2 @@\n-nonexistent\n+changed\n"
            with patch.object(tools_mod, "_resolve_in_workspace", return_value=p):
                res = tools_mod._tool_patch_file(str(p), "", diff, mode="diff")
            self.assertTrue(res.startswith("ERROR"))
            self.assertEqual(p.read_text(encoding="utf-8"), original)


class TestGitAndSkillSecurity(unittest.TestCase):
    def test_git_handles_quoted_commit_messages_and_blocks_option_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(tools_mod, "_workspace_root", return_value=Path(tmp)):
                with patch.object(tools_mod.proc_mod, "run") as mock_run:
                    mock_run.return_value = type("R", (), {
                        "timed_out": False, "returncode": 0, "stdout": "ok", "stderr": ""
                    })()
                    out = tools_mod._tool_git('commit -m "fix: handle spaces"')
                    self.assertIn("exit=0", out)
                    argv = mock_run.call_args[0][0]
                    self.assertEqual(argv, ["git", "commit", "-m", "fix: handle spaces"])

                blocked = tools_mod._tool_git("status --git-dir=/tmp/evil")
                self.assertIn("ERROR", blocked)
                blocked2 = tools_mod._tool_git("status -C /etc")
                self.assertIn("ERROR", blocked2)

    def test_load_skill_blocks_arbitrary_host_file_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            ws.mkdir()
            secret = Path(tmp) / "secret.txt"
            secret.write_text("TOP_SECRET", encoding="utf-8")
            cfg = dict(load_config())
            cfg["BAIZE_WORKSPACE_DIR"] = str(ws)
            cfg["BAIZE_ALLOW_OUTSIDE_WORKSPACE"] = "0"
            with patch.object(tools_mod, "load_config", return_value=cfg):
                out = tools_mod._tool_load_skill(str(secret))
            self.assertIn("ERROR", out)
            self.assertNotIn("TOP_SECRET", out)


class TestLLMAndAgentProtocol(unittest.TestCase):
    def test_anthropic_request_translates_tool_calls_and_tool_results(self):
        spec = ModelSpec(name="claude", base_url="https://api.anthropic.com", provider="anthropic")
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "check file"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "print(1)"},
        ]
        body = _anthropic_request(spec, msgs, None, None)
        self.assertEqual(len(body["messages"]), 3)
        self.assertEqual(body["messages"][1]["role"], "assistant")
        self.assertEqual(body["messages"][1]["content"][0]["type"], "tool_use")
        self.assertEqual(body["messages"][1]["content"][0]["input"], {"path": "a.py"})
        self.assertEqual(body["messages"][2]["role"], "user")
        self.assertEqual(body["messages"][2]["content"][0]["type"], "tool_result")
        self.assertEqual(body["messages"][2]["content"][0]["tool_use_id"], "call_1")
        self.assertEqual(body["messages"][2]["content"][0]["content"], "print(1)")

    def test_select_preserves_weight_priority_order(self):
        router = json.dumps([
            {"name": "backup", "base_url": "http://b/v1", "weight": 1},
            {"name": "primary", "base_url": "http://a/v1", "weight": 5},
        ])
        client = LLMClient(cfg={"BAIZE_MODEL_ROUTER": router})
        names = [m.name for m in client._select()]
        self.assertEqual(names, ["primary", "backup"])

    def test_stream_does_not_duplicate_when_partial_chunks_already_yielded(self):
        def broken_midstream(url, headers, payload):
            yield {"choices": [{"delta": {"content": "part1 "}}]}
            raise RuntimeError("socket reset")

        client = LLMClient(
            cfg={"BAIZE_MODEL_BASE_URL": "http://x/v1", "BAIZE_MODEL_NAME": "m"},
            transport=lambda u, h, p: {"choices": [{"message": {"content": "full"}}]},
            stream_transport=broken_midstream,
        )
        gen = client.chat([{"role": "user", "content": "hi"}], stream=True)
        first = next(gen)
        self.assertEqual(first, {"delta": "part1 "})
        with self.assertRaises(LLMError):
            next(gen)

    def test_agent_malformed_json_retry_keeps_valid_tool_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = dict(load_config())
            cfg["BAIZE_SESSIONS_DIR"] = tmp
            cfg["BAIZE_PERSISTENCE_DIR"] = tmp
            cfg["BAIZE_WORKSPACE_DIR"] = tmp
            cfg["BAIZE_AUTO_HARVEST_SKILLS"] = "0"
            cfg["BAIZE_REPO_MAP_ENABLED"] = "0"
            cfg["BAIZE_TOOL_RETRY_MAX"] = "1"

            seen_convos: list[list[dict]] = []
            turn = {"n": 0}

            def fake_transport(url, headers, payload):
                seen_convos.append(payload["messages"])
                turn["n"] += 1
                if turn["n"] == 1:
                    return {"choices": [{"message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": "tc_bad",
                            "type": "function",
                            "function": {"name": "list_dir", "arguments": "{bad json"},
                        }],
                    }}]}
                if turn["n"] == 2:
                    return {"choices": [{"message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": "tc_good",
                            "type": "function",
                            "function": {"name": "list_dir", "arguments": '{"path":"."}'},
                        }],
                    }}]}
                return {"choices": [{"message": {"role": "assistant", "content": "done"}}]}

            client = LLMClient(cfg={**cfg, "BAIZE_MODEL_BASE_URL": "http://x/v1", "BAIZE_MODEL_NAME": "m"},
                               transport=fake_transport)
            agent = Agent(cfg=cfg, client=client)
            res = agent.run("list workspace")
            self.assertEqual(res.stopped_reason, "final")
            # Second call (retry) must contain a tool role response for tc_bad
            retry_msgs = seen_convos[1]
            self.assertTrue(any(m.get("role") == "tool" and m.get("tool_call_id") == "tc_bad" for m in retry_msgs))


class TestDocCrawlerAndMCP(unittest.TestCase):
    def test_ssrf_and_scheme_validation(self):
        for bad in (
            "file:///etc/passwd",
            "http://127.0.0.1:8787/health",
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost:8000/",
            "http://10.0.0.1/",
        ):
            ok, _ = validate_public_http_url(bad)
            self.assertFalse(ok, f"expected blocked: {bad}")

    def test_html_parser_recovers_from_unclosed_tag_inside_ignore_stack(self):
        parser = DocHTMLToMarkdownParser()
        parser.feed("<nav><aside>noise</nav><p>Visible documentation content</p>")
        md = parser.get_markdown()
        self.assertIn("Visible documentation content", md)
        self.assertNotIn("noise", md)

    def test_mcp_sqlite_executes_real_readonly_sql_and_blocks_writes(self):
        res = call_mcp_tool("sqlite", "sqlite_query", {"sql": "SELECT 2 + 3 AS total"})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], [{"total": 5}])

        bad = call_mcp_tool("sqlite", "sqlite_query", {"sql": "DROP TABLE users"})
        self.assertEqual(bad["status"], "error")


class TestConcurrencyDAGAndServe(unittest.TestCase):
    def test_observability_thread_safety_and_prometheus_sanitization(self):
        o = Observability()
        o.inc("err-type.v1", 2)
        prom = o.prometheus()
        self.assertIn("baize_err_type_v1 2", prom)

        def worker():
            for i in range(100):
                o.inc(f"c_{i % 5}")
                with o.span("op"):
                    pass
                _ = o.prometheus()

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(o.counter(f"c_{i}") for i in range(5)), 600)

    def test_orchestrator_dag_detects_cycle_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = dict(load_config())
            cfg["BAIZE_PERSISTENCE_DIR"] = tmp
            cfg["BAIZE_SESSIONS_DIR"] = tmp
            cfg["BAIZE_WORKSPACE_DIR"] = tmp
            orch = Orchestrator(cfg=cfg, client=LLMClient(cfg=cfg))
            plan = [
                {"id": 1, "task": "a", "verify": "ok", "depends_on": [2]},
                {"id": 2, "task": "b", "verify": "ok", "depends_on": [1]},
            ]
            reports = orch._run_dag(plan, set(), [], workers=2)
            self.assertEqual(len(reports), 2)
            self.assertTrue(all(r.verdict == "fail" for r in reports))

    def test_autonomy_level_and_yolo_mode_wired(self):
        self.assertEqual(resolve_autonomy_level({"BAIZE_AUTONOMY_LEVEL": "1"}), "supervised")
        self.assertEqual(resolve_autonomy_level({"BAIZE_AUTONOMY_LEVEL": "3"}), "autonomous")
        self.assertEqual(resolve_autonomy_level({"BAIZE_YOLO_MODE": "1"}), "autonomous")
        pol = build_policy({"BAIZE_AUTONOMY_LEVEL": "1"})
        self.assertEqual(pol.level, "supervised")

    def test_studio_modular_assets_and_render(self):
        css = read_studio_asset("styles.css")
        js = read_studio_asset("app.js")
        self.assertIsNotNone(css)
        self.assertIsNotNone(js)
        html = render_desktop_studio("39.0.0")
        self.assertIn("V39.0.0", html)
        self.assertIn("testMcpCall", html)
        self.assertNotIn("__STYLE_BLOCK__", html)
        self.assertNotIn("__SCRIPT_BLOCK__", html)

    def test_serve_path_traversal_and_session_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {
                "BAIZE_AUTH_TOKEN": "tok123",
                "BAIZE_SESSIONS_DIR": tmp,
            }):
                srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                t = threading.Thread(target=srv.serve_forever, daemon=True)
                t.start()
                base = f"http://127.0.0.1:{srv.server_address[1]}"
                try:
                    # Path traversal on save_skill
                    req = urllib.request.Request(
                        f"{base}/api/skills",
                        data=json.dumps({"name": "../evil", "content": "x"}).encode(),
                        headers={"Content-Type": "application/json", "Authorization": "Bearer tok123"},
                        method="POST",
                    )
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen(req, timeout=5)
                    self.assertEqual(ctx.exception.code, 400)

                    # Path traversal on DELETE /sessions/
                    req2 = urllib.request.Request(
                        f"{base}/sessions/..%2Fevil",
                        headers={"Authorization": "Bearer tok123"},
                        method="DELETE",
                    )
                    with self.assertRaises(urllib.error.HTTPError) as ctx2:
                        urllib.request.urlopen(req2, timeout=5)
                    self.assertEqual(ctx2.exception.code, 400)

                    # Static studio asset served with ETag
                    with urllib.request.urlopen(f"{base}/studio/styles.css", timeout=5) as r:
                        self.assertEqual(r.status, 200)
                        self.assertTrue(r.headers.get("ETag"))
                finally:
                    srv.shutdown()
                    srv.server_close()

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                _read_records("../escape", cfg={"BAIZE_SESSIONS_DIR": tmp, "BAIZE_PERSISTENCE_DIR": tmp})

    def test_arch_cache_concurrent_saves(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = ArchCacheManager(cache_file=Path(tmp) / "arch_cache.json")
            mgr.cache_data = {"a.py": {"mtime": 1.0, "size": 10, "symbols": []}}
            errors: list[Exception] = []

            def saver():
                try:
                    for _ in range(10):
                        mgr.save()
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=saver) for _ in range(4)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            self.assertEqual(errors, [])


    def test_serve_live_sse_and_autonomy_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {
                "BAIZE_AUTH_TOKEN": "tok123",
                "BAIZE_SESSIONS_DIR": tmp,
                "BAIZE_PERSISTENCE_DIR": tmp,
                "BAIZE_WORKSPACE_DIR": tmp,
                "BAIZE_MODEL_BASE_URL": "http://mock-llm/v1",
                "BAIZE_MODEL_NAME": "mock-model",
                "BAIZE_MODEL_API_KEY": "real-looking-key",
            }):
                def fake_chat(self_client, msgs, tools=None, temperature=None, stream=False):
                    # Slow down slightly and emit a tool call then final answer
                    if not any(m.get("role") == "tool" for m in msgs):
                        return {"role": "assistant", "content": "", "tool_calls": [{
                            "id": "c1", "type": "function",
                            "function": {"name": "list_dir", "arguments": '{"path":"."}'},
                        }]}
                    return {"role": "assistant", "content": "streamed final answer"}

                srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                t = threading.Thread(target=srv.serve_forever, daemon=True)
                t.start()
                base = f"http://127.0.0.1:{srv.server_address[1]}"
                try:
                    # 1. /api/config reports effective=True and updates build_policy()
                    cfg_req = urllib.request.Request(
                        f"{base}/api/config",
                        data=json.dumps({"autonomy_level": 3}).encode(),
                        headers={"Content-Type": "application/json", "Authorization": "Bearer tok123"},
                        method="POST",
                    )
                    with urllib.request.urlopen(cfg_req, timeout=5) as resp:
                        cfg_body = json.loads(resp.read().decode())
                    self.assertTrue(cfg_body["effective"])
                    self.assertEqual(build_policy().level, "autonomous")

                    # 2. /run/stream emits real-time tool events before delta/done
                    with patch.object(LLMClient, "chat", fake_chat):
                        sse_req = urllib.request.Request(
                            f"{base}/run/stream",
                            data=json.dumps({"goal": "check dir"}).encode(),
                            headers={"Content-Type": "application/json", "Authorization": "Bearer tok123"},
                            method="POST",
                        )
                        with urllib.request.urlopen(sse_req, timeout=10) as resp:
                            sse_raw = resp.read().decode("utf-8")
                    self.assertIn("event: think", sse_raw)
                    self.assertIn("event: tool", sse_raw)
                    self.assertIn("event: delta", sse_raw)
                    self.assertIn("event: done", sse_raw)
                    self.assertIn("streamed final answer", sse_raw)
                finally:
                    srv.shutdown()
                    srv.server_close()


    def test_grep_search_and_find_files_tools(self):
        from baize.execution.tools import default_registry
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "alpha.py").write_text("def needle_fn():\n    return 42\n", encoding="utf-8")
            (Path(tmp) / "beta.txt").write_text("just plain text\n", encoding="utf-8")
            (Path(tmp) / "bin.dat").write_bytes(b"\x00\x01\x02needle_fn\x00")
            with patch.dict(os.environ, {"BAIZE_WORKSPACE_DIR": tmp}):
                reg = default_registry()
                grep_out = reg.execute("grep_search", {"pattern": r"def needle_\w+", "glob": "*.py"})
                self.assertIn("alpha.py:1: def needle_fn():", grep_out)
                self.assertNotIn("bin.dat", grep_out)

                files_out = reg.execute("find_files", {"pattern": "*.py"})
                self.assertIn("alpha.py", files_out)
                self.assertNotIn("beta.txt", files_out)

    def test_http_pool_reuse_and_llm_telemetry(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from baize.core.llm import LLMClient, _CONN_POOL

        class KeepAliveHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                self.rfile.read(n)
                body = json.dumps({
                    "choices": [{"message": {"content": "pooled-ok"}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 5},
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Connection", "keep-alive")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a):
                pass

        _CONN_POOL.close_all()
        before = _CONN_POOL.stats()
        srv = HTTPServer(("127.0.0.1", 0), KeepAliveHandler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            client = LLMClient(cfg={
                "BAIZE_MODEL_BASE_URL": f"http://127.0.0.1:{srv.server_address[1]}/v1",
                "BAIZE_MODEL_NAME": "test-model",
                "BAIZE_MODEL_API_KEY": "real-key",
            })
            r1 = client.chat([{"role": "user", "content": "one"}])
            r2 = client.chat([{"role": "user", "content": "two"}])
            self.assertEqual(r1["content"], "pooled-ok")
            self.assertEqual(r2["content"], "pooled-ok")
            after = _CONN_POOL.stats()
            self.assertGreater(after["hits"], before["hits"])
            tel = client.telemetry()
            self.assertEqual(tel["requests"], 2)
            self.assertEqual(tel["prompt_tokens"], 24)
            self.assertEqual(tel["completion_tokens"], 10)
        finally:
            _CONN_POOL.close_all()
            srv.shutdown()
            srv.server_close()

    def test_perf_profile_and_serve_search_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "sample.py").write_text("class DemoEngine:\n    pass\n", encoding="utf-8")
            with patch.dict(os.environ, {
                "BAIZE_AUTH_TOKEN": "tok123",
                "BAIZE_WORKSPACE_DIR": tmp,
                "BAIZE_PERSISTENCE_DIR": tmp,
                "BAIZE_SESSIONS_DIR": tmp,
            }):
                srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                t = threading.Thread(target=srv.serve_forever, daemon=True)
                t.start()
                base = f"http://127.0.0.1:{srv.server_address[1]}"
                try:
                    req_s = urllib.request.Request(
                        f"{base}/api/workspace/search?q=DemoEngine",
                        headers={"Authorization": "Bearer tok123"},
                    )
                    with urllib.request.urlopen(req_s, timeout=5) as resp:
                        body_s = json.loads(resp.read().decode())
                    self.assertIn("sample.py:1:", body_s["output"])

                    req_p = urllib.request.Request(
                        f"{base}/api/perf/profile",
                        headers={"Authorization": "Bearer tok123"},
                    )
                    with urllib.request.urlopen(req_p, timeout=5) as resp:
                        body_p = json.loads(resp.read().decode())
                    self.assertIn("timings", body_p)
                    self.assertIn("top_bottlenecks", body_p)
                    self.assertGreaterEqual(len(body_p["timings"]), 5)
                finally:
                    srv.shutdown()
                    srv.server_close()

if __name__ == "__main__":
    unittest.main()
