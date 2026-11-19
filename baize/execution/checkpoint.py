"""Non-invasive Git transactional checkpoints and atomic rollback.

Creates exact working-tree snapshots using an isolated temporary ``GIT_INDEX_FILE``
and ``git write-tree``, so neither the user's real index, HEAD, branches, nor
``git stash`` stack are ever modified. On verification failure or user request,
``rollback()`` restores every tracked/snapshot file to the exact tree SHA and
removes newly introduced untracked files outside the snapshot manifest.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "Checkpoint",
    "GitCheckpointManager",
]

_CHECKPOINT_DIR = ".baize_checkpoints"
_PROTECTED_PREFIXES = (".git/", ".git", _CHECKPOINT_DIR + "/", _CHECKPOINT_DIR)


@dataclass
class Checkpoint:
    checkpoint_id: str
    workspace: str
    tree_sha: str
    base_head: str
    label: str = ""
    run_id: str = ""
    created_at: float = 0.0
    status: str = "active"  # active | committed | rolled_back
    files_count: int = 0
    tracked_snapshot: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_protected(rel_posix: str) -> bool:
    norm = rel_posix.strip("/")
    return norm in (".git", _CHECKPOINT_DIR) or norm.startswith((".git/", f"{_CHECKPOINT_DIR}/"))


class GitCheckpointManager:
    """Manage atomic Git working-tree checkpoints without touching user stashes."""

    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()
        self.store_dir = self.workspace / _CHECKPOINT_DIR

    def _git(self, args: list[str], env: dict[str, str] | None = None,
             timeout: int = 30) -> subprocess.CompletedProcess[str]:
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        return subprocess.run(
            ["git", *args],
            cwd=str(self.workspace),
            env=run_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    def is_git_repo(self) -> bool:
        if not shutil.which("git"):
            return False
        res = self._git(["rev-parse", "--is-inside-work-tree"])
        return res.returncode == 0 and res.stdout.strip() == "true"

    def _meta_path(self, checkpoint_id: str) -> Path:
        safe = "".join(c for c in checkpoint_id if c.isalnum() or c in ("-", "_"))
        if not safe:
            raise ValueError(f"invalid checkpoint_id: {checkpoint_id!r}")
        return self.store_dir / f"{safe}.json"

    def _save(self, cp: Checkpoint) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._meta_path(cp.checkpoint_id).write_text(
            json.dumps(cp.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def get(self, checkpoint_id: str) -> Checkpoint | None:
        p = self._meta_path(checkpoint_id)
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return Checkpoint(**data)

    def list_checkpoints(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.store_dir.is_dir():
            return []
        items: list[dict[str, Any]] = []
        for p in sorted(self.store_dir.glob("*.json"), reverse=True):
            try:
                items.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        items.sort(key=lambda x: x.get("created_at", 0.0), reverse=True)
        return items[:limit]

    def create(self, label: str = "", run_id: str = "") -> Checkpoint:
        """Capture an exact, non-invasive Git tree snapshot of the workspace."""
        if not self.is_git_repo():
            raise RuntimeError(f"not a git repository: {self.workspace}")

        head_res = self._git(["rev-parse", "--verify", "HEAD"])
        base_head = head_res.stdout.strip() if head_res.returncode == 0 else ""

        tmp_fd, tmp_index = tempfile.mkstemp(prefix="baize-idx-")
        os.close(tmp_fd)
        os.unlink(tmp_index)  # git requires the fresh index file not to exist yet
        idx_env = {"GIT_INDEX_FILE": tmp_index}
        try:
            if base_head:
                self._git(["read-tree", base_head], env=idx_env)
            # Stage current working tree (excluding .baize_checkpoints) into temp index
            add_res = self._git(
                ["add", "-A", "--", ".", f":(exclude){_CHECKPOINT_DIR}"],
                env=idx_env,
            )
            if add_res.returncode != 0:
                raise RuntimeError(f"git add to temp index failed: {add_res.stderr.strip()}")
            wt_res = self._git(["write-tree"], env=idx_env)
            if wt_res.returncode != 0:
                raise RuntimeError(f"git write-tree failed: {wt_res.stderr.strip()}")
            tree_sha = wt_res.stdout.strip()

            ls_res = self._git(["ls-files"], env=idx_env)
            snap_files = [
                f for f in ls_res.stdout.splitlines()
                if f.strip() and not _is_protected(f)
            ]
        finally:
            if os.path.exists(tmp_index):
                try:
                    os.unlink(tmp_index)
                except OSError:
                    pass

        cp = Checkpoint(
            checkpoint_id=f"cp-{int(time.time())}-{uuid.uuid4().hex[:6]}",
            workspace=str(self.workspace),
            tree_sha=tree_sha,
            base_head=base_head,
            label=label[:160],
            run_id=run_id,
            created_at=time.time(),
            status="active",
            files_count=len(snap_files),
            tracked_snapshot=snap_files,
        )
        self._save(cp)
        return cp

    def diff_stat(self, checkpoint_id: str) -> str:
        """Return ``git diff --stat`` between the checkpoint tree and current working tree."""
        cp = self.get(checkpoint_id)
        if cp is None:
            return ""
        res = self._git(["diff", "--stat", cp.tree_sha])
        return (res.stdout or "").strip()

    def commit(self, checkpoint_id: str) -> dict[str, Any]:
        """Mark checkpoint as committed after verification succeeds."""
        cp = self.get(checkpoint_id)
        if cp is None:
            return {"ok": False, "error": f"checkpoint not found: {checkpoint_id}"}
        cp.status = "committed"
        self._save(cp)
        return {"ok": True, "checkpoint_id": cp.checkpoint_id, "status": cp.status}

    def rollback(self, checkpoint_id: str) -> dict[str, Any]:
        """Atomically restore the working tree to the exact checkpoint tree."""
        cp = self.get(checkpoint_id)
        if cp is None:
            return {"ok": False, "error": f"checkpoint not found: {checkpoint_id}"}
        if not self.is_git_repo():
            return {"ok": False, "error": f"not a git repository: {self.workspace}"}

        diff_before = self.diff_stat(checkpoint_id)
        snap_set = set(cp.tracked_snapshot)

        # 1. Remove any newly created files not present in the snapshot manifest
        removed_new: list[str] = []
        status_res = self._git(["status", "--porcelain", "-uall"])
        for line in status_res.stdout.splitlines():
            if len(line) < 4:
                continue
            code = line[:2]
            rel = line[3:].strip().strip('"')
            if " -> " in rel:
                rel = rel.split(" -> ", 1)[1].strip().strip('"')
            if not rel or _is_protected(rel):
                continue
            if rel not in snap_set and ("?" in code or "A" in code):
                target = (self.workspace / rel).resolve()
                if self.workspace in target.parents and target.exists():
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        target.unlink(missing_ok=True)
                    removed_new.append(rel)

        # 2. Restore exact working tree contents from tree_sha via isolated index
        tmp_fd, tmp_index = tempfile.mkstemp(prefix="baize-rb-")
        os.close(tmp_fd)
        os.unlink(tmp_index)
        idx_env = {"GIT_INDEX_FILE": tmp_index}
        try:
            rt = self._git(["read-tree", cp.tree_sha], env=idx_env)
            if rt.returncode != 0:
                return {"ok": False, "error": f"git read-tree failed: {rt.stderr.strip()}"}
            co = self._git(["checkout-index", "-a", "-f"], env=idx_env)
            if co.returncode != 0:
                return {"ok": False, "error": f"git checkout-index failed: {co.stderr.strip()}"}
        finally:
            if os.path.exists(tmp_index):
                try:
                    os.unlink(tmp_index)
                except OSError:
                    pass

        # Remove tracked files that were deleted vs snapshot? Check any remaining untracked/extra
        # files from workspace that were created after snapshot even if ignored? No, leave gitignored build caches alone.
        # Ensure files present in current HEAD but absent in snapshot are removed if needed
        cur_tracked = set(self._git(["ls-files"]).stdout.splitlines())
        for rel in sorted(cur_tracked - snap_set):
            if _is_protected(rel):
                continue
            target = (self.workspace / rel).resolve()
            if self.workspace in target.parents and target.is_file():
                target.unlink(missing_ok=True)
                removed_new.append(rel)

        cp.status = "rolled_back"
        self._save(cp)
        return {
            "ok": True,
            "checkpoint_id": cp.checkpoint_id,
            "tree_sha": cp.tree_sha,
            "removed_new_files": removed_new,
            "diff_before_rollback": diff_before,
            "status": cp.status,
        }
