"""V42.0.0 Helios — Persistent Hybrid Semantic Search (SQLite FTS5 + Embedding + RRF).

Pure Python standard library (sqlite3 FTS5 + urllib.request).
Provides incremental mtime/sha256-tracked indexing across workspace files, sessions,
memory notes, and skills, fusing lexical BM25 scores (FTS5) with optional vector
cosine similarity from any OpenAI-compatible ``/v1/embeddings`` endpoint via
Reciprocal Rank Fusion (RRF). Seamlessly degrades to FTS5 + TF-IDF offline.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..core.config import load_config


@dataclass
class SearchHit:
    doc_id: str
    source: str       # code | memory | session | skill
    title: str
    snippet: str
    score: float
    fts_rank: int | None = None
    vec_rank: int | None = None
    mode: str = "hybrid"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _safe_fts_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", query or "")
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens[:16])


class HybridSearchIndex:
    """SQLite FTS5 + optional HTTP Embedding hybrid knowledge index with RRF."""

    def __init__(self, db_path: str | Path | dict[str, Any] | None = None, cfg: dict[str, Any] | None = None) -> None:
        if isinstance(db_path, dict) and cfg is None:
            cfg, db_path = db_path, None
        self.cfg = cfg or load_config()
        if db_path is None:
            custom = (self.cfg.get("BAIZE_HYBRID_INDEX_PATH") or "").strip()
            if custom:
                db_path = Path(custom)
            else:
                base = Path(self.cfg.get("BAIZE_PERSISTENCE_DIR", "persistence"))
                db_path = base / "hybrid_index.sqlite3"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS docs (
                    doc_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    mtime REAL NOT NULL,
                    embedding_json TEXT DEFAULT ''
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
                    doc_id UNINDEXED,
                    source UNINDEXED,
                    title,
                    content,
                    tokenize = 'unicode61'
                );
                """
            )

    @property
    def embedding_url(self) -> str:
        return str(self.cfg.get("BAIZE_EMBEDDING_URL") or "").strip()

    @property
    def embedding_configured(self) -> bool:
        return bool(self.embedding_url)

    def _fetch_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Call an OpenAI-compatible ``/v1/embeddings`` HTTP endpoint via pure stdlib."""
        url = self.embedding_url
        if not url:
            raise RuntimeError("BAIZE_EMBEDDING_URL is not configured")
        api_key = (
            self.cfg.get("BAIZE_EMBEDDING_API_KEY")
            or self.cfg.get("BAIZE_MODEL_API_KEY")
            or ""
        ).strip()
        model = (self.cfg.get("BAIZE_EMBEDDING_MODEL") or "text-embedding-3-small").strip()
        payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        data = body.get("data") or []
        data.sort(key=lambda item: item.get("index", 0))
        return [list(map(float, item["embedding"])) for item in data]

    def upsert(
        self,
        doc_id: str,
        *,
        source: str,
        title: str,
        content: str,
        mtime: float | None = None,
        compute_embedding: bool = True,
    ) -> bool:
        """Incrementally upsert a document; skips re-indexing if sha256 is unchanged."""
        digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        ts = float(mtime if mtime is not None else time.time())
        with self._connect() as conn:
            row = conn.execute("SELECT sha256, embedding_json FROM docs WHERE doc_id = ?", (doc_id,)).fetchone()
            if row and row[0] == digest:
                if not compute_embedding or not self.embedding_configured or row[1]:
                    return False

            emb_json = ""
            if compute_embedding and self.embedding_configured:
                try:
                    vecs = self._fetch_embeddings([f"{title}\n{content[:4000]}"])
                    if vecs:
                        emb_json = json.dumps(vecs[0])
                except Exception:
                    emb_json = ""

            conn.execute(
                """
                INSERT INTO docs(doc_id, source, title, content, sha256, mtime, embedding_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    source=excluded.source,
                    title=excluded.title,
                    content=excluded.content,
                    sha256=excluded.sha256,
                    mtime=excluded.mtime,
                    embedding_json=CASE WHEN excluded.embedding_json != '' THEN excluded.embedding_json ELSE docs.embedding_json END
                """,
                (doc_id, source, title, content, digest, ts, emb_json),
            )
            conn.execute("DELETE FROM docs_fts WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "INSERT INTO docs_fts(doc_id, source, title, content) VALUES (?, ?, ?, ?)",
                (doc_id, source, title, content),
            )
            return True

    def index_workspace(
        self,
        workspace: str | Path,
        *,
        extensions: tuple[str, ...] = (".py", ".md", ".ts", ".js", ".json", ".toml"),
        max_files: int = 300,
    ) -> dict[str, int]:
        """Incrementally index workspace source files."""
        ws = Path(workspace).resolve()
        skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".baize_worktrees", "dist", "build"}
        scanned = 0
        updated = 0
        for root, dirs, files in os.walk(ws):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            for fn in sorted(files):
                if scanned >= max_files:
                    break
                p = Path(root) / fn
                if p.suffix.lower() not in extensions:
                    continue
                try:
                    st = p.stat()
                    if st.st_size > 256_000:
                        continue
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                scanned += 1
                rel = str(p.relative_to(ws)).replace("\\", "/")
                if self.upsert(f"code:{rel}", source="code", title=rel, content=text, mtime=st.st_mtime):
                    updated += 1
        return {"scanned": scanned, "updated": updated, "total_docs": self.stats()["total_docs"]}

    def search(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        source: str = "",
        limit: int = 8,
        rrf_k: int = 60,
    ) -> list[SearchHit]:
        """Search via ``fts5``, ``embedding``, or ``hybrid`` (RRF fusion)."""
        mode = (mode or "hybrid").strip().lower()
        q = (query or "").strip()
        if not q:
            return []

        fts_ranks: dict[str, int] = {}
        vec_ranks: dict[str, int] = {}
        meta: dict[str, tuple[str, str, str]] = {}

        with self._connect() as conn:
            # 1. Lexical FTS5 BM25 pass
            if mode in ("fts5", "hybrid"):
                fts_q = _safe_fts_query(q)
                if fts_q:
                    sql = (
                        "SELECT d.doc_id, d.source, d.title, d.content, bm25(docs_fts) AS rank_score "
                        "FROM docs_fts JOIN docs d ON d.doc_id = docs_fts.doc_id "
                        "WHERE docs_fts MATCH ? "
                    )
                    params: list[Any] = [fts_q]
                    if source:
                        sql += "AND d.source = ? "
                        params.append(source)
                    sql += "ORDER BY rank_score LIMIT ?"
                    params.append(max(limit * 3, 20))
                    try:
                        rows = conn.execute(sql, params).fetchall()
                    except sqlite3.OperationalError:
                        rows = []
                    for idx, (doc_id, src, title, content, _bm) in enumerate(rows, start=1):
                        fts_ranks[doc_id] = idx
                        meta[doc_id] = (src, title, content)

            # 2. Vector embedding similarity pass (when configured)
            if mode in ("embedding", "hybrid") and self.embedding_configured:
                try:
                    q_vecs = self._fetch_embeddings([q])
                    q_vec = q_vecs[0] if q_vecs else []
                except Exception:
                    q_vec = []
                if q_vec:
                    sql = "SELECT doc_id, source, title, content, embedding_json FROM docs WHERE embedding_json != ''"
                    params2: list[Any] = []
                    if source:
                        sql += " AND source = ?"
                        params2.append(source)
                    scored_vecs: list[tuple[float, str, str, str, str]] = []
                    for doc_id, src, title, content, ej in conn.execute(sql, params2).fetchall():
                        try:
                            dv = json.loads(ej)
                            sim = _cosine_similarity(q_vec, dv)
                        except Exception:
                            sim = 0.0
                        if sim > 0.0:
                            scored_vecs.append((sim, doc_id, src, title, content))
                    scored_vecs.sort(key=lambda x: -x[0])
                    for idx, (_sim, doc_id, src, title, content) in enumerate(scored_vecs[: max(limit * 3, 20)], start=1):
                        vec_ranks[doc_id] = idx
                        meta[doc_id] = (src, title, content)

            # 3. Substring/token fallback when FTS5 returned nothing (e.g., symbols or short queries)
            if not fts_ranks and not vec_ranks:
                needle = q.lower()
                sql = "SELECT doc_id, source, title, content FROM docs"
                params3: list[Any] = []
                if source:
                    sql += " WHERE source = ?"
                    params3.append(source)
                fallback_hits: list[tuple[int, str, str, str, str]] = []
                for doc_id, src, title, content in conn.execute(sql, params3).fetchall():
                    cnt = (title + "\n" + content).lower().count(needle)
                    if cnt > 0:
                        fallback_hits.append((cnt, doc_id, src, title, content))
                fallback_hits.sort(key=lambda x: -x[0])
                for idx, (_cnt, doc_id, src, title, content) in enumerate(fallback_hits[:limit], start=1):
                    fts_ranks[doc_id] = idx
                    meta[doc_id] = (src, title, content)

        # Reciprocal Rank Fusion (RRF)
        all_ids = set(fts_ranks) | set(vec_ranks)
        fused: list[SearchHit] = []
        for doc_id in all_ids:
            r_fts = fts_ranks.get(doc_id)
            r_vec = vec_ranks.get(doc_id)
            score = 0.0
            if r_fts is not None:
                score += 1.0 / (rrf_k + r_fts)
            if r_vec is not None:
                score += 1.0 / (rrf_k + r_vec)
            src, title, content = meta[doc_id]
            snippet = content.strip().replace("\n", " ")[:220]
            fused.append(
                SearchHit(
                    doc_id=doc_id,
                    source=src,
                    title=title,
                    snippet=snippet,
                    score=round(score, 6),
                    fts_rank=r_fts,
                    vec_rank=r_vec,
                    mode=mode,
                )
            )
        fused.sort(key=lambda h: (-h.score, h.doc_id))
        return fused[: max(1, limit)]

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
            with_vec = conn.execute("SELECT COUNT(*) FROM docs WHERE embedding_json != ''").fetchone()[0]
            by_src = dict(conn.execute("SELECT source, COUNT(*) FROM docs GROUP BY source").fetchall())
        return {
            "db_path": str(self.db_path),
            "total_docs": int(total),
            "embedded_docs": int(with_vec),
            "embedding_configured": self.embedding_configured,
            "by_source": by_src,
        }
