"""End-to-end OTel tracing, OTLP export, git-delta hybrid RAG, fuzzy auto-diagnose edit & CodingBench tests (V44 Atlas)."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from baize.execution import tools
from baize.governance.eval_harness import EvalHistoryStore, run_coding_benchmark
from baize.governance.telemetry import Tracer, format_traceparent, parse_traceparent
from baize.knowledge.hybrid_index import HybridSearchIndex


class TestV44AtlasTelemetryEval(unittest.TestCase):
    def test_w3c_traceparent_nested_spans_and_otlp_export(self) -> None:
        received: list[dict] = []

        class _OTLPHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                return

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                received.append(json.loads(body))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

        srv = ThreadingHTTPServer(("127.0.0.1", 0), _OTLPHandler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                cfg = {
                    "BAIZE_PERSISTENCE_DIR": td,
                    "BAIZE_OTLP_ENDPOINT": f"http://127.0.0.1:{port}/v1/traces",
                    "BAIZE_EGRESS_ALLOWLIST": "",
                }
                tracer = Tracer(service_name="baize-test", cfg=cfg)
                tp = format_traceparent("4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7", "01")
                parsed = parse_traceparent(tp)
                self.assertEqual(parsed, ("4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7", "01"))

                with tracer.start_span("http.request", traceparent=tp, attributes={"route": "/api/chat"}) as parent:
                    with tracer.start_span("tool.read_file", attributes={"path": "README.md"}) as child:
                        child.add_event("file_opened", {"bytes": 128})
                    self.assertEqual(child.trace_id, parent.trace_id)
                    self.assertEqual(child.parent_span_id, parent.span_id)

                recent = tracer.recent_traces(limit=10)
                self.assertGreaterEqual(len(recent), 2)

                flushed = tracer.flush_otlp(timeout=2.0)
                self.assertTrue(flushed["ok"])
                self.assertEqual(flushed["exported"], 2)
                self.assertEqual(len(received), 1)
                spans = received[0]["resourceSpans"][0]["scopeSpans"][0]["spans"]
                self.assertEqual(len(spans), 2)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_hybrid_index_git_delta_and_deletion_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "keep.py").write_text("def alpha_keep_token():\n    return 1\n", encoding="utf-8")
            (repo / "obsolete.py").write_text("def zulu_obsolete_marker():\n    return 2\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

            idx = HybridSearchIndex(
                db_path=Path(td) / "hybrid.sqlite3",
                cfg={"BAIZE_EMBEDDING_BASE_URL": "", "BAIZE_HYBRID_MAX_FILES": "100"},
            )
            r1 = idx.index_git_delta(repo)
            self.assertEqual(r1["updated"], 2)
            self.assertGreaterEqual(len(idx.search("zulu_obsolete_marker", mode="lexical")), 1)

            (repo / "obsolete.py").unlink()
            (repo / "fresh.py").write_text("def atlas_fresh_signal():\n    return 44\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "delta"], cwd=repo, check=True)

            r2 = idx.index_git_delta(repo)
            self.assertEqual(r2["updated"], 1)
            self.assertEqual(r2["scanned"], 2)
            self.assertEqual(r2["pruned"], 1)
            self.assertEqual(len(idx.search("zulu_obsolete_marker", mode="lexical")), 0)
            self.assertGreaterEqual(len(idx.search("atlas_fresh_signal", mode="lexical")), 1)

    def test_tools_fuzzy_whitespace_patch_and_auto_diagnose(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            target = ws / "sample.py"
            target.write_text("def calc():\n    x = 1\n    return x + 1\n", encoding="utf-8")
            old_ws = os.environ.get("BAIZE_WORKSPACE_DIR")
            old_diag = os.environ.get("BAIZE_AUTO_DIAGNOSE_ON_EDIT")
            os.environ["BAIZE_WORKSPACE_DIR"] = str(ws)
            os.environ["BAIZE_AUTO_DIAGNOSE_ON_EDIT"] = "1"
            try:
                patch_res = tools._tool_patch_file(
                    "sample.py",
                    "  x = 1\n  return x + 1",
                    "    x = 43\n    return x + 1",
                )
                self.assertIn("fuzzy", patch_res.lower())
                self.assertIn("x = 43", target.read_text(encoding="utf-8"))

                write_res = tools._tool_write_file("broken.py", "def oops(:\n    pass\n")
                self.assertIn("auto-diagnose", write_res.lower())
            finally:
                if old_ws is None:
                    os.environ.pop("BAIZE_WORKSPACE_DIR", None)
                else:
                    os.environ["BAIZE_WORKSPACE_DIR"] = old_ws
                if old_diag is None:
                    os.environ.pop("BAIZE_AUTO_DIAGNOSE_ON_EDIT", None)
                else:
                    os.environ["BAIZE_AUTO_DIAGNOSE_ON_EDIT"] = old_diag

    def test_coding_benchmark_offline_and_regression_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = {"BAIZE_PERSISTENCE_DIR": td}
            r1 = run_coding_benchmark(mode="offline", cfg=cfg, persist_history=True)
            self.assertEqual(r1["mode"], "offline")
            self.assertEqual(r1["total_tasks"], 4)
            self.assertEqual(r1["passed_tasks"], 4)
            self.assertEqual(r1["pass_rate"], 1.0)

            r2 = run_coding_benchmark(mode="offline", cfg=cfg, persist_history=True)
            self.assertEqual(r2["regression_delta"], 0.0)
            self.assertFalse(r2["regressed"])

            store = EvalHistoryStore(cfg=cfg)
            hist = store.recent(limit=10)
            self.assertEqual(len(hist), 2)


if __name__ == "__main__":
    unittest.main()
