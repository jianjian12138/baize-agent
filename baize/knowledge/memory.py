"""Layered episodic/semantic memory and cross-role team memory ledger."""

from __future__ import annotations

# ===========================================================================
# Section: memory.py
# ===========================================================================

import json
import os
import time
from pathlib import Path

from ..core.config import load_config
from ..core.config import redact


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
           category: str | None = None,
           semantic: bool = False) -> list[dict]:
    """Search notes and all daily logs.

    - Multiple keywords (space-separated) use AND semantics: all must match.
    - If ``tags`` is given, only log records whose tags intersect the filter
      are returned (notes.md has no tags, so it is excluded when filtering).
    - If ``category`` is given, only log records matching the category are
      returned (notes.md is excluded when filtering by category).
    - Results are ranked by relevance (number of keyword hits, descending).
    - If ``semantic=True``, augments results with TF-IDF fuzzy ranking.
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
    hits.sort(key=lambda h: h.get("score", 0), reverse=True)
    if not semantic or len(hits) >= limit or not keywords:
        return hits[:limit]

    # V31: TF-IDF semantic augmentation for partial / fuzzy semantic recall
    try:
        from .rag import TfidfIndex
        idx = TfidfIndex()
        candidates: list[dict] = []
        # Collect all notes lines and log entries not already exact-hit
        seen_texts = {h.get("text", "") for h in hits}
        if notes.exists() and tag_filter is None and cat_filter is None:
            for line in notes.read_text(encoding="utf-8").splitlines():
                t = line.strip()
                if t and t not in seen_texts:
                    doc_id = f"note:{len(candidates)}"
                    idx.add(doc_id, t, {"source": "notes.md", "text": t, "category": "fact"})
                    candidates.append({"doc_id": doc_id, "source": "notes.md", "text": t, "category": "fact"})

        for log_file in sorted((p / "logs").glob("*.jsonl"), reverse=True):
            for line in log_file.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = rec.get("text", "")
                if t and t not in seen_texts:
                    doc_id = f"log:{len(candidates)}"
                    idx.add(doc_id, t, {
                        "source": log_file.name,
                        "text": t,
                        "ts": rec.get("ts", ""),
                        "tags": rec.get("tags", []),
                        "category": rec.get("category", "fact"),
                    })
                    candidates.append(rec)

        if len(idx) > 0:
            idx.build()
            raw_hits = idx.search(query, top_k=limit - len(hits))
            for rh in raw_hits:
                if rh.get("score", 0) > 0.05:
                    m = rh.get("meta", {})
                    hits.append({
                        "source": m.get("source", "memory"),
                        "text": m.get("text", ""),
                        "ts": m.get("ts", ""),
                        "tags": m.get("tags", []),
                        "category": m.get("category", "fact"),
                        "score": round(rh.get("score", 0), 3),
                        "semantic": True,
                    })
    except Exception:
        pass

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


def archive_old_logs(days: int = 30, cfg: dict | None = None) -> dict:
    """Archive logs older than ``days`` into persistence/archive/ (V33-C1).

    Moves old daily JSONL logs into an archive directory and generates a
    consolidated weekly/monthly summary. Returns summary statistics.
    """
    cfg = cfg or load_config()
    p = _persistence_dir(cfg)
    archive_dir = p / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    cutoff = time.strftime(
        "%Y-%m-%d", time.localtime(time.time() - days * 86400))
    archived_files = 0
    archived_events = 0

    for log_file in sorted((p / "logs").glob("*.jsonl")):
        day = log_file.stem
        if day >= cutoff:
            continue
        # Move to archive directory
        target = archive_dir / log_file.name
        event_count = sum(1 for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip())
        log_file.rename(target)
        archived_files += 1
        archived_events += event_count

    return {
        "archived_files": archived_files,
        "archived_events": archived_events,
        "archive_dir": str(archive_dir),
    }


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

# ===========================================================================
# Section: team_memory.py
# ===========================================================================

import json
import threading
import time
from pathlib import Path

from ..core.config import load_config
from ..governance.observability import obs

__all__ = ["TeamMemory", "MAX_CONTEXT_ENTRIES"]

MAX_CONTEXT_ENTRIES = 12   # bounded prompt injection - newest wins


class TeamMemory:
    """Append-only shared blackboard for one team run (thread-safe)."""

    def __init__(self, team_id: str = "default", cfg: dict | None = None):
        self.cfg = cfg or load_config()
        self.team_id = "".join(c for c in team_id
                               if c.isalnum() or c in "-_") or "default"
        self._lock = threading.RLock()
        self.backend = self.cfg.get("BAIZE_TEAM_MEMORY_BACKEND", "local")
        if self.backend not in ("local", "shared"):
            raise ValueError(f"unknown team memory backend: {self.backend}")
        if self.backend == "shared":
            obs.record_error("team_memory_backend_unavailable")
            raise RuntimeError(
                "shared team-memory backend is reserved and not enabled - "
                "use BAIZE_TEAM_MEMORY_BACKEND=local")

    # --- storage ------------------------------------------------------------

    @property
    def file(self) -> Path:
        d = Path(self.cfg["BAIZE_PERSISTENCE_DIR"]) / "team_memory"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self.team_id}.jsonl"

    def _read(self) -> list[dict]:
        with self._lock:
            f = self.file
            if not f.exists():
                return []
            out = []
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # defensive: a bad line never breaks the board
            return out

    def _append(self, rec: dict) -> dict:
        with self._lock:
            with self.file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return rec

    # --- blackboard API -----------------------------------------------------

    def post(self, role: str, text: str, tags: list[str] | None = None) -> dict:
        """Publish a finding so every other role can see it."""
        text = (text or "").strip()
        if not text:
            raise ValueError("team_memory.post requires non-empty text")
        rec = {"kind": "note", "role": role, "text": text,
               "tags": tags or [], "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        obs.inc("team_memory_posts")
        return self._append(rec)

    def read(self, tags: list[str] | None = None,
             role: str | None = None, limit: int = 50) -> list[dict]:
        """Read notes, newest last, optionally filtered by tag/role."""
        want = {t.lower() for t in tags} if tags else None
        out = []
        for rec in self._read():
            if rec.get("kind") != "note":
                continue
            if role and rec.get("role") != role:
                continue
            if want and not (want & {t.lower() for t in rec.get("tags", [])}):
                continue
            out.append(rec)
        return out[-limit:]

    def context(self, limit: int = MAX_CONTEXT_ENTRIES) -> str:
        """Compact digest ready for prompt injection ('' when empty)."""
        notes = self.read(limit=limit)
        if not notes:
            return ""
        lines = [f"- [{n['role']}] {n['text']}" for n in notes]
        return "Shared team findings:\n" + "\n".join(lines)

    # --- task claiming (prevents duplicate work) ----------------------------

    def claim(self, task_id: str, role: str) -> bool:
        """Claim a task for a role. False when someone else already owns it.

        The read and the write must happen inside ONE critical section. They used
        to be two: ``owner_of()`` took the lock, released it, then ``_append()``
        took it again. With ten threads that meant all ten could read
        "unclaimed", all ten appended a claim, and all ten were told they had
        won - the duplicate-work guard silently did nothing under exactly the
        concurrency it exists for.

        Scope: atomic within one process. Two processes sharing the same JSONL
        are not serialised by an RLock; cross-process ownership is what the
        (reserved) ``shared`` backend would have to provide.
        """
        with self._lock:
            owner = self.owner_of(task_id)
            if owner is not None:
                obs.inc("team_memory_claim_conflicts")
                return owner == role      # idempotent for the same role
            self._append({"kind": "claim", "task_id": str(task_id), "role": role,
                          "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
            obs.inc("team_memory_claims")
            return True

    def owner_of(self, task_id: str) -> str | None:
        for rec in self._read():
            if rec.get("kind") == "claim" and rec.get("task_id") == str(task_id):
                return rec.get("role")
        return None

    def stats(self) -> dict:
        recs = self._read()
        notes = [r for r in recs if r.get("kind") == "note"]
        claims = [r for r in recs if r.get("kind") == "claim"]
        return {"team_id": self.team_id, "notes": len(notes),
                "claims": len(claims),
                "roles": sorted({r.get("role", "") for r in notes if r.get("role")})}

    def clear(self) -> None:
        """Wipe this team's board (used between runs / in tests).

        Truncates rather than unlinks: same semantics, but it keeps working
        under sandboxes and file-policy hooks that forbid deletion.
        """
        if self.file.exists():
            self.file.write_text("", encoding="utf-8")


# ---------------------------------------------------------------------------
# V41: Bounded Cache-Friendly Memory Snapshots (MEMORY.md & USER.md)
# ---------------------------------------------------------------------------

class BoundedMemoryStore:
    """Hermes-inspired bounded markdown memory slots injected stably into the
    system prompt prefix to preserve LLM Prompt Cache hit rates.

    Maintains two strictly bounded markdown files under ``BAIZE_PERSISTENCE_DIR``:
      - ``MEMORY.md``: durable project architecture facts & conventions (default 2400 chars)
      - ``USER.md``: developer preferences & collaboration style (default 1400 chars)
    """

    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg or load_config()
        self.root = _persistence_dir(self.cfg)
        self.max_memory_chars = max(200, int(self.cfg.get("BAIZE_MEMORY_MAX_CHARS", "2400") or "2400"))
        self.max_user_chars = max(200, int(self.cfg.get("BAIZE_USER_PROFILE_MAX_CHARS", "1400") or "1400"))

    def _slot_file(self, slot: str) -> tuple[Path, int]:
        key = (slot or "memory").strip().lower()
        if key in ("user", "user.md", "profile"):
            return self.root / "USER.md", self.max_user_chars
        return self.root / "MEMORY.md", self.max_memory_chars

    def read(self, slot: str = "memory") -> str:
        fp, cap = self._slot_file(slot)
        if not fp.is_file():
            return ""
        return fp.read_text(encoding="utf-8", errors="replace")[:cap]

    def stats(self) -> dict:
        m = self.read("memory")
        u = self.read("user")
        return {
            "memory": {"chars": len(m), "limit": self.max_memory_chars},
            "user": {"chars": len(u), "limit": self.max_user_chars},
            "revision": self.revision_hash(),
        }

    def revision_hash(self) -> str:
        import hashlib
        combined = f"M:{self.read('memory')}\n---\nU:{self.read('user')}".encode("utf-8")
        return hashlib.sha256(combined).hexdigest()[:16]

    def update(self, slot: str, action: str, content: str = "", target: str = "") -> dict:
        fp, cap = self._slot_file(slot)
        act = (action or "add").strip().lower()
        existing = fp.read_text(encoding="utf-8", errors="replace") if fp.is_file() else ""
        entry = (content or "").strip()

        if act == "add":
            if not entry:
                return {"ok": False, "error": "content is required for add"}
            line = entry if entry.startswith("- ") else f"- {entry}"
            lines = [ln for ln in existing.splitlines() if ln.strip()]
            if line not in lines:
                lines.append(line)
            new_text = "\n".join(lines) + "\n"
        elif act == "replace":
            if not target:
                return {"ok": False, "error": "target substring is required for replace"}
            if target not in existing:
                return {"ok": False, "error": f"target {target!r} not found in {fp.name}"}
            new_text = existing.replace(target, entry, 1)
        elif act == "remove":
            if not target:
                return {"ok": False, "error": "target substring is required for remove"}
            kept = [ln for ln in existing.splitlines() if target not in ln]
            new_text = ("\n".join(kept) + "\n") if kept else ""
        elif act == "set":
            new_text = entry + ("\n" if entry else "")
        else:
            return {"ok": False, "error": f"invalid action {action!r}; use add|replace|remove|set"}

        truncated = False
        if len(new_text) > cap:
            lines = [ln for ln in new_text.splitlines() if ln.strip()]
            kept_rev: list[str] = []
            used = 0
            for ln in reversed(lines):
                need = len(ln) + 1
                if used + need > cap:
                    truncated = True
                    break
                kept_rev.append(ln)
                used += need
            new_text = "\n".join(reversed(kept_rev)) + ("\n" if kept_rev else "")

        fp.parent.mkdir(parents=True, exist_ok=True)
        tmp = fp.with_suffix(".md.tmp")
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, fp)
        return {
            "ok": True,
            "file": str(fp),
            "slot": "user" if fp.name == "USER.md" else "memory",
            "chars": len(new_text),
            "max_chars": cap,
            "truncated": truncated,
            "revision_hash": self.revision_hash(),
        }

    def render_prefix_snapshot(self) -> str:
        mem = self.read("memory").strip()
        usr = self.read("user").strip()
        if not mem and not usr:
            return ""
        blocks: list[str] = ["[BOUNDED PERSISTENT MEMORY SNAPSHOT]"]
        if mem:
            blocks.append(f"<MEMORY.md>\n{mem}\n</MEMORY.md>")
        if usr:
            blocks.append(f"<USER.md>\n{usr}\n</USER.md>")
        return "\n".join(blocks)
