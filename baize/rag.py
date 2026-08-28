"""V20 RAG - retrieval-augmented context over skills + persistent memory.

Builds a unified TF-IDF corpus from:
  - the skill index (name + description per skill)
  - memory notes.md lines and daily log events

`retrieve()` returns ranked hits; `augment()` renders them as a compact
context block ready for injection into an agent's first user turn (replaces
the naive keyword-only recall_context path when useful).

Also hosts skill usage scoring: every recorded outcome updates
persistence/skill_stats.json so ranking can favor skills that actually work.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import load_config
from .logging_setup import redact
from .observability import obs
from .vector import TfidfIndex
from . import memory as memory_mod
from . import skill_index

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
