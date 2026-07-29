"""Persistence memory store - real cross-session memory.

Storage layout (inside BAIZE_PERSISTENCE_DIR):
    logs/YYYY-MM-DD.jsonl   append-only daily event log
    notes.md                curated long-term notes (markdown)
    skill_index.json        skill index cache (written by skill_index module)

Every write is a real file operation; every recall reads real files.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import load_config


def _persistence_dir(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    p = Path(cfg["BAIZE_PERSISTENCE_DIR"])
    (p / "logs").mkdir(parents=True, exist_ok=True)
    return p


def log_event(text: str, tags: list[str] | None = None,
              cfg: dict | None = None) -> Path:
    """Append an event to today's JSONL log. Returns the log file path."""
    p = _persistence_dir(cfg)
    day = time.strftime("%Y-%m-%d")
    log_file = p / "logs" / f"{day}.jsonl"
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "text": text,
        "tags": tags or [],
    }
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return log_file


def remember(text: str, cfg: dict | None = None) -> Path:
    """Append a curated note to notes.md (long-term memory)."""
    p = _persistence_dir(cfg)
    notes = p / "notes.md"
    stamp = time.strftime("%Y-%m-%d")
    with notes.open("a", encoding="utf-8") as f:
        f.write(f"- [{stamp}] {text}\n")
    return notes


def recall(query: str, cfg: dict | None = None, limit: int = 20,
           tags: list[str] | None = None) -> list[dict]:
    """Search notes and all daily logs.

    - Multiple keywords (space-separated) use AND semantics: all must match.
    - If ``tags`` is given, only log records whose tags intersect the filter
      are returned (notes.md has no tags, so it is excluded when filtering).
    - Results are ranked by relevance (number of keyword hits, descending).
    - Empty query returns everything (respecting limit / tags).
    """
    p = _persistence_dir(cfg)
    keywords = [k.lower() for k in query.split() if k]
    tag_filter = {t.lower() for t in tags} if tags else None
    hits: list[dict] = []

    def _score(text: str) -> int:
        """Count how many keywords appear in text (-1 if any keyword misses)."""
        text_l = text.lower()
        if not keywords:
            return 1
        total = 0
        for kw in keywords:
            if kw in text_l:
                total += 1
            else:
                return -1  # AND semantics: any miss = no match
        return total

    # notes.md (no tags field — skip when tag filter is active)
    notes = p / "notes.md"
    if notes.exists() and tag_filter is None:
        for line in notes.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            score = _score(line)
            if score >= 0:
                hits.append({"source": "notes.md", "text": line.strip(),
                             "score": score})

    for log_file in sorted((p / "logs").glob("*.jsonl"), reverse=True):
        for line in log_file.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec_tags = {t.lower() for t in rec.get("tags", [])}
            if tag_filter is not None and not (rec_tags & tag_filter):
                continue
            score = _score(rec.get("text", ""))
            if score >= 0:
                hits.append({"source": log_file.name, "text": rec["text"],
                             "ts": rec.get("ts", ""), "tags": rec.get("tags", []),
                             "score": score})
            if len(hits) >= limit * 3:
                break

    hits.sort(key=lambda h: h.get("score", 0), reverse=True)
    return hits[:limit]


def stats(cfg: dict | None = None) -> dict:
    """Real counts of what memory actually contains."""
    p = _persistence_dir(cfg)
    log_files = list((p / "logs").glob("*.jsonl"))
    total_events = 0
    for lf in log_files:
        total_events += sum(1 for line in lf.read_text(encoding="utf-8")
                            .splitlines() if line.strip())
    notes = p / "notes.md"
    note_count = 0
    if notes.exists():
        note_count = sum(1 for line in notes.read_text(encoding="utf-8")
                         .splitlines() if line.strip().startswith("-"))
    return {
        "persistence_dir": str(p),
        "log_files": len(log_files),
        "events": total_events,
        "notes": note_count,
    }
