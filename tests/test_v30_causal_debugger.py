"""Tests for V30 AST-level Causal Debugger & Mutation Fuzzing."""
import pytest
from baize.knowledge.causal import (
    ASTCausalTracker, MutationFuzzer, CausalProof
)


SAMPLE_CODE = """
def process_user_order(user_id, items, discount=0.0):
    total = sum(item['price'] * item['qty'] for item in items)
    if discount > 0:
        total = total * (1.0 - discount)
    return total
"""


def test_ast_causal_slice_extraction():
    """Tracker accurately slices target function AST and identifies culprit parameter variables."""
    tracker = ASTCausalTracker()
    cslice = tracker.extract_slice(
        source_code=SAMPLE_CODE,
        function_name="process_user_order",
        error_context="TypeError: 'NoneType' object is not iterable on items"
    )
    assert cslice.target_function == "process_user_order"
    assert "items" in cslice.culprit_variables
    assert cslice.line_range[0] >= 2


def test_mutation_fuzzer_generates_adversarial_cases():
    """Fuzzer creates boundary, null, and type mismatch tests."""
    fuzzer = MutationFuzzer()
    cases = fuzzer.generate_mutations(
        function_name="process_user_order",
        params=["user_id", "items", "discount"]
    )
    assert len(cases) >= 3
    types = {c.mutation_type for c in cases}
    assert "null_pointer" in types
    assert "boundary_overflow" in types


def test_causal_proof_validation():
    """CausalProof verifies that fix withstands adversarial mutation cases."""
    proof = CausalProof(
        hypothesis="Handling items=None and empty lists gracefully",
        target_function="process_user_order",
        passed_mutation_tests=3,
        total_mutation_tests=3
    )
    assert proof.is_valid
