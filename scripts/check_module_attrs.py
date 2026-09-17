#!/usr/bin/env python3
"""Fail the build when code calls a module attribute that does not exist.

WHY THIS EXISTS
    ``baize/cli.py`` called ``skill_index.build(cfg)``. The function is
    ``build_index``, and it returns a dict rather than a count. Nothing caught
    it because no test had ever run ``plugin install`` or ``plugin remove`` -
    ``plugin install`` needs the network, so it is not testable in CI at all.
    The bug's symptom was the worst kind: ``plugin remove`` deleted the plugin
    directory and *then* crashed with AttributeError, so the user saw a
    traceback for an operation that had already succeeded.

    This check resolves every ``from . import X`` / ``from .mod import X``
    binding in the package and asserts each ``X.attr`` that is actually used
    exists on the imported object. It is deliberately narrow: it only inspects
    attributes reached through a *module* binding, so it does not try to reason
    about instance attributes, and it produces no false positives from dynamic
    access.

Exit codes: 0 clean, 1 missing attribute found, 2 could not analyse.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "baize"

# `python scripts/check_module_attrs.py` puts scripts/ - not the repo root - on
# sys.path, so `import baize` fails. The first version of this script swallowed
# that failure in its `except Exception` and reported "OK" for every file while
# checking nothing. coverage_gate.py carries the same scar. Add the root.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKIP_MODULES = {"baize.__main__"}


def _file_module(path: Path) -> tuple[str, bool]:
    """``(dotted_module_name, is_package)`` for a file inside this repo.

    A file outside the repo - the gate's own tests write samples into tmp_path -
    is treated as a direct child of the package, because that is what a level-1
    relative import in such a file would resolve against anyway.
    """
    try:
        rel = path.resolve().relative_to(ROOT)
        parts = list(rel.with_suffix("").parts)
    except ValueError:
        parts = ["baize", path.stem]
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _imports(tree: ast.AST, path: Path) -> list[tuple[str, str, int]]:
    """Every ``baize`` import as ``(local_name, fully_qualified_path, lineno)``.

    Relative imports are resolved against the file's own package, so
    ``from .knowledge.causal import CausalDebugger`` inside ``baize/serve.py``
    becomes ``baize.knowledge.causal.CausalDebugger`` - a path that can then be
    resolved and found missing.
    """
    module_name, is_package = _file_module(path)
    package = module_name if is_package else module_name.rsplit(".", 1)[0]

    out: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith("baize"):
                    continue
                out.append((alias.asname or alias.name.split(".")[-1], alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                continue
            if node.level == 0:
                if not (node.module or "").startswith("baize"):
                    continue
                base = node.module
            else:
                parts = package.split(".")
                keep = len(parts) - (node.level - 1)
                if keep < 1:
                    continue
                base = ".".join(parts[:keep])
                if node.module:
                    base = f"{base}.{node.module}"
            for alias in node.names:
                out.append((alias.asname or alias.name, f"{base}.{alias.name}", node.lineno))
    return out


def _module_bindings(tree: ast.AST, path: Path) -> dict[str, str]:
    """Map local name -> fully-qualified path, for the attribute checks below."""
    return {local: fq for local, fq, _ in _imports(tree, path)}


class _Missing:
    pass


_MISSING = _Missing()


def _rel(path: Path) -> str:
    """Path relative to the repo root, or the path itself if it is outside."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _resolve(fq: str):
    """Resolve ``baize.a.b.c`` to an object, trying shorter prefixes as modules.

    ``from . import tools`` gives a module; ``from .observability import obs``
    gives an *instance*. Both are legitimate targets for attribute checks, and
    the first version of this script conflated them: it tried
    ``import_module("baize.observability.obs")``, failed with "is not a package",
    and reported every such file as unverifiable. Resolving the longest
    importable prefix and then walking attributes handles both.
    """
    parts = fq.split(".")
    for i in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:i]))
        except Exception:  # noqa: BLE001 - try a shorter prefix
            continue
        for attr in parts[i:]:
            obj = getattr(obj, attr, _MISSING)
            if obj is _MISSING:
                return None, f"{'.'.join(parts[:i])} has no attribute {attr!r}"
        return obj, None
    return None, f"no importable prefix of {fq!r}"


def scan_file(path: Path) -> list[str]:
    """Return human-readable problems for one file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return [f"{_rel(path)}: cannot parse ({exc})"]

    problems: list[str] = []

    # 1. Every imported name must exist. `baize/serve.py` did
    #    `from .knowledge.causal import CausalDebugger` and CausalDebugger was
    #    never defined anywhere, so /v30/causal raised ImportError on every
    #    request. The previous version of this gate only checked attributes
    #    *reached through* a binding, so a binding to a name that does not exist
    #    slipped through untouched.
    broken: set[str] = set()
    for local, fq, lineno in _imports(tree, path):
        if fq in SKIP_MODULES:
            continue
        obj, err = _resolve(fq)
        if obj is None:
            problems.append(
                f"{_rel(path)}:{lineno}: imports {local!r} from {fq}, which does "
                f"not exist - {err}"
            )
            broken.add(local)

    bindings = _module_bindings(tree, path)
    if not bindings:
        return problems

    used: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in bindings):
            used.setdefault(node.value.id, set()).add(node.attr)

    for local, attrs in sorted(used.items()):
        if local in broken:
            # Already reported as a missing import; repeating it as an
            # unverifiable attribute would just be noise.
            continue
        fq = bindings[local]
        if fq in SKIP_MODULES:
            continue
        obj, err = _resolve(fq)
        if obj is None:
            # NOT a silent skip. "Could not verify" must never read as
            # "verified" - that is how the first version of this script reported
            # OK for all 88 files while checking nothing at all.
            problems.append(
                f"{_rel(path)}: cannot verify {local}.* - {err}")
            continue
        for attr in sorted(attrs):
            if not hasattr(obj, attr):
                problems.append(
                    f"{_rel(path)}: {local}.{attr} - "
                    f"{fq} has no attribute {attr!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    target = Path((argv or sys.argv[1:] or [PKG])[0])
    files = sorted(target.rglob("*.py")) if target.is_dir() else [target]

    problems: list[str] = []
    for f in files:
        problems.extend(scan_file(f))

    if problems:
        print(f"module-attribute check FAILED ({len(problems)} problem(s)):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"module-attribute check OK: {len(files)} file(s), "
          f"no reference to a missing module attribute")
    return 0


if __name__ == "__main__":
    sys.exit(main())
