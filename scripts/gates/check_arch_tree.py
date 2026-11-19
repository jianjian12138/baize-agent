#!/usr/bin/env python3
"""Verify that the package tree in docs/architecture.md matches the filesystem."""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

FLAT_FILE = re.compile(r"^[├└]── ([A-Za-z_][\w.-]*\.py)\b")
SUB_DIR = re.compile(r"^(?P<prefix>(?:[│ ]   )*)[├└]── (?P<name>[A-Za-z_][\w.-]*)/")
SUB_FILE = re.compile(r"^(?P<prefix>(?:[│ ]   )+)[├└]── (?P<rest>[A-Za-z_][\w.-]*\.py\b.*)$")
CONTINUATION = re.compile(r"^│\s+(?!\s*[├└])([A-Za-z_][\w.-]*\.py\b.*)$")
ROOT_HEADER = re.compile(
    r"^([A-Za-z_][\w.-]*)/\s+#\s+(\d+) (?:flat )?modules \+ __main__\.py"
)


def parse_tree(text: str) -> tuple[str | None, list[str], list[str], int | None]:
    blocks = re.findall(r"```text\n(.*?)```", text, re.S)
    if not blocks:
        raise ValueError("no ```text block found")

    root: str | None = None
    flat: list[str] = []
    sub: list[str] = []
    declared: int | None = None
    dir_stack: list[str] = []

    for line in blocks[0].splitlines():
        m = ROOT_HEADER.match(line)
        if m:
            root = m.group(1)
            declared = int(m.group(2))
            continue

        m = SUB_DIR.match(line)
        if m:
            depth = len(m.group("prefix")) // 4
            dir_stack = dir_stack[:depth]
            dir_stack.append(m.group("name"))
            continue

        m = SUB_FILE.match(line)
        if m:
            depth = len(m.group("prefix")) // 4
            parent_parts = dir_stack[:depth]
            if parent_parts:
                prefix_path = "/".join(parent_parts)
                for tok in m.group("rest").split("#", 1)[0].split():
                    if tok.endswith(".py"):
                        sub.append(f"{prefix_path}/{tok}")
            continue

        m = FLAT_FILE.match(line)
        if m:
            for tok in line.split("── ", 1)[1].split("#", 1)[0].split():
                if tok.endswith(".py"):
                    flat.append(tok)
            dir_stack = []
            continue

        m = CONTINUATION.match(line)
        if m:
            for tok in m.group(1).split("#", 1)[0].split():
                if tok.endswith(".py"):
                    flat.append(tok)

    return root, flat, sub, declared


def check(doc: Path, pkg: Path) -> list[str]:
    try:
        root, flat, sub, declared = parse_tree(doc.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read the package tree from {doc}: {exc}"]

    problems: list[str] = []
    if root is not None and root != pkg.name:
        problems.append(f"tree is rooted at {root}/ but the package is {pkg.name}/")
    for name in flat:
        if not (pkg / name).is_file():
            problems.append(f"flat module listed but missing: {pkg.name}/{name}")
    for rel in sub:
        if not (pkg / rel).is_file():
            problems.append(f"subpackage module listed but missing: {pkg.name}/{rel}")
    real_flat = sorted(p.name for p in pkg.glob("*.py") if p.name not in ("__init__.py", "__main__.py"))
    listed_flat = set(flat)
    for name in real_flat:
        if name not in listed_flat:
            problems.append(f"real module not listed in the tree: {pkg.name}/{name}")
    if declared is not None and declared != len(real_flat):
        problems.append(f"documented flat count {declared} != actual {len(real_flat)}")
    real_sub = sorted(
        p.relative_to(pkg).as_posix()
        for p in pkg.rglob("*.py")
        if p.parent != pkg and p.name != "__init__.py" and "__pycache__" not in p.parts
    )
    listed_sub = set(sub)
    for rel in real_sub:
        if rel not in listed_sub:
            problems.append(f"real subpackage module not listed in the tree: {pkg.name}/{rel}")
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
    print(f"arch-tree check OK: {len(set(flat))} flat modules, {len(sub)} subpackage modules, all present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
