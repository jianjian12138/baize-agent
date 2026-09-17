#!/usr/bin/env python3
"""Verify that the package tree in docs/architecture.md matches the filesystem.

WHY THIS EXISTS
    Section 2 of docs/architecture.md used to describe a layout of
    ``core/ orchestration/ tooling/ knowledge/ security/ server/`` subpackages.
    None of it was real: 39 of the 43 files it listed are flat modules directly
    under ``baize/``. A reader planning a change around "baize/tooling/tools.py"
    would have been looking for a file that does not exist.

    This check parses the ``text`` block in section 2, asserts every file it
    names exists, and asserts the documented flat-module count is the real one.
    It runs in the ``hygiene`` gate (Makefile + CI).

Exit code 0 = consistent, 1 = drift found, 2 = the doc has no tree to check.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

FLAT_FILE = re.compile(r"^[├└]── ([A-Za-z_][\w.-]*\.py)\b")
SUB_DIR = re.compile(r"^[├└]── ([A-Za-z_][\w.-]*)/")
SUB_FILE = re.compile(r"^│\s+[├└]── ([A-Za-z_][\w.-]*\.py)\b")
CONTINUATION = re.compile(r"^│\s+(?!\s*[├└])([A-Za-z_][\w.-]*\.py\b.*)$")
ROOT_HEADER = re.compile(
    r"^([A-Za-z_][\w.-]*)/\s+#\s+(\d+) modules \+ __main__\.py")


def parse_tree(text: str) -> tuple[str | None, list[str], list[str], int | None]:
    """Parse the first ```text block.

    Returns ``(root_name, flat, subpackage, declared_count)``.
    """
    blocks = re.findall(r"```text\n(.*?)```", text, re.S)
    if not blocks:
        raise ValueError("no ```text block found")

    root: str | None = None
    flat: list[str] = []
    sub: list[str] = []
    declared: int | None = None
    current_sub: str | None = None

    for line in blocks[0].splitlines():
        m = ROOT_HEADER.match(line)
        if m:
            root = m.group(1)
            declared = int(m.group(2))
            continue

        m = SUB_DIR.match(line)
        if m:
            current_sub = m.group(1)
            continue

        m = SUB_FILE.match(line)
        if m:
            if current_sub:
                sub.append(f"{current_sub}/{m.group(1)}")
            continue

        m = FLAT_FILE.match(line)
        if m:
            # The first flat line carries several names, e.g.
            # "├── agent.py  agent_rules.py  automations.py  bench.py".
            for tok in line.split("── ", 1)[1].split("#", 1)[0].split():
                if tok.endswith(".py"):
                    flat.append(tok)
            current_sub = None
            continue

        m = CONTINUATION.match(line)
        if m:
            for tok in m.group(1).split("#", 1)[0].split():
                if tok.endswith(".py"):
                    flat.append(tok)

    return root, flat, sub, declared


def check(doc: Path, pkg: Path) -> list[str]:
    """Return a list of human-readable problems; empty means consistent."""
    try:
        root, flat, sub, declared = parse_tree(doc.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read the package tree from {doc}: {exc}"]

    problems: list[str] = []

    if root is not None and root != pkg.name:
        problems.append(
            f"tree is rooted at {root}/ but the package is {pkg.name}/")

    for name in flat:
        if not (pkg / name).is_file():
            problems.append(f"flat module listed but missing: {pkg.name}/{name}")

    for rel in sub:
        if not (pkg / rel).is_file():
            problems.append(
                f"subpackage module listed but missing: {pkg.name}/{rel}")

    real_flat = sorted(p.name for p in pkg.glob("*.py")
                       if p.name not in ("__init__.py", "__main__.py"))
    listed = set(flat)

    for name in real_flat:
        if name not in listed:
            problems.append(
                f"real module not listed in the tree: {pkg.name}/{name}")

    if declared is not None and declared != len(real_flat):
        problems.append(
            f"documented flat count {declared} != actual {len(real_flat)}")

    return problems


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    doc = Path(argv[0]) if argv else REPO / "docs" / "architecture.md"
    pkg = Path(argv[1]) if len(argv) > 1 else REPO / "baize"

    problems = check(doc, pkg)
    if problems:
        print(f"arch-tree check FAILED ({len(problems)} problem(s)):")
        for p in problems:
            print(f"  - {p}")
        return 1

    _root, flat, sub, _declared = parse_tree(doc.read_text(encoding="utf-8"))
    print(f"arch-tree check OK: {len(set(flat))} flat modules, "
          f"{len(sub)} subpackage modules, all present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
