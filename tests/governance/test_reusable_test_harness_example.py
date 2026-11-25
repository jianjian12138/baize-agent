"""Regression tests for the reusable Test Harness system in examples/test_harness/."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = ROOT / "examples" / "test_harness"
RUNNER = HARNESS_DIR / "runner.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestReusableTestHarnessExample(unittest.TestCase):
    def test_01_builtin_demo_suite_and_junit_export(self):
        with tempfile.TemporaryDirectory() as td:
            art = Path(td) / "artifacts"
            junit = Path(td) / "junit.xml"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--suite",
                    "all",
                    "--json",
                    "--artifacts-dir",
                    str(art),
                    "--junit",
                    str(junit),
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            report = json.loads(proc.stdout)
            self.assertEqual(report["total"], 6)
            self.assertEqual(report["passed"], 6)
            self.assertEqual(report["failed"], 0)
            self.assertTrue((art / "latest_report.json").is_file())
            self.assertTrue(junit.is_file())
            tree = ET.parse(junit)
            root_el = tree.getroot()
            self.assertEqual(root_el.attrib.get("tests"), "6")
            self.assertEqual(root_el.attrib.get("failures"), "0")

    def test_02_external_real_business_service_adapter_with_env_auth_and_var_chaining(self):
        items_store: dict[str, dict] = {}
        expected_token = "tok_live_harness_verify_99"

        class _BusinessHandler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code: int, obj: dict):
                raw = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/health":
                    self._send(200, {"status": "ok"})
                    return
                if self.headers.get("Authorization") != f"Bearer {expected_token}":
                    self._send(401, {"error": "UNAUTHORIZED"})
                    return
                if self.path.startswith("/api/v1/items/"):
                    iid = self.path.rsplit("/", 1)[-1]
                    if iid in items_store:
                        self._send(200, items_store[iid])
                        return
                self._send(404, {"error": "NOT_FOUND"})

            def do_POST(self):
                if self.headers.get("Authorization") != f"Bearer {expected_token}":
                    self._send(401, {"error": "UNAUTHORIZED"})
                    return
                if self.path == "/api/v1/items":
                    length = int(self.headers.get("Content-Length", "0") or 0)
                    body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                    iid = f"item-{len(items_store) + 1}"
                    rec = {"id": iid, "name": body.get("name", "")}
                    items_store[iid] = rec
                    self._send(201, rec)
                    return
                self._send(404, {"error": "NOT_FOUND"})

        port = _free_port()
        srv = ThreadingHTTPServer(("127.0.0.1", port), _BusinessHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as td:
                td_p = Path(td)
                cfg_p = td_p / "biz.harness.json"
                cfg_p.write_text(
                    (HARNESS_DIR / "real_service.config.example.json").read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                env = dict(os.environ)
                env["TEST_BASE_URL"] = f"http://127.0.0.1:{port}"
                env["TEST_API_TOKEN"] = expected_token
                proc = subprocess.run(
                    [
                        sys.executable,
                        str(RUNNER),
                        "--config",
                        str(cfg_p),
                        "--suite",
                        "all",
                        "--json",
                        "--artifacts-dir",
                        str(td_p / "art"),
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                rep = json.loads(proc.stdout)
                self.assertEqual(rep["passed"], 2)
                self.assertEqual(rep["failed"], 0)

                env_bad = dict(env, TEST_API_TOKEN="wrong_token")
                proc_bad = subprocess.run(
                    [
                        sys.executable,
                        str(RUNNER),
                        "--config",
                        str(cfg_p),
                        "--suite",
                        "e2e",
                        "--json",
                        "--artifacts-dir",
                        str(td_p / "art_bad"),
                    ],
                    env=env_bad,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(proc_bad.returncode, 1)
                rep_bad = json.loads(proc_bad.stdout)
                self.assertEqual(rep_bad["failed"], 1)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_03_streamable_http_mcp_server_with_baize_client(self):
        if str(HARNESS_DIR) not in sys.path:
            sys.path.insert(0, str(HARNESS_DIR))
        from baize.ext.mcp.client import MCPClient, MCPServerSpec
        from mcp_server import make_mcp_handler

        old_egress = os.environ.get("BAIZE_ALLOW_EGRESS")
        old_allow = os.environ.get("BAIZE_EGRESS_ALLOWLIST")
        os.environ["BAIZE_ALLOW_EGRESS"] = "1"
        os.environ["BAIZE_EGRESS_ALLOWLIST"] = "127.0.0.1,localhost"

        with tempfile.TemporaryDirectory() as td:
            port = _free_port()
            srv = ThreadingHTTPServer(
                ("127.0.0.1", port),
                make_mcp_handler(HARNESS_DIR / "harness.config.json", Path(td) / "art"),
            )
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            client = None
            try:
                client = MCPClient(
                    MCPServerSpec(name="harness", url=f"http://127.0.0.1:{port}/mcp", transport_type="http")
                ).connect()
                tools = [t.name for t in client.list_tools()]
                self.assertIn("run_harness", tools)
                self.assertIn("list_scenarios", tools)

                out = json.loads(client.call_tool("run_harness", {"suite": "smoke"}))
                self.assertEqual(out["passed"], 1)
                self.assertEqual(out["failed"], 0)

                resources = [r.uri for r in client.list_resources()]
                self.assertIn("evidence://latest", resources)
                ev = json.loads(client.read_resource("evidence://latest"))
                self.assertEqual(ev["suite"], "smoke")

                prompts = [p.name for p in client.list_prompts()]
                self.assertIn("triage_harness_failure", prompts)
            finally:
                if client is not None:
                    client.close()
                srv.shutdown()
                srv.server_close()
                if old_egress is None:
                    os.environ.pop("BAIZE_ALLOW_EGRESS", None)
                else:
                    os.environ["BAIZE_ALLOW_EGRESS"] = old_egress
                if old_allow is None:
                    os.environ.pop("BAIZE_EGRESS_ALLOWLIST", None)
                else:
                    os.environ["BAIZE_EGRESS_ALLOWLIST"] = old_allow


if __name__ == "__main__":
    unittest.main()
