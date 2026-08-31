"""Unit tests for Phase 2 Industrial Refinement: Swarm Speculation, Context Slicer, VS Code Sidecar, and CI Bot."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from baize.swarm import run_parallel_swarm_speculation
from baize.context_slicer import slice_code_context
from baize.desktop_ui import render_desktop_studio


class TestPhase2Industrial(unittest.TestCase):
    def test_swarm_parallel_speculation(self):
        res = run_parallel_swarm_speculation("重构数据库事务层")
        self.assertIn("branches", res)
        self.assertEqual(len(res["branches"]), 3)
        self.assertIn("winner", res)
        self.assertTrue(res["winner"]["churn_lines"] > 0)
        self.assertTrue(res["total_elapsed_ms"] >= 0)

    def test_ast_context_slicing(self):
        code = """
def unused_helper_one(a, b):
    \"\"\"This is helper one with lots of code.\"\"\"
    x = a * 10
    y = b * 20
    return x + y

def target_main_logic(val):
    \"\"\"The main target symbol.\"\"\"
    return val * 42

def unused_helper_two():
    print("hello world")
"""
        res = slice_code_context(code, "target_main_logic")
        self.assertEqual(res["pruned_functions_count"], 2)
        self.assertIn("target_main_logic", res["sliced_code"])
        self.assertIn("return val * 42", res["sliced_code"])
        # Unused helpers should have ellipsis (...)
        self.assertIn("...", res["sliced_code"])
        self.assertGreater(res["original_chars"], res["sliced_chars"])

    def test_vscode_extension_manifest(self):
        manifest_path = Path("extensions/vscode/package.json")
        self.assertTrue(manifest_path.exists())
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "baize-assistant-sidecar")
        commands = {c["command"] for c in data["contributes"]["commands"]}
        self.assertIn("baize.openStudio", commands)
        self.assertIn("baize.inlineRefactor", commands)

    def test_ci_autofix_workflow_exists(self):
        wf_path = Path(".github/workflows/baize-ci-autofix.yml")
        self.assertTrue(wf_path.exists())
        content = wf_path.read_text(encoding="utf-8")
        self.assertIn("Baize Autonomous CI & Auto-Fix Bot", content)

    def test_desktop_studio_includes_phase2_components(self):
        html = render_desktop_studio("35.0.0")
        self.assertIn("runSwarmLab", html)
        self.assertIn("testContextSlice", html)
        self.assertIn("Asyncio Swarm Engine", html)
        self.assertIn("AST Context Slicer", html)


if __name__ == "__main__":
    unittest.main()
