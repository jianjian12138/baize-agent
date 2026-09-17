#!/usr/bin/env python
"""Enforce the "zero runtime dependencies" promise for the baize package.

The headline claim is that `pip install baize-agent` pulls in no third-party
packages and that `import baize` works on a bare interpreter. This script is the
gate for that claim.

The question that matters is not "does a non-stdlib name appear in the source"
but "would `import baize` fail without it". Those are different questions, and
conflating them is why the previous version of this check was red from V24
(commit 7af42a5) until now - all five names it flagged were legitimate optional
imports, so the job had never once been green and everyone had learned to ignore
it.

    HARD  a module-level import of a non-stdlib module. It runs on
          `import baize`, so on a clean interpreter it raises
          ModuleNotFoundError. One HARD finding means the promise is broken.

    SOFT  the same import wrapped in `try/except ImportError`, deferred into a
          function body, or gated on `TYPE_CHECKING`. `import baize` still
          succeeds and only the optional feature degrades. Reported so a
          reviewer can see it, never failed on.

Usage:
    python scripts/check_zero_deps.py [package_dir]   # default: baize/

Exit codes: 0 no hard finding, 1 hard finding, 2 cannot inspect.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = "baize"

# Exception types that make a `try` block a legitimate optional-import guard.
GUARD_EXCEPTIONS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _handler_reason(node: ast.Try) -> str | None:
    """Describe why this try block guards its body, or None if it does not."""
    for handler in node.handlers:
        if handler.type is None:
            return "bare except"
        names: list[str] = []
        if isinstance(handler.type, ast.Name):
            names = [handler.type.id]
        elif isinstance(handler.type, ast.Tuple):
            names = [e.id for e in handler.type.elts if isinstance(e, ast.Name)]
        hit = sorted(set(names) & GUARD_EXCEPTIONS)
        if hit:
            return "except " + "/".join(hit)
    return None


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _imported_modules(node: ast.AST) -> list[str]:
    """Top-level module names imported by this node. Relative imports -> []."""
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level != 0:  # `from . import x` / `from .ext import y`
            return []
        return [(node.module or "").split(".")[0]]
    return []


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _soft_reason(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    """Return why this import cannot break `import baize`, or None if it can."""
    child = node
    parent = parents.get(child)
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Executes at call time, not import time. The feature may fail, the
            # package still imports.
            return "deferred into a function body"
        if isinstance(parent, ast.Try) and child in parent.body:
            why = _handler_reason(parent)
            if why:
                return f"guarded by {why}"
        if isinstance(parent, ast.If) and _is_type_checking(parent.test):
            return "TYPE_CHECKING only"
        child = parent
        parent = parents.get(child)
    return None


def scan(root: Path) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str, str]]]:
    """Return (hard, soft). hard = [(path, line, module)], soft = [..., reason]."""
    stdlib = set(sys.stdlib_module_names)
    hard: list[tuple[str, int, str]] = []
    soft: list[tuple[str, int, str, str]] = []

    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, OSError) as exc:
            # A file we cannot parse is a file we cannot clear.
            hard.append((str(path), 0, f"<unparseable: {exc.__class__.__name__}>"))
            continue

        parents = _parent_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for module in _imported_modules(node):
                if not module or module == PACKAGE or module in stdlib:
                    continue
                reason = _soft_reason(node, parents)
                if reason:
                    soft.append((str(path), node.lineno, module, reason))
                else:
                    hard.append((str(path), node.lineno, module))
    return hard, soft


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(PACKAGE)
    if not root.is_dir():
        print(f"ZERO-DEP CHECK ERROR: {root} is not a directory", file=sys.stderr)
        return 2

    hard, soft = scan(root)

    if soft:
        print(f"Optional imports in {root}/ (allowed - `import {PACKAGE}` still works):")
        for path, line, module, reason in soft:
            print(f"  {path}:{line}  {module}  [{reason}]")
        print()

    if hard:
        print(f"HARD FAIL: {len(hard)} module-level third-party import(s) in {root}/")
        print("These execute on `import baize` and would raise ModuleNotFoundError")
        print("on a clean interpreter, breaking the zero-dependency promise.\n")
        for path, line, module in hard:
            print(f"  {path}:{line}  {module}")
        print("\nFix: move the import into the function that needs it, or wrap it in")
        print("     `try: import x / except ImportError:` and degrade honestly.")
        return 1

    print(f"ZERO-DEP CHECK PASSED: {root}/ imports stdlib only at module level"
          f" ({len(soft)} optional import(s) allowed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
