"""Unit tests for IntentRouter."""
from __future__ import annotations

import unittest
from baize.intent_router import IntentRouter, route_goal
from baize.system1 import IntentDecision


class TestIntentRouter(unittest.TestCase):
    def setUp(self):
        self.router = IntentRouter()

    def test_router_classification_and_explanation(self):
        dec = self.router.route("设计一个全生命周期的 Ralph PRD 需求文档并生成 task_decomposition.json")
        self.assertEqual(dec.route, "ralph_state_machine")
        self.assertGreaterEqual(dec.confidence, 0.7)
        
        explanation = self.router.explain_route(dec)
        self.assertIn("[System 1 Router]", explanation)
        self.assertIn("Ralph", explanation)
        self.assertIn("置信度", explanation)

    def test_route_goal_helper(self):
        dec = route_goal("修复 tests/test_system1.py 中的语法错误")
        self.assertEqual(dec.route, "autonomous_run")
        self.assertEqual(dec.recommended_mode, "run")


if __name__ == "__main__":
    unittest.main()
