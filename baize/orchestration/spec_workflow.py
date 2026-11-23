"""V46 Sovereign Spec-Driven Hard-Gate Workflow Engine.

Pure Python standard library + SQLite WAL persistence.
When Spec Mode is enabled for a session, the runtime hard-blocks mutating tools
during ``explore`` and ``spec_draft`` phases until the user explicitly approves
the frozen specification (``approved`` -> ``executing`` -> ``verified``).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..core.config import load_config

__all__ = [
    "SPEC_PHASES",
    "LOCKED_PHASES",
    "SpecState",
    "SpecWorkflowManager",
    "get_spec_manager",
]

SPEC_PHASES = ("off", "explore", "spec_draft", "approved", "executing", "verified")
LOCKED_PHASES = frozenset({"explore", "spec_draft"})


@dataclass
class SpecState:
    session_id: str
    phase: str = "off"
    spec_summary: str = ""
    spec_hash: str = ""
    tasks_json: str = "[]"
    approved_by: str = ""
    approved_at: float = 0.0
    updated_at: float = 0.0
    note: str = ""

    @property
    def enabled(self) -> bool:
        return self.phase != "off"

    @property
    def write_locked(self) -> bool:
        return self.phase in LOCKED_PHASES

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["enabled"] = self.enabled
        d["write_locked"] = self.write_locked
        try:
            d["tasks"] = json.loads(self.tasks_json or "[]")
        except Exception:
            d["tasks"] = []
        return d


class SpecWorkflowManager:
    """SQLite WAL backed state machine enforcing read-only lock prior to spec approval."""

    def __init__(self, db_path: str | Path | None = None, *, cfg: dict[str, Any] | None = None) -> None:
        self._explicit_db = Path(db_path) if db_path is not None else None
        self._cfg = cfg
        self._lock = threading.Lock()
        self._initialized_db = ""

    def _db_path(self) -> Path:
        if self._explicit_db is not None:
            return self._explicit_db
        c = self._cfg if self._cfg is not None else load_config()
        return Path(c.get("BAIZE_PERSISTENCE_DIR", "persistence")) / "spec_workflow.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        p = self._db_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        if self._initialized_db != str(p):
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS spec_sessions (
                    session_id TEXT PRIMARY KEY,
                    phase TEXT NOT NULL,
                    spec_summary TEXT NOT NULL,
                    spec_hash TEXT NOT NULL,
                    tasks_json TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    approved_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    note TEXT NOT NULL
                )
                """
            )
            self._initialized_db = str(p)
        return conn

    def _save(self, st: SpecState) -> SpecState:
        st.updated_at = round(time.time(), 3)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO spec_sessions
                (session_id, phase, spec_summary, spec_hash, tasks_json, approved_by, approved_at, updated_at, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    st.session_id,
                    st.phase,
                    st.spec_summary,
                    st.spec_hash,
                    st.tasks_json,
                    st.approved_by,
                    st.approved_at,
                    st.updated_at,
                    st.note,
                ),
            )
        return st

    def get(self, session_id: str = "default") -> SpecState:
        sid = (session_id or "default").strip() or "default"
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, phase, spec_summary, spec_hash, tasks_json,
                       approved_by, approved_at, updated_at, note
                FROM spec_sessions WHERE session_id = ?
                """,
                (sid,),
            ).fetchone()
        if row:
            return SpecState(
                session_id=row[0],
                phase=row[1],
                spec_summary=row[2],
                spec_hash=row[3],
                tasks_json=row[4],
                approved_by=row[5],
                approved_at=float(row[6]),
                updated_at=float(row[7]),
                note=row[8],
            )
        c = self._cfg if self._cfg is not None else load_config()
        default_on = str(c.get("BAIZE_SPEC_MODE", "0")).strip().lower() in ("1", "true", "on", "yes")
        return SpecState(session_id=sid, phase="explore" if default_on else "off")

    def enable(self, session_id: str = "default", *, note: str = "") -> SpecState:
        st = self.get(session_id)
        if st.phase == "off":
            st.phase = "explore"
        st.note = note or "spec mode enabled: read-only until approved"
        return self._save(st)

    def disable(self, session_id: str = "default", *, note: str = "") -> SpecState:
        st = self.get(session_id)
        st.phase = "off"
        st.note = note or "spec mode disabled"
        return self._save(st)

    def submit_spec(
        self,
        session_id: str = "default",
        *,
        spec_summary: str = "",
        summary: str = "",
        content: str = "",
        tasks: list[str] | None = None,
        note: str = "",
    ) -> SpecState:
        st = self.get(session_id)
        merged = (spec_summary or summary or content or "").strip()
        st.phase = "spec_draft"
        st.spec_summary = merged
        st.spec_hash = hashlib.sha256(merged.encode("utf-8")).hexdigest()[:16] if merged else ""
        st.tasks_json = json.dumps(list(tasks or []), ensure_ascii=False)
        st.approved_by = ""
        st.approved_at = 0.0
        st.note = note or "spec drafted and awaiting user approval"
        return self._save(st)

    def approve(self, session_id: str = "default", *, actor: str = "user", note: str = "") -> SpecState:
        st = self.get(session_id)
        st.phase = "approved"
        st.approved_by = actor or "user"
        st.approved_at = round(time.time(), 3)
        st.note = note or "spec approved; write tools unlocked"
        res = self._save(st)
        try:
            from ..governance.dlp import get_audit_ledger
            get_audit_ledger().append(
                "spec_approved",
                actor=st.approved_by,
                target=st.session_id,
                outcome="approved",
                details={"spec_hash": st.spec_hash, "note": st.note},
            )
        except Exception:
            pass
        return res

    def reject(self, session_id: str = "default", *, reason: str = "") -> SpecState:
        st = self.get(session_id)
        st.phase = "spec_draft"
        st.approved_by = ""
        st.approved_at = 0.0
        st.note = reason or "spec rejected; revise before execution"
        return self._save(st)

    def mark_executing(self, session_id: str = "default") -> SpecState:
        st = self.get(session_id)
        if st.phase == "approved":
            st.phase = "executing"
            return self._save(st)
        return st

    def mark_verified(self, session_id: str = "default", *, note: str = "") -> SpecState:
        st = self.get(session_id)
        if st.phase in ("approved", "executing"):
            st.phase = "verified"
            st.note = note or "implementation verified"
            return self._save(st)
        return st

    def check_tool_allowed(
        self,
        session_id: str,
        tool_name: str,
        read_only_tools: set[str] | frozenset[str],
    ) -> tuple[bool, str]:
        """Enforce read-only lock when Spec Mode is in explore or spec_draft phase."""
        st = self.get(session_id)
        if not st.write_locked:
            return True, ""
        if tool_name in read_only_tools:
            return True, ""
        return (
            False,
            f"SPEC_GATE_LOCKED (phase={st.phase}): mutating tool '{tool_name}' is blocked until "
            "the specification is approved. Inspect the codebase with read-only tools, present the "
            "spec/plan, and wait for approval (/spec approve or Studio Approve).",
        )


_SPEC_LOCK = threading.Lock()
_SPEC_SINGLETON: SpecWorkflowManager | None = None
_SPEC_DB_PATH = ""


def get_spec_manager(cfg: dict[str, Any] | None = None) -> SpecWorkflowManager:
    global _SPEC_SINGLETON, _SPEC_DB_PATH
    c = cfg if cfg is not None else load_config()
    target = str(Path(c.get("BAIZE_PERSISTENCE_DIR", "persistence")) / "spec_workflow.sqlite3")
    with _SPEC_LOCK:
        if _SPEC_SINGLETON is None or _SPEC_DB_PATH != target:
            _SPEC_SINGLETON = SpecWorkflowManager(db_path=target, cfg=c)
            _SPEC_DB_PATH = target
        return _SPEC_SINGLETON
