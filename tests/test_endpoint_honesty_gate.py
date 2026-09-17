"""Tests for ``scripts/check_endpoint_honesty.py``.

The gate has to walk a narrow line. It must fail when a fabricated-evidence
literal survives in executable code, and it must *not* fail when a comment or a
docstring explains the fix by quoting the literal - "the field used to read
``Bypass (Isolated Sandboxed)``" and "the emitted test used to be ``assert
True``" are the sentences that stop the next reader from re-adding the bug.

``strip_documentation`` is what makes that distinction, so it is tested directly
rather than only through the gate's verdict. And because a gate that can only
turn green is not a gate, the last test injects a fabrication into a fake package
and requires the gate to report it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "check_endpoint_honesty", ROOT / "scripts" / "check_endpoint_honesty.py"
)
honesty = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(honesty)


class TestStripDocumentation:
    def test_a_module_docstring_is_removed(self):
        code = '"""This docstring says assert True."""\nx = 1\n'
        assert "assert True" not in honesty.strip_documentation(code)
        assert "x = 1" in honesty.strip_documentation(code)

    def test_a_function_docstring_is_removed(self):
        code = 'def f():\n    """mentions bft_signature"""\n    return 1\n'
        stripped = honesty.strip_documentation(code)
        assert "bft_signature" not in stripped
        assert "return 1" in stripped

    def test_a_class_docstring_is_removed(self):
        code = 'class C:\n    """mentions self.downloads: int = 12"""\n    pass\n'
        assert "self.downloads: int = 12" not in honesty.strip_documentation(code)

    def test_a_non_docstring_string_literal_is_kept(self):
        """The bug lived in a string literal inside a function body. That is code."""
        code = 'def f():\n    return "assert True"\n'
        assert "assert True" in honesty.strip_documentation(code)

    def test_an_assigned_string_is_kept_even_at_module_level(self):
        code = 'TEMPLATE = "assert True"\n'
        assert "assert True" in honesty.strip_documentation(code)

    def test_a_comment_is_removed(self):
        assert "assert True" not in honesty.strip_documentation("# assert True\nx = 1\n")

    def test_a_hash_inside_a_string_is_not_treated_as_a_comment(self):
        code = 'x = "a # b"\n'
        assert honesty.strip_documentation(code).strip() == code.strip()

    def test_line_count_is_preserved(self):
        code = '"""\nline\nline\n"""\nx = 1\n'
        assert len(honesty.strip_documentation(code).splitlines()) == len(code.splitlines())

    def test_unparseable_source_is_returned_unchanged(self):
        """A file we cannot parse must not be silently treated as clean."""
        code = "def (:\n"
        assert honesty.strip_documentation(code) == code


class TestTheRealPackageIsClean:
    def test_no_fabrication_marker_survives_in_executable_code(self):
        assert honesty.check_source_markers() == []

    def test_the_markers_include_this_round_of_findings(self):
        """Otherwise the clean verdict above would be about an empty list."""
        for marker in (
            "killed_count = len(mutants)",
            "assert True",
            '"bft_signature"',
            '"fuzzing_rounds": 50',
            "self.verified_gate: bool = True",
            "self.downloads: int = 12",
            "已通过物理门禁认证",
        ):
            assert marker in honesty.FABRICATION_MARKERS, marker


class TestTheGateCanActuallyFail:
    """A gate that cannot go red is decoration. Inject each class of finding."""

    def test_an_injected_code_literal_is_reported(self, tmp_path, monkeypatch):
        package = tmp_path / "baize"
        package.mkdir()
        (package / "offender.py").write_text(
            'def arena(mutants):\n    killed_count = len(mutants)\n', encoding="utf-8"
        )
        monkeypatch.setattr(honesty, "ROOT", tmp_path)
        problems = honesty.check_source_markers()
        assert len(problems) == 1
        assert "killed_count = len(mutants)" in problems[0]
        assert "offender.py" in problems[0]

    def test_an_injected_placeholder_assertion_is_reported(self, tmp_path, monkeypatch):
        package = tmp_path / "baize"
        package.mkdir()
        (package / "gen.py").write_text(
            'def synthesize():\n    return "def test_x():\\n    assert True\\n"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(honesty, "ROOT", tmp_path)
        assert honesty.check_source_markers()

    def test_the_same_literal_in_a_docstring_is_not_reported(self, tmp_path, monkeypatch):
        package = tmp_path / "baize"
        package.mkdir()
        (package / "explained.py").write_text(
            '"""An earlier revision computed ``killed_count = len(mutants)``."""\n'
            "VALUE = 1\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(honesty, "ROOT", tmp_path)
        assert honesty.check_source_markers() == []

    def test_a_clean_package_reports_nothing(self, tmp_path, monkeypatch):
        package = tmp_path / "baize"
        package.mkdir()
        (package / "fine.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        monkeypatch.setattr(honesty, "ROOT", tmp_path)
        assert honesty.check_source_markers() == []


class TestLiveRoutes:
    def test_every_declared_stub_answers_501(self):
        assert honesty.check_live_routes() == []

    def test_the_control_route_is_not_itself_a_stub(self):
        """The gate proves it can still see a working route, so it cannot pass by
        breaking the server. That only holds if the control is a real route."""
        from baize.serve import STUB_ROUTES

        assert honesty.CONTROL_ROUTE not in STUB_ROUTES
        assert honesty.CONTROL_PAYLOAD, "the control needs a payload to exercise"
