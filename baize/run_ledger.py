"""V26-A2: Run Ledger — append-only task event log.

Implements the RunLedger described in the V26 upgrade plan (§3.1, third record
type) and specified in openspec/specs/baize-agent/v26-ledger.md.

Storage: persistence/runs/<run-id>.jsonl

Key design decisions:
- Pure stdlib only (json, pathlib, time) — Red Line A.
- Append-only: never modifies or deletes existing lines — audit invariant.
- fail-closed: corrupt JSONL lines are skipped in replay(), not crashed on.
- Does NOT replace manifest (manifest is still the sole state source).
- Does NOT replace sessions (sessions store model dialogue, this stores task events).

Event types (from OpenSpec §3):
    plan_created, task_started, task_claimed, tool_result,
    task_verified, state_transition, task_failed,
    skill_candidate, run_completed
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .config import load_config

__all__ = ["RunLedger", "get_ledger", "list_runs"]

# Valid event types — documented here for reference; not enforced at runtime
# (forward compatibility: new event types are silently accepted by replay).
KNOWN_EVENTS = {
    "plan_created", "task_started", "task_claimed", "tool_result",
    "task_verified", "state_transition", "task_failed",
    "skill_candidate", "run_completed",
}


def _runs_dir(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    d = Path(cfg["BAIZE_PERSISTENCE_DIR"]) / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


class RunLedger:
    """Append-only task event log for a single agent run (thread-safe).

    Writes to persistence/runs/<run-id>.jsonl.
    Each line is a JSON event object; lines are never modified or deleted.
    """

    def __init__(self, run_id: str, cfg: dict | None = None) -> None:
        self._run_id = run_id
        self._cfg = cfg
        self._path = _runs_dir(cfg) / f"{run_id}.jsonl"
        self._lock = threading.RLock()

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event: str, payload: dict,
               task_id: str | None = None) -> None:
        """Append a single event record to the ledger (append-only, thread-safe).

        Args:
            event: Event type string (e.g. 'task_verified').
            payload: Arbitrary dict with event-specific data.
            task_id: Optional task identifier for task-scoped events.
        """
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": event,
            "run_id": self._run_id,
            "task_id": task_id,
            "payload": payload,
        }
        with self._lock:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def events(self) -> list[dict]:
        """Return all events from the ledger.

        Corrupt JSONL lines are silently skipped (fail-closed for bad lines,
        not for the whole ledger).
        """
        if not self._path.exists():
            return []
        result: list[dict] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                # Corrupt line: skip, do not crash (defensive)
                continue
        return result

    def replay(self) -> dict:
        """Rebuild the current run state from the ledger.

        Returns a dict describing the state after all events are applied:
        {
            "run_id": str,
            "goal": str | None,
            "claimed_tasks": set[str],
            "verified_tasks": set[str],
            "failed_tasks": set[str],
            "in_progress_tasks": set[str],
            "skill_candidates": list[dict],
            "completed": bool,
        }

        Already-verified tasks will not appear in in_progress_tasks or
        current_unfinished(), supporting the --resume use case.
        """
        state: dict = {
            "run_id": self._run_id,
            "goal": None,
            "claimed_tasks": set(),
            "verified_tasks": set(),
            "failed_tasks": set(),
            "in_progress_tasks": set(),
            "skill_candidates": [],
            "completed": False,
        }
        for ev in self.events():
            etype = ev.get("event", "")
            tid = ev.get("task_id")
            payload = ev.get("payload", {})

            if etype == "plan_created":
                state["goal"] = payload.get("goal")
            elif etype == "task_claimed" and tid:
                state["claimed_tasks"].add(tid)
            elif etype == "task_started" and tid:
                if tid not in state["verified_tasks"] and tid not in state["failed_tasks"]:
                    state["in_progress_tasks"].add(tid)
            elif etype == "task_verified" and tid:
                state["verified_tasks"].add(tid)
                state["in_progress_tasks"].discard(tid)
            elif etype == "task_failed" and tid:
                state["failed_tasks"].add(tid)
                state["in_progress_tasks"].discard(tid)
            elif etype == "skill_candidate":
                state["skill_candidates"].append(payload)
            elif etype == "run_completed":
                state["completed"] = True

        return state

    def current_unfinished(self) -> list[str]:
        """Return task ids that are started but not yet verified or failed.

        Used by --resume to determine which tasks still need to run.
        """
        state = self.replay()
        return sorted(
            state["in_progress_tasks"] -
            state["verified_tasks"] -
            state["failed_tasks"]
        )

    def is_task_claimed(self, task_id: str) -> bool:
        """Return True if the task has been claimed (prevents double-claim)."""
        state = self.replay()
        return task_id in state["claimed_tasks"]

    def is_task_verified(self, task_id: str) -> bool:
        """Return True if the task has passed independent verification."""
        state = self.replay()
        return task_id in state["verified_tasks"]


def get_ledger(run_id: str, cfg: dict | None = None) -> RunLedger:
    """Factory: return a RunLedger for the given run_id."""
    return RunLedger(run_id, cfg=cfg)


def list_runs(cfg: dict | None = None) -> list[str]:
    """List all run_ids in persistence/runs/, sorted by filename (chronological)."""
    d = _runs_dir(cfg)
    return sorted(p.stem for p in d.glob("*.jsonl"))
