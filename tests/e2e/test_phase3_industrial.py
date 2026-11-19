"""Unit tests for Phase 3 Industrial Surpassing: Mutation Testing, Darwin Marketplace, and Byzantine Consensus."""
from __future__ import annotations

import unittest

import pytest

from baize.governance.mutation import run_ast_mutation_arena
from baize.execution.powershell import get_powershell_status
from baize.interfaces.desktop import render_desktop_studio




class TestPhase3Industrial(unittest.TestCase):
    def test_ast_mutation_testing(self):
        code = "def check_score(s):\n    return True if s > 60 else False"
        res = run_ast_mutation_arena(code, "check_score")
        self.assertEqual(res["status"], "success")
        self.assertGreater(res["total_mutants_generated"], 0)
        self.assertIn("mutation_score", res)
        self.assertIn("synthesized_guardrail_test", res)
        # The score has to follow from verdicts that were observed, not from the
        # mutant count. `killed_count = len(mutants)` scored every input 100%.
        self.assertEqual(
            res["mutants_executed"], res["mutants_killed"] + res["mutants_survived"]
        )
        self.assertNotIn("assert True", res["synthesized_guardrail_test"])
        self.assertIs(res["guardrail_verification"]["passes_original"], True)
        # And the score is not a constant: an undetectable flip must not score 100.
        undetectable = run_ast_mutation_arena("def f(x):\n    return x + 0", "f")
        self.assertEqual(undetectable["mutation_score"], "0.0%")



    def test_windows_powershell_status_includes_wsl2(self):
        status = get_powershell_status()
        self.assertIn("wsl2", status)

    def test_desktop_studio_includes_phase3_components(self):
        html = render_desktop_studio("35.0.0")
        self.assertIn("runMutationArena", html)
        self.assertIn("runByzantineConsensus", html)
        self.assertIn("publishCustomTool", html)
        self.assertIn("Darwin Marketplace", html)
        self.assertIn("Byzantine BFT Consensus", html)


if __name__ == "__main__":
    unittest.main()
