"""Unit tests for Baize Titan Evolution: Persistent PS Session, Stream Shims, Interactive Detector, Polyglot Graph, and Invariants Anchor."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from baize.powershell import (
    PersistentPowerShellSession,
    translate_posix_to_powershell,
    get_powershell_status,
)
from baize.interactive_detector import detect_interactive_prompt, get_safe_auto_answer
from baize.symbol_graph import SymbolGraph
from baize.invariants_anchor import create_invariants_anchor
from baize.swarm import GitWorktreeSandbox


class TestTitanEvolution(unittest.TestCase):
    def test_complex_unix_stream_translation(self):
        # 1. awk '{print $1}'
        res_awk = translate_posix_to_powershell("cat list.txt | awk '{print $1}'")
        self.assertIn("ForEach-Object", res_awk)

        # 2. wc -l
        res_wc = translate_posix_to_powershell("cat list.txt | wc -l")
        self.assertIn("Measure-Object -Line", res_wc)

        # 3. sort -u
        res_sort = translate_posix_to_powershell("cat list.txt | sort -u")
        self.assertIn("Sort-Object -Unique", res_sort)

    def test_persistent_powershell_session(self):
        session = PersistentPowerShellSession(".")
        code, out = session.execute('python -c "print(\'Titan PS Session: OK\')"')
        self.assertEqual(code, 0)
        self.assertIn("Titan PS Session: OK", out)

    def test_interactive_detector_prompts(self):
        # Test confirmation prompt
        p1 = detect_interactive_prompt("Do you want to apply this migration? [y/N]")
        self.assertTrue(p1["is_interactive"])
        self.assertEqual(p1["prompt_type"], "confirmation")

        # Test password prompt
        p2 = detect_interactive_prompt("Enter password for user root:")
        self.assertTrue(p2["is_interactive"])
        self.assertEqual(p2["prompt_type"], "password_prompt")

        # Test npm init
        p3 = detect_interactive_prompt("package name: (my-app)")
        self.assertTrue(p3["is_interactive"])
        self.assertEqual(p3["prompt_type"], "npm_init_field")

        # Non-interactive output
        p4 = detect_interactive_prompt("Compilation succeeded in 1.2s.")
        self.assertFalse(p4["is_interactive"])

    def test_polyglot_symbol_graph_ts_and_rust_and_go(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # TS file
            (tmp_path / "service.ts").write_text(
                "export interface UserStore {\n  getUser(): string;\n}\nexport class UserService implements UserStore {}\nexport async function initService() {}\n",
                encoding="utf-8"
            )

            # Rust file
            (tmp_path / "core.rs").write_text(
                "pub struct EngineConfig {\n  port: u16,\n}\npub fn start_engine() {}\npub trait Runner {}\n",
                encoding="utf-8"
            )

            # Go file
            (tmp_path / "server.go").write_text(
                "type Server struct {}\ntype Handler interface {}\nfunc StartServer() {}\n",
                encoding="utf-8"
            )

            graph = SymbolGraph(root_dir=tmp_dir)
            graph.index_workspace()
            summary = graph.get_summary()

            self.assertEqual(summary["total_files_indexed"], 3)
            self.assertIn("typescript", summary["languages_detected"])
            self.assertIn("rust", summary["languages_detected"])
            self.assertIn("go", summary["languages_detected"])

            # Search symbols
            user_service = graph.search_symbols("UserService")
            self.assertTrue(len(user_service) > 0)
            self.assertEqual(user_service[0]["kind"], "class")

            engine_config = graph.search_symbols("EngineConfig")
            self.assertTrue(len(engine_config) > 0)
            self.assertEqual(engine_config[0]["kind"], "struct")

            start_server = graph.search_symbols("StartServer")
            self.assertTrue(len(start_server) > 0)
            self.assertEqual(start_server[0]["kind"], "function")

    def test_long_horizon_invariants_anchor(self):
        anchor = create_invariants_anchor("重构数据持久化层，严格遵循 TDD 规范与零依赖哲学")
        self.assertTrue(len(anchor.invariants) >= 3)
        self.assertTrue(any("TDD" in inv for inv in anchor.invariants))
        self.assertTrue(any("零依赖" in inv for inv in anchor.invariants))

        wrapped = anchor.inject_anchor_header("请修改 database.py", turn_index=55)
        self.assertIn("第 55 步置顶约束", wrapped)
        self.assertIn("不可违背的核心工程不变量约束", wrapped)
        self.assertIn("请修改 database.py", wrapped)
        self.assertEqual(anchor.total_turns_anchored, 1)

    def test_git_worktree_physical_sandbox(self):
        sb = GitWorktreeSandbox(branch_id="test_exp_1")
        p = sb.create()
        self.assertTrue(p.exists())
        sb.cleanup()
        self.assertFalse(p.exists())


if __name__ == "__main__":
    unittest.main()
