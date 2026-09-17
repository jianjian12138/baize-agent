"""Tests for ``scripts/check_arch_tree.py``.

The gate exists because docs/architecture.md section 2 described a package
layout that did not exist. These tests pin both directions: a tree that matches
the filesystem passes, and a tree that does not is caught.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "check_arch_tree", ROOT / "scripts" / "check_arch_tree.py"
)
check_arch_tree = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_arch_tree)


GOOD_TREE = """\
Some prose.

```text
pkg/                              # 2 modules + __main__.py, flat by design
├── alpha.py  beta.py
│
├── sub/
│   └── gamma.py
└── empty/                        # package marker only - no modules
```

More prose.
"""


def _make_pkg(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__main__.py").write_text("", encoding="utf-8")
    (pkg / "alpha.py").write_text("", encoding="utf-8")
    (pkg / "beta.py").write_text("", encoding="utf-8")
    (pkg / "sub").mkdir()
    (pkg / "sub" / "gamma.py").write_text("", encoding="utf-8")
    (pkg / "empty").mkdir()
    return pkg


def _write_doc(tmp_path: Path, text: str) -> Path:
    doc = tmp_path / "architecture.md"
    doc.write_text(text, encoding="utf-8")
    return doc


def test_parse_extracts_flat_and_subpackage_modules():
    root, flat, sub, declared = check_arch_tree.parse_tree(GOOD_TREE)
    assert root == "pkg"
    assert flat == ["alpha.py", "beta.py"]
    assert sub == ["sub/gamma.py"]
    assert declared == 2


def test_parse_rejects_a_doc_without_a_tree():
    with pytest.raises(ValueError):
        check_arch_tree.parse_tree("no code block here")


def test_matching_tree_passes(tmp_path):
    pkg = _make_pkg(tmp_path)
    doc = _write_doc(tmp_path, GOOD_TREE)
    assert check_arch_tree.check(doc, pkg) == []


def test_missing_flat_module_is_caught(tmp_path):
    pkg = _make_pkg(tmp_path)
    doc = _write_doc(tmp_path, GOOD_TREE.replace("beta.py", "beta_typo.py"))
    problems = check_arch_tree.check(doc, pkg)
    assert any("beta_typo.py" in p for p in problems)
    assert any("beta.py" in p and "not listed" in p for p in problems)


def test_missing_subpackage_module_is_caught(tmp_path):
    pkg = _make_pkg(tmp_path)
    doc = _write_doc(tmp_path, GOOD_TREE.replace("gamma.py", "delta.py"))
    problems = check_arch_tree.check(doc, pkg)
    assert any("sub/delta.py" in p for p in problems)


def test_wrong_flat_count_is_caught(tmp_path):
    pkg = _make_pkg(tmp_path)
    doc = _write_doc(tmp_path, GOOD_TREE.replace("# 2 modules", "# 7 modules"))
    problems = check_arch_tree.check(doc, pkg)
    assert any("documented flat count 7" in p for p in problems)


def test_wrong_root_name_is_caught(tmp_path):
    pkg = _make_pkg(tmp_path)
    doc = _write_doc(tmp_path, GOOD_TREE.replace("pkg/  ", "other/"))
    problems = check_arch_tree.check(doc, pkg)
    assert any("rooted at other/" in p for p in problems)


def test_the_real_repository_is_consistent():
    """The actual docs/architecture.md must match the actual package."""
    problems = check_arch_tree.check(ROOT / "docs" / "architecture.md",
                                     ROOT / "baize")
    assert problems == [], "\n".join(problems)


def test_main_exit_codes(tmp_path, capsys):
    pkg = _make_pkg(tmp_path)
    good = _write_doc(tmp_path, GOOD_TREE)
    assert check_arch_tree.main([str(good), str(pkg)]) == 0

    bad = tmp_path / "bad.md"
    bad.write_text(GOOD_TREE.replace("beta.py", "nope.py"), encoding="utf-8")
    assert check_arch_tree.main([str(bad), str(pkg)]) == 1

    assert check_arch_tree.main(
        [str(tmp_path / "does-not-exist.md"), str(pkg)]) == 1
