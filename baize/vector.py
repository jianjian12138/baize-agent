"""V20 vector search - stdlib-only TF-IDF backend + reserved embedding interface.

Default backend is a real TF-IDF cosine-similarity index (zero dependencies,
works offline, deterministic). When BAIZE_VECTOR_BACKEND=embedding and
BAIZE_EMBEDDING_URL is set, the reserved EmbeddingBackend calls an
OpenAI-compatible /embeddings endpoint - interface is final, transport is
injectable for tests.

Tokenization handles both English (word tokens) and Chinese (character
bigrams) so mixed-language skill/memory text is searchable.
"""
from __future__ import annotations

import json
import math
import re
import urllib.request
from collections import Counter

from .config import load_config
from .observability import obs

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
