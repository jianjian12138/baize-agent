"""Unit tests for Phase 3 Industrial Surpassing: Mutation Testing, Darwin Marketplace, and Byzantine Consensus."""
from __future__ import annotations

import unittest
from baize.mutation import run_ast_mutation_arena
from baize.tool_market import list_market_tools, publish_market_tool
from baize.byzantine import run_byzantine_consensus
from baize.powershell import get_powershell_status
from baize.desktop_ui import render_desktop_studio


class TestPhase3Industrial(unittest.TestCase):
    def test_ast_mutation_testing(self):
        code = "def check_score(s):\n    return True if s > 60 else False"
        res = run_ast_mutation_arena(code, "check_score")
        self.assertEqual(res["status"], "success")
        self.assertGreater(res["total_mutants_generated"], 0)
        self.assertIn("mutation_score", res)
        self.assertIn("synthesized_guardrail_test", res)

    def test_darwin_tool_market(self):
        tools = list_market_tools()
        self.assertTrue(len(tools) >= 3)
        tool_names = {t["name"] for t in tools}
        self.assertIn("k8s_manifest_validator", tool_names)
        self.assertIn("ast_sql_injection_guard", tool_names)

        # Publish a tool
        pub_res = publish_market_tool({
            "name": "unit_test_synthesized_tool",
            "category": "Testing",
            "description": "Auto synthesized tool for tests",
            "fitness_score": 0.99,
            "generation_id": 7,
            "code": "def run(): return 42"
        })
        self.assertEqual(pub_res["status"], "published")
        self.assertIn("DARWIN-", pub_res["tool"]["darwin_hash"])

    def test_byzantine_consensus(self):
        res = run_byzantine_consensus("def secure_flow(): pass", "发布加密支付门禁")
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["consensus_reached"])
        self.assertIn("BFT-SIG-", res["bft_signature"])
        self.assertEqual(len(res["nodes"]), 2)

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
