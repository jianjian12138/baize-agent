"""Tests for V33-A1 patch_file, V33-A2 fetch_url, V33-A3 run_python, V33-A4 schema validation."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from baize.tools import (
    ToolRegistry,
    _tool_patch_file,
    _tool_run_python,
    _ast_check_python,
    _tool_fetch_url,
    default_registry,
    _PYTHON_BLOCKED_MODULES,
)


# ---------------------------------------------------------------------------
# A1: patch_file
# ---------------------------------------------------------------------------

class TestPatchFile(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        # Temporarily redirect workspace to tmpdir
        self._orig_resolve = None

    def _make_file(self, name: str, content: str) -> Path:
        p = Path(self.tmpdir) / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_replace_mode_success(self):
        from baize import tools as tools_mod
        orig = tools_mod._resolve_in_workspace

        p = self._make_file("test.py", "def foo():\n    return 42\n")

        def fake_resolve(path_str, cfg=None):
            return p

        tools_mod._resolve_in_workspace = fake_resolve
        try:
            result = _tool_patch_file(str(p), "return 42", "return 99")
            self.assertIn("patched", result)
            self.assertEqual(p.read_text(), "def foo():\n    return 99\n")
        finally:
            tools_mod._resolve_in_workspace = orig

    def test_replace_mode_not_found(self):
        from baize import tools as tools_mod
        orig = tools_mod._resolve_in_workspace
        p = self._make_file("test2.py", "hello world")

        def fake_resolve(path_str, cfg=None):
            return p

        tools_mod._resolve_in_workspace = fake_resolve
        try:
            result = _tool_patch_file(str(p), "not_present", "replacement")
            self.assertIn("ERROR", result)
            self.assertIn("not found", result)
        finally:
            tools_mod._resolve_in_workspace = orig

    def test_replace_mode_ambiguous(self):
        from baize import tools as tools_mod
        orig = tools_mod._resolve_in_workspace
        p = self._make_file("test3.py", "x = 1\nx = 1\n")

        def fake_resolve(path_str, cfg=None):
            return p

        tools_mod._resolve_in_workspace = fake_resolve
        try:
            result = _tool_patch_file(str(p), "x = 1", "x = 2")
            self.assertIn("ERROR", result)
            self.assertIn("2 times", result)
        finally:
            tools_mod._resolve_in_workspace = orig

    def test_diff_mode(self):
        from baize import tools as tools_mod
        orig = tools_mod._resolve_in_workspace
        p = self._make_file("test4.py", "old line\n")

        def fake_resolve(path_str, cfg=None):
            return p

        diff = "@@ -1 +1 @@\n-old line\n+new line\n"
        tools_mod._resolve_in_workspace = fake_resolve
        try:
            result = _tool_patch_file(str(p), "", diff, mode="diff")
            self.assertIn("patched", result)
            self.assertEqual(p.read_text(), "new line\n")
        finally:
            tools_mod._resolve_in_workspace = orig

    def test_invalid_mode(self):
        from baize import tools as tools_mod
        orig = tools_mod._resolve_in_workspace
        p = self._make_file("test5.py", "content")

        def fake_resolve(path_str, cfg=None):
            return p

        tools_mod._resolve_in_workspace = fake_resolve
        try:
            result = _tool_patch_file(str(p), "content", "new", mode="invalid")
            self.assertIn("ERROR", result)
        finally:
            tools_mod._resolve_in_workspace = orig


# ---------------------------------------------------------------------------
# A3: run_python AST guard
# ---------------------------------------------------------------------------

class TestAstCheck(unittest.TestCase):
    def test_safe_code_passes(self):
        err = _ast_check_python("x = 1 + 2\nprint(x)")
        self.assertIsNone(err)

    def test_safe_math_passes(self):
        err = _ast_check_python("import math\nprint(math.sqrt(4))")
        self.assertIsNone(err)

    def test_blocked_os_import(self):
        err = _ast_check_python("import os\nos.system('ls')")
        self.assertIsNotNone(err)
        self.assertIn("os", err)

    def test_blocked_subprocess_from_import(self):
        err = _ast_check_python("from subprocess import run")
        self.assertIsNotNone(err)
        self.assertIn("subprocess", err)

    def test_blocked_exec(self):
        err = _ast_check_python("exec('import os')")
        self.assertIsNotNone(err)
        self.assertIn("exec", err)

    def test_blocked_eval(self):
        err = _ast_check_python("eval('1+1')")
        self.assertIsNotNone(err)
        self.assertIn("eval", err)

    def test_blocked_open(self):
        err = _ast_check_python("f = open('/etc/passwd')")
        self.assertIsNotNone(err)
        self.assertIn("open", err)

    def test_syntax_error(self):
        err = _ast_check_python("def foo(:\n    pass")
        self.assertIsNotNone(err)
        self.assertIn("SyntaxError", err)

    def test_blocked_dunder_import(self):
        err = _ast_check_python("__import__('os').system('ls')")
        self.assertIsNotNone(err)
        self.assertIn("__import__", err)


class TestRunPython(unittest.TestCase):
    def test_basic_execution(self):
        result = _tool_run_python("print(2 + 2)")
        self.assertEqual(result.strip(), "4")

    def test_blocked_os_import(self):
        result = _tool_run_python("import os")
        self.assertIn("ERROR", result)

    def test_timeout(self):
        result = _tool_run_python("import time\ntime.sleep(30)", timeout=1)
        self.assertIn("ERROR", result)
        self.assertIn("timed out", result)

    def test_no_output(self):
        result = _tool_run_python("x = 1")
        self.assertEqual(result, "(no output)")


# ---------------------------------------------------------------------------
# A4: Schema validation in ToolRegistry
# ---------------------------------------------------------------------------

class TestSchemaValidation(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()
        self.reg.register(
            "test_tool",
            "A test tool",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "count": {"type": "integer"},
                },
                "required": ["name"],
            },
            lambda name, count=0: f"ok name={name} count={count}",
        )

    def test_valid_args(self):
        result = self.reg.execute("test_tool", {"name": "hello", "count": 5})
        self.assertEqual(result, "ok name=hello count=5")

    def test_missing_required(self):
        result = self.reg.execute("test_tool", {})
        self.assertIn("ERROR", result)
        self.assertIn("missing required", result)
        self.assertIn("name", result)

    def test_wrong_type(self):
        result = self.reg.execute("test_tool", {"name": "hello", "count": "not_an_int"})
        self.assertIn("ERROR", result)
        self.assertIn("expected integer", result)

    def test_extra_args_allowed(self):
        # Extra args should be allowed (forward-compat)
        result = self.reg.execute("test_tool", {"name": "hello", "unknown": "value"})
        self.assertIn("ok", result)

    def test_unknown_tool(self):
        result = self.reg.execute("nonexistent", {})
        self.assertIn("ERROR", result)
        self.assertIn("unknown tool", result)


# ---------------------------------------------------------------------------
# A2: fetch_url (mock transport)
# ---------------------------------------------------------------------------

class TestFetchUrl(unittest.TestCase):
    def test_scheme_validation(self):
        result = _tool_fetch_url("file:///etc/passwd")
        self.assertIn("ERROR", result)
        self.assertIn("http/https", result)

    def test_ftp_blocked(self):
        result = _tool_fetch_url("ftp://example.com/file.txt")
        self.assertIn("ERROR", result)

    def test_http_fetch_mocked(self):
        import urllib.request
        from io import BytesIO

        class FakeResponse:
            headers = {"Content-Type": "text/html; charset=utf-8"}
            def read(self, n):
                return b"<html><body><p>Hello World</p></body></html>"
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def get(self, key, default=""):
                return self.headers.get(key, default)

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = _tool_fetch_url("https://example.com")
            self.assertIn("Hello World", result)


if __name__ == "__main__":
    unittest.main()
