"""V49.0.0 Zenith: Per-session contextvars isolation, optimistic file-read locking & crash-safe atomic writes."""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator


@dataclass(frozen=True)
class ExecutionContext:
    """Immutable per-session / per-worktree runtime context bound via ``contextvars``."""

    workspace: Path | None = None
    session_id: str = ""
    tenant_id: str = ""
    sandbox_mode: str = ""
    on_tool_output: Callable[[str, str, str], None] | None = None


_CURRENT_CTX: contextvars.ContextVar[ExecutionContext | None] = contextvars.ContextVar(
    "baize_execution_context",
    default=None,
)


def get_execution_context() -> ExecutionContext | None:
    return _CURRENT_CTX.get()


@contextlib.contextmanager
def execution_context(
    *,
    workspace: str | Path | None = None,
    session_id: str | None = None,
    tenant_id: str | None = None,
    sandbox_mode: str | None = None,
    on_tool_output: Callable[[str, str, str], None] | None = None,
) -> Iterator[ExecutionContext]:
    parent = _CURRENT_CTX.get()
    ws_path: Path | None
    if workspace is not None and str(workspace).strip():
        ws_path = Path(workspace).resolve()
    elif parent is not None:
        ws_path = parent.workspace
    else:
        ws_path = None

    ctx = ExecutionContext(
        workspace=ws_path,
        session_id=session_id if session_id is not None else (parent.session_id if parent else ""),
        tenant_id=tenant_id if tenant_id is not None else (parent.tenant_id if parent else ""),
        sandbox_mode=sandbox_mode if sandbox_mode is not None else (parent.sandbox_mode if parent else ""),
        on_tool_output=on_tool_output if on_tool_output is not None else (parent.on_tool_output if parent else None),
    )
    tok = _CURRENT_CTX.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT_CTX.reset(tok)


def current_workspace(cfg: dict[str, Any] | None = None, fallback: str | Path = ".") -> Path:
    ctx = _CURRENT_CTX.get()
    if ctx is not None and ctx.workspace is not None:
        return ctx.workspace
    raw = (cfg or {}).get("BAIZE_WORKSPACE_DIR") if isinstance(cfg, dict) else None
    if raw and str(raw).strip():
        return Path(str(raw)).resolve()
    return Path(fallback).resolve()


def current_session_id(default: str = "default") -> str:
    ctx = _CURRENT_CTX.get()
    if ctx is not None and ctx.session_id:
        return ctx.session_id
    return default


def emit_tool_output(tool_name: str, stream: str, chunk: str) -> None:
    if not chunk:
        return
    ctx = _CURRENT_CTX.get()
    cb = ctx.on_tool_output if ctx is not None else None
    if cb is not None:
        try:
            cb(tool_name, stream, chunk)
        except Exception:
            pass


@dataclass(frozen=True)
class FileReadSnapshot:
    path: str
    mtime_ns: int
    size: int
    sha256: str
    recorded_at: float


class FileReadTracker:
    """Thread-safe per-session tracker of file read snapshots for optimistic locking."""

    def __init__(self, max_entries: int = 2048) -> None:
        self._lock = threading.Lock()
        self._max_entries = max(64, int(max_entries))
        self._records: dict[tuple[str, str], FileReadSnapshot] = {}

    @staticmethod
    def _stat_and_hash(path: Path) -> tuple[int, int, str] | None:
        try:
            st = path.stat()
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            return st.st_mtime_ns, st.st_size, digest
        except OSError:
            return None

    def record_read(self, path: str | Path, *, session_id: str | None = None) -> FileReadSnapshot | None:
        p = Path(path).resolve()
        info = self._stat_and_hash(p)
        if info is None:
            return None
        sid = session_id if session_id is not None else current_session_id()
        snap = FileReadSnapshot(
            path=str(p),
            mtime_ns=info[0],
            size=info[1],
            sha256=info[2],
            recorded_at=time.time(),
        )
        with self._lock:
            if len(self._records) >= self._max_entries:
                oldest = sorted(self._records.items(), key=lambda kv: kv[1].recorded_at)[: max(1, self._max_entries // 10)]
                for k, _ in oldest:
                    self._records.pop(k, None)
            self._records[(sid, str(p))] = snap
        return snap

    def get_snapshot(self, path: str | Path, *, session_id: str | None = None) -> FileReadSnapshot | None:
        p = str(Path(path).resolve())
        sid = session_id if session_id is not None else current_session_id()
        with self._lock:
            return self._records.get((sid, p))

    def verify_fresh(
        self,
        path: str | Path,
        *,
        require_prior_read: bool = False,
        session_id: str | None = None,
    ) -> tuple[bool, str]:
        p = Path(path).resolve()
        if not p.exists():
            return True, ""
        snap = self.get_snapshot(p, session_id=session_id)
        if snap is None:
            if require_prior_read:
                return (
                    False,
                    f"read-before-edit policy requires calling read_file on existing file '{p.name}' before editing.",
                )
            return True, ""
        cur = self._stat_and_hash(p)
        if cur is None:
            return False, f"file '{p.name}' became unreadable before write."
        cur_mtime, cur_size, cur_hash = cur
        if cur_hash != snap.sha256:
            return (
                False,
                f"stale file conflict: '{p.name}' was modified externally since it was last read "
                f"(expected sha256={snap.sha256[:12]}, current={cur_hash[:12]}). "
                "Call read_file to inspect the latest version before editing.",
            )
        return True, ""

    def clear(self, session_id: str | None = None) -> None:
        with self._lock:
            if session_id is None:
                self._records.clear()
            else:
                for k in [k for k in self._records if k[0] == session_id]:
                    self._records.pop(k, None)


_GLOBAL_FILE_TRACKER = FileReadTracker()


def get_file_read_tracker() -> FileReadTracker:
    return _GLOBAL_FILE_TRACKER


def atomic_write_bytes(path: str | Path, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        try:
            if target.exists():
                os.chmod(tmp_path, target.stat().st_mode & 0o7777)
        except OSError:
            pass
        os.replace(tmp_path, target)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def atomic_write_text(path: str | Path, content: str, encoding: str = "utf-8") -> Path:
    return atomic_write_bytes(path, content.encode(encoding))
