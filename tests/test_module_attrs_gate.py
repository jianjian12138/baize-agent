"""Tests for ``scripts/check_module_attrs.py``.

The gate exists because ``baize plugin remove`` deleted a directory and *then*
crashed on a call to a function that does not exist. Two lessons are pinned
here: it must catch the missing attribute, and it must not pass by skipping.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "check_module_attrs", ROOT / "scripts" / "check_module_attrs.py"
)
check_module_attrs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_module_attrs)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "sample.py"
    p.write_text(body, encoding="utf-8")
    return p


def test_real_package_is_clean():
    problems = []
    for f in sorted((ROOT / "baize").rglob("*.py")):
        problems.extend(check_module_attrs.scan_file(f))
    assert problems == [], "\n".join(problems)


def test_missing_module_attribute_is_caught(tmp_path):
    f = _write(tmp_path, (
        "from . import skill_index\n"
        "def go():\n"
        "    return skill_index.build({})\n"
    ))
    problems = check_module_attrs.scan_file(f)
    assert len(problems) == 1
    assert "skill_index.build" in problems[0]
    assert "has no attribute" in problems[0]


def test_existing_module_attribute_passes(tmp_path):
    f = _write(tmp_path, (
        "from . import skill_index\n"
        "def go():\n"
        "    return skill_index.build_index()\n"
    ))
    assert check_module_attrs.scan_file(f) == []


def test_object_binding_is_resolved_not_treated_as_a_module(tmp_path):
    """`from .observability import obs` binds an instance. Treating it as a
    module path made the first version report every such file as unverifiable."""
    f = _write(tmp_path, (
        "from .observability import obs\n"
        "def go():\n"
        "    obs.inc('x')\n"
    ))
    assert check_module_attrs.scan_file(f) == []


def test_object_binding_with_a_bad_attribute_is_caught(tmp_path):
    f = _write(tmp_path, (
        "from .observability import obs\n"
        "def go():\n"
        "    obs.no_such_method('x')\n"
    ))
    problems = check_module_attrs.scan_file(f)
    assert len(problems) == 1
    assert "no_such_method" in problems[0]


def test_unresolvable_binding_is_reported_not_skipped(tmp_path):
    """'Could not verify' must never be reported as 'verified'.

    An unresolvable binding now fails on the import itself rather than on the
    attribute reached through it, which is both more precise and earlier: the
    line number points at the import that does not exist.
    """
    f = _write(tmp_path, (
        "from . import no_such_module_anywhere\n"
        "def go():\n"
        "    return no_such_module_anywhere.thing()\n"
    ))
    problems = check_module_attrs.scan_file(f)
    assert len(problems) == 1, problems
    assert "does not exist" in problems[0]
    assert ":1:" in problems[0], "the problem should point at the import line"
    assert "no_such_module_anywhere" in problems[0]


def test_a_missing_imported_name_is_caught(tmp_path):
    """The bug this pins: `from .knowledge.causal import CausalDebugger` where
    CausalDebugger is defined nowhere. serve.py imported it, so /v30/causal
    raised ImportError on every request. The attribute check alone never looked
    at the binding itself, only at attributes reached through it."""
    f = _write(tmp_path, (
        "from .knowledge.causal import CausalDebugger\n"
        "def go():\n"
        "    return CausalDebugger()\n"
    ))
    problems = check_module_attrs.scan_file(f)
    assert len(problems) == 1, problems
    assert "CausalDebugger" in problems[0]
    assert "baize.knowledge.causal" in problems[0]


def test_a_real_imported_name_passes(tmp_path):
    f = _write(tmp_path, (
        "from .knowledge.causal import ASTCausalTracker\n"
        "def go():\n"
        "    return ASTCausalTracker()\n"
    ))
    assert check_module_attrs.scan_file(f) == []


def test_relative_import_depth_is_resolved_against_the_file(tmp_path):
    """A level-2 import inside a subpackage must resolve through that subpackage,
    not through the package root."""
    pkg = tmp_path / "baize" / "knowledge"
    pkg.mkdir(parents=True)
    f = pkg / "sample.py"
    f.write_text(
        "from ..observability import obs\ndef go():\n    return obs\n", encoding="utf-8"
    )
    assert check_module_attrs.scan_file(f) == []


def test_star_imports_are_skipped_rather_than_guessed(tmp_path):
    f = _write(tmp_path, "from .knowledge.causal import *\n")
    assert check_module_attrs.scan_file(f) == []


def test_non_baize_imports_are_not_checked(tmp_path):
    f = _write(tmp_path, "import json\nfrom pathlib import Path\n")
    assert check_module_attrs.scan_file(f) == []


def test_repo_root_is_on_sys_path():
    """The first version ran with scripts/ on sys.path, so `import baize` failed
    and the gate reported OK for everything while checking nothing."""
    import sys

    assert str(ROOT) in sys.path


def test_main_exit_codes(tmp_path, capsys):
    clean = tmp_path / "clean"
    clean.mkdir()
    _write(clean, "from . import skill_index\ndef go():\n    return skill_index.build_index()\n")
    assert check_module_attrs.main([str(clean)]) == 0

    dirty = tmp_path / "dirty"
    dirty.mkdir()
    _write(dirty, "from . import skill_index\ndef go():\n    return skill_index.build()\n")
    assert check_module_attrs.main([str(dirty)]) == 1
