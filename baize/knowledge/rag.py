"""Zero-dependency TF-IDF vector index and RAG retrieval augmentation."""

from __future__ import annotations

# ===========================================================================
# Section: vector.py
# ===========================================================================

import json
import math
import re
import urllib.request
from collections import Counter

from ..core.config import load_config
from ..governance.observability import obs

__all__ = ["tokenize", "TfidfIndex", "EmbeddingBackend", "get_backend"]

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """Lowercased word tokens + CJK character bigrams (and single chars)."""
    text = text.lower()
    tokens = _WORD_RE.findall(text)
    cjk = _CJK_RE.findall(text)
    tokens.extend(cjk)
    tokens.extend(a + b for a, b in zip(cjk, cjk[1:]))
    return tokens


class TfidfIndex:
    """In-memory index supporting both TF-IDF cosine similarity and BM25 ranking."""

    def __init__(self) -> None:
        self._docs: dict[str, Counter] = {}      # doc_id -> term freq
        self._meta: dict[str, dict] = {}
        self._df: Counter = Counter()            # term -> doc freq
        self._doc_lengths: dict[str, int] = {}   # doc_id -> total tokens
        self._built = False
        self._idf: dict[str, float] = {}
        self._bm25_idf: dict[str, float] = {}
        self._norms: dict[str, float] = {}
        self._avgdl: float = 1.0

    def add(self, doc_id: str, text: str, meta: dict | None = None) -> None:
        tokens = tokenize(text)
        tf = Counter(tokens)
        if not tf:
            return
        if doc_id in self._docs:                 # re-add = replace
            for term in self._docs[doc_id]:
                self._df[term] -= 1
        self._docs[doc_id] = tf
        self._doc_lengths[doc_id] = len(tokens)
        self._meta[doc_id] = meta or {}
        for term in tf:
            self._df[term] += 1
        self._built = False

    def build(self) -> None:
        n = max(1, len(self._docs))
        self._idf = {t: math.log((n + 1) / (df + 1)) + 1.0
                     for t, df in self._df.items() if df > 0}
        # BM25 probabilistic IDF: ln((N - df + 0.5) / (df + 0.5) + 1)
        self._bm25_idf = {
            t: max(0.0, math.log((n - df + 0.5) / (df + 0.5) + 1.0))
            for t, df in self._df.items() if df > 0
        }
        self._avgdl = (sum(self._doc_lengths.values()) / n) if n > 0 else 1.0
        self._norms = {}
        for doc_id, tf in self._docs.items():
            norm = math.sqrt(sum(
                (freq * self._idf.get(t, 0.0)) ** 2 for t, freq in tf.items()))
            self._norms[doc_id] = norm or 1.0
        self._built = True

    def search(self, query: str, top_k: int = 5, method: str = "tfidf") -> list[dict]:
        if not self._built:
            self.build()
        q_tokens = tokenize(query)
        q_tf = Counter(q_tokens)
        if not q_tf or not self._docs:
            return []

        if method == "bm25":
            # BM25: k1=1.5, b=0.75
            k1 = 1.5
            b = 0.75
            scored = []
            for doc_id, tf in self._docs.items():
                dl = self._doc_lengths.get(doc_id, 1)
                score = 0.0
                for term in q_tf:
                    if term not in tf:
                        continue
                    f = tf[term]
                    idf = self._bm25_idf.get(term, 0.0)
                    denom = f + k1 * (1.0 - b + b * (dl / (self._avgdl or 1.0)))
                    score += idf * (f * (k1 + 1.0)) / (denom or 1.0)
                if score > 0:
                    scored.append({"id": doc_id,
                                   "score": round(score, 4),
                                   "meta": self._meta.get(doc_id, {})})
            scored.sort(key=lambda h: -h["score"])
            return scored[:top_k]

        # Default: TF-IDF cosine similarity
        q_vec = {t: freq * self._idf.get(t, 0.0) for t, freq in q_tf.items()}
        q_norm = math.sqrt(sum(w * w for w in q_vec.values())) or 1.0
        scored = []
        for doc_id, tf in self._docs.items():
            dot = sum(q_vec.get(t, 0.0) * freq * self._idf.get(t, 0.0)
                      for t, freq in tf.items() if t in q_vec)
            if dot <= 0:
                continue
            scored.append({"id": doc_id,
                           "score": round(dot / (self._norms[doc_id] * q_norm), 4),
                           "meta": self._meta.get(doc_id, {})})
        scored.sort(key=lambda h: -h["score"])
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self._docs)


class EmbeddingBackend:
    """Reserved V20 interface: OpenAI-compatible /embeddings endpoint.

    The interface is final; enable it by setting BAIZE_VECTOR_BACKEND=embedding
    and BAIZE_EMBEDDING_URL. Transport is injectable so tests never need a
    network. Falls back with a clear error instead of pretending to work.
    """

    def __init__(self, cfg: dict | None = None, transport=None):
        self.cfg = cfg or load_config()
        self.url = self.cfg.get("BAIZE_EMBEDDING_URL", "")
        self.transport = transport or self._http_transport

    @property
    def configured(self) -> bool:
        return bool(self.url)

    @staticmethod
    def _http_transport(url: str, payload: dict) -> dict:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.configured:
            obs.record_error("embedding_not_configured")
            raise RuntimeError(
                "embedding backend not configured - set BAIZE_EMBEDDING_URL "
                "(or use the default tfidf backend)")
        raw = self.transport(self.url, {"input": texts})
        return [d["embedding"] for d in raw.get("data", [])]


def get_backend(cfg: dict | None = None):
    """Backend factory honoring BAIZE_VECTOR_BACKEND (tfidf | embedding)."""
    cfg = cfg or load_config()
    if cfg.get("BAIZE_VECTOR_BACKEND", "tfidf") == "embedding":
        return EmbeddingBackend(cfg)
    return TfidfIndex()

# ===========================================================================
# Section: rag.py
# ===========================================================================

import json
import time
from pathlib import Path

from ..core.config import load_config
from ..core.config import redact
from ..governance.observability import obs
from . import memory as memory_mod
from . import skills as skill_index

__all__ = ["build_corpus", "retrieve", "augment",
           "record_skill_outcome", "skill_scores"]

MAX_MEMORY_DOCS = 500          # bounded corpus - newest first


def build_corpus(cfg: dict | None = None) -> TfidfIndex:
    """Index skills + memory into one searchable TF-IDF corpus."""
    cfg = cfg or load_config()
    index = TfidfIndex()

    idx = skill_index.load_index(cfg)
    for s in idx.get("skills", []):
        index.add(f"skill:{s['name']}",
                  redact(f"{s['name']} {s['description']}"),
                  {"kind": "skill", "name": s["name"],
                   "skill_file": s.get("skill_file", "")})

    hits = memory_mod.recall("", cfg=cfg, limit=MAX_MEMORY_DOCS)
    for i, h in enumerate(hits):
        text = redact(str(h.get("text", "")))
        index.add(f"mem:{i}:{h.get('source', '')}",
                  text,
                  {"kind": "memory", "source": h.get("source", ""),
                   "text": text[:300]})

    index.build()
    obs.gauge("rag_corpus_docs", len(index))
    return index


# Common dev synonym mapping for query expansion
SYNONYM_MAP: dict[str, list[str]] = {
    "bug": ["错误", "异常", "fix", "defect"],
    "调试": ["debug", "排查", "log", "trace"],
    "测试": ["test", "pytest", "unit", "check"],
    "配置": ["config", "env", "settings"],
    "网络": ["network", "http", "fetch", "url"],
    "工具": ["tool", "plugin", "skill"],
    "部署": ["deploy", "docker", "release"],
}


def expand_query(query: str) -> str:
    """Expand query with relevant synonyms."""
    extra = []
    q_lower = query.lower()
    for word, syns in SYNONYM_MAP.items():
        if word in q_lower:
            extra.extend(syns)
    if extra:
        return f"{query} {' '.join(extra)}"
    return query


def retrieve(query: str, cfg: dict | None = None, top_k: int = 5,
             corpus: TfidfIndex | None = None) -> list[dict]:
    """Hybrid RAG retrieval combining TF-IDF and BM25 with Reciprocal Rank Fusion."""
    corpus = corpus or build_corpus(cfg)
    expanded = expand_query(query)

    # Search with TF-IDF
    tfidf_hits = corpus.search(expanded, top_k=top_k * 2, method="tfidf")
    # Search with BM25
    bm25_hits = corpus.search(expanded, top_k=top_k * 2, method="bm25")

    # Reciprocal Rank Fusion (RRF): score(d) = sum(1 / (k + rank))
    k = 60
    rrf_scores: dict[str, float] = {}
    meta_map: dict[str, dict] = {}

    for rank, h in enumerate(tfidf_hits):
        doc_id = h["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank + 1))
        meta_map[doc_id] = h.get("meta", {})

    for rank, h in enumerate(bm25_hits):
        doc_id = h["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank + 1))
        meta_map[doc_id] = h.get("meta", {})

    # Sort merged results by fused score
    fused = [
        {"id": doc_id, "score": round(score * 100, 3), "meta": meta_map[doc_id]}
        for doc_id, score in sorted(rrf_scores.items(), key=lambda kv: -kv[1])
    ]
    obs.inc("rag_queries")
    return fused[:top_k]


def augment(goal: str, cfg: dict | None = None, top_k: int = 5) -> str:
    """Render RAG hits as a context block for prompt injection ('' if none)."""
    hits = retrieve(goal, cfg=cfg, top_k=top_k)
    if not hits:
        return ""
    lines = []
    seen = set()
    for h in hits:
        m = h["meta"]
        if m.get("kind") == "skill":
            name = m.get("name", "")
            if name and name not in seen:
                seen.add(name)
                lines.append(f"- [skill {h['score']}] {name} "
                             f"(load with load_skill: {m.get('skill_file', '')})")
        else:
            text = m.get("text", "").strip()
            if text and text not in seen:
                seen.add(text)
                lines.append(f"- [memory {h['score']}] {text}")
    return ("Retrieved context (RAG):\n" + "\n".join(lines)) if lines else ""


# --- skill usage scoring -----------------------------------------------------

def _stats_file(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    p = Path(cfg["BAIZE_PERSISTENCE_DIR"])
    p.mkdir(parents=True, exist_ok=True)
    return p / "skill_stats.json"


def record_skill_outcome(skill_name: str, success: bool,
                         cfg: dict | None = None) -> dict:
    """Persist a real usage outcome for a skill (drives future ranking)."""
    f = _stats_file(cfg)
    try:
        data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except json.JSONDecodeError:
        data = {}
    entry = data.setdefault(skill_name, {"uses": 0, "successes": 0,
                                         "last_used": ""})
    entry["uses"] += 1
    if success:
        entry["successes"] += 1
    entry["last_used"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return entry


def skill_scores(cfg: dict | None = None) -> dict:
    """{skill_name: {"uses","successes","success_rate","last_used"}}."""
    f = _stats_file(cfg)
    try:
        data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except json.JSONDecodeError:
        data = {}
    for entry in data.values():
        uses = entry.get("uses", 0)
        entry["success_rate"] = (round(entry.get("successes", 0) / uses, 3)
                                 if uses else 0.0)
    return data
