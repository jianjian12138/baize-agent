"""Fast Intent & Architecture Router (V38.0.0 Dual-System).

Provides sub-5ms goal classification and routing between:
1. `direct_repl` -> Direct question answering / interactive REPL.
2. `autonomous_run` -> Single-objective agent autonomous loop.
3. `multi_agent_team` -> Multi-agent DAG collaborative team pipeline (Director -> Executor -> Verifier).
4. `ralph_state_machine` -> Long-horizon autonomous PRD state machine engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import load_config
from .system1 import IntentDecision, fast_route_intent, get_system1_engine


class IntentRouter:
    """High-performance intent classifier and dispatcher for Baize tasks."""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or load_config()

    def route(self, goal: str, context: dict | None = None) -> IntentDecision:
        """Classify the given goal into the optimal execution path."""
        engine = get_system1_engine(self.cfg)
        return engine.decide_intent(goal, context)

    def explain_route(self, decision: IntentDecision) -> str:
        """Format an explanation for the user or logs."""
        mode_names = {
            "direct_repl": "交互式对话 / 直接响应 (REPL Direct)",
            "autonomous_run": "单任务自主执行闭环 (Autonomous Run)",
            "multi_agent_team": "多代理 DAG 协同团队 (Multi-Agent Team)",
            "ralph_state_machine": "Ralph 需求全生命周期状态机 (Ralph PRD Engine)",
        }
        name = mode_names.get(decision.route, decision.route)
        return (
            f"[System 1 Router] 目标分类: {name}\n"
            f"  - 置信度 (Confidence): {decision.confidence * 100:.1f}%\n"
            f"  - 预估复杂度 (Complexity): {decision.complexity_score * 100:.1f}%\n"
            f"  - 决策引擎 (Engine): {decision.provenance} ({decision.latency_ms:.2f}ms)"
        )


def route_goal(goal: str, cfg: dict | None = None) -> IntentDecision:
    """Global convenience function for goal routing."""
    router = IntentRouter(cfg)
    return router.route(goal)
