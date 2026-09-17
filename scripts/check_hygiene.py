#!/usr/bin/env python
"""Fail the build if the repository is not in a state a fresh clone can use.

Why this exists
---------------
Two failure modes, one root cause (the gate looked only at the index):

1. ``.gitignore`` never applies retroactively. Once a path is tracked, adding it
   to ``.gitignore`` changes nothing - ``git status`` stays clean and every later
   ``git add -A`` keeps it alive. That is exactly how baize-agent ended up with
   31 ``persistence/`` runtime files, 78 ``__pycache__/*.pyc`` blobs and 21
   one-off ``examples/_probe*`` scripts committed across its branches, while
   ``.gitignore`` had been listing those very paths for months.

2. The mirror image: a path that is *never* added. ``git ls-files`` cannot see
   it, so the gate printed "318 tracked files, none matching a banned pattern" -
   a true sentence that read like "the repo is clean" - while ``baize/proc.py``,
   ``baize/safe_exec.py``, three gate scripts and 17 test files sat untracked on
   disk. The working tree was green; a fresh clone was missing the modules those
   tracked files import, and ``import baize.swarm`` failed with ``ImportError``.

Cleaning case 1 once did not fix the class of bug, so this gate inspects what is
*actually tracked* and refuses the paths the ignore rules meant to exclude. Case
2 is the complement: it inspects what is *not* tracked, in the directories where
a missing file breaks an import or a gate.

Usage
-----
    python scripts/check_hygiene.py          # scan index + untracked, exit 1 on either
    python scripts/check_hygiene.py -v       # also list every clean file group
    python scripts/check_hygiene.py --index-only
                                             # skip the untracked scan (e.g. mid-bisect)

Exit codes: 0 clean, 1 junk tracked or key file untracked, 2 could not inspect.
"""
from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories where an untracked file is a delivery bug, not a work-in-progress.
# A missing module here breaks an import (`baize/`), a gate (`scripts/`), or the
# suite (`tests/`); anywhere else an untracked file is merely a draft.
KEY_DIRS = ("baize/", "scripts/", "tests/")

# Untracked paths matching one of these are work products of a test run, not
# source. They are expected to be present and untracked.
UNTRACKED_IGNORE_PATTERNS = [
    "__pycache__/*",
    "*.pyc",
    ".pytest_cache/*",
    ".coverage*",
]

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

# Tracked paths that match a JUNK_PATTERN but are deliberately committed anyway.
# fnmatch cannot express gitignore's negation (``!projects/.gitkeep``), so the
# exception has to be listed here. Keep this list tiny and justified - every
# entry is a claim that the file earns its place in the repository.
ALLOWED_TRACKED = {
    # Makes BAIZE_PROJECTS_DIR physically exist in a fresh clone.
    # baize/doctor.py requires that directory (required=True) and nothing in the
    # codebase creates it, so ignoring the whole directory made every fresh
    # clone end in "RESULT: FAILED" - the documented quickstart could not pass.
    "projects/.gitkeep",
}

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


def untracked_files() -> list[str]:
    """Paths git would add on ``git add -A``: untracked, not ignored.

    ``--exclude-standard`` applies ``.gitignore``/``.git/info/exclude``, so build
    products do not show up here and only files a developer created are listed.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"HYGIENE GATE ERROR: cannot list untracked files ({exc})", file=sys.stderr)
        raise SystemExit(2)
    return [p for p in out.split("\0") if p]


def untracked_key_files() -> list[str]:
    """Untracked files in :data:`KEY_DIRS` that are not test-run by-products."""
    found = []
    for path in untracked_files():
        posix = path.replace("\\", "/")
        if not posix.startswith(KEY_DIRS):
            continue
        if any(fnmatch.fnmatch(posix, p) or fnmatch.fnmatch(Path(posix).name, p)
               for p in UNTRACKED_IGNORE_PATTERNS):
            continue
        found.append(path)
    return found


def main(argv: list[str]) -> int:
    verbose = "-v" in argv[1:]
    index_only = "--index-only" in argv[1:]

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    missing = [p for p in GITIGNORE_MUST_CONTAIN if p not in gitignore]
    if missing:
        print("HYGIENE GATE FAILED: .gitignore lost patterns this gate relies on:")
        for m in missing:
            print(f"  {m}")
        return 1

    offenders: list[tuple[str, str]] = []
    for path in tracked_files():
        if path in ALLOWED_TRACKED:
            continue
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

    if not index_only:
        untracked = untracked_key_files()
        if untracked:
            print(
                f"HYGIENE GATE FAILED: {len(untracked)} file(s) under "
                f"{', '.join(KEY_DIRS)} are untracked, so a fresh clone does not "
                f"have them:\n")
            for path in untracked:
                print(f"  {path}")
            print(
                "\nA tracked file that imports one of these works on this machine "
                "and fails everywhere else. Commit them:\n"
                "  git add " + " ".join(untracked[:3]) + (" ..." if len(untracked) > 3 else "") + "\n"
                "If you deliberately want to check only the index, pass --index-only."
            )
            return 1

    n = len(tracked_files())
    print(f"HYGIENE GATE PASSED: {n} tracked files, none matching a banned pattern")
    if not index_only:
        print(f"  untracked scan: {', '.join(KEY_DIRS)} clear")
    if verbose:
        print("  patterns enforced: " + ", ".join(JUNK_PATTERNS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
