"""V30 Darwinian Meta-Tool Synthesizer & Gene Evolution (Pure Python Stdlib).

Enables agents to synthesize, inline-test, certify, and evolve pure Python
micro-tools dynamically at runtime.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Callable

from ..safe_exec import exec_restricted


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
    """Compiles and self-certifies micro-tools in a restricted-builtin namespace.

    "Restricted" means the obvious escapes are gone (no open, no __import__, no
    eval/exec), not that the code is sandboxed. Callers are responsible for
    authorising the request before handing code here - see
    baize/serve.py::_code_exec_gate.
    """

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

            # 2. Execution environment.
            # Restricted builtins only - see baize/safe_exec for what this does and
            # does not buy. This used to pass full __builtins__, which made the
            # docstring's "constrained namespace" claim false: the synthesised
            # code could import os and touch the filesystem.
            local_scope = exec_restricted(code_source)

            # Extract target function
            target_func = local_scope.get(name)
            if not callable(target_func):
                return tool

            # 3. Run inline self-certification test
            test_scope = exec_restricted(test_source, seed={name: target_func})

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
