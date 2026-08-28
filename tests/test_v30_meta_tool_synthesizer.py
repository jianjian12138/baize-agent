"""Tests for V30 Darwinian Meta-Tool Synthesizer & Gene Evolution."""
import pytest
from baize.tooling.synthesizer import (
    SynthesizedTool, MetaToolSynthesizer, GeneStore
)


SAMPLE_TOOL_CODE = """
def clean_identifier(raw_name: str) -> str:
    import re
    return re.sub(r'[^a-zA-Z0-9_]', '_', raw_name.strip())
"""

SAMPLE_TEST_CODE = """
def test_clean():
    assert clean_identifier("hello-world 123!") == "hello_world_123_"
"""


def test_synthesizer_self_certification_pass():
    """Valid tool code with passing inline test succeeds self-certification."""
    synth = MetaToolSynthesizer()
    tool = synth.certify_tool(
        name="clean_identifier",
        description="Sanitizes identifiers with regex",
        code_source=SAMPLE_TOOL_CODE,
        test_source=SAMPLE_TEST_CODE
    )
    assert tool.certified is True
    assert callable(tool.executable)
    assert tool.executable("foo bar") == "foo_bar"


def test_synthesizer_self_certification_fail():
    """Broken tool code or failing test is rejected."""
    synth = MetaToolSynthesizer()
    broken_test = "def test_broken(): assert clean_identifier('a') == 'b'"
    tool = synth.certify_tool(
        name="clean_identifier_broken",
        description="Fails certification",
        code_source=SAMPLE_TOOL_CODE,
        test_source=broken_test
    )
    assert tool.certified is False
    assert tool.executable is None


def test_gene_store_evolution_promotion():
    """Tools with >=3 uses and >=0.8 success rate are promoted."""
    store = GeneStore()
    tool = SynthesizedTool(
        name="batch_trim",
        description="Trims lines",
        code_source="",
        test_source="",
        gene_signature="str_trim"
    )
    store.register(tool)

    store.record_outcome("batch_trim", success=True)
    store.record_outcome("batch_trim", success=True)
    store.record_outcome("batch_trim", success=True)

    status = store.get_status("batch_trim")
    assert status == "promoted"
