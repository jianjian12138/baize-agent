"""Tests for V40 production server: SQLite WAL JobStore, rate limiter,
real /team/dag, /api/git/apply_hunk, /api/diagnostics, /api/jobs, /api/checkpoints.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from baize.interfaces import serve
from baize.interfaces.server.jobs import JobStore, SlidingWindowRateLimiter


def _http(url: str, method: str = "GET", payload: dict | None = None,
          token: str = "v40-tok") -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


class TestV40ServerProduction(unittest.TestCase):
    def test_sliding_window_rate_limiter(self):
        rl = SlidingWindowRateLimiter(max_requests=2, window_seconds=10.0)
        self.assertEqual(rl.allow("k", now=1.0), (True, 0.0))
        self.assertEqual(rl.allow("k", now=2.0), (True, 0.0))
        ok, retry = rl.allow("k", now=3.0)
        self.assertFalse(ok)
        self.assertGreater(retry, 0.0)
        self.assertEqual(rl.allow("k", now=12.0), (True, 0.0))

    def test_job_store_lifecycle_and_crash_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "jobs.sqlite3"
            store = JobStore(db, max_workers=2)
            try:
                job = store.enqueue(
                    "eval",
                    {"mode": "oracle"},
                    lambda jid, payload, cancel_ev, emit: (emit("step", "done"), {"ok": True})[1],
                )
                jid = job["job_id"]
                deadline = time.time() + 5.0
                cur = store.get(jid)
                while cur and cur["status"] in ("queued", "running") and time.time() < deadline:
                    time.sleep(0.05)
                    cur = store.get(jid)
                self.assertEqual(cur["status"], "succeeded")
                self.assertEqual(cur["result"], {"ok": True})
                self.assertGreaterEqual(len(cur["events"]), 2)
            finally:
                store.shutdown(wait=True)

            conn = sqlite3.connect(str(db))
            conn.execute(
                "INSERT INTO jobs(job_id, kind, status, payload_json, created_at, started_at) "
                "VALUES ('job-orphan', 'run', 'running', '{}', 1.0, 1.0)"
            )
            conn.commit()
            conn.close()

            store2 = JobStore(db, max_workers=1)
            try:
                orphan = store2.get("job-orphan")
                self.assertEqual(orphan["status"], "failed")
                self.assertEqual(orphan["error"], "interrupted_by_restart")
            finally:
                store2.shutdown(wait=True)

    def test_live_http_routes_dag_apply_hunk_diagnostics_jobs_checkpoints(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "repo"
            pers = Path(td) / "pers"
            ws.mkdir()
            pers.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
            subprocess.run(["git", "config", "user.email", "t@baize.local"], cwd=ws, check=True)
            subprocess.run(["git", "config", "user.name", "Baize"], cwd=ws, check=True)
            (ws / "hello.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "hello.py"], cwd=ws, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=ws, check=True)

            env_patch = {
                "BAIZE_AUTH_TOKEN": "v40-tok",
                "BAIZE_WORKSPACE_DIR": str(ws),
                "BAIZE_PERSISTENCE_DIR": str(pers),
                "BAIZE_HTTP_RPM": "0",
            }
            with mock.patch.dict(os.environ, env_patch, clear=False):
                srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
                t = threading.Thread(target=srv.serve_forever, daemon=True)
                t.start()
                base = f"http://127.0.0.1:{srv.server_address[1]}"
                try:
                    st, body = _http(f"{base}/health")
                    self.assertEqual(st, 200)
                    self.assertIn("sandbox_posture", body)

                    st, body = _http(f"{base}/team/dag", "POST", {"goal": "add tests; run gates"})
                    self.assertEqual(st, 200)
                    self.assertEqual(body["mode"], "plan_only")
                    self.assertGreaterEqual(len(body["nodes"]), 3)

                    patch = (
                        "--- a/hello.py\n"
                        "+++ b/hello.py\n"
                        "@@ -1 +1 @@\n"
                        "-VALUE = 1\n"
                        "+VALUE = 2\n"
                    )
                    st, body = _http(f"{base}/api/git/apply_hunk", "POST", {"patch": patch})
                    self.assertEqual(st, 200)
                    self.assertEqual(body["status"], "applied")
                    cp_id = body["checkpoint_id"]
                    self.assertEqual((ws / "hello.py").read_text(encoding="utf-8"), "VALUE = 2\n")

                    st, cps = _http(f"{base}/api/checkpoints")
                    self.assertEqual(st, 200)
                    self.assertGreaterEqual(cps["total"], 1)

                    st, rb = _http(f"{base}/api/checkpoints/rollback", "POST", {"checkpoint_id": cp_id})
                    self.assertEqual(st, 200)
                    self.assertTrue(rb["ok"])
                    self.assertEqual((ws / "hello.py").read_text(encoding="utf-8"), "VALUE = 1\n")

                    st, dg = _http(f"{base}/api/diagnostics", "POST", {"path": "hello.py"})
                    self.assertEqual(st, 200)
                    self.assertTrue(dg["ok"])

                    st, job = _http(f"{base}/api/jobs", "POST", {"kind": "eval", "mode": "oracle", "task_ids": ["bugfix_rate_limit"]})
                    self.assertEqual(st, 202)
                    jid = job["job_id"]
                    deadline = time.time() + 10.0
                    cur = job
                    while cur["status"] in ("queued", "running") and time.time() < deadline:
                        time.sleep(0.05)
                        _, cur = _http(f"{base}/api/jobs/{jid}")
                    self.assertEqual(cur["status"], "succeeded")
                    self.assertEqual(cur["result"]["passed_tasks"], 1)
                finally:
                    srv.shutdown()
                    srv.server_close()


if __name__ == "__main__":
    unittest.main()
