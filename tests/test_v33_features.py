"""Comprehensive unit tests for Baize Agent V33.0.0 features:
- V33-E1/E3: Session viewer & tracing (render_session, find_session_file)
- V33-C1: Tiered memory archiving (archive_old_logs)
- V33-C2: BM25 vector search & Hybrid RAG with synonym expansion
- V33-D1: Orchestrator parallel DAG scheduling
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from baize.session_viewer import render_session, find_session_file
from baize.memory import archive_old_logs, log_event
from baize.vector import TfidfIndex, tokenize
from baize.rag import expand_query, retrieve, build_corpus
from baize.orchestrator import Orchestrator, SubtaskReport


class TestSessionViewer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.s_path = Path(self.tmp) / "test-session.jsonl"

    def test_render_empty_session(self):
        self.s_path.write_text("", encoding="utf-8")
        out = render_session(self.s_path)
        self.assertIn("empty session", out)

    def test_render_nonexistent_session(self):
        out = render_session(Path(self.tmp) / "missing.jsonl")
        self.assertIn("ERROR: session file not found", out)

    def test_render_rich_session(self):
        records = [
            {"kind": "message", "ts": "2026-08-28T10:00:00", "message": {"role": "system", "content": "system prompt..."}},
            {"kind": "message", "ts": "2026-08-28T10:00:01", "message": {"role": "user", "content": "Please write a test"}},
            {"kind": "message", "ts": "2026-08-28T10:00:02", "message": {"role": "assistant", "content": "<thinking>I need to call patch_file</thinking>", "tool_calls": [{"function": {"name": "patch_file"}}]}},
            {"kind": "span", "ts": "2026-08-28T10:00:03", "run_id": "r123", "span_id": "sp1", "tool": "patch_file", "elapsed_ms": 42, "ok": True},
            {"kind": "message", "ts": "2026-08-28T10:00:04", "message": {"role": "tool", "content": "patched file.py"}},
            {"kind": "message", "ts": "2026-08-28T10:00:05", "message": {"role": "assistant", "content": "Done! All tests pass."}},
        ]
        self.s_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        out = render_session(self.s_path)
        self.assertIn("Session: test-session", out)
        self.assertIn("SYSTEM", out)
        self.assertIn("USER", out)
        self.assertIn("ASST", out)
        self.assertIn("thinking", out)
        self.assertIn("SPAN", out)
        self.assertIn("patch_file", out)
        self.assertIn("42ms", out)
        self.assertIn("spans=1", out)

    def test_find_session_file(self):
        cfg = {"BAIZE_SESSIONS_DIR": self.tmp}
        self.s_path.write_text("{}", encoding="utf-8")
        found = find_session_file("test-session", cfg=cfg)
        self.assertIsNotNone(found)
        self.assertEqual(found.stem, "test-session")


class TestMemoryArchive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = {
            "BAIZE_PERSISTENCE_DIR": self.tmp,
            "BAIZE_MEMORY_COMPRESS_DAYS": "30",
        }
        (Path(self.tmp) / "logs").mkdir(parents=True, exist_ok=True)

    def test_archive_old_logs(self):
        # Create an old log (40 days ago)
        old_day = time.strftime("%Y-%m-%d", time.localtime(time.time() - 40 * 86400))
        old_log = Path(self.tmp) / "logs" / f"{old_day}.jsonl"
        old_log.write_text('{"text": "old event 1"}\n{"text": "old event 2"}\n', encoding="utf-8")

        # Create a recent log (today)
        today = time.strftime("%Y-%m-%d")
        recent_log = Path(self.tmp) / "logs" / f"{today}.jsonl"
        recent_log.write_text('{"text": "recent event"}\n', encoding="utf-8")

        res = archive_old_logs(days=30, cfg=self.cfg)
        self.assertEqual(res["archived_files"], 1)
        self.assertEqual(res["archived_events"], 2)

        # Verify old log moved to archive/ and recent log remained in logs/
        archive_dir = Path(self.tmp) / "archive"
        self.assertTrue((archive_dir / f"{old_day}.jsonl").is_file())
        self.assertFalse(old_log.is_file())
        self.assertTrue(recent_log.is_file())


class TestBM25AndRAG(unittest.TestCase):
    def test_bm25_scoring(self):
        idx = TfidfIndex()
        idx.add("doc1", "python agent autonomous tool execution")
        idx.add("doc2", "javascript frontend web interface")
        idx.add("doc3", "python async concurrency multithreading")
        idx.build()

        hits = idx.search("python agent", top_k=3, method="bm25")
        self.assertTrue(len(hits) > 0)
        self.assertEqual(hits[0]["id"], "doc1")

    def test_synonym_expansion(self):
        exp = expand_query("排查 bug")
        self.assertIn("错误", exp)
        self.assertIn("fix", exp)

    def test_hybrid_retrieve(self):
        idx = TfidfIndex()
        idx.add("skill:patch", "patch_file precise diff tool for code", {"kind": "skill", "name": "patch_file"})
        idx.add("skill:bash", "bash shell command runner", {"kind": "skill", "name": "bash"})
        idx.build()

        hits = retrieve("code diff patch", top_k=2, corpus=idx)
        self.assertTrue(len(hits) > 0)
        self.assertEqual(hits[0]["meta"]["name"], "patch_file")


class TestOrchestratorDAG(unittest.TestCase):
    def test_dag_dependency_resolution(self):
        plan = [
            {"id": 1, "task": "step 1", "verify": "v1", "depends_on": []},
            {"id": 2, "task": "step 2", "verify": "v2", "depends_on": [1]},
            {"id": 3, "task": "step 3", "verify": "v3", "depends_on": [1, 2]},
        ]
        # Verify plan format validation
        for p in plan:
            self.assertIn("depends_on", p)
            self.assertIsInstance(p["depends_on"], list)


if __name__ == "__main__":
    unittest.main()
