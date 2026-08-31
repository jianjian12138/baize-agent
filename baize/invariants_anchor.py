"""Long-Horizon Task Invariants Anchor & Anti-Drift Guard (V36.0.0 Titan).

Pure Python standard library — zero third-party dependencies.
Prevents attention drift and context degradation in multi-step (>50 turns) autonomous tasks
by dynamically pinning and injecting foundational architectural constraints on every prompt turn.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = [
    "CoreInvariantsAnchor",
    "create_invariants_anchor",
]


class CoreInvariantsAnchor:
    """Maintains pinned invariant constraints throughout long-horizon task execution."""
    def __init__(self, initial_goal: str, explicit_constraints: list[str] | None = None):
        self.initial_goal = initial_goal.strip()
        self.invariants: list[str] = explicit_constraints or self._extract_implicit_invariants(initial_goal)
        self.total_turns_anchored = 0

    def _extract_implicit_invariants(self, text: str) -> list[str]:
        """Extract high-level invariants from goal text or apply foundational engineering rules."""
        invariants = [
            "【物理门禁】必须产生真实运行凭据（NO FAKE DONE），严禁口头完成。",
            "【向下兼容】严禁在无明确要求下破坏既有 Public API 与核心接口签名。",
            "【极简设计】严格遵循最小代码抖动原则，杜绝无意义冗余代码生成。",
        ]

        if re.search(r'(?i)tdd|测试驱动|先测后写', text):
            invariants.append("【TDD 规范】必须遵循先写测试后写实现（红绿重构）。")
        if re.search(r'(?i)零依赖|标准库|zero[- ]dep', text):
            invariants.append("【零依赖哲学】必须严格使用标准库，严禁引入未经批准的外部第三方库。")
        if re.search(r'(?i)windows|powershell', text):
            invariants.append("【Windows 原生】确保命令与路径 100% 兼容 PowerShell 与 Windows 原生。")

        return invariants

    def add_custom_invariant(self, rule: str) -> None:
        """Add custom user invariant rule."""
        if rule and rule not in self.invariants:
            self.invariants.append(rule)

    def inject_anchor_header(self, current_turn_prompt: str, turn_index: int = 1) -> str:
        """Wrap prompt with persistent high-priority pinned invariant header."""
        self.total_turns_anchored += 1
        header_lines = [
            f"=== 🚨 [BAIZE CORE INVARIANTS ANCHOR · 任务第 {turn_index} 步置顶约束] ===",
            f"🎯 原始总目标: {self.initial_goal}",
            "⚠️ 不可违背的核心工程不变量约束（即使长程多轮后依然绝对有效）：",
        ]
        for i, inv in enumerate(self.invariants, 1):
            header_lines.append(f"  {i}. {inv}")
        header_lines.append("====================================================================\n")

        return "\n".join(header_lines) + current_turn_prompt

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_goal": self.initial_goal,
            "invariants": self.invariants,
            "total_turns_anchored": self.total_turns_anchored,
            "anti_drift_active": True,
        }


def create_invariants_anchor(goal: str, constraints: list[str] | None = None) -> CoreInvariantsAnchor:
    """Factory helper to initialize invariant anchor."""
    return CoreInvariantsAnchor(goal, constraints)
