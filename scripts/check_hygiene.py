#!/usr/bin/env python
"""Fail the build if junk that .gitignore already bans is *tracked* anyway.

Why this exists
---------------
``.gitignore`` never applies retroactively. Once a path is tracked, adding it
to ``.gitignore`` changes nothing - ``git status`` stays clean and every later
``git add -A`` keeps it alive. That is exactly how baize-agent ended up with
31 ``persistence/`` runtime files, 78 ``__pycache__/*.pyc`` blobs and 21
one-off ``examples/_probe*`` scripts committed across its branches, while
``.gitignore`` had been listing those very paths for months.

Cleaning them once does not fix the class of bug. This gate does: it inspects
what is *actually tracked* and refuses the paths the ignore rules were meant to
exclude.

Usage
-----
    python scripts/check_hygiene.py          # scan the index, exit 1 on junk
    python scripts/check_hygiene.py -v       # also list every clean file group

Exit codes: 0 clean, 1 junk tracked, 2 could not inspect (not a git repo).
"""
from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Paths that must never be tracked. Kept deliberately narrow: a pattern earns
# its place here only if committing it is *always* wrong for this repo.
JUNK_PATTERNS = [
    "__pycache__/*",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".pytest_cache/*",
    ".coverage",
    ".coverage.*",
    "coverage.xml",
    "htmlcov/*",
    "build/*",
    "dist/*",
    "*.egg-info/*",
    "persistence/*",
    "projects/*",
    "legacy/*",
    ".workbuddy/*",
    ".env",
    "*.log",
    "examples/_probe*",
    "examples/_diag*",
    "Thumbs.db",
    ".DS_Store",
]

# These patterns must also be present in .gitignore, otherwise the gate and the
# ignore file have silently diverged and the gate is guarding the wrong thing.
GITIGNORE_MUST_CONTAIN = [
    "__pycache__/",
    "persistence/",
    "*.log",
    "examples/_probe*",
    "examples/_diag*",
]


def tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"HYGIENE GATE ERROR: cannot list tracked files ({exc})", file=sys.stderr)
        raise SystemExit(2)
    return [p for p in out.split("\0") if p]


def main(argv: list[str]) -> int:
    verbose = "-v" in argv[1:]

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    missing = [p for p in GITIGNORE_MUST_CONTAIN if p not in gitignore]
    if missing:
        print("HYGIENE GATE FAILED: .gitignore lost patterns this gate relies on:")
        for m in missing:
            print(f"  {m}")
        return 1

    offenders: list[tuple[str, str]] = []
    for path in tracked_files():
        for pat in JUNK_PATTERNS:
            # Match the full path and every suffix, so "baize/core/__pycache__/x.pyc"
            # is caught by both "__pycache__/*" and "*.pyc".
            if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(Path(path).name, pat):
                offenders.append((path, pat))
                break
            if pat.endswith("/*") and fnmatch.fnmatch(path, pat[:-2] + "/*"):
                offenders.append((path, pat))
                break

    if offenders:
        print(f"HYGIENE GATE FAILED: {len(offenders)} tracked path(s) that .gitignore bans:\n")
        for path, pat in offenders:
            print(f"  {path}   (matched {pat})")
        print(
            "\nFix without touching history:\n"
            "  git rm -r --cached <path>     # keep the file on disk, drop it from the index\n"
            "  git commit -m 'chore(clean): untrack ...'\n"
            "For one-off scratch scripts use plain `git rm` - they are worthless to others."
        )
        return 1

    n = len(tracked_files())
    print(f"HYGIENE GATE PASSED: {n} tracked files, none matching a banned pattern")
    if verbose:
        print("  patterns enforced: " + ", ".join(JUNK_PATTERNS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
