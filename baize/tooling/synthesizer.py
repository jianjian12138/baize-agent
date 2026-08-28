"""V30 Darwinian Meta-Tool Synthesizer & Gene Evolution (Pure Python Stdlib).

Enables agents to synthesize, inline-test, certify, and evolve pure Python
micro-tools dynamically at runtime.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SynthesizedTool:
    name: str
    description: str
    code_source: str
    test_source: str
    gene_signature: str = ""
    certified: bool = False
    usage_count: int = 0
    success_count: int = 0
    executable: Callable[..., Any] | None = None


class GeneStore:
    """Tracks the usage history and evolutionary status of synthesized tools."""

    def __init__(self):
        self._tools: dict[str, SynthesizedTool] = {}
        self._status: dict[str, str] = {}  # candidate | promoted | deprecated

    def register(self, tool: SynthesizedTool) -> None:
        self._tools[tool.name] = tool
        self._status[tool.name] = "candidate"

    def record_outcome(self, name: str, success: bool) -> None:
        if name in self._tools:
            t = self._tools[name]
            t.usage_count += 1
            if success:
                t.success_count += 1

            rate = t.success_count / max(1, t.usage_count)
            if t.usage_count >= 3 and rate >= 0.8:
                self._status[name] = "promoted"
            elif t.usage_count >= 5 and rate < 0.4:
                self._status[name] = "deprecated"

    def get_status(self, name: str) -> str:
        return self._status.get(name, "unknown")

    def get_tool(self, name: str) -> SynthesizedTool | None:
        return self._tools.get(name)


class MetaToolSynthesizer:
    """Compiles and self-certifies micro-tools in a constrained Python namespace."""

    def certify_tool(self, name: str, description: str, code_source: str, test_source: str) -> SynthesizedTool:
        tool = SynthesizedTool(
            name=name,
            description=description,
            code_source=code_source,
            test_source=test_source,
            gene_signature=f"gene_{name}"
        )

        try:
            # 1. Syntax check
            ast.parse(code_source)
            ast.parse(test_source)

            # 2. Execution environment
            local_scope: dict[str, Any] = {}
            exec(code_source, {"__builtins__": __builtins__}, local_scope)

            # Extract target function
            target_func = local_scope.get(name)
            if not callable(target_func):
                return tool

            # 3. Run inline self-certification test
            test_scope = {name: target_func, "__builtins__": __builtins__}
            exec(test_source, test_scope, test_scope)

            # Find and execute test functions
            test_funcs = [v for k, v in test_scope.items() if k.startswith("test_") and callable(v)]
            for tf in test_funcs:
                tf()

            # Certified!
            tool.certified = True
            tool.executable = target_func
            return tool

        except Exception:
            tool.certified = False
            tool.executable = None
            return tool
