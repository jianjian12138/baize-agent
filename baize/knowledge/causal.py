"""V30 AST-Level Causal Debugging & Mutation Fuzzing (Pure Python Standard Library).

Performs AST slicing of failing Python code and synthesizes adversarial mutation
tests to guarantee robust, anti-fragile fixes without hallucinated passes.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field


@dataclass
class CausalSlice:
    target_function: str
    line_range: tuple[int, int]
    culprit_variables: list[str]
    ast_node_type: str
    source_snippet: str


@dataclass
class MutationCase:
    name: str
    mutation_type: str  # null_pointer | boundary_overflow | type_mismatch | empty_container
    payload: dict
    description: str


@dataclass
class CausalProof:
    hypothesis: str
    target_function: str
    passed_mutation_tests: int
    total_mutation_tests: int
    proof_patch: str = ""

    @property
    def is_valid(self) -> bool:
        return self.total_mutation_tests > 0 and self.passed_mutation_tests == self.total_mutation_tests


class ASTCausalTracker:
    """Extracts function AST node and identifies culprit variables from errors."""

    def extract_slice(self, source_code: str, function_name: str, error_context: str = "") -> CausalSlice:
        tree = ast.parse(source_code)
        target_node = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
                target_node = node
                break

        if not target_node:
            return CausalSlice(
                target_function=function_name,
                line_range=(1, len(source_code.splitlines())),
                culprit_variables=[],
                ast_node_type="Unknown",
                source_snippet=source_code
            )

        # Collect function argument names
        param_names = [arg.arg for arg in target_node.args.args]

        # Scan error context for mentioned variable names
        culprits = []
        for p in param_names:
            if re.search(rf"\b{p}\b", error_context, re.IGNORECASE):
                culprits.append(p)
        if not culprits and param_names:
            culprits = param_names[:2]

        start_line = getattr(target_node, "lineno", 1)
        end_line = getattr(target_node, "end_lineno", start_line + len(target_node.body))

        lines = source_code.splitlines()
        snippet = "\n".join(lines[start_line - 1:end_line])

        return CausalSlice(
            target_function=function_name,
            line_range=(start_line, end_line),
            culprit_variables=culprits,
            ast_node_type="FunctionDef",
            source_snippet=snippet
        )


class MutationFuzzer:
    """Synthesizes adversarial edge-case mutations."""

    def generate_mutations(self, function_name: str, params: list[str]) -> list[MutationCase]:
        cases = []
        if not params:
            params = ["input_val"]

        # Case 1: Null Pointer / None injection
        cases.append(MutationCase(
            name=f"test_{function_name}_none_input",
            mutation_type="null_pointer",
            payload={p: None for p in params},
            description="Injects None into all function parameters to test null safety."
        ))

        # Case 2: Boundary Overflow / Negative / Extreme limit
        cases.append(MutationCase(
            name=f"test_{function_name}_boundary_overflow",
            mutation_type="boundary_overflow",
            payload={p: -999999 if "id" in p or "num" in p or "discount" in p else "A" * 5000 for p in params},
            description="Injects extreme boundary numbers and oversized strings."
        ))

        # Case 3: Empty Containers
        cases.append(MutationCase(
            name=f"test_{function_name}_empty_containers",
            mutation_type="empty_container",
            payload={p: [] if "items" in p or "list" in p else {} if "dict" in p else "" for p in params},
            description="Injects empty list/dict/string to test empty collection safety."
        ))

        # Case 4: Type Mismatch
        cases.append(MutationCase(
            name=f"test_{function_name}_type_mismatch",
            mutation_type="type_mismatch",
            payload={p: object() for p in params},
            description="Injects invalid object types to test defensive type validation."
        ))

        return cases
