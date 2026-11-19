"""Tests for V40 zero-dependency LSP/compiler diagnostics and coding eval harness."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from baize.codebase.diagnostics import LspClient, diagnose_file, diagnose_workspace
from baize.governance.eval_harness import compare_runs, load_eval_runs, run_eval_suite


class TestV40DiagnosticsAndEval(unittest.TestCase):
    def test_diagnose_python_clean_and_syntax_error(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            ok_py = ws / "ok.py"
            ok_py.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
            rep_ok = diagnose_file(ok_py, workspace=ws)
            self.assertTrue(rep_ok.ok)
            self.assertEqual(rep_ok.error_count, 0)

            bad_py = ws / "bad.py"
            bad_py.write_text("def broken(:\n    return 1\n", encoding="utf-8")
            rep_bad = diagnose_file(bad_py, workspace=ws)
            self.assertFalse(rep_bad.ok)
            self.assertEqual(rep_bad.error_count, 1)
            self.assertIn("SyntaxError", rep_bad.format_for_agent())

    def test_diagnose_json_catches_invalid_syntax(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            bad = ws / "bad.json"
            bad.write_text("{invalid", encoding="utf-8")
            rep = diagnose_file(bad, workspace=ws)
            self.assertFalse(rep.ok)
            self.assertEqual(rep.backend, "json-parser")

    def test_diagnose_workspace_aggregates_errors(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "good.py").write_text("X = 1\n", encoding="utf-8")
            (ws / "bad.py").write_text("if True\n    pass\n", encoding="utf-8")
            summary = diagnose_workspace(ws)
            self.assertFalse(summary["ok"])
            self.assertEqual(summary["files_checked"], 2)
            self.assertEqual(summary["total_errors"], 1)

    def test_lsp_client_stdio_jsonrpc_handshake_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            fake_lsp = ws / "fake_lsp.py"
            fake_lsp.write_text(
                "import json, sys\n"
                "def read_msg():\n"
                "    hdrs = {}\n"
                "    while True:\n"
                "        line = sys.stdin.buffer.readline()\n"
                "        if not line: return None\n"
                "        s = line.decode().strip()\n"
                "        if not s: break\n"
                "        k, v = s.split(':', 1)\n"
                "        hdrs[k.lower()] = v.strip()\n"
                "    n = int(hdrs.get('content-length', '0'))\n"
                "    return json.loads(sys.stdin.buffer.read(n).decode())\n"
                "def send_msg(obj):\n"
                "    b = json.dumps(obj).encode()\n"
                "    sys.stdout.buffer.write(f'Content-Length: {len(b)}\\r\\n\\r\\n'.encode() + b)\n"
                "    sys.stdout.buffer.flush()\n"
                "while True:\n"
                "    m = read_msg()\n"
                "    if not m: break\n"
                "    if m.get('method') == 'initialize':\n"
                "        send_msg({'jsonrpc': '2.0', 'id': m['id'], 'result': {'capabilities': {}}})\n"
                "    elif m.get('method') == 'textDocument/didOpen':\n"
                "        uri = m['params']['textDocument']['uri']\n"
                "        send_msg({'jsonrpc': '2.0', 'method': 'textDocument/publishDiagnostics', 'params': {\n"
                "            'uri': uri, 'diagnostics': [{'range': {'start': {'line': 2, 'character': 4}}, 'severity': 1, 'code': 'E001', 'source': 'mock-lsp', 'message': 'undefined symbol foo'}]\n"
                "        }})\n"
                "    elif m.get('method') == 'exit':\n"
                "        break\n",
                encoding="utf-8",
            )
            sample = ws / "sample.py"
            sample.write_text("x = 1\n", encoding="utf-8")
            client = LspClient([sys.executable, str(fake_lsp)], workspace=ws, timeout=5.0)
            diags = client.diagnose_file(sample)
            self.assertEqual(len(diags), 1)
            self.assertEqual(diags[0].line, 3)
            self.assertEqual(diags[0].col, 5)
            self.assertEqual(diags[0].code, "E001")
            self.assertEqual(diags[0].source, "mock-lsp")

    def test_eval_harness_oracle_passes_all_curated_tasks_and_persists(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {"BAIZE_PERSISTENCE_DIR": td}
            summary = run_eval_suite(mode="oracle", cfg=cfg, persist=True)
            self.assertEqual(summary.total_tasks, 4)
            self.assertEqual(summary.passed_tasks, 4)
            self.assertEqual(summary.pass_rate, 1.0)
            for r in summary.results:
                self.assertTrue(r.baseline_failed, f"{r.task_id} baseline must fail first")
                self.assertTrue(r.passed, f"{r.task_id} oracle must pass")
            loaded = load_eval_runs(cfg=cfg)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["eval_run_id"], summary.eval_run_id)

    def test_eval_compare_runs_surfaces_regressions_and_improvements(self):
        run_a = {
            "eval_run_id": "eval-a",
            "pass_rate": 0.5,
            "avg_steps": 4.0,
            "avg_duration_ms": 100.0,
            "results": [
                {"task_id": "t1", "passed": True},
                {"task_id": "t2", "passed": False},
            ],
        }
        run_b = {
            "eval_run_id": "eval-b",
            "pass_rate": 0.5,
            "avg_steps": 3.0,
            "avg_duration_ms": 80.0,
            "results": [
                {"task_id": "t1", "passed": False},
                {"task_id": "t2", "passed": True},
            ],
        }
        diff = compare_runs(run_a, run_b)
        self.assertEqual(diff["regressions"], ["t1"])
        self.assertEqual(diff["improvements"], ["t2"])
        self.assertEqual(diff["avg_steps_delta"], -1.0)


if __name__ == "__main__":
    unittest.main()
