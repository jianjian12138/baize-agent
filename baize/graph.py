"""V20 knowledge graph - lightweight triple store over persistence (stdlib-only).

Real, working minimal implementation (not a mock): triples are persisted as
append-only JSONL in persistence/graph.jsonl and queried in memory. The
interface (add / query / neighbors / stats) is final; a pluggable backend
(BAIZE_GRAPH_BACKEND) is reserved for future external graph stores.

Design notes:
  - Append-only file keeps writes crash-safe and diff-friendly.
  - Duplicate triples are de-duplicated at read time (last write wins on meta).
  - No global state: every call re-reads the file; corpus is small by design
    (agents record distilled facts, not raw logs - raw history lives in memory).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import load_config
from .observability import obs

__all__ = ["add", "query", "neighbors", "stats"]


def _graph_file(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    p = Path(cfg["BAIZE_PERSISTENCE_DIR"])
    p.mkdir(parents=True, exist_ok=True)
    return p / "graph.jsonl"


def _load(cfg: dict | None = None) -> dict[tuple, dict]:
    """Read all triples, de-duplicated by (subject, predicate, object)."""
    f = _graph_file(cfg)
    triples: dict[tuple, dict] = {}
    if not f.exists():
        return triples
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            key = (rec["s"], rec["p"], rec["o"])
        except (json.JSONDecodeError, KeyError, TypeError):
            continue  # defensive: one bad line never breaks the graph
        triples[key] = rec
    return triples


def add(subject: str, predicate: str, obj: str,
        cfg: dict | None = None) -> dict:
    """Append one triple (idempotent at query time)."""
    subject, predicate, obj = subject.strip(), predicate.strip(), obj.strip()
    if not (subject and predicate and obj):
        raise ValueError("graph.add requires non-empty subject/predicate/object")
    rec = {"s": subject, "p": predicate, "o": obj,
           "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with _graph_file(cfg).open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    obs.inc("graph_triples_added")
    return rec


def query(subject: str | None = None, predicate: str | None = None,
          obj: str | None = None, cfg: dict | None = None) -> list[dict]:
    """Pattern match: any combination of s/p/o filters (None = wildcard)."""
    out = []
    for rec in _load(cfg).values():
        if subject is not None and rec["s"] != subject:
            continue
        if predicate is not None and rec["p"] != predicate:
            continue
        if obj is not None and rec["o"] != obj:
            continue
        out.append(rec)
    return out


def neighbors(node: str, cfg: dict | None = None) -> list[dict]:
    """All triples where node appears as subject or object."""
    return [rec for rec in _load(cfg).values()
            if rec["s"] == node or rec["o"] == node]


def stats(cfg: dict | None = None) -> dict:
    triples = _load(cfg)
    nodes = {t[0] for t in triples} | {t[2] for t in triples}
    predicates = {t[1] for t in triples}
    return {"triples": len(triples), "nodes": len(nodes),
            "predicates": sorted(predicates)}
