"""F6 统一扩展总线收口 — MCP 作为可注册 Component (baize.ext.mcp).

This module is part of ``baize.ext`` and is reached through the composition bus,
NOT through a top-level core import (red line C). The canonical ways to wire an
ext module into the core runtime are:

  1. Explicit override (high trust, fail-closed)::
         BAIZE_COMPONENTS="baize.ext.mcp:MCPComponent"
     ``CompositionKernel._load_override`` imports this class by dotted path and
     calls ``build``. Build/type failure blocks startup (ComponentError).

  2. Auto-discovery (low trust) via ``plugin.discover()`` scanning
     ``baize/plugins/`` + ``BAIZE_PLUGINS_DIR``. Because TOOL is a
     security-critical kind, an auto-discovered MCPComponent is *rejected* by
     the kernel — only an explicit ``BAIZE_COMPONENTS`` override may augment the
     tool surface. This is the deliberate trust boundary (F1).

  3. The sanctioned exception: ``baize.tools.register_mcp_client`` imports this
     package lazily inside its function body.

``build`` lazily imports the core registry + ext client so importing
``baize.ext.mcp`` itself stays cheap, and any failure is surfaced fail-closed by
the kernel rather than crashing the host runtime.
"""
from __future__ import annotations

from typing import Any

from baize.component import Kind


class MCPToolProvider:
    """ToolProviderProto adapter over the default ``ToolRegistry``.

    Exposes the engine's built-in tools plus any MCP tools registered into the
    same registry. Returned by :class:`MCPComponent.build` so an MCP-backed tool
    surface still satisfies the kernel's ``Kind.TOOL`` Protocol check.
    """

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def schemas(self) -> list[dict]:
        return self._registry.schemas()

    def execute(self, name: str, arguments: dict) -> str:
        return self._registry.execute(name, arguments)


class MCPComponent:
    """Canonical example of an ext module participating in the composition bus.

    Registered explicitly via ``BAIZE_COMPONENTS="baize.ext.mcp:MCPComponent"``.
    Because TOOL is security-critical, an auto-discovered instance is rejected;
    only an explicit override may augment the tool surface.

    ``build`` is a ``staticmethod`` so the composition kernel can call it as
    ``build(cfg)`` (the kernel wraps ``cls.build`` without binding ``self``).
    The MCP server spec is taken from ``BAIZE_MCP_SPEC`` in config; the direct
    ``baize.tools.register_mcp_client(spec)`` path remains for ad-hoc wiring.
    """

    KIND = Kind.TOOL

    @staticmethod
    def build(cfg: dict | None = None) -> MCPToolProvider:
        # Lazy imports keep the ext->core direction clean and fail-closed.
        from baize.tools import default_registry, register_mcp_client

        registry = default_registry()
        cfg = cfg or {}
        spec_path = cfg.get("BAIZE_MCP_SPEC")
        if spec_path:
            # transport defaults to StdioTransport (real subprocess). Callers
            # who want in-process wiring pass transport explicitly.
            register_mcp_client(spec_path, registry=registry)
        return MCPToolProvider(registry)
