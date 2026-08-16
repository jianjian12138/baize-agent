"""Tests for baize.mcp — pure-stdlib MCP client (fail-closed).

A real child-process MCP server (tests/mock_mcp_server.py) is spawned so the
JSON-RPC handshake and tools/list + tools/call are exercised end to end, not
mocked away.
"""
import ast
import json
import sys
from pathlib import Path

import pytest

from baize.mcp import (
    MCPClient,
    MCPError,
    _parse_servers,
    connect_mcp_servers,
)
from baize.tools import ToolRegistry

MOCK = str(Path(__file__).resolve().parent / "mock_mcp_server.py")
PY = sys.executable


# ---------------------------------------------------------------------------
# Criterion ⑤: zero third-party dependency
# ---------------------------------------------------------------------------
def test_mcp_module_is_stdlib_only():
    src = Path(__file__).resolve().parent.parent / "baize" / "mcp.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    forbidden = {"mcp", "httpx", "requests", "aiohttp"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in forbidden, f"forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in forbidden, f"forbidden import from: {node.module}"


# ---------------------------------------------------------------------------
# Criterion ②: real tools/list + tools/call round-trip
# ---------------------------------------------------------------------------
def test_handshake_and_list_tools():
    client = MCPClient(name="mock", timeout=15).start([PY, MOCK])
    try:
        tools = client.list_tools()
        names = {t["name"] for t in tools}
        assert {"echo", "add"} <= names
        echo = next(t for t in tools if t["name"] == "echo")
        assert echo["inputSchema"]["required"] == ["message"]
    finally:
        client.stop()


def test_call_tool_echo_and_add():
    client = MCPClient(name="mock", timeout=15).start([PY, MOCK])
    try:
        assert client.call_tool("echo", {"message": "hello"}) == "echo: hello"
        assert client.call_tool("add", {"a": 2, "b": 3}) == "5"
    finally:
        client.stop()


def test_call_tool_is_error_returns_error_string():
    client = MCPClient(name="mock", timeout=15).start([PY, MOCK])
    try:
        out = client.call_tool("nope", {})
        assert out.startswith("ERROR:")
        assert ("isError" in out) or ("unknown tool" in out)
    finally:
        client.stop()


# ---------------------------------------------------------------------------
# Criterion ④: register into ToolRegistry and reachable via execute()
# ---------------------------------------------------------------------------
def test_register_tools_into_registry_and_execute():
    reg = ToolRegistry()
    client = MCPClient(name="mock", timeout=15).start([PY, MOCK])
    try:
        registered = client.register_tools(reg, server_name="mock")
        assert "mcp__mock__echo" in registered
        assert "mcp__mock__add" in registered
        assert "mcp__mock__echo" in reg.names()
        out = reg.execute("mcp__mock__echo", {"message": "hi"})
        assert out == "echo: hi"
        assert reg.execute("mcp__mock__add", {"a": 10, "b": 5}) == "15"
    finally:
        client.stop()


# ---------------------------------------------------------------------------
# Criterion ③: server crash -> ERROR observation, never an Agent crash
# ---------------------------------------------------------------------------
def test_server_crash_yields_error_observation():
    # The registered callable must swallow MCPError and return an ERROR string
    # rather than propagating an exception to the Agent loop.
    client = MCPClient(name="mock", timeout=15).start(
        [PY, MOCK, "--die-on-call"])
    try:
        reg = ToolRegistry()
        client.register_tools(reg, server_name="mock")
        out = reg.execute("mcp__mock__echo", {"message": "x"})
        assert out.startswith("ERROR:")
        assert "MCP tool 'echo' failed" in out
    finally:
        client.stop()


def test_call_tool_after_server_dies_raises_mcp_error():
    client = MCPClient(name="mock", timeout=15).start(
        [PY, MOCK, "--die-on-call"])
    # Force the process dead, then a direct call_tool must fail-closed.
    client._proc.terminate()
    client._proc.wait(timeout=5)
    with pytest.raises(MCPError):
        client.call_tool("echo", {"message": "x"})


# ---------------------------------------------------------------------------
# Criterion ①/③ extras: fail-closed transport edges
# ---------------------------------------------------------------------------
def test_non_stdio_transport_is_reserved():
    with pytest.raises(NotImplementedError):
        MCPClient(name="x", transport="http").start([PY, MOCK])


def test_bad_command_fail_closed():
    with pytest.raises(MCPError):
        MCPClient(name="bad", timeout=5).start(
            ["this_command_does_not_exist_xyz_12345"])


def test_hung_server_times_out():
    # A server that answers initialize but then hangs must time out on
    # tools/list (not hang the Agent forever).
    client = MCPClient(name="hung", timeout=1.0).start(
        [PY, MOCK, "--hang-after-init"])
    try:
        with pytest.raises(MCPError):
            client.list_tools()
    finally:
        client.stop()


def test_stderr_is_captured():
    # Server that prints to stderr at startup — capture must not deadlock.
    client = MCPClient(name="err", timeout=10).start(
        [PY, MOCK, "--stderr", "boom log"])
    try:
        client._request("tools/list", {})  # exercises stderr drain path
        assert any("boom log" in s for s in client._stderr_buf)
    finally:
        client.stop()


def test_malformed_server_line_is_skipped():
    # Server emits a garbage line first, then answers valid protocol.
    client = MCPClient(name="garb", timeout=10).start(
        [PY, MOCK, "--garbage-first"])
    try:
        res = client._request("tools/list", {})
        # valid response parsed despite the leading garbage line
        assert "tools" in res
    finally:
        client.stop()


# ---------------------------------------------------------------------------
# Criterion ⑤: opt-in, default OFF, explicit whitelist
# ---------------------------------------------------------------------------
def test_connect_disabled_by_default(monkeypatch):
    monkeypatch.setenv("BAIZE_MCP_ENABLED", "0")
    reg = ToolRegistry()
    assert connect_mcp_servers(reg) == []


def test_connect_invalid_whitelist_is_safe(monkeypatch):
    monkeypatch.setenv("BAIZE_MCP_ENABLED", "1")
    monkeypatch.setenv("BAIZE_MCP_SERVERS", "this is not json")
    reg = ToolRegistry()
    assert connect_mcp_servers(reg) == []


def test_connect_real_whitelist(monkeypatch):
    spec = json.dumps([{
        "name": "demo", "command": PY, "args": [MOCK],
        "transport": "stdio", "timeout": 15}])
    monkeypatch.setenv("BAIZE_MCP_ENABLED", "1")
    monkeypatch.setenv("BAIZE_MCP_SERVERS", spec)
    reg = ToolRegistry()
    clients = connect_mcp_servers(reg)
    try:
        assert len(clients) == 1
        assert "mcp__demo__echo" in reg.names()
        assert reg.execute("mcp__demo__echo", {"message": "ok"}) == "echo: ok"
    finally:
        for c in clients:
            c.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def test_parse_servers_tolerates_bad_input():
    assert _parse_servers("") == []
    assert _parse_servers("   ") == []
    assert _parse_servers("not json") == []
    assert _parse_servers(json.dumps({"a": 1})) == []  # not a list
    out = _parse_servers(json.dumps([
        {"name": "a", "command": "x"}, {"no_command": 1}, {"name": "b", "command": "y"}]))
    assert [s["name"] for s in out] == ["a", "b"]


# ---------------------------------------------------------------------------
# Honest branch coverage for defensive / edge paths
# ---------------------------------------------------------------------------
def test_stop_when_never_started_is_safe():
    # stop() on an unstarted client must be a no-op (no AttributeError).
    MCPClient(name="idle").stop()


def test_call_tool_without_start_fail_closed():
    # No process -> _ensure_alive must raise MCPError, not crash.
    with pytest.raises(MCPError):
        MCPClient(name="idle").call_tool("echo", {"message": "x"})


def test_spawn_oserror_is_fail_closed(monkeypatch):
    import subprocess
    def _boom(*a, **k):
        raise OSError("no such program")
    monkeypatch.setattr(subprocess, "Popen", _boom)
    with pytest.raises(MCPError):
        MCPClient(name="boom", timeout=5).start([PY, MOCK])


def test_non_text_content_block_is_formatted():
    # A tool returning an image block (not just text) must be surfaced.
    client = MCPClient(name="img", timeout=15).start(
        [PY, MOCK, "--image-result"])
    try:
        out = client.call_tool("echo", {"message": "hi"})
        assert out.startswith("echo: hi")
        assert "[image]" in out
    finally:
        client.stop()


def test_tools_list_skips_entries_without_name():
    client = MCPClient(name="miss", timeout=15).start(
        [PY, MOCK, "--missing-name"])
    try:
        tools = client.list_tools()
        # server returned the nameless entry; list_tools passes it through
        assert len(tools) == 3
        # register_tools is what skips entries without a name (fail-closed)
        reg = ToolRegistry()
        registered = client.register_tools(reg, server_name="miss")
        assert "mcp__miss__echo" in registered
        assert "mcp__miss__add" in registered
        assert not any(n.endswith("__") for n in reg.names())  # none nameless
    finally:
        client.stop()


def test_connect_skips_failing_server(monkeypatch, capsys):
    spec = json.dumps([
        {"name": "bad", "command": "this_command_does_not_exist_xyz"},
        {"name": "good", "command": PY, "args": [MOCK]},
    ])
    monkeypatch.setenv("BAIZE_MCP_ENABLED", "1")
    monkeypatch.setenv("BAIZE_MCP_SERVERS", spec)
    reg = ToolRegistry()
    clients = connect_mcp_servers(reg)
    try:
        # the good server connected; the bad one was skipped (fail-closed boot)
        assert len(clients) == 1
        assert "mcp__good__echo" in reg.names()
        captured = capsys.readouterr()
        assert "skipping server 'bad'" in captured.err
    finally:
        for c in clients:
            c.stop()
