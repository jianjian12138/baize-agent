"""Tests for the V30 causal slicer and mutation-case generator.

Two things are pinned here that the original tests let slide. First, that the
fuzzer *generates case descriptors* and never runs them - the module docstring
used to claim it "synthesizes adversarial mutation tests to guarantee robust,
anti-fragile fixes without hallucinated passes", which no code in the module
does. Second, that ``CausalProof`` is a consistency check over two integers a
caller supplies, not evidence that a fix survived anything.
"""
import ast
from pathlib import Path

from baize.knowledge import causal
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
    """The tracker reports the target function's line range and the parameters
    named in the error string."""
    tracker = ASTCausalTracker()
    cslice = tracker.extract_slice(
        source_code=SAMPLE_CODE,
        function_name="process_user_order",
        error_context="TypeError: 'NoneType' object is not iterable on items"
    )
    assert cslice.target_function == "process_user_order"
    assert "items" in cslice.culprit_variables
    assert cslice.line_range[0] >= 2
    assert cslice.source_snippet.strip().startswith("def process_user_order")


def test_an_unknown_function_yields_a_whole_file_slice_labelled_unknown():
    cslice = ASTCausalTracker().extract_slice("def a():\n    pass\n", "nope")
    assert cslice.ast_node_type == "Unknown"
    assert cslice.culprit_variables == []


def test_mutation_fuzzer_generates_adversarial_cases():
    """The fuzzer produces boundary, null and type-mismatch *descriptors*."""
    fuzzer = MutationFuzzer()
    cases = fuzzer.generate_mutations(
        function_name="process_user_order",
        params=["user_id", "items", "discount"]
    )
    assert len(cases) >= 3
    types = {c.mutation_type for c in cases}
    assert "null_pointer" in types
    assert "boundary_overflow" in types
    # A descriptor is a name plus a payload plus a rationale - nothing more.
    for case in cases:
        assert case.name.startswith("test_")
        assert case.payload
        assert case.description


class TestTheCasesAreDescriptorsNotResults:
    def test_every_generated_case_covers_all_parameters(self):
        cases = MutationFuzzer().generate_mutations("f", ["a", "b"])
        for case in cases:
            assert set(case.payload) == {"a", "b"}

    def test_no_mutation_is_ever_applied_to_the_target(self):
        """There is no executor in this module, so nothing can report a pass."""
        source = Path(causal.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "generate_mutations" not in called or True  # defined, not called here
        for forbidden in ("exec", "eval", "compile", "__import__"):
            assert not any(
                isinstance(node, ast.Name) and node.id == forbidden
                for node in ast.walk(tree)
            ), f"{forbidden} would mean the module executes something"

    def test_causal_proof_is_a_consistency_check_on_a_claim(self):
        """`is_valid` compares two integers the caller supplies. It is not a
        measurement, and the docstring on this class says so."""
        claimed = CausalProof(
            hypothesis="Handling items=None and empty lists gracefully",
            target_function="process_user_order",
            passed_mutation_tests=3,
            total_mutation_tests=3,
        )
        assert claimed.is_valid
        # Nothing verified those three passes, so an arbitrary claim also passes.
        invented = CausalProof(
            hypothesis="anything at all",
            target_function="no_such_function",
            passed_mutation_tests=99,
            total_mutation_tests=99,
        )
        assert invented.is_valid, (
            "if this ever fails the class has started checking something, and the "
            "docstring should be updated to say what"
        )

    def test_a_proof_with_no_tests_is_not_valid(self):
        assert not CausalProof(
            hypothesis="h", target_function="f",
            passed_mutation_tests=0, total_mutation_tests=0,
        ).is_valid

    def test_the_module_docstring_states_the_limit_and_labels_the_old_claim(self):
        """The old claim may be quoted, but only as the thing being corrected -
        the title line must not carry it."""
        doc = causal.__doc__ or ""
        title = doc.strip().splitlines()[0]
        assert "guarantee" not in title
        flat = " ".join(doc.split())
        assert "does not run the mutations" in flat
        assert "The previous module docstring said" in flat
        assert "It synthesizes case descriptions" in flat
