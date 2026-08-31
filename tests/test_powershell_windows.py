"""Unit tests for Baize Windows & PowerShell native execution and POSIX translation shim."""
from __future__ import annotations

import sys
import unittest
from baize.powershell import (
    resolve_powershell_executable,
    translate_posix_to_powershell,
    build_powershell_invocation,
    get_powershell_status,
    _fix_python_inline_quotes,
)
from baize.tools import _tool_bash


class TestPowerShellWindows(unittest.TestCase):
    def test_resolve_powershell_executable(self):
        exe = resolve_powershell_executable()
        self.assertTrue(isinstance(exe, str))
        self.assertTrue(len(exe) > 0)

    def test_translate_cat(self):
        cmd = "cat file.txt"
        trans = translate_posix_to_powershell(cmd)
        self.assertEqual(trans, "Get-Content file.txt -Raw")

    def test_translate_ls(self):
        self.assertEqual(translate_posix_to_powershell("ls"), "Get-ChildItem -Force")
        self.assertEqual(translate_posix_to_powershell("ls -la"), "Get-ChildItem -Force")
        self.assertEqual(translate_posix_to_powershell("ls -lh mydir"), "Get-ChildItem -Force mydir")

    def test_translate_rm_rf(self):
        self.assertEqual(translate_posix_to_powershell("rm -rf temp_dir"), "Remove-Item -Recurse -Force temp_dir")
        self.assertEqual(translate_posix_to_powershell("rm file.log"), "Remove-Item -Force file.log")

    def test_translate_export_and_unset(self):
        self.assertEqual(translate_posix_to_powershell("export FOO=bar"), '$env:FOO="bar"')
        self.assertEqual(translate_posix_to_powershell('export TOKEN="secret_123"'), '$env:TOKEN="secret_123"')
        self.assertEqual(translate_posix_to_powershell("unset FOO"), 'Remove-Item "Env:\\FOO" -ErrorAction SilentlyContinue')

    def test_translate_which(self):
        self.assertEqual(translate_posix_to_powershell("which python"), "(Get-Command python -ErrorAction SilentlyContinue).Source")

    def test_translate_touch_and_mkdir(self):
        self.assertEqual(translate_posix_to_powershell("touch new.py"), "New-Item -ItemType File -Force new.py | Out-Null")
        self.assertEqual(translate_posix_to_powershell("mkdir -p src/utils"), "New-Item -ItemType Directory -Force src/utils | Out-Null")

    def test_translate_compound_commands(self):
        cmd = "mkdir -p dist && cat input.txt > dist/output.txt"
        trans = translate_posix_to_powershell(cmd)
        self.assertIn("New-Item -ItemType Directory -Force dist", trans)
        self.assertIn("Get-Content input.txt -Raw > dist/output.txt", trans)

    def test_fix_python_inline_quotes(self):
        raw = "python -c 'print(\"hello world\")'"
        fixed = _fix_python_inline_quotes(raw)
        self.assertEqual(fixed, 'python -c "print(\\"hello world\\")"')

    def test_build_powershell_invocation(self):
        args = build_powershell_invocation("echo hello")
        self.assertIn("-NoProfile", args)
        self.assertIn("-NonInteractive", args)
        self.assertIn("-ExecutionPolicy", args)
        self.assertIn("Bypass", args)

    def test_get_powershell_status(self):
        status = get_powershell_status()
        self.assertIn("shell_executable", status)
        self.assertTrue(status.get("utf8_enforced"))
        self.assertTrue(status.get("posix_shim_active"))

    def test_tool_run_command_powershell_execution(self):
        # Test executing a Python inline command through _tool_bash
        res = _tool_bash('python -c "import sys; print(\'Python UTF-8 Test: 白泽\')"')
        self.assertIn("exit=0", res)
        self.assertIn("白泽", res)


if __name__ == "__main__":
    unittest.main()
