"""Session fork + compression (P2-4). Zero dependencies.

Two honest primitives built on the existing append-only ``Session``:

* ``fork_session`` - branch a session from a chosen message index, producing a
  new independent session that retains the prefix. Divergent exploration never
  mutates the parent; lineage is recorded so the UI can draw the tree.
* ``compress_session`` - deterministic *extractive* compression that PRESERVES
  verifier evidence (tool calls, verdicts, errors, goals) instead of blindly
  truncating to a character budget. Returns real before/after token counts and
  a retained summary so the dashboard can visualise the savings (NO FAKE DONE).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .agent import Session
from .config import load_config

__all__ = ["fork_session", "compress_session", "list_lineage",
           "session_tokens", "LINEAGE_FILE"]

LINEAGE_FILE = "forks.json"


def _sessions_dir(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    d = Path(cfg["BAIZE_SESSIONS_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def _token_estimate(text: str) -> int:
    """Approximate token count (~4 chars/token). Marked approximate."""
    return max(1, len(text) // 4)


def _read_records(session_id: str, cfg: dict | None = None) -> list[dict]:
    d = _sessions_dir(cfg)
    src = d / f"{session_id}.jsonl"
    if not src.exists():
        raise FileNotFoundError(f"session not found: {session_id}")
    out: list[dict] = []
    for line in src.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _record_lineage(cfg: dict | None, child_id: str, parent_id: str,
                    at_index: int) -> None:
    d = _sessions_dir(cfg)
    path = d / LINEAGE_FILE
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data[child_id] = {
        "parent": parent_id,
        "at_index": at_index,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def list_lineage(cfg: dict | None = None) -> dict:
    d = _sessions_dir(cfg)
    path = d / LINEAGE_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def fork_session(parent_id: str, at_index: int | None = None,
                 cfg: dict | None = None) -> str:
    """Branch ``parent_id`` up to ``at_index`` messages into a new session.

    Returns the new session id. The new session contains a ``fork`` marker
    record followed by the retained prefix messages (redacted like any other
    append). The parent is never modified.
    """
    recs = _read_records(parent_id, cfg)
    msgs = [r for r in recs if r.get("kind") == "message"]
    n = len(msgs)
    if at_index is None or at_index < 0:
        at_index = n
    if at_index > n:
        at_index = n
    prefix = msgs[:at_index]

    child = Session(cfg=cfg)  # generates a fresh id
    child.append_record({
        "kind": "fork",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "message": {"fork_of": parent_id, "at_index": at_index},
    })
    for m in prefix:
        child.append(m.get("message", m))
    _record_lineage(cfg, child.id, parent_id, at_index)
    return child.id


def session_tokens(session_id: str, cfg: dict | None = None) -> int:
    recs = _read_records(session_id, cfg)
    total = 0
    for r in recs:
        if r.get("kind") == "message":
            total += _token_estimate(
                json.dumps(r.get("message", ""), ensure_ascii=False))
    return total


def compress_session(session_id: str, cfg: dict | None = None,
                     keep_head: int = 4, keep_tail: int = 8) -> dict:
    """Extractive, evidence-preserving compression of a transcript.

    Keeps the first ``keep_head`` and last ``keep_tail`` messages and builds a
    structured summary that retains the verifier evidence (user goals, tool
    calls, verdicts, errors) - never a blind character truncation.
    """
    recs = _read_records(session_id, cfg)
    msgs = [r.get("message", r) for r in recs if r.get("kind") == "message"]
    before = session_tokens(session_id, cfg)

    roles: dict[str, int] = {}
    goals: list[str] = []
    tool_calls: list[str] = []
    verdicts: list[str] = []
    errors: int = 0
    for m in msgs:
        role = str(m.get("role", "unknown"))
        roles[role] = roles.get(role, 0) + 1
        content = m.get("content")
        if role == "user" and isinstance(content, str) and len(goals) < 3:
            goals.append(content[:160])
        if isinstance(content, list):                  # Anthropic-style blocks
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool_use":
                    tool_calls.append(str(part.get("name", "?")))
                elif part.get("type") == "tool_result":
                    if "error" in str(part.get("content", "")).lower():
                        errors += 1
        elif isinstance(content, str):
            low = content.lower()
            if "verdict" in low and ("pass" in low or "fail" in low):
                verdicts.append(content[:200])
            if "traceback" in low or low.startswith("error:"):
                errors += 1

    kept = msgs[:keep_head]
    if len(msgs) > keep_head:
        kept += msgs[-keep_tail:]
    after = sum(_token_estimate(json.dumps(m, ensure_ascii=False)) for m in kept)

    summary = {
        "total_messages": len(msgs),
        "roles": roles,
        "goals": goals,
        "tool_calls": tool_calls,
        "verdicts": verdicts[:5],
        "errors": errors,
        "head_kept": keep_head,
        "tail_kept": keep_tail,
        "retained_messages": len(kept),
    }
    return {
        "session_id": session_id,
        "before_tokens": before,
        "after_tokens": after,
        "saved_tokens": max(0, before - after),
        "compression_ratio": round(after / before, 3) if before else 1.0,
        "retained_messages": len(kept),
        "summary": summary,
    }
