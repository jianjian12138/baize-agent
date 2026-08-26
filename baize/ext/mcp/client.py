"""MCP client — connect to an external MCP server and wrap its tools.

Part of ``baize.ext.mcp``; imported lazily by ``baize.tools.register_mcp_client``
(the single, deliberate exception to the static "no top-level import baize.ext"
gate). The core runtime never imports this module at import time, so the
zero-dependency red line (A) and the fail-closed red line (C) both hold:
if ``baize.ext.mcp`` is unavailable the registration simply fails closed.

Protocol: stdio JSON-RPC 2.0 (MCP 2024-11-05). We perform the `initialize`
handshake (protocolVersion negotiation + capabilities exchange) and then the
`notifications/initialized` signal before issuing any tool calls.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from .transport import JsonRpcError, Transport, StdioTransport, MemoryTransport

PROTOCOL_VERSION = "2024-11-05"
HANDSHAKE_TIMEOUT = 5.0  # seconds (design §3.5.4)
TOOL_CALL_TIMEOUT = 30.0  # seconds (design §3.5.4)


@dataclass
class MCPServerSpec:
    """Deserialized ``mcp_server.json`` (design §4.2.1)."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict = field(default_factory=dict)
    protocol_version: str = PROTOCOL_VERSION


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict


class MCPClient:
    """Lifecycle: ``from_spec`` -> ``connect`` -> ``list_tools`` ->
    ``register_into`` (or ``call_tool``)."""

    def __init__(self, spec: MCPServerSpec, transport: Transport | None = None,
                 _id: int = 1) -> None:
        self.spec = spec
        self._id = _id
        if transport is None:
            transport = StdioTransport(spec.command, spec.args, spec.env or None,
                                       timeout=HANDSHAKE_TIMEOUT)
        self.transport = transport
        self._tools: list[McpTool] = []

    @classmethod
    def from_spec_file(cls, path: str,
                       transport: Transport | None = None) -> "MCPClient":
        raw = json.loads(_read_text(path))
        spec = MCPServerSpec(
            name=raw["name"], command=raw["command"],
            args=raw.get("args", []), env=raw.get("env", {}),
            protocol_version=raw.get("protocol_version", PROTOCOL_VERSION))
        return cls(spec, transport=transport)

    # -- handshake --------------------------------------------------------
    def connect(self) -> "MCPClient":
        self.transport.send({
            "jsonrpc": "2.0", "id": self._id, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "baize",
                               "version": "25.0.0"},
            },
        })
        resp = self.transport.recv()
        if resp is None:
            self.transport.close()
            raise JsonRpcError("MCP initialize: no response from server")
        if "error" in resp:
            self.transport.close()
            raise JsonRpcError(f"MCP initialize failed: {resp['error']}")
        # Signal completion of the handshake (notification, no response).
        self.transport.send({
            "jsonrpc": "2.0", "method": "notifications/initialized",
            "params": {},
        })
        return self

    # -- tool discovery ---------------------------------------------------
    def list_tools(self) -> list[McpTool]:
        self._id += 1
        self.transport.send({
            "jsonrpc": "2.0", "id": self._id, "method": "tools/list",
            "params": {},
        })
        resp = self.transport.recv()
        if resp is None or "error" in resp:
            self.transport.close()
            raise JsonRpcError(f"MCP tools/list failed: {resp}")
        raw_tools = (resp.get("result") or {}).get("tools", [])
        self._tools = [
            McpTool(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema",
                                   {"type": "object", "properties": {}}),
            )
            for t in raw_tools
        ]
        return self._tools

    # -- tool execution ---------------------------------------------------
    def call_tool(self, name: str, arguments: dict) -> str:
        self._id += 1
        self.transport.send({
            "jsonrpc": "2.0", "id": self._id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        resp = self.transport.recv()
        if resp is None:
            raise JsonRpcError(f"MCP tools/call '{name}': no response")
        if "error" in resp:
            return f"ERROR: MCP tool '{name}' failed: {resp['error']}"
        result = resp.get("result") or {}
        if result.get("isError"):
            parts = [c.get("text", "") for c in result.get("content", [])
                     if c.get("type") == "text"]
            return "ERROR: " + "\n".join(parts)
        parts = [c.get("text", "") for c in result.get("content", [])
                 if c.get("type") == "text"]
        return "\n".join(parts)

    def register_into(self, registry, prefix: str | None = None) -> list[str]:
        """Wrap every discovered MCP tool as a :class:`baize.tools.Tool` in the
        given registry. Returns the registered tool names. Tool names are
        prefixed with ``{server_name}__`` to avoid colliding with built-ins."""
        if not self._tools:
            self.list_tools()
        pfx = prefix or f"{self.spec.name}__"
        registered: list[str] = []
        for tool in self._tools:
            full_name = f"{pfx}{tool.name}"
            # Closure binds the current tool name (not the loop variable).
            tool_name = tool.name

            def _fn(tool_name=tool_name, **arguments) -> str:
                return self.call_tool(tool_name, arguments)

            registry.register(full_name, tool.description or f"MCP tool {tool_name}",
                              tool.input_schema, _fn)
            registered.append(full_name)
        return registered

    def close(self) -> None:
        try:
            self.transport.close()
        except Exception:
            pass


def _read_text(path: str) -> str:
    from pathlib import Path
    return Path(path).read_text(encoding="utf-8")


# Backwards-friendly alias used by some docs/examples.
MCPClientResult = dict
