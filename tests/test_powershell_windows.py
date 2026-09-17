"""Unit tests for Baize Windows & PowerShell native execution and POSIX translation shim."""
from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path
from baize.powershell import (
    NOT_TRANSLATED,
    SUPPORTED_TRANSLATIONS,
    resolve_powershell_executable,
    translate_posix_to_powershell,
    build_powershell_invocation,
    detect_wsl2_status,
    get_powershell_status,
    _fix_python_inline_quotes,
)
from baize.tools import _tool_bash


def _powershell_can_launch_absolute_paths() -> bool:
    """Whether PowerShell here can start an absolute-path executable at all.

    Measured failure mode (this sandbox, and plausibly other locked-down
    images): PowerShell starts, exits 0, and returns EMPTY stdout - no error
    text at all. ``& "C:\\Windows\\System32\\cmd.exe" /c "echo SANE"`` behaves
    the same as a broken ``python`` invocation, so the failure cannot be
    attributed to the product. Verified counterexample in the same shell:
    ``echo hello`` returns ``hello``, i.e. builtins work and external
    programs do not.

    The tests below need PowerShell to run ``python``. When the environment
    cannot launch external programs, skipping with this reason is honest;
    reporting a product failure would not be.
    """
    exe = resolve_powershell_executable()
    probe = shutil.which("cmd") or shutil.which("echo")
    if not exe or not probe:
        return False
    try:
        res = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command",
             f'& "{Path(probe).resolve()}" /c echo BAIZE_PS_PROBE'],
            capture_output=True, text=True, timeout=10)
    except Exception:
        return False
    return "BAIZE_PS_PROBE" in (res.stdout or "")


PS_ABS_OK = _powershell_can_launch_absolute_paths()
PS_SKIP_REASON = (
    "PowerShell in this environment cannot launch absolute-path executables "
    "(starts, exits 0, empty stdout); the test needs PowerShell to run "
    "`python`. Not a product defect - see _powershell_can_launch_absolute_paths."
)


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


class TestPosixShimHonesty(unittest.TestCase):
    """The shim must not advertise translations it does not perform.

    The previous capability list contained ``grep -> Select-String`` and the
    module docstring claimed sed / xargs / find support. None of those was ever
    written: the inputs fall through ``_translate_single_command`` unchanged and
    reach PowerShell verbatim. These tests pin the corrected list.
    """

    def test_every_advertised_translation_actually_translates(self):
        for src, fragment in SUPPORTED_TRANSLATIONS:
            out = translate_posix_to_powershell(src)
            self.assertIn(fragment, out,
                          f"advertised {src!r} -> {fragment!r} but got {out!r}")
            self.assertNotEqual(out.strip(), src.strip(),
                                f"{src!r} was advertised but passed through")

    def test_grep_is_not_advertised(self):
        advertised = " ".join(
            f"{src} {dst}" for src, dst in SUPPORTED_TRANSLATIONS)
        self.assertNotIn("grep", advertised)
        self.assertIn("grep", NOT_TRANSLATED)
        # ...and the behaviour matches the corrected claim.
        self.assertEqual(translate_posix_to_powershell("grep foo bar.txt"),
                         "grep foo bar.txt")

    def test_status_exposes_the_not_translated_list(self):
        status = get_powershell_status()
        self.assertIn("grep", status["not_translated"])
        self.assertEqual(
            sorted(status["supported_posix_translations"][0]),
            ["posix", "powershell"])

    def test_status_does_not_claim_os_isolation(self):
        status = get_powershell_status()
        self.assertEqual(status["execution_policy"], "Bypass")
        self.assertIs(status["os_isolation"], False)
        self.assertNotIn("Isolated", status["execution_policy"])

    def test_shell_version_is_null_or_real_never_guessed(self):
        status = get_powershell_status()
        version = status["shell_version"]
        if version is None:
            self.assertTrue(status["shell_version_error"],
                            "a null version must come with a reason")
        else:
            self.assertTrue(version.startswith("PowerShell v"),
                            f"unexpected version string {version!r}")

    def test_failed_wsl_probe_is_unknown_not_available(self):
        real_run = subprocess.run

        def boom(*a, **kw):
            raise OSError("probe exploded")

        with unittest.mock.patch.object(subprocess, "run", boom):
            if sys.platform != "win32":
                self.skipTest("wsl probe only runs on Windows")
            res = detect_wsl2_status()
        self.assertIsNone(res["available"],
                          "a failed probe must not report availability")
        self.assertIn("error", res)
        self.assertEqual(res["distros"], [])

    def test_no_distro_name_is_invented_when_none_is_listed(self):
        if sys.platform != "win32":
            self.skipTest("wsl probe only runs on Windows")
        res = detect_wsl2_status()
        # Whatever the host says, the answer must be internally consistent.
        if res["available"] is True:
            self.assertTrue(res["distros"])
            self.assertEqual(res["default"], res["distros"][0])
        else:
            self.assertIsNone(res["default"])

    @unittest.skipUnless(PS_ABS_OK, PS_SKIP_REASON)
    def test_tool_run_command_powershell_execution(self):
        # Test executing a Python inline command through _tool_bash
        res = _tool_bash('python -c "import sys; print(\'Python UTF-8 Test: 白泽\')"')
        self.assertIn("exit=0", res)
        self.assertIn("白泽", res)


if __name__ == "__main__":
    unittest.main()
