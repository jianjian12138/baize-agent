"""MCP compatibility layer (part of ``baize.ext``).

This package is NEVER imported at the top level of core ``baize/`` modules.
The sanctioned entry points from the core runtime are
``baize.execution.tools.register_mcp_client`` and ``baize.interfaces.cli.cmd_mcp``,
which import this package *lazily* inside their function bodies.

Modules:
- ``transport``  — stdio JSON-RPC 2.0 + Content-Length framing + StdioTransport / MemoryTransport
- ``client``     — MCPClient (connect/handshake/list/call) + MCPServerSpec
- ``server``     — MCPServer (expose baize tools to external MCP clients)
- ``dispatcher`` — high-level MCP config loader, built-in read-only SQLite adapter, and tool dispatch
- ``component``  — CompositionKernel ToolProvider adapter
"""
from __future__ import annotations

from .client import (
    MCP_TEMPLATES,
    MCPClient,
    MCPServerSpec,
    McpTool,
    check_mcp_health,
    list_mcp_templates,
    render_mcp_template,
)
from .component import MCPComponent, MCPToolProvider
from .dispatcher import (
    DEFAULT_MCP_CONFIG,
    call_mcp_tool,
    list_all_mcp_tools,
    load_mcp_config,
    load_mcp_servers,
)
from .server import MCPServer
from .transport import JsonRpcError, MemoryTransport, StdioTransport, Transport

__all__ = [
    "MCPClient",
    "MCPServerSpec",
    "McpTool",
    "MCPServer",
    "JsonRpcError",
    "StdioTransport",
    "MemoryTransport",
    "Transport",
    "MCPComponent",
    "MCPToolProvider",
    "DEFAULT_MCP_CONFIG",
    "load_mcp_config",
    "load_mcp_servers",
    "list_all_mcp_tools",
    "call_mcp_tool",
    "MCP_TEMPLATES",
    "list_mcp_templates",
    "render_mcp_template",
    "check_mcp_health",
]
