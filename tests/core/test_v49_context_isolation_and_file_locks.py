"""V49.0.0 Zenith tests: contextvars workspace isolation, optimistic file locks, atomic writes, and unified sandbox dispatch."""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from baize.core.runtime_ctx import (
    atomic_write_bytes,
    atomic_write_text,
    current_session_id,
    current_workspace,
    execution_context,
    get_file_read_tracker,
)
from baize.execution import tools as tools_mod


class TestV49ContextIsolationAndFileLocks(unittest.TestCase):
    def setUp(self) -> None:
        get_file_read_tracker().clear()

    def tearDown(self) -> None:
        get_file_read_tracker().clear()

    def test_concurrent_execution_context_isolates_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            ws1 = Path(d1).resolve()
            ws2 = Path(d2).resolve()
            barrier = threading.Barrier(2)
            results: dict[str, tuple[str, str, str]] = {}
            errors: list[Exception] = []

            def worker(tag: str, ws: Path, sid: str) -> None:
                try:
                    with execution_context(workspace=ws, session_id=sid):
                        barrier.wait(timeout=5)
                        w_out = tools_mod._tool_write_file("hello.txt", f"from-{tag}")
                        barrier.wait(timeout=5)
                        r_out = tools_mod._tool_read_file("hello.txt")
                        results[tag] = (str(current_workspace({})), current_session_id(), f"{w_out}|{r_out}")
                except Exception as exc:
                    errors.append(exc)

            t1 = threading.Thread(target=worker, args=("alpha", ws1, "sess-alpha"))
            t2 = threading.Thread(target=worker, args=("beta", ws2, "sess-beta"))
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)

            self.assertEqual(errors, [])
            self.assertEqual(results["alpha"][0], str(ws1))
            self.assertEqual(results["alpha"][1], "sess-alpha")
            self.assertIn("from-alpha", results["alpha"][2])
            self.assertEqual(results["beta"][0], str(ws2))
            self.assertEqual(results["beta"][1], "sess-beta")
            self.assertIn("from-beta", results["beta"][2])
            self.assertEqual((ws1 / "hello.txt").read_text(encoding="utf-8"), "from-alpha")
            self.assertEqual((ws2 / "hello.txt").read_text(encoding="utf-8"), "from-beta")

    def test_optimistic_lock_detects_external_modification_and_recovers_after_reread(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d).resolve()
            target = ws / "app.py"
            target.write_text("value = 1\n", encoding="utf-8")

            with execution_context(workspace=ws, session_id="sess-lock"):
                read1 = tools_mod._tool_read_file("app.py")
                self.assertIn("value = 1", read1)

                time.sleep(0.02)
                target.write_text("value = 999  # external edit\n", encoding="utf-8")

                patch_err = tools_mod._tool_patch_file("app.py", "value = 999", "value = 2")
                self.assertIn("ERROR:", patch_err)
                self.assertIn("stale", patch_err.lower())
                self.assertIn("value = 999", target.read_text(encoding="utf-8"))

                write_err = tools_mod._tool_write_file("app.py", "value = 3\n")
                self.assertIn("ERROR:", write_err)

                tools_mod._tool_read_file("app.py")
                patch_ok = tools_mod._tool_patch_file("app.py", "value = 999", "value = 2")
                self.assertNotIn("ERROR:", patch_ok)
                self.assertIn("value = 2", target.read_text(encoding="utf-8"))

    def test_strict_require_read_before_edit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d).resolve()
            existing = ws / "config.py"
            existing.write_text("DEBUG = False\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {"BAIZE_REQUIRE_READ_BEFORE_EDIT": "1"}):
                with execution_context(workspace=ws, session_id="sess-strict"):
                    err = tools_mod._tool_patch_file("config.py", "False", "True")
                    self.assertIn("ERROR:", err)
                    self.assertIn("read_file", err)

                    ok_new = tools_mod._tool_write_file("brand_new.py", "x = 42\n")
                    self.assertNotIn("ERROR:", ok_new)
                    self.assertEqual((ws / "brand_new.py").read_text(encoding="utf-8"), "x = 42\n")

                    tools_mod._tool_read_file("config.py")
                    ok_patch = tools_mod._tool_patch_file("config.py", "False", "True")
                    self.assertNotIn("ERROR:", ok_patch)
                    self.assertEqual(existing.read_text(encoding="utf-8"), "DEBUG = True\n")

    def test_atomic_write_text_and_bytes_leave_no_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p_txt = Path(d) / "sub" / "hello.txt"
            p_bin = Path(d) / "sub" / "data.bin"
            atomic_write_text(p_txt, "hello atomic\n")
            atomic_write_bytes(p_bin, b"\x00\x01\x02baize")
            self.assertEqual(p_txt.read_text(encoding="utf-8"), "hello atomic\n")
            self.assertEqual(p_bin.read_bytes(), b"\x00\x01\x02baize")
            leftovers = [f.name for f in (Path(d) / "sub").iterdir() if f.name.startswith(".")]
            self.assertEqual(leftovers, [])

    def test_tool_bash_honors_unified_resolve_sandbox_mode(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d).resolve()
            env_patch = {
                "BAIZE_SANDBOX_ENABLED": "0",
                "BAIZE_SANDBOX_MODE": "local-hardened",
                "BAIZE_STREAM_TOOL_OUTPUT": "0",
            }
            fake_res = mock.MagicMock(
                returncode=0,
                stdout="sandboxed-ok\n",
                stderr="",
                backend="local-hardened",
                sandboxed=True,
                degraded=False,
            )
            with mock.patch.dict(os.environ, env_patch):
                with execution_context(workspace=ws, session_id="sess-sb"):
                    with mock.patch("baize.core.component.resolve_sandbox", return_value=fake_res) as m_sb:
                        out = tools_mod._tool_bash("echo hello")
                        self.assertEqual(m_sb.call_count, 1)
                        self.assertIn("sandboxed-ok", out)


if __name__ == "__main__":
    unittest.main()
