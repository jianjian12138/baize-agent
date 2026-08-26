"""W3 F6 — unified extension bus收口 (red line C: ext fail-closed).

Proves that an ext module (MCP) participates in the composition bus through the
sanctioned paths, and that the security-critical trust boundary holds:

  * Explicit override via ``BAIZE_COMPONENTS="baize.ext.mcp:MCPComponent"``
    is loaded fail-closed (build/type failure -> ComponentError).
  * An auto-discovered TOOL component is REJECTED by the kernel — only an
    explicit override may augment the security-critical tool surface.
  * ``baize.tools.register_mcp_client`` remains the only sanctioned core-side
    ext hook (verified indirectly by the static grep gate, test_grep_gate.py).
"""
from __future__ import annotations

import pytest

pytest.importorskip("baize.ext.mcp")

from baize.component import Component, CompositionKernel, Kind, ToolProviderProto
from baize.ext.mcp import MCPComponent, MCPToolProvider
from baize.tools import default_registry, register_mcp_client


def test_mcp_component_is_tool_kind():
    assert MCPComponent.KIND == Kind.TOOL


def test_mcp_component_build_satisfies_tool_provider_proto():
    provider = MCPComponent().build({})
    assert isinstance(provider, MCPToolProvider)
    # ToolProviderProto: schemas() -> list[dict], execute(name, args) -> str
    assert isinstance(provider, ToolProviderProto)
    assert isinstance(provider.schemas(), list)


def test_explicit_override_loads_mcp_component_fail_closed():
    kernel = CompositionKernel()
    comp = kernel._load_override("baize.ext.mcp:MCPComponent")
    assert comp is not None
    assert comp.explicit is True
    assert comp.kind == Kind.TOOL
    assert comp.name == "baize.ext.mcp:MCPComponent"
    # build yields a ToolProviderProto-satisfying object
    assert isinstance(comp.build({}), ToolProviderProto)


def test_explicit_override_malformed_token_is_fail_closed():
    kernel = CompositionKernel()
    with pytest.raises(Exception):  # ComponentError (explicit => fail closed)
        kernel._load_override("baize.ext.mcp:DoesNotExist")


def test_auto_discovered_tool_component_is_rejected():
    # TOOL is security-critical: an auto-discovered (explicit=False) MCP-like
    # component must NOT replace the trusted built-in default-tools.
    kernel = CompositionKernel()
    assert kernel.components[Kind.TOOL].name == "default-tools"
    auto = Component(
        Kind.TOOL, "auto-mcp",
        lambda c: MCPToolProvider(default_registry()),
        provides=["tool"], explicit=False)
    kernel.add_component(auto)
    # add_component rejected the security-critical kind -> default retained
    assert kernel.components[Kind.TOOL].name == "default-tools"


def test_register_mcp_client_remains_core_side_hook():
    # The sanctioned exception: core-side ext access flows only through this.
    assert callable(register_mcp_client)
