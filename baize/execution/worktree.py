"""V42.0.0 Helios — Isolated Git Worktree Pool for True Parallel Multi-Agent Execution.

Creates an isolated temporary ``git worktree`` and short-lived branch per parallel
subtask so concurrent Executor agents never collide on file writes. Only subtasks
that pass deterministic verification gates are three-way merged back to the base
branch; merge conflicts abort cleanly without polluting the main working tree.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _run_git(cwd: str | Path, args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


@dataclass
class WorktreeEntry:
    """Lifecycle metadata for one isolated parallel subtask worktree."""

    worktree_id: str
    subtask_id: str
    branch_name: str
    base_branch: str
    base_commit: str
    worktree_path: str
    status: str = "running"  # running | verified | merged | conflict | failed | cleaned
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    changed_files: list[str] = field(default_factory=list)
    merge_commit: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitWorktreePool:
    """Thread-safe pool managing ephemeral Git worktrees and verified 3-way merges."""

    def __init__(self, workspace: str | Path = ".", state_dir: str | Path | None = None) -> None:
        self.workspace = Path(workspace).resolve()
        self._lock = threading.RLock()
        self._state_dir = Path(state_dir).resolve() if state_dir else (self.workspace / ".baize_worktrees")
        self._registry_file = self._state_dir / "registry.json"
        self._entries: dict[str, WorktreeEntry] = {}
        self._ensure_git_exclude()
        self._load_registry()

    def _ensure_git_exclude(self) -> None:
        exclude = self.workspace / ".git" / "info" / "exclude"
        if not exclude.is_file():
            return
        try:
            rel = self._state_dir.relative_to(self.workspace)
            pattern = f"/{rel.as_posix().rstrip('/')}/"
        except ValueError:
            return
        try:
            text = exclude.read_text(encoding="utf-8", errors="replace")
            if pattern not in text.splitlines():
                prefix = "" if (not text or text.endswith("\n")) else "\n"
                exclude.write_text(text + prefix + pattern + "\n", encoding="utf-8")
        except OSError:
            pass

    def is_git_repo(self) -> bool:
        rc, out, _ = _run_git(self.workspace, ["rev-parse", "--is-inside-work-tree"])
        return rc == 0 and out.strip() == "true"

    def _current_branch_and_head(self) -> tuple[str, str]:
        rc_b, branch, _ = _run_git(self.workspace, ["rev-parse", "--abbrev-ref", "HEAD"])
        rc_h, head, _ = _run_git(self.workspace, ["rev-parse", "HEAD"])
        if rc_h != 0 or not head:
            raise RuntimeError("Workspace has no Git HEAD commit; commit initial files before using worktrees")
        return (branch if rc_b == 0 and branch != "HEAD" else head), head

    def _load_registry(self) -> None:
        if not self._registry_file.is_file():
            return
        try:
            raw = json.loads(self._registry_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict) and item.get("worktree_id"):
                        self._entries[item["worktree_id"]] = WorktreeEntry(**item)
        except Exception:
            pass

    def _save_registry(self) -> None:
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            tmp = self._registry_file.with_suffix(".tmp")
            payload = [e.to_dict() for e in self._entries.values()]
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._registry_file)
        except OSError:
            pass

    def create(self, subtask_id: str, label: str = "") -> WorktreeEntry:
        """Allocate an isolated Git worktree and dedicated short-lived branch."""
        with self._lock:
            if not self.is_git_repo():
                raise RuntimeError(f"Workspace is not a Git repository: {self.workspace}")
            base_branch, base_commit = self._current_branch_and_head()
            wt_id = f"wt-{uuid.uuid4().hex[:8]}"
            safe_sub = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(subtask_id))[:24] or "task"
            branch_name = f"baize/{safe_sub}-{wt_id}"
            self._state_dir.mkdir(parents=True, exist_ok=True)
            wt_path = self._state_dir / wt_id

            rc, _out, err = _run_git(
                self.workspace,
                ["worktree", "add", "-b", branch_name, str(wt_path), base_commit],
            )
            if rc != 0:
                raise RuntimeError(f"git worktree add failed: {err}")

            entry = WorktreeEntry(
                worktree_id=wt_id,
                subtask_id=str(subtask_id),
                branch_name=branch_name,
                base_branch=base_branch,
                base_commit=base_commit,
                worktree_path=str(wt_path),
                status="running",
            )
            self._entries[wt_id] = entry
            self._save_registry()
            return entry

    def commit_worktree_changes(self, worktree_id: str, message: str = "") -> dict[str, Any]:
        """Stage and commit all edits inside a worktree so it can be cleanly three-way merged."""
        with self._lock:
            entry = self._entries.get(worktree_id)
            if entry is None:
                return {"ok": False, "error": f"unknown worktree_id: {worktree_id}"}
            wt_path = Path(entry.worktree_path)
            if not wt_path.exists():
                return {"ok": False, "error": f"worktree path missing: {wt_path}"}

            rc_st, status_out, _ = _run_git(wt_path, ["status", "--porcelain"])
            if rc_st != 0:
                return {"ok": False, "error": "git status failed in worktree"}
            changed = [line[3:].strip() for line in status_out.splitlines() if len(line) > 3]
            entry.changed_files = changed
            if not changed:
                entry.status = "verified"
                entry.updated_at = time.time()
                self._save_registry()
                return {"ok": True, "committed": False, "changed_files": []}

            _run_git(wt_path, ["add", "-A"])
            commit_msg = message.strip() or f"baize(worktree): subtask {entry.subtask_id}"
            rc_c, _o, err = _run_git(
                wt_path,
                [
                    "-c", "user.name=Baize Agent",
                    "-c", "user.email=baize@local",
                    "commit", "-m", commit_msg,
                ],
            )
            if rc_c != 0:
                entry.status = "failed"
                entry.error = f"commit failed: {err}"
                entry.updated_at = time.time()
                self._save_registry()
                return {"ok": False, "error": entry.error}

            entry.status = "verified"
            entry.updated_at = time.time()
            self._save_registry()
            return {"ok": True, "committed": True, "changed_files": changed}

    def merge_verified(self, worktree_id: str, *, auto_cleanup: bool = True) -> dict[str, Any]:
        """Three-way merge a verified worktree branch back into the main workspace branch.

        If a merge conflict occurs, executes ``git merge --abort`` immediately so the
        main working tree stays clean and marks the worktree entry as ``conflict``.
        """
        with self._lock:
            entry = self._entries.get(worktree_id)
            if entry is None:
                return {"ok": False, "error": f"unknown worktree_id: {worktree_id}"}
            # Ensure latest changes in worktree are committed
            if entry.status == "running":
                c_res = self.commit_worktree_changes(worktree_id)
                if not c_res.get("ok"):
                    return c_res

            # Check if branch actually has commits ahead of HEAD
            rc_cnt, cnt_out, _ = _run_git(
                self.workspace,
                ["rev-list", "--count", f"HEAD..{entry.branch_name}"],
            )
            if rc_cnt == 0 and cnt_out.strip() == "0":
                entry.status = "merged"
                entry.updated_at = time.time()
                self._save_registry()
                if auto_cleanup:
                    self.cleanup(worktree_id)
                return {"ok": True, "merged": False, "reason": "no_changes", "worktree_id": worktree_id}

            rc_m, out_m, err_m = _run_git(
                self.workspace,
                [
                    "-c", "user.name=Baize Agent",
                    "-c", "user.email=baize@local",
                    "merge", "--no-ff", "--no-edit", entry.branch_name,
                ],
            )
            if rc_m != 0:
                # Identify conflicting files before aborting cleanly
                _, cf_out, _ = _run_git(self.workspace, ["diff", "--name-only", "--diff-filter=U"])
                conflict_files = [ln.strip() for ln in cf_out.splitlines() if ln.strip()]
                _run_git(self.workspace, ["merge", "--abort"])
                entry.status = "conflict"
                entry.error = f"merge conflict in {conflict_files or [err_m or out_m]}"
                entry.updated_at = time.time()
                self._save_registry()
                return {
                    "ok": False,
                    "status": "conflict",
                    "worktree_id": worktree_id,
                    "branch": entry.branch_name,
                    "conflict_files": conflict_files,
                    "error": entry.error,
                }

            _, head_sha, _ = _run_git(self.workspace, ["rev-parse", "HEAD"])
            entry.status = "merged"
            entry.merge_commit = head_sha
            entry.updated_at = time.time()
            self._save_registry()
            if auto_cleanup:
                self.cleanup(worktree_id)
            return {
                "ok": True,
                "status": "merged",
                "worktree_id": worktree_id,
                "merge_commit": head_sha,
                "changed_files": list(entry.changed_files),
            }

    def cleanup(self, worktree_id: str, *, force: bool = True) -> dict[str, Any]:
        """Remove the temporary worktree directory and delete its temporary branch."""
        with self._lock:
            entry = self._entries.get(worktree_id)
            if entry is None:
                return {"ok": False, "error": f"unknown worktree_id: {worktree_id}"}
            wt_path = Path(entry.worktree_path)
            if wt_path.exists():
                cmd = ["worktree", "remove", "--force", str(wt_path)] if force else ["worktree", "remove", str(wt_path)]
                rc, _, _ = _run_git(self.workspace, cmd)
                if rc != 0 and wt_path.exists():
                    shutil.rmtree(wt_path, ignore_errors=True)
            _run_git(self.workspace, ["worktree", "prune"])
            _run_git(self.workspace, ["branch", "-D", entry.branch_name])
            if entry.status not in ("merged", "conflict"):
                entry.status = "cleaned"
            entry.updated_at = time.time()
            self._save_registry()
            return {"ok": True, "worktree_id": worktree_id, "status": entry.status}

    def cleanup_all(self) -> dict[str, Any]:
        with self._lock:
            cleaned = []
            for wt_id in list(self._entries):
                res = self.cleanup(wt_id, force=True)
                if res.get("ok"):
                    cleaned.append(wt_id)
            _run_git(self.workspace, ["worktree", "prune"])
            return {"ok": True, "cleaned": cleaned, "count": len(cleaned)}

    def recover_orphans(self, *, max_age_s: float = 3600.0) -> dict[str, Any]:
        """Detect & prune orphaned worktrees left behind by crashed/killed runs."""
        now = time.time()
        recovered: list[str] = []
        with self._lock:
            self._load_registry()
            for wid, entry in list(self._entries.items()):
                path_missing = not Path(entry.worktree_path).exists()
                stale_running = (entry.status == "running" and (now - entry.updated_at) >= max_age_s)
                if path_missing or stale_running:
                    _run_git(self.workspace, ["worktree", "remove", "--force", entry.worktree_path])
                    if entry.branch_name:
                        _run_git(self.workspace, ["branch", "-D", entry.branch_name])
                    entry.status = "recovered"
                    entry.error = "orphaned worktree pruned during startup crash recovery"
                    entry.updated_at = now
                    recovered.append(wid)
            _run_git(self.workspace, ["worktree", "prune"])
            self._save_registry()
        return {"ok": True, "recovered": recovered, "count": len(recovered)}

    def list_worktrees(self) -> list[dict[str, Any]]:
        with self._lock:
            self._load_registry()
            return [e.to_dict() for e in sorted(self._entries.values(), key=lambda x: x.created_at, reverse=True)]
