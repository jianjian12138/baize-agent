"""MCP compatibility layer (part of ``baize.ext``).

This package is NEVER imported at the top level of core ``baize/`` modules.
The one and only sanctioned entry point from the core runtime is
``baize.tools.register_mcp_client``, which imports this package *lazily* inside
its function body. That keeps the zero-dependency red line (A) intact and lets
the package fail closed if its (pure-stdlib) transport is unusable.

Modules:
- ``transport`` — stdio JSON-RPC 2.0 + Content-Length framing + StdioTransport / MemoryTransport
- ``client``    — MCPClient (connect/handshake/list/call) + MCPServerSpec
- ``server``    — MCPServer (expose baize tools to external MCP clients)
"""
from __future__ import annotations

from .client import MCPClient, MCPServerSpec, McpTool
from .server import MCPServer
from .transport import JsonRpcError, StdioTransport, MemoryTransport, Transport
from .component import MCPComponent, MCPToolProvider

__all__ = [
    "MCPClient", "MCPServerSpec", "McpTool", "MCPServer",
    "JsonRpcError", "StdioTransport", "MemoryTransport", "Transport",
    "MCPComponent", "MCPToolProvider",
]
