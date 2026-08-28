"""W3 F7 — static grep gate (red line C: ext fail-closed).

Core ``baize/*.py`` MUST never do a TOP-LEVEL ``import baize.ext``. The only
sanctioned ext access from the core runtime is through ``tools.register_mcp_client``
and ``cli.cmd_mcp``, both of which import ``baize.ext.*`` *inside* a function body
(indented), which this AST scan deliberately ignores.

This test is part of the normal suite, so the 422-passed baseline protects the
invariant continuously. The same check is mirrored as a CI shell step in
``.github/workflows/ci.yml`` (the ``Static grep gate`` job step).

We scan only ``baize/*.py`` (top-level core modules). ``baize/ext/`` is excluded
on purpose: ext modules are *allowed* to import each other, and ``baize/plugins/``
loads third-party code via importlib in isolation.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

BAIZE = pathlib.Path(__file__).resolve().parent.parent / "baize"


def _top_level_ext_imports(py_file: pathlib.Path) -> list[str]:
    """Return any TOP-LEVEL (module-body) imports of ``baize.ext`` in ``py_file``."""
    violations: list[str] = []
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    for node in tree.body:  # top-level statements only — nested imports are exempt
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[:2] == ["baize", "ext"]:
                    violations.append(f"{py_file.name}: import {alias.name!r}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and mod.split(".")[:2] == ["baize", "ext"]:
                violations.append(f"{py_file.name}: from {mod!r}")
    return violations


def test_no_top_level_ext_import_in_core():
    violations: list[str] = []
    for py in sorted(BAIZE.glob("*.py")):  # top-level core modules only
        violations.extend(_top_level_ext_imports(py))
    assert not violations, (
        "RED LINE C violation — core must not top-level import baize.ext:\n"
        + "\n".join(violations)
    )


def test_ext_self_package_imports_are_allowed():
    # The ext package itself (and its siblings) importing baize.ext.* is the
    # sanctioned direction (ext -> core/ext, never core -> ext). This guard
    # documents the asymmetry so a future refactor does not "fix" it wrongly.
    assert (BAIZE / "ext" / "__init__.py").exists()
    client = BAIZE / "ext" / "mcp" / "__init__.py"
    if client.exists():
        src = client.read_text(encoding="utf-8")
        # mcp/__init__.py imports its own siblings — allowed (ext -> ext).
        assert "from .client import" in src or "from . import" in src
