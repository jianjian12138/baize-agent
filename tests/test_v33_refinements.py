"""Tests for V33 Masterpiece Refinements:
- Read file line slicing
- Patch file CRLF / LF newline tolerance
- Run python deep AST sandbox escape blocking
- RunLedger & TeamMemory thread-safety
- Bi-directional evidence preservation in context compression
"""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from baize.tools import _tool_read_file, _tool_patch_file, _ast_check_python, default_registry
from baize.run_ledger import RunLedger
from baize.team_memory import TeamMemory
from baize.agent import _evidence_note, compress_context


class TestRefinedTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        from baize import tools as tools_mod
        self._orig_resolve = tools_mod._resolve_in_workspace

        def fake_resolve(p, cfg=None):
            return Path(self.tmp) / Path(p).name

        tools_mod._resolve_in_workspace = fake_resolve

    def tearDown(self):
        from baize import tools as tools_mod
        tools_mod._resolve_in_workspace = self._orig_resolve

    def test_read_file_line_range_slicing(self):
        p = Path(self.tmp) / "large.txt"
        lines = [f"line {i}" for i in range(1, 101)]
        p.write_text("\n".join(lines), encoding="utf-8")

        # Slice lines 10 to 15
        sliced = _tool_read_file("large.txt", start_line=10, end_line=15)
        self.assertIn("line 10", sliced)
        self.assertIn("line 15", sliced)
        self.assertNotIn("line 9\n", sliced)
        self.assertNotIn("line 16", sliced)

    def test_patch_file_crlf_tolerance(self):
        p = Path(self.tmp) / "crlf.txt"
        p.write_text("first line\ndef foo():\n    return 1\nlast line\n", encoding="utf-8")

        # Model provides CRLF string (\r\n) against LF file
        res = _tool_patch_file("crlf.txt", "def foo():\r\n    return 1", "def foo():\r\n    return 42")
        self.assertIn("patched", res)
        self.assertIn("newline normalization", res)
        self.assertIn("return 42", p.read_text(encoding="utf-8"))

    def test_ast_blocks_reflection_escapes(self):
        # sys.modules access
        err = _ast_check_python("import sys\nsys.modules['os'].system('ls')")
        self.assertIsNotNone(err)

        # __subclasses__ traversal
        err2 = _ast_check_python("x = ().__class__.__bases__[0].__subclasses__()")
        self.assertIsNotNone(err2)
        self.assertIn("__subclasses__", err2)

        # __globals__ access
        err3 = _ast_check_python("f = lambda: None\ng = f.__globals__")
        self.assertIsNotNone(err3)
        self.assertIn("__globals__", err3)


class TestConcurrencySafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"BAIZE_PERSISTENCE_DIR": self.tmp}

    def test_run_ledger_concurrent_writes(self):
        ledger = RunLedger("test-run-thread", cfg=self.cfg)
        num_threads = 8
        events_per_thread = 25

        def writer(thread_id):
            for i in range(events_per_thread):
                ledger.append("task_verified", {"thread": thread_id, "i": i}, task_id=f"t-{thread_id}")

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        events = ledger.events()
        self.assertEqual(len(events), num_threads * events_per_thread)

    def test_team_memory_concurrent_claims(self):
        tm = TeamMemory(team_id="team-thread", cfg=self.cfg)
        num_threads = 10
        claims_success = []
        lock = threading.Lock()

        def claimer(role_name):
            ok = tm.claim("unique-task-1", role_name)
            with lock:
                if ok:
                    claims_success.append(role_name)

        threads = [threading.Thread(target=claimer, args=(f"executor-{i}",)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly ONE thread should win the claim
        self.assertEqual(len(claims_success), 1)


class TestEvidencePreservation(unittest.TestCase):
    def test_evidence_preserves_head_and_tail(self):
        long_output = "STARTING TEST SUITE\n" + ("x" * 500) + "\nTraceback: AssertionError in test_auth.py line 42\nexit=1"
        note = _evidence_note(long_output)
        self.assertIn("STARTING TEST SUITE", note)
        self.assertIn("AssertionError", note)
        self.assertIn("exit=1", note)
        self.assertIn("errors=yes", note)


if __name__ == "__main__":
    unittest.main()
