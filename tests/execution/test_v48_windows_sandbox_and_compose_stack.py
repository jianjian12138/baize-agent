"""V48.0.0 Apex tests: Windows native Job Object sandbox, Docker Compose stack orchestrator & HTTP/Studio integration."""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from baize.execution.compose_stack import ComposeStackManager, discover_compose_file
from baize.execution.sandbox import (
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JOB_OBJECT_LIMIT_PROCESS_MEMORY,
    SandboxPolicy,
    _run_with_win_job_object,
    build_win_job_limits,
    platform_mechanism,
    sandbox_posture,
    win_sandbox_capabilities,
)


class _FakeWin32API:
    """Deterministic fake Win32 kernel32/advapi32 surface for cross-platform unit tests."""

    def __init__(self, *, allow_restricted_token: bool = True) -> None:
        self.calls: list[str] = []
        self.allow_restricted_token = allow_restricted_token
        self.kernel32 = self
        self.advapi32 = self

    def CreateJobObjectW(self, sec, name):
        self.calls.append("CreateJobObjectW")
        return 0x1234

    def SetInformationJobObject(self, handle, info_class, info_ptr, size):
        self.calls.append(f"SetInformationJobObject:{info_class}:{size}")
        return 1

    def AssignProcessToJobObject(self, job_handle, proc_handle):
        self.calls.append("AssignProcessToJobObject")
        return 1

    def TerminateJobObject(self, job_handle, exit_code):
        self.calls.append("TerminateJobObject")
        return 1

    def CloseHandle(self, handle):
        self.calls.append("CloseHandle")
        return 1

    def GetCurrentProcess(self):
        return 0xFFFF

    def OpenProcessToken(self, proc, access, out_ref):
        self.calls.append("OpenProcessToken")
        out_ref._obj.value = 0x2222
        return 1

    def CreateRestrictedToken(self, h_tok, flags, n1, p1, n2, p2, n3, p3, out_ref):
        self.calls.append("CreateRestrictedToken")
        if self.allow_restricted_token:
            out_ref._obj.value = 0x3333
            return 1
        return 0


class TestV48WindowsJobObjectSandbox(unittest.TestCase):
    def test_build_win_job_limits_and_honest_capabilities(self):
        pol = SandboxPolicy(mode="local-hardened", cpu_seconds=45, memory_mb=512, max_processes=16, win_restricted_token=True)
        lim = build_win_job_limits(pol)
        self.assertTrue(lim["kill_on_job_close"])
        self.assertEqual(lim["active_process_limit"], 16)
        self.assertEqual(lim["process_memory_bytes"], 512 * 1024 * 1024)
        flags = lim["limit_flags"]
        self.assertTrue(flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        self.assertTrue(flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS)
        self.assertTrue(flags & JOB_OBJECT_LIMIT_PROCESS_MEMORY)

        caps = win_sandbox_capabilities({"BAIZE_WIN_SANDBOX_RESTRICTED_TOKEN": "1", "BAIZE_SANDBOX_MEM_LIMIT_MB": "512"})
        self.assertTrue(caps["restricted_token_enabled"])
        self.assertIn("docker", caps["filesystem_isolation"].lower())

    def test_linux_windows_monkeypatch_preserves_backward_compat(self):
        if os.name == "nt":
            self.skipTest("only tests non-NT host monkeypatch behavior")
        with mock.patch("baize.execution.sandbox.platform.system", return_value="Windows"):
            self.assertEqual(platform_mechanism(), "logical-only")

    def test_run_with_win_job_object_lifecycle_and_restricted_token(self):
        api = _FakeWin32API(allow_restricted_token=True)
        pol = SandboxPolicy(mode="local-hardened", memory_mb=256, win_restricted_token=True)
        res = _run_with_win_job_object("echo win-job-ok", ".", 10, pol, _win_api=api)
        self.assertEqual(res.returncode, 0)
        self.assertIn("win-job-ok", res.stdout)
        self.assertEqual(res.mechanism, "win-job-object+restricted-token")
        self.assertFalse(res.degraded)
        self.assertIn("CreateJobObjectW", api.calls)
        self.assertIn("AssignProcessToJobObject", api.calls)
        self.assertIn("CreateRestrictedToken", api.calls)
        self.assertIn("CloseHandle", api.calls)

    def test_sandbox_posture_discloses_process_and_filesystem_isolation(self):
        post = sandbox_posture({"BAIZE_SANDBOX_MODE": "local-hardened"})
        self.assertIn("win_job_object_available", post)
        self.assertIn("win_restricted_token", post)
        self.assertIn("process_isolation", post)
        self.assertIn("filesystem_isolation", post)


class TestV48ComposeStackOrchestrator(unittest.TestCase):
    def test_discover_and_honest_failure_when_missing(self):
        mgr = ComposeStackManager()
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(discover_compose_file(td))
            res = mgr.up(td)
            self.assertFalse(res["ok"])
            self.assertTrue(res.get("degraded"))

    def test_up_wait_ports_status_logs_down_and_down_all_mocked(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(2)

        mgr = ComposeStackManager()
        invocations: list[list[str]] = []

        def fake_run(argv, **kwargs):
            invocations.append(list(argv))
            cp = mock.Mock()
            cp.returncode = 0
            if "ps" in argv:
                cp.stdout = json.dumps({"Name": "baize-db-1", "Service": "db", "State": "running"}) + "\n"
            elif "logs" in argv:
                cp.stdout = "db | ready to accept connections\n"
            else:
                cp.stdout = "started\n"
            cp.stderr = ""
            return cp

        try:
            with tempfile.TemporaryDirectory() as td:
                cf = Path(td) / "docker-compose.yml"
                cf.write_text("services:\n  db:\n    image: postgres:16\n", encoding="utf-8")
                self.assertEqual(discover_compose_file(td), cf.resolve())

                with mock.patch("baize.execution.compose_stack.detect_compose_cmd", return_value=["docker", "compose"]), \
                     mock.patch("baize.execution.compose_stack.subprocess.run", side_effect=fake_run):
                    r_up = mgr.up(td, services=["db"], wait_ports=[port], timeout=5)
                    self.assertTrue(r_up["ok"])
                    self.assertTrue(r_up["project_name"].startswith("baize-stack-"))
                    self.assertTrue(r_up["ports_ready"])

                    r_st = mgr.status(td)
                    self.assertTrue(r_st["ok"])
                    self.assertEqual(len(r_st["services"]), 1)

                    r_logs = mgr.logs(td, service="db", tail=20)
                    self.assertTrue(r_logs["ok"])
                    self.assertIn("ready to accept connections", r_logs["logs"])

                    stopped = mgr.down_all()
                    self.assertEqual(stopped, 1)
                    self.assertTrue(any("down" in cmd for cmd in invocations))
        finally:
            srv.close()


class TestV48ServerRoutesAndStudio(unittest.TestCase):
    def test_v47_v48_http_endpoints_and_studio_tab(self):
        from baize.interfaces.serve import Handler

        token = "v48-secret-token"
        with tempfile.TemporaryDirectory() as td:
            env_patch = {
                "BAIZE_AUTH_TOKEN": token,
                "BAIZE_WORKSPACE_DIR": td,
                "BAIZE_STATE_DIR": str(Path(td) / "state"),
            }
            with mock.patch.dict(os.environ, env_patch, clear=False):
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                port = httpd.server_address[1]
                th = threading.Thread(target=httpd.serve_forever, daemon=True)
                th.start()
                try:
                    base = f"http://127.0.0.1:{port}"
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen(f"{base}/api/browser/sessions", timeout=5)
                    self.assertEqual(ctx.exception.code, 401)

                    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

                    req = urllib.request.Request(f"{base}/api/browser/sessions", headers=headers)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("active_count", body)

                    req = urllib.request.Request(f"{base}/api/mobile/devices", headers=headers)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("devices", body)

                    req = urllib.request.Request(f"{base}/api/compose/status", headers=headers)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("project_name", body)

                    req = urllib.request.Request(
                        f"{base}/api/compose",
                        data=json.dumps({"action": "status"}).encode("utf-8"),
                        headers=headers,
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("project_name", body)

                    req = urllib.request.Request(
                        f"{base}/api/browser/action",
                        data=json.dumps({}).encode("utf-8"),
                        headers=headers,
                        method="POST",
                    )
                    with self.assertRaises(urllib.error.HTTPError) as ctx400:
                        urllib.request.urlopen(req, timeout=5)
                    self.assertEqual(ctx400.exception.code, 400)

                    with urllib.request.urlopen(f"{base}/", timeout=5) as resp:
                        html = resp.read().decode("utf-8")
                    self.assertIn("helios-v48", html)
                    self.assertIn("全端验证与容器栈", html)
                finally:
                    httpd.shutdown()
                    httpd.server_close()


if __name__ == "__main__":
    unittest.main()
