"""Unit tests for Baize Agent System 1 Fast Decision Kernel."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch, MagicMock
import io
import urllib.error

from baize.system1 import (
    LocalCalibratedEngine,
    RemoteJevClient,
    get_system1_engine,
    fast_route_intent,
    fast_check_safety,
    fast_rank_branches,
    IntentDecision,
    SafetyDecision,
    BranchRankingDecision,
)


class TestSystem1LocalEngine(unittest.TestCase):
    def setUp(self):
        self.engine = LocalCalibratedEngine()

    def test_intent_routing_direct_repl(self):
        res = self.engine.decide_intent("请解释一下什么是白泽引擎？")
        self.assertEqual(res.route, "direct_repl")
        self.assertGreaterEqual(res.confidence, 0.8)
        self.assertLessEqual(res.latency_ms, 5.0)  # Sub-5ms execution

    def test_intent_routing_autonomous_run(self):
        res = self.engine.decide_intent("为 baize/system1.py 编写单元测试并修复存在的 bug")
        self.assertEqual(res.route, "autonomous_run")
        self.assertGreaterEqual(res.confidence, 0.7)
        self.assertEqual(res.recommended_mode, "run")

    def test_intent_routing_multi_agent_team(self):
        res = self.engine.decide_intent("执行复杂多阶段架构重构，需要 Director 规划 DAG 任务并由 Verifier 双人核验")
        self.assertEqual(res.route, "multi_agent_team")
        self.assertGreaterEqual(res.confidence, 0.7)
        self.assertEqual(res.recommended_mode, "team")

    def test_intent_routing_ralph_prd(self):
        res = self.engine.decide_intent("启动 Ralph 全生命周期 PRD 状态机演进并完成阶段验收")
        self.assertEqual(res.route, "ralph_state_machine")
        self.assertGreaterEqual(res.confidence, 0.7)
        self.assertEqual(res.recommended_mode, "ralph")

    def test_safety_veto_destructive_commands(self):
        # 1. rm -rf /
        s1 = self.engine.evaluate_safety("bash", {"command": "rm -rf / --no-preserve-root"})
        self.assertFalse(s1.is_safe)
        self.assertGreaterEqual(s1.risk_score, 0.95)
        self.assertIn("System 1", s1.veto_reason or "")

        # 2. fork bomb
        s2 = self.engine.evaluate_safety("bash", {"command": ":(){ :|:& };:"})
        self.assertFalse(s2.is_safe)
        self.assertEqual(s2.risk_score, 1.0)

        # 3. safe pytest command
        s3 = self.engine.evaluate_safety("bash", {"command": "pytest tests/test_system1.py -q"})
        self.assertTrue(s3.is_safe)
        self.assertLess(s3.risk_score, 0.5)

        # 4. read-only tool
        s4 = self.engine.evaluate_safety("read_file", {"path": "baize/agent.py"})
        self.assertTrue(s4.is_safe)
        self.assertEqual(s4.risk_score, 0.0)

    def test_branch_ranking(self):
        branches = [
            {"branch_id": "b1", "verified": True, "churn_lines": 20, "mutation_score": 0.90},
            {"branch_id": "b2", "verified": False, "churn_lines": 10, "mutation_score": 0.0},
            {"branch_id": "b3", "verified": None, "churn_lines": 50, "mutation_score": 0.5},
        ]
        decision = self.engine.rank_branches(branches, "目标测试")
        self.assertEqual(decision.winner_branch, "b1")
        self.assertGreater(decision.scores["b1"], decision.scores["b2"])
        self.assertGreater(decision.scores["b1"], decision.scores["b3"])
        self.assertIn("Elected b1", decision.rationale)


class TestRemoteJevClientFallback(unittest.TestCase):
    def test_remote_jev_fallback_on_network_error(self):
        client = RemoteJevClient(api_key="mock_key", base_url="http://127.0.0.1:59998/api")
        # Should cleanly fallback to local heuristic without throwing exception
        res = client.decide_intent("快速修复单测")
        self.assertIn(res.provenance, ("fallback", "local-calibrated"))
        self.assertIn(res.route, ("autonomous_run", "direct_repl"))

    def test_remote_jev_mock_success(self):
        client = RemoteJevClient(api_key="valid_key", base_url="https://api.typesafe.ai/v1")
        mock_payload = json.dumps({
            "route": "autonomous_run",
            "confidence": 0.94,
            "recommended_mode": "run",
            "complexity_score": 0.45
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_payload
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = client.decide_intent("编写用户登录模块")
            self.assertEqual(res.route, "autonomous_run")
            self.assertEqual(res.confidence, 0.94)
            self.assertEqual(res.provenance, "remote-jev")


if __name__ == "__main__":
    unittest.main()
