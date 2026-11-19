"""End-to-end tests for V42 SQLite WAL TeamMemory and Hybrid FTS5+Embedding Search."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from baize.knowledge.hybrid_index import HybridSearchIndex
from baize.knowledge.memory import TeamMemory


class _MockEmbeddingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        inp = body.get("input", [])
        if isinstance(inp, str):
            inp = [inp]
        data = []
        for idx, text in enumerate(inp):
            low = str(text).lower()
            # Deterministic 3D semantic embeddings:
            # dim0 = circuit/budget/cost concept
            # dim1 = worktree/git/branch concept
            # dim2 = browser/cdp/websocket concept
            v0 = 1.0 if any(w in low for w in ("budget", "cost", "circuit", "usd", "billing")) else 0.05
            v1 = 1.0 if any(w in low for w in ("worktree", "git", "branch", "merge")) else 0.05
            v2 = 1.0 if any(w in low for w in ("cdp", "browser", "websocket", "screenshot")) else 0.05
            data.append({"index": idx, "embedding": [v0, v1, v2]})
        resp = json.dumps({"data": data}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, fmt, *args):
        return


class TestV42HybridAndSharedMemory(unittest.TestCase):
    def test_team_memory_sqlite_wal_concurrent_claims(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {
                "BAIZE_PERSISTENCE_DIR": td,
                "BAIZE_TEAM_MEMORY_BACKEND": "shared",
            }
            winners: list[str] = []
            lock = threading.Lock()
            barrier = threading.Barrier(8)

            def _worker(i: int) -> None:
                tm = TeamMemory("team-wal", cfg=cfg)
                barrier.wait()
                if tm.claim("task-alpha", f"worker-{i}"):
                    with lock:
                        winners.append(f"worker-{i}")
                tm.post(f"worker-{i}", f"hello from {i}")

            threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

            self.assertEqual(len(winners), 1, f"expected 1 winner, got {winners}")
            tm_check = TeamMemory("team-wal", cfg=cfg)
            self.assertIn(tm_check.backend, ("shared", "sqlite"))
            self.assertEqual(tm_check.owner_of("task-alpha"), winners[0])
            self.assertEqual(len(tm_check.read(limit=50)), 8)
            st = tm_check.stats()
            self.assertEqual(st["notes"], 8)
            self.assertEqual(st["claims"], 1)
            tm_check.clear()
            self.assertEqual(tm_check.read(), [])

    def test_hybrid_index_fts5_incremental_and_offline_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            ws.mkdir()
            (ws / "cost.py").write_text("def check_budget_limit(usd):\n    return usd < 1.5\n", encoding="utf-8")
            (ws / "worktree.py").write_text("def merge_git_worktree(branch):\n    return True\n", encoding="utf-8")

            cfg = {
                "BAIZE_PERSISTENCE_DIR": td,
                "BAIZE_HYBRID_INDEX_PATH": str(Path(td) / "hybrid.sqlite3"),
                "BAIZE_EMBEDDING_URL": "",
            }
            idx = HybridSearchIndex(cfg)
            self.assertFalse(idx.embedding_configured)
            r1 = idx.index_workspace(ws)
            self.assertEqual(r1["updated"], 2)
            r2 = idx.index_workspace(ws)
            self.assertEqual(r2["updated"], 0)
            self.assertGreaterEqual(r2["scanned"], 2)

            hits = idx.search("check_budget_limit", mode="hybrid", limit=5)
            self.assertTrue(hits)
            self.assertIn("cost.py", hits[0].doc_id)

    def test_hybrid_index_rrf_fusion_with_mock_embedding_server(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockEmbeddingHandler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                cfg = {
                    "BAIZE_PERSISTENCE_DIR": td,
                    "BAIZE_HYBRID_INDEX_PATH": str(Path(td) / "hybrid_vec.sqlite3"),
                    "BAIZE_EMBEDDING_URL": f"http://127.0.0.1:{port}/v1/embeddings",
                    "BAIZE_EMBEDDING_API_KEY": "test-key",
                    "BAIZE_EMBEDDING_MODEL": "mock-embed-v1",
                }
                idx = HybridSearchIndex(cfg)
                self.assertTrue(idx.embedding_configured)
                idx.upsert("doc_cost", source="code", title="cost.py", content="session billing circuit breaker usd cap")
                idx.upsert("doc_wt", source="code", title="worktree.py", content="parallel git worktree merge isolation")
                idx.upsert("doc_cdp", source="code", title="cdp.py", content="headless chrome websocket screenshot")

                st = idx.stats()
                self.assertEqual(st["total_docs"], 3)
                self.assertEqual(st["embedded_docs"], 3)

                # Semantic query with word "budget" (not in doc_cost text literally!)
                emb_hits = idx.search("budget", mode="embedding", limit=3)
                self.assertTrue(emb_hits)
                self.assertEqual(emb_hits[0].doc_id, "doc_cost")

                hyb_hits = idx.search("budget circuit", mode="hybrid", limit=3)
                self.assertTrue(hyb_hits)
                self.assertEqual(hyb_hits[0].doc_id, "doc_cost")
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
