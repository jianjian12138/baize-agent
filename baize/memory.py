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
from .logging_setup import redact


def _persistence_dir(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    p = Path(cfg["BAIZE_PERSISTENCE_DIR"])
    (p / "logs").mkdir(parents=True, exist_ok=True)
    return p


VALID_CATEGORIES = frozenset({"fact", "decision", "assumption", "lesson"})


def log_event(text: str, tags: list[str] | None = None,
              category: str = "fact",
              run_id: str | None = None,
              task_id: str | None = None,
              evidence: str | None = None,
              cfg: dict | None = None) -> Path:
    """Append an event to today's JSONL log. Returns the log file path.

    V26-C1: Supports memory layering (category) and provenance lineage
    (run_id, task_id, evidence). Handles legacy callers where cfg was the 3rd arg.
    """
    if isinstance(category, dict) and cfg is None:
        cfg = category
        category = "fact"

    p = _persistence_dir(cfg)
    day = time.strftime("%Y-%m-%d")
    log_file = p / "logs" / f"{day}.jsonl"
    cat = category if isinstance(category, str) and category in VALID_CATEGORIES else "fact"
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "text": redact(text),
        "tags": tags or [],
        "category": cat,
        "run_id": run_id,
        "task_id": task_id,
        "evidence": evidence,
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
        f.write(f"- [{stamp}] {redact(text)}\n")
    return notes


def recall(query: str, cfg: dict | None = None, limit: int = 20,
           tags: list[str] | None = None,
           category: str | None = None) -> list[dict]:
    """Search notes and all daily logs.

    - Multiple keywords (space-separated) use AND semantics: all must match.
    - If ``tags`` is given, only log records whose tags intersect the filter
      are returned (notes.md has no tags, so it is excluded when filtering).
    - If ``category`` is given, only log records matching the category are
      returned (notes.md is excluded when filtering by category).
    - Results are ranked by relevance (number of keyword hits, descending).
    - Empty query returns everything (respecting limit / tags / category).
    """
    p = _persistence_dir(cfg)
    keywords = [k.lower() for k in query.split() if k]
    tag_filter = {t.lower() for t in tags} if tags else None
    cat_filter = category.lower() if category else None
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

    # notes.md (no tags / category field — skip when tag or category filter is active)
    notes = p / "notes.md"
    if notes.exists() and tag_filter is None and cat_filter is None:
        for line in notes.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            score = _score(line)
            if score >= 0:
                hits.append({"source": "notes.md", "text": line.strip(),
                             "category": "fact", "score": score})

    for log_file in sorted((p / "logs").glob("*.jsonl"), reverse=True):
        for line in log_file.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec_tags = {t.lower() for t in rec.get("tags", [])}
            if tag_filter is not None and not (rec_tags & tag_filter):
                continue
            rec_cat = str(rec.get("category", "fact")).lower()
            if cat_filter is not None and rec_cat != cat_filter:
                continue
            score = _score(rec.get("text", ""))
            if score >= 0:
                hits.append({
                    "source": log_file.name,
                    "text": rec["text"],
                    "ts": rec.get("ts", ""),
                    "tags": rec.get("tags", []),
                    "category": rec.get("category", "fact"),
                    "run_id": rec.get("run_id"),
                    "task_id": rec.get("task_id"),
                    "evidence": rec.get("evidence"),
                    "score": score,
                })
            if len(hits) >= limit * 3:
                break

    hits.sort(key=lambda h: h.get("score", 0), reverse=True)
    return hits[:limit]


def compress(days: int | None = None, cfg: dict | None = None) -> dict:
    """Long-term memory compression (V20).

    Distills daily logs older than ``days`` into a compact summary appended to
    notes.md (event count + tag histogram + up to 5 representative entries per
    file), then deletes the old log files. Keeps memory bounded over months of
    operation instead of growing forever.

    Returns {"compressed_files": N, "events_distilled": M, "notes": path}.
    """
    cfg = cfg or load_config()
    if days is None:
        days = int(cfg.get("BAIZE_MEMORY_COMPRESS_DAYS", "30"))
    p = _persistence_dir(cfg)
    cutoff = time.strftime(
        "%Y-%m-%d", time.localtime(time.time() - days * 86400))
    notes = p / "notes.md"
    compressed_files = 0
    events_distilled = 0

    for log_file in sorted((p / "logs").glob("*.jsonl")):
        day = log_file.stem                      # YYYY-MM-DD
        if day >= cutoff:                        # string compare works for ISO dates
            continue
        records: list[dict] = []
        for line in log_file.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if records:
            tag_hist: dict[str, int] = {}
            for r in records:
                for t in r.get("tags", []):
                    tag_hist[t] = tag_hist.get(t, 0) + 1
            top_tags = ", ".join(
                f"{t}x{n}" for t, n in
                sorted(tag_hist.items(), key=lambda kv: -kv[1])[:6]) or "untagged"
            samples = "; ".join(
                redact(str(r.get("text", ""))[:80]) for r in records[:5])
            with notes.open("a", encoding="utf-8") as f:
                f.write(f"- [compressed {day}] {len(records)} events "
                        f"({top_tags}). Samples: {samples}\n")
            events_distilled += len(records)
        log_file.unlink()
        compressed_files += 1

    return {"compressed_files": compressed_files,
            "events_distilled": events_distilled,
            "notes": str(notes)}


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
