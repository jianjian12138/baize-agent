"""W2 F3 — MCP transport / client / server unit tests (pure stdlib, in-memory).

The "real" MCP server is simulated by an in-process handler driven through
``MemoryTransport`` (the W2 "server 暂 mock" path). No subprocess, fully
deterministic, and exercises the real framing, handshake, tool discovery,
registration and execution code paths.
"""
from __future__ import annotations

import io
import json

import pytest

# F7 guard: ext tests must skip (not error) if the ext module is unavailable.
# Our ext modules are pure stdlib so this never skips in practice, but the
# guard is the contract that keeps the 422 baseline stable under env variance.
pytest.importorskip("baize.ext.mcp")

from baize.ext.mcp.client import MCPClient, MCPServerSpec
from baize.ext.mcp.server import MCPServer
from baize.ext.mcp.transport import MemoryTransport
from baize.tools import ToolRegistry, register_mcp_client


def _fake_server(message: dict) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1.0"}}}
    if method == "notifications/initialized":
        return None  # notification: no response
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [
            {"name": "echo", "description": "echo a message",
             "inputSchema": {"type": "object",
                             "properties": {"text": {"type": "string"}},
                             "required": ["text"]}}]}}
    if method == "tools/call":
        params = message.get("params", {})
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "content": [{"type": "text", "text": "echoed:"
                         + str(params.get("arguments", {}).get("text", ""))}],
            "isError": False}}
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def test_client_handshake_and_register():
    client = MCPClient(MCPServerSpec(name="fake", command="x"),
                       transport=MemoryTransport(_fake_server))
    client.connect()
    tools = client.list_tools()
    assert [t.name for t in tools] == ["echo"]
    reg = ToolRegistry()
    names = client.register_into(reg)
    assert names == ["fake__echo"]
    # Executing the wrapped MCP tool goes through call_tool -> fake server.
    assert reg.execute("fake__echo", {"text": "hi"}) == "echoed:hi"


def test_register_mcp_client_from_spec_file(tmp_path):
    spec_file = tmp_path / "mcp_server.json"
    spec_file.write_text(json.dumps(
        {"name": "fake", "command": "x", "args": [], "env": {}}),
        encoding="utf-8")
    reg = ToolRegistry()
    names = register_mcp_client(str(spec_file), registry=reg,
                                transport=MemoryTransport(_fake_server))
    assert names == ["fake__echo"]
    assert reg.execute("fake__echo", {"text": "z"}) == "echoed:z"


def test_register_mcp_client_missing_file():
    with pytest.raises(FileNotFoundError):
        register_mcp_client("/no/such/file.json")


def test_client_handshake_error_propagates():
    def bad_server(message):
        if message.get("method") == "initialize":
            return {"jsonrpc": "2.0", "id": message.get("id"),
                    "error": {"code": -32000, "message": "refused"}}
        return None
    client = MCPClient(MCPServerSpec(name="b", command="x"),
                       transport=MemoryTransport(bad_server))
    with pytest.raises(Exception):
        client.connect()


def test_server_handle_protocol():
    reg = ToolRegistry()
    reg.register("add", "add two ints",
                 {"type": "object",
                  "properties": {"a": {"type": "integer"},
                                 "b": {"type": "integer"}}},
                 lambda a, b: str(int(a) + int(b)))
    server = MCPServer(reg)

    init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {}})
    assert init["result"]["serverInfo"]["name"] == "baize"
    # notification yields no response
    assert server.handle({"jsonrpc": "2.0",
                          "method": "notifications/initialized"}) is None
    lst = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert lst["result"]["tools"][0]["name"] == "add"
    call = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                          "params": {"name": "add", "arguments": {"a": 2, "b": 3}}})
    assert call["result"]["content"][0]["text"] == "5"
    assert call["result"]["isError"] is False
    # unknown method -> JSON-RPC error (fail closed)
    unknown = server.handle({"jsonrpc": "2.0", "id": 4, "method": "bogus"})
    assert unknown["error"]["code"] == -32601
    # missing tool -> execute raises -> isError True (never crash the loop)
    err = server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                         "params": {"name": "nope", "arguments": {}}})
    assert err["result"]["isError"] is True


def test_server_framing_roundtrip():
    reg = ToolRegistry()
    reg.register("ping", "ping", {"type": "object", "properties": {}},
                 lambda: "pong")
    server = MCPServer(reg)
    out = io.BytesIO()
    server._write_frame(out, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    out.seek(0)
    msg, leftover = server._read_frame(out, bytearray())
    assert msg["method"] == "tools/list"
    assert leftover == bytearray()


def test_server_serve_stdio_loop():
    reg = ToolRegistry()
    reg.register("ping", "ping", {"type": "object", "properties": {}},
                 lambda: "pong")
    server = MCPServer(reg)
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
                         ).encode("utf-8")
    inp = io.BytesIO(b"Content-Length: " + str(len(payload)).encode()
                     + b"\r\n\r\n" + payload)
    out = io.BytesIO()
    server.serve_stdio(stdin=inp, stdout=out)
    out.seek(0)
    msg, _ = server._read_frame(out, bytearray())
    assert msg["result"]["tools"][0]["name"] == "ping"
