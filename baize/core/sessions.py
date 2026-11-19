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
import uuid
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


def _safe_session_file(sessions_dir: Path, session_id: str) -> Path:
    sid = (session_id or "").strip()
    if not sid or "/" in sid or "\\" in sid or ".." in sid or "\x00" in sid:
        raise ValueError(f"invalid session id: {session_id!r}")
    root = sessions_dir.resolve()
    cand = (root / f"{sid}.jsonl").resolve()
    if root not in cand.parents:
        raise ValueError(f"session id escapes sessions dir: {session_id!r}")
    return cand


def _read_records(session_id: str, cfg: dict | None = None) -> list[dict]:
    d = _sessions_dir(cfg)
    src = _safe_session_file(d, session_id)
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


# ---------------------------------------------------------------------------
# V41: Dual-Axis Tree Session Navigation & Git Checkpoint Rewind (/tree, /rewind)
# ---------------------------------------------------------------------------

def _tree_ledger_path(cfg: dict | None = None) -> Path:
    d = _sessions_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    return d / "_tree_nodes.jsonl"


def record_checkpoint_node(
    session_id: str,
    *,
    turn_index: int,
    checkpoint_id: str = "",
    summary: str = "",
    parent_node_id: str = "",
    cfg: dict | None = None,
) -> dict:
    """Record a navigable tree node linking a session turn to an optional Git checkpoint."""
    node_id = f"node-{uuid.uuid4().hex[:8]}"
    rec = {
        "node_id": node_id,
        "parent_node_id": parent_node_id or "",
        "session_id": session_id,
        "turn_index": int(turn_index),
        "checkpoint_id": checkpoint_id or "",
        "summary": (summary or "")[:160],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    p = _tree_ledger_path(cfg)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def list_checkpoint_nodes(session_id: str | None = None, cfg: dict | None = None) -> list[dict]:
    p = _tree_ledger_path(cfg)
    if not p.is_file():
        return []
    out: list[dict] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if session_id is None or rec.get("session_id") == session_id:
            out.append(rec)
    return out


def build_session_tree(cfg: dict | None = None) -> dict:
    """Build a unified tree across session lineage and checkpoint nodes."""
    lineage = list_lineage(cfg)
    nodes = list_checkpoint_nodes(cfg=cfg)
    by_id = {n["node_id"]: {**n, "children": []} for n in nodes}
    roots: list[dict] = []
    for n in by_id.values():
        pid = n.get("parent_node_id") or ""
        if pid and pid in by_id:
            by_id[pid]["children"].append(n)
        else:
            roots.append(n)
    return {
        "lineage": lineage,
        "node_count": len(nodes),
        "roots": roots,
        "nodes": nodes,
    }


def format_session_tree(cfg: dict | None = None) -> str:
    tree = build_session_tree(cfg)
    roots = tree["roots"]
    if not roots:
        return "(no tree checkpoints recorded yet)"
    lines: list[str] = ["Session Checkpoint Tree:"]

    def _walk(node: dict, prefix: str, is_last: bool) -> None:
        branch = "└── " if is_last else "├── "
        ckpt = f" ckpt={node['checkpoint_id']}" if node.get("checkpoint_id") else ""
        summ = f" — {node['summary']}" if node.get("summary") else ""
        lines.append(
            f"{prefix}{branch}{node['node_id']} [sess={node['session_id']} turn={node['turn_index']}{ckpt}]{summ}"
        )
        kids = node.get("children") or []
        child_prefix = prefix + ("    " if is_last else "│   ")
        for idx, kid in enumerate(kids):
            _walk(kid, child_prefix, idx == len(kids) - 1)

    for i, r in enumerate(roots):
        _walk(r, "", i == len(roots) - 1)
    return "\n".join(lines)


def rewind_session(
    session_id: str,
    node_id: str,
    *,
    restore_code: bool = False,
    workspace: str = ".",
    cfg: dict | None = None,
) -> dict:
    """Fork a session back to a recorded tree node and optionally roll back Git workspace."""
    nodes = list_checkpoint_nodes(cfg=cfg)
    target = next((n for n in nodes if n.get("node_id") == node_id), None)
    if target is None:
        return {"ok": False, "error": f"unknown node_id: {node_id}"}
    src_sid = session_id or target["session_id"]
    turn_idx = int(target.get("turn_index", 0))
    try:
        new_sid = fork_session(src_sid, at_index=max(1, turn_idx), cfg=cfg)
    except Exception as exc:
        return {"ok": False, "error": f"fork_session failed: {exc}"}

    code_restored = False
    rollback_detail: dict = {}
    ckpt_id = str(target.get("checkpoint_id") or "")
    if restore_code and ckpt_id:
        from ..execution.checkpoint import GitCheckpointManager

        mgr = GitCheckpointManager(workspace)
        rb = mgr.rollback(ckpt_id)
        code_restored = bool(rb.get("ok"))
        rollback_detail = rb

    child_node = record_checkpoint_node(
        new_sid,
        turn_index=turn_idx,
        checkpoint_id=ckpt_id,
        summary=f"rewound from {node_id}",
        parent_node_id=node_id,
        cfg=cfg,
    )
    return {
        "ok": True,
        "new_session_id": new_sid,
        "new_node_id": child_node["node_id"],
        "rewound_to": node_id,
        "checkpoint_id": ckpt_id,
        "code_restored": code_restored,
        "rollback_detail": rollback_detail,
    }
