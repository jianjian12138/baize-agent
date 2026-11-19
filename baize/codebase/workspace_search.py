"""Fast Pure-Python Workspace Search & File Discovery (zero subprocess overhead).

Provides cross-platform, workspace-confined text/regex grep and mtime-ordered
file discovery using os.scandir(), skipping VCS/build/binary artifacts.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from .symbol_graph import SKIP_DIRS as _BASE_SKIP_DIRS

__all__ = [
    "SKIP_DIRS",
    "grep_workspace",
    "find_workspace_files",
]

SKIP_DIRS = _BASE_SKIP_DIRS - {"persistence"}


def grep_workspace(
    base: Path,
    ws_root: Path,
    pattern: str,
    glob: str = "",
    case_sensitive: bool = True,
    regex: bool = True,
    max_results: int = 50,
) -> str:
    """Search workspace files with optional regex and filename glob filter."""
    if not pattern:
        return "ERROR: pattern is required"
    if not base.exists():
        return f"ERROR: path does not exist: {base}"
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rx = re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as exc:
        return f"ERROR: invalid regex pattern: {exc}"

    cap = max(1, min(int(max_results), 200))
    matches: list[str] = []
    files_scanned = 0

    def _scan_file(fpath: Path) -> None:
        nonlocal files_scanned
        if len(matches) >= cap:
            return
        if glob and not fnmatch.fnmatch(fpath.name, glob):
            return
        try:
            raw = fpath.read_bytes()
        except OSError:
            return
        if b"\x00" in raw[:4096] or len(raw) > 1_500_000:
            return
        files_scanned += 1
        rel = os.path.relpath(fpath, ws_root).replace("\\", "/")
        text = raw.decode("utf-8", errors="replace")
        for idx, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                snippet = line.strip()
                if len(snippet) > 180:
                    snippet = snippet[:177] + "..."
                matches.append(f"{rel}:{idx}: {snippet}")
                if len(matches) >= cap:
                    return

    if base.is_file():
        _scan_file(base)
    else:
        stack = [str(base)]
        while stack and len(matches) < cap:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    entries = sorted(it, key=lambda e: e.name)
            except OSError:
                continue
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    if not entry.name.startswith(".") and entry.name not in SKIP_DIRS:
                        stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    _scan_file(Path(entry.path))
                    if len(matches) >= cap:
                        break

    if not matches:
        return f"(no matches for {pattern!r} across {files_scanned} scanned files)"
    return f"[{len(matches)} match(es) across {files_scanned} file(s)]\n" + "\n".join(matches)


def find_workspace_files(
    base: Path,
    ws_root: Path,
    pattern: str = "*",
    max_results: int = 100,
) -> str:
    """Find workspace files matching ``pattern``, sorted newest first by mtime."""
    if not base.exists():
        return f"ERROR: path does not exist: {base}"
    cap = max(1, min(int(max_results), 500))
    found: list[tuple[float, str, int]] = []
    pat = (pattern or "*").strip() or "*"

    stack = [str(base)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if entry.is_dir(follow_symlinks=False):
                if not name.startswith(".") and name not in SKIP_DIRS:
                    stack.append(entry.path)
            elif entry.is_file(follow_symlinks=False):
                rel = os.path.relpath(entry.path, ws_root).replace("\\", "/")
                if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat):
                    try:
                        st = entry.stat(follow_symlinks=False)
                        found.append((st.st_mtime, rel, st.st_size))
                    except OSError:
                        found.append((0.0, rel, 0))

    found.sort(key=lambda item: -item[0])
    total = len(found)
    lines = [f"{rel} ({size} B)" for _, rel, size in found[:cap]]
    if not lines:
        return f"(no files matching {pat!r})"
    return f"[{min(total, cap)}/{total} matching file(s)]\n" + "\n".join(lines)
