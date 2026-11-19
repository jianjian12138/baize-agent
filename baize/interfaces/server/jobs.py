"""SQLite WAL persistent async job queue and sliding-window HTTP rate limiter.

Provides production-grade async job orchestration using only Python's standard
library ``sqlite3`` and ``concurrent.futures.ThreadPoolExecutor``:
- Persistent job state machine: ``queued -> running -> succeeded | failed | cancelled``.
- Crash recovery on startup: orphaned ``running`` jobs are honestly marked
  ``failed (interrupted_by_restart)`` instead of staying stuck forever.
- Cooperative cancellation via per-job ``threading.Event``.
- Persisted event log per job enabling both polling and live SSE replay.
- Sliding-window per-client HTTP rate limiter (returns 429 when exceeded).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "SlidingWindowRateLimiter",
    "JobStore",
]


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window per-key HTTP rate limiter."""

    def __init__(self, max_requests: int = 0, window_seconds: float = 60.0) -> None:
        self.max_requests = max(0, int(max_requests))
        self.window_seconds = float(window_seconds)
        self._lock = threading.Lock()
        self._buckets: dict[str, list[float]] = {}

    def allow(self, key: str, now: float | None = None) -> tuple[bool, float]:
        """Return ``(allowed, retry_after_seconds)``. ``max_requests == 0`` disables limiting."""
        if self.max_requests <= 0:
            return True, 0.0
        ts = time.monotonic() if now is None else now
        cutoff = ts - self.window_seconds
        with self._lock:
            hits = [t for t in self._buckets.get(key, []) if t > cutoff]
            if len(hits) >= self.max_requests:
                self._buckets[key] = hits
                retry_after = max(1.0, round(self.window_seconds - (ts - hits[0]), 2))
                return False, retry_after
            hits.append(ts)
            self._buckets[key] = hits
            return True, 0.0


class JobStore:
    """SQLite WAL-backed persistent async job queue with bounded worker pool."""

    def __init__(self, db_path: str | Path, max_workers: int = 2) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._executor = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="baize-job")
        self._init_db()
        self.recover_orphaned_jobs()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    checkpoint_id TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL
                );
                CREATE TABLE IF NOT EXISTS job_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    ts REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id, seq);
                """
            )

    def recover_orphaned_jobs(self) -> int:
        """Mark any stale ``running`` jobs left over from a prior process crash."""
        now = time.time()
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT job_id FROM jobs WHERE status = 'running'").fetchall()
            if not rows:
                return 0
            conn.execute(
                "UPDATE jobs SET status = 'failed', error = 'interrupted_by_restart', finished_at = ? "
                "WHERE status = 'running'",
                (now,),
            )
            for r in rows:
                conn.execute(
                    "INSERT INTO job_events(job_id, kind, detail, ts) VALUES (?, ?, ?, ?)",
                    (r["job_id"], "error", "interrupted_by_restart", now),
                )
            return len(rows)

    def append_event(self, job_id: str, kind: str, detail: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO job_events(job_id, kind, detail, ts) VALUES (?, ?, ?, ?)",
                (job_id, kind, detail[:2000], time.time()),
            )

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        worker_fn: Callable[[str, dict[str, Any], threading.Event, Callable[[str, str], None]], dict[str, Any]],
    ) -> dict[str, Any]:
        job_id = f"job-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        now = time.time()
        cancel_ev = threading.Event()
        with self._lock, self._connect() as conn:
            self._cancel_events[job_id] = cancel_ev
            conn.execute(
                "INSERT INTO jobs(job_id, kind, status, payload_json, created_at) VALUES (?, ?, 'queued', ?, ?)",
                (job_id, kind, json.dumps(payload, ensure_ascii=False), now),
            )
            conn.execute(
                "INSERT INTO job_events(job_id, kind, detail, ts) VALUES (?, 'queued', ?, ?)",
                (job_id, f"enqueued {kind} job", now),
            )

        def _run() -> None:
            if cancel_ev.is_set():
                return
            with self._lock, self._connect() as conn:
                cur = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
                if not cur or cur["status"] != "queued":
                    return
                conn.execute(
                    "UPDATE jobs SET status = 'running', started_at = ? WHERE job_id = ?",
                    (time.time(), job_id),
                )
            self.append_event(job_id, "running", f"started {kind}")
            try:
                res = worker_fn(
                    job_id,
                    payload,
                    cancel_ev,
                    lambda k, d: self.append_event(job_id, k, d),
                )
                final_status = "cancelled" if cancel_ev.is_set() else "succeeded"
                cp_id = res.get("checkpoint_id") if isinstance(res, dict) else None
                with self._lock, self._connect() as conn:
                    conn.execute(
                        "UPDATE jobs SET status = ?, result_json = ?, checkpoint_id = ?, finished_at = ? "
                        "WHERE job_id = ?",
                        (final_status, json.dumps(res, ensure_ascii=False), cp_id, time.time(), job_id),
                    )
                self.append_event(job_id, final_status, "job completed")
            except Exception as exc:  # noqa: BLE001
                final_status = "cancelled" if cancel_ev.is_set() else "failed"
                with self._lock, self._connect() as conn:
                    conn.execute(
                        "UPDATE jobs SET status = ?, error = ?, finished_at = ? WHERE job_id = ?",
                        (final_status, f"{type(exc).__name__}: {exc}", time.time(), job_id),
                    )
                self.append_event(job_id, final_status, str(exc))
            finally:
                with self._lock:
                    self._cancel_events.pop(job_id, None)

        self._executor.submit(_run)
        return self.get(job_id) or {"job_id": job_id, "status": "queued"}

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            ev = self._cancel_events.get(job_id)
            if ev is not None:
                ev.set()
            if row["status"] == "queued":
                conn.execute(
                    "UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE job_id = ?",
                    (time.time(), job_id),
                )
                conn.execute(
                    "INSERT INTO job_events(job_id, kind, detail, ts) VALUES (?, 'cancelled', 'cancelled before start', ?)",
                    (job_id, time.time()),
                )
            elif row["status"] == "running":
                conn.execute(
                    "INSERT INTO job_events(job_id, kind, detail, ts) VALUES (?, 'cancel_requested', 'cooperative cancel signaled', ?)",
                    (job_id, time.time()),
                )
        return self.get(job_id)

    def _row_to_dict(self, row: sqlite3.Row, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "job_id": row["job_id"],
            "kind": row["kind"],
            "status": row["status"],
            "payload": json.loads(row["payload_json"]) if row["payload_json"] else {},
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"],
            "checkpoint_id": row["checkpoint_id"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }
        if events is not None:
            d["events"] = events
        return d

    def get(self, job_id: str, include_events: bool = True) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            events = None
            if include_events:
                ev_rows = conn.execute(
                    "SELECT seq, kind, detail, ts FROM job_events WHERE job_id = ? ORDER BY seq ASC LIMIT 200",
                    (job_id,),
                ).fetchall()
                events = [dict(r) for r in ev_rows]
            return self._row_to_dict(row, events)

    def list_jobs(self, status: str = "", limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait)
