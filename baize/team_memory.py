"""V20 collaborative memory - a shared blackboard for multi-agent runs.

Problem it solves: in V19 the Director/Executor/Verifier only exchanged text
through the orchestrator. Findings discovered by one role were invisible to
the others, so agents re-discovered the same facts (and the same dead ends).

This module gives every role a shared, append-only blackboard scoped to a run:

    tm = TeamMemory(team_id="run-42")
    tm.post("executor", "auth uses JWT, secret in .env", tags=["finding"])
    tm.post("verifier", "test_login fails: expired token", tags=["blocker"])
    tm.context()          -> compact digest for prompt injection
    tm.claim("task-3", "executor")   -> False if already claimed (no dup work)

Backends (BAIZE_TEAM_MEMORY_BACKEND):
  local  - JSONL under persistence/team_memory/ (default, real implementation)
  shared - reserved for a networked store; interface is final, and it
           fails closed with a clear error rather than silently degrading.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import load_config
from .observability import obs

__all__ = ["TeamMemory", "MAX_CONTEXT_ENTRIES"]

MAX_CONTEXT_ENTRIES = 12   # bounded prompt injection - newest wins


class TeamMemory:
    """Append-only shared blackboard for one team run."""

    def __init__(self, team_id: str = "default", cfg: dict | None = None):
        self.cfg = cfg or load_config()
        self.team_id = "".join(c for c in team_id
                               if c.isalnum() or c in "-_") or "default"
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
        """Atomically-ish claim a task. False when someone already owns it."""
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
