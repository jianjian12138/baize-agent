"""Unit tests for Phase 3 Industrial Surpassing: Mutation Testing, Darwin Marketplace, and Byzantine Consensus."""
from __future__ import annotations

import unittest

import pytest

from baize.mutation import run_ast_mutation_arena
from baize.tool_market import clear_published_tools, list_market_tools, publish_market_tool
from baize.byzantine import run_byzantine_consensus
from baize.powershell import get_powershell_status
from baize.desktop_ui import render_desktop_studio


@pytest.fixture(autouse=True)
def _isolate_the_marketplace():
    """The registry is process-global; a publication in one test must not be
    visible to the next."""
    clear_published_tools()
    yield
    clear_published_tools()


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
        # Nothing verified or mounted the tool, so those fields must not claim
        # otherwise. They used to read `verified_gate: True` and `downloads: 12`.
        self.assertIsNone(pub_res["tool"]["verified_gate"])
        self.assertIsNone(pub_res["tool"]["downloads"])
        self.assertIs(pub_res["tool"]["mounted"], False)
        self.assertIs(pub_res["persisted"], False)
        self.assertIn("not a", pub_res["tool"]["digest_kind"])
        # A digest has to be reproducible, not a fresh nonce per call.
        again = publish_market_tool({
            "name": "unit_test_synthesized_tool",
            "generation_id": 7,
            "code": "def run(): return 42",
        })
        self.assertEqual(
            pub_res["tool"]["darwin_hash"], again["tool"]["darwin_hash"]
        )

    def test_byzantine_consensus(self):
        # With no verdicts there is nothing to arbitrate, and the response says
        # so. It used to return two literal APPROVEs and reach consensus for
        # every input, including this one.
        empty = run_byzantine_consensus("def secure_flow(): pass", "发布加密支付门禁")
        self.assertEqual(empty["status"], "awaiting_verdicts")
        self.assertIsNone(empty["consensus_reached"])
        self.assertIs(empty["signed"], False)
        self.assertEqual(empty["nodes"], [])
        self.assertNotIn("bft_signature", empty)

        verdicts = [
            {"node_id": "red", "role": "attacker", "vote": "APPROVE"},
            {"node_id": "blue", "role": "defender", "vote": "APPROVE"},
        ]
        res = run_byzantine_consensus(
            "def secure_flow(): pass", "发布加密支付门禁", verdicts=verdicts
        )
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["consensus_reached"])
        self.assertEqual(res["approvals"], 2)
        self.assertEqual(len(res["nodes"]), 2)
        self.assertIn("BFT-DIGEST-", res["digest"])
        self.assertIs(res["signed"], False)
        # The digest is a function of the inputs, so it must be reproducible.
        again = run_byzantine_consensus(
            "def secure_flow(): pass", "发布加密支付门禁", verdicts=verdicts
        )
        self.assertEqual(res["digest"], again["digest"])

        # A quorum is only met when the votes actually clear it.
        one_approval = run_byzantine_consensus(
            "", "g", verdicts=[{"vote": "APPROVE"}, {"vote": "REJECT"}]
        )
        self.assertFalse(one_approval["consensus_reached"])
        self.assertEqual(one_approval["approvals"], 1)

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
