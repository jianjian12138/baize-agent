"""Tests for ``scripts/check_zero_deps.py`` - the zero-runtime-dependency gate.

The gate exists because the previous inline CI version failed on *any* non-stdlib
name, which meant it was red from V24 (7af42a5) onward and had never once been
green. A gate nobody has seen pass gets ignored, and an ignored gate is worse
than no gate.

So this file pins both directions:

  * a module-level third-party import is HARD (it breaks ``import baize``)
  * the sanctioned optional shapes are SOFT (the feature degrades, the package
    still imports): ``try/except ImportError``, a function-body import, and
    ``if TYPE_CHECKING``

It also pins the fail-closed behaviour: a file that cannot be parsed is HARD,
because an unparseable file is one we cannot clear.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "check_zero_deps", ROOT / "scripts" / "check_zero_deps.py"
)
check_zero_deps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_zero_deps)


def _write_pkg(tmp_path: pathlib.Path, name: str, source: str) -> pathlib.Path:
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(source, encoding="utf-8")
    return pkg


# --- the real package -------------------------------------------------------


def test_real_package_has_no_hard_finding():
    """The actual shipped package must satisfy the promise."""
    hard, _soft = check_zero_deps.scan(ROOT / "baize")
    assert not hard, "module-level third-party imports found:\n" + "\n".join(
        f"  {p}:{n} {m}" for p, n, m in hard
    )


def test_real_package_optional_imports_are_all_reported_with_a_reason():
    """Every non-stdlib import in the package is classified, not silently skipped."""
    _hard, soft = check_zero_deps.scan(ROOT / "baize")
    assert soft, "expected the known optional imports (webview/coverage/landlock)"
    for path, line, module, reason in soft:
        assert module in {"webview", "coverage", "landlock"}, module
        assert reason, f"{path}:{line} {module} classified without a reason"


# --- hard findings ----------------------------------------------------------


def test_module_level_third_party_import_is_hard(tmp_path):
    pkg = _write_pkg(tmp_path, "pkg", "import requests\n")
    hard, soft = check_zero_deps.scan(pkg)
    assert [m for _p, _n, m in hard] == ["requests"]
    assert soft == []


def test_module_level_from_import_is_hard(tmp_path):
    pkg = _write_pkg(tmp_path, "pkg", "from numpy import array\n")
    hard, _soft = check_zero_deps.scan(pkg)
    assert [m for _p, _n, m in hard] == ["numpy"]


def test_unparseable_file_is_hard_not_ignored(tmp_path):
    """Fail closed: a file we cannot parse is a file we cannot clear."""
    pkg = _write_pkg(tmp_path, "pkg", "def broken(:\n")
    hard, _soft = check_zero_deps.scan(pkg)
    assert len(hard) == 1
    assert "unparseable" in hard[0][2]


# --- soft findings ----------------------------------------------------------


def test_try_except_import_error_is_soft(tmp_path):
    pkg = _write_pkg(tmp_path, "pkg", "try:\n    import numpy\nexcept ImportError:\n    numpy = None\n")
    hard, soft = check_zero_deps.scan(pkg)
    assert hard == []
    assert [m for _p, _n, m, _r in soft] == ["numpy"]
    assert "ImportError" in soft[0][3]


def test_bare_except_guard_is_soft(tmp_path):
    pkg = _write_pkg(tmp_path, "pkg", "try:\n    import landlock\nexcept Exception:\n    pass\n")
    hard, soft = check_zero_deps.scan(pkg)
    assert hard == []
    assert [m for _p, _n, m, _r in soft] == ["landlock"]


def test_function_body_import_is_soft(tmp_path):
    pkg = _write_pkg(tmp_path, "pkg", "def late():\n    import pandas\n    return pandas\n")
    hard, soft = check_zero_deps.scan(pkg)
    assert hard == []
    assert [m for _p, _n, m, _r in soft] == ["pandas"]
    assert "function body" in soft[0][3]


def test_type_checking_import_is_soft(tmp_path):
    src = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import mypy_ext\n"
    pkg = _write_pkg(tmp_path, "pkg", src)
    hard, soft = check_zero_deps.scan(pkg)
    assert hard == []
    assert [m for _p, _n, m, _r in soft] == ["mypy_ext"]
    assert "TYPE_CHECKING" in soft[0][3]


def test_import_inside_try_but_in_handler_is_not_guarded(tmp_path):
    """Only the ``try`` body is protected by its handlers."""
    src = "try:\n    pass\nexcept ImportError:\n    import fallback_pkg\n"
    pkg = _write_pkg(tmp_path, "pkg", src)
    hard, _soft = check_zero_deps.scan(pkg)
    assert [m for _p, _n, m in hard] == ["fallback_pkg"]


# --- things that are never findings ----------------------------------------


def test_stdlib_self_and_relative_imports_are_ignored(tmp_path):
    src = (
        "import json\n"
        "import os.path\n"
        "from collections import OrderedDict\n"
        "import baize\n"
        "from baize.tools import default_registry\n"
        "from . import sibling\n"
        "from .sub import thing\n"
    )
    pkg = _write_pkg(tmp_path, "pkg", src)
    hard, soft = check_zero_deps.scan(pkg)
    assert hard == []
    assert soft == []


# --- exit codes -------------------------------------------------------------


def test_main_returns_zero_on_clean_package(tmp_path, capsys):
    pkg = _write_pkg(tmp_path, "pkg", "try:\n    import numpy\nexcept ImportError:\n    pass\n")
    assert check_zero_deps.main(["check_zero_deps.py", str(pkg)]) == 0
    assert "PASSED" in capsys.readouterr().out


def test_main_returns_one_on_violation(tmp_path, capsys):
    pkg = _write_pkg(tmp_path, "pkg", "import requests\n")
    assert check_zero_deps.main(["check_zero_deps.py", str(pkg)]) == 1
    out = capsys.readouterr().out
    assert "HARD FAIL" in out
    assert "requests" in out


def test_main_returns_two_on_missing_directory(tmp_path, capsys):
    assert check_zero_deps.main(["check_zero_deps.py", str(tmp_path / "nope")]) == 2
    assert "not a directory" in capsys.readouterr().err
