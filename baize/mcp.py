"""Anthropic Model Context Protocol (MCP) Standard Client & Dispatcher.

Pure Python standard library — zero third-party dependencies.
Routes configured MCP servers through the real JSON-RPC 2.0 stdio client
(``baize.ext.mcp.client.MCPClient``), and executes built-in local SQLite queries
against a real stdlib ``sqlite3`` connection (read-only) rather than returning
fabricated results.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import load_config

__all__ = [
    "MCPClient",
    "load_mcp_config",
    "load_mcp_servers",
    "list_all_mcp_tools",
    "call_mcp_tool",
]


def _load_mcp_client_cls():
    from .ext.mcp.client import MCPClient, MCPServerSpec
    return MCPClient, MCPServerSpec


class MCPClient:  # facade forwarding to baize.ext.mcp.client.MCPClient (zero top-level ext import)
    """Deferred facade over ``baize.ext.mcp.client.MCPClient``."""

    def __new__(cls, *args, **kwargs):
        real_cls, _ = _load_mcp_client_cls()
        return real_cls(*args, **kwargs)


# Standard default MCP servers configuration template
DEFAULT_MCP_CONFIG = {
    "mcpServers": {
        "sqlite": {
            "command": "python",
            "args": ["-m", "baize.ext.mcp_sqlite_server"],
            "description": "本地 SQLite 数据库查询与结构分析 MCP 适配器",
            "tools": [
                {"name": "sqlite_query", "description": "执行只读 SQL 查询", "inputSchema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}},
                {"name": "sqlite_schema", "description": "查看数据库表结构信息", "inputSchema": {"type": "object", "properties": {"table": {"type": "string"}}}},
            ],
        },
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "description": "GitHub 远程仓库 Issue、PR、Commit 交互 MCP 适配器",
            "tools": [
                {"name": "github_create_issue", "description": "创建 GitHub Issue", "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}}, "required": ["title"]}},
                {"name": "github_list_prs", "description": "获取当前仓库活跃 Pull Requests", "inputSchema": {"type": "object", "properties": {"state": {"type": "string"}}}},
            ],
        },
        "puppeteer": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
            "description": "无头浏览器网页抓取与控制 MCP 适配器",
            "tools": [
                {"name": "puppeteer_navigate", "description": "浏览器导航至指定 URL", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
                {"name": "puppeteer_screenshot", "description": "网页全屏截图与渲染", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}}},
            ],
        },
    }
}


def load_mcp_config(workspace_dir: str = ".") -> dict[str, Any]:
    """Search for mcp_config.json in workspace or fallback to default template."""
    root = Path(workspace_dir).resolve()
    for p in [root / "mcp_config.json", root / ".agents" / "mcp_config.json"]:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return DEFAULT_MCP_CONFIG


def load_mcp_servers(workspace_dir: str = ".") -> dict[str, dict[str, Any]]:
    """Return configured MCP server map from workspace config."""
    return dict(load_mcp_config(workspace_dir).get("mcpServers", {}))


def list_all_mcp_tools(workspace_dir: str = ".") -> list[dict[str, Any]]:
    """Retrieve all available tools from registered MCP servers."""
    servers = load_mcp_servers(workspace_dir)
    all_tools: list[dict[str, Any]] = []
    for server_name, s_info in servers.items():
        for t in s_info.get("tools", []):
            all_tools.append({
                "server": server_name,
                "name": t.get("name"),
                "description": f"[{server_name.upper()} MCP] {t.get('description', '')}",
                "inputSchema": t.get("inputSchema", {}),
                "is_mcp": True,
            })
    return all_tools


def _resolve_sqlite_db(workspace_dir: str, arguments: dict[str, Any]) -> str:
    root = Path(workspace_dir).resolve()
    db_arg = (arguments.get("db_path") or "").strip()
    if db_arg:
        cand = (root / db_arg).resolve() if not Path(db_arg).is_absolute() else Path(db_arg).resolve()
        if root not in cand.parents and cand != root:
            raise PermissionError(f"sqlite db_path {cand} is outside workspace {root}")
        return str(cand)
    for candidate in sorted(root.glob("*.db")) + sorted(root.glob("*.sqlite")):
        if candidate.is_file():
            return str(candidate)
    return ":memory:"


def _run_sqlite_readonly(tool_name: str, arguments: dict[str, Any], workspace_dir: str) -> dict[str, Any]:
    db_target = _resolve_sqlite_db(workspace_dir, arguments)
    if db_target == ":memory:":
        conn = sqlite3.connect(":memory:")
    else:
        uri = f"file:{db_target}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if tool_name == "sqlite_query":
            sql = str(arguments.get("sql") or "SELECT 1").strip()
            head = sql.lstrip("(").split(None, 1)[0].upper() if sql else ""
            if head not in ("SELECT", "PRAGMA", "EXPLAIN", "WITH"):
                return {
                    "status": "error",
                    "server": "sqlite",
                    "tool": tool_name,
                    "error": f"only read-only SQL statements (SELECT/PRAGMA/EXPLAIN/WITH) are permitted, got {head!r}",
                    "protocol": "mcp/json-rpc-2.0",
                }
            cur = conn.execute(sql)
            rows = [dict(r) for r in cur.fetchmany(200)]
            return {
                "status": "success",
                "server": "sqlite",
                "tool": tool_name,
                "db": db_target,
                "result": rows,
                "protocol": "mcp/json-rpc-2.0",
            }
        # sqlite_schema
        table = str(arguments.get("table") or "").strip()
        if table:
            if not table.replace("_", "").isalnum():
                return {"status": "error", "server": "sqlite", "tool": tool_name, "error": "invalid table identifier"}
            cur = conn.execute(f"PRAGMA table_info({table})")
            cols = [dict(r) for r in cur.fetchall()]
            return {
                "status": "success",
                "server": "sqlite",
                "tool": tool_name,
                "db": db_target,
                "result": {"table": table, "columns": cols},
                "protocol": "mcp/json-rpc-2.0",
            }
        cur = conn.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")
        return {
            "status": "success",
            "server": "sqlite",
            "tool": tool_name,
            "db": db_target,
            "result": {"tables": [dict(r) for r in cur.fetchall()]},
            "protocol": "mcp/json-rpc-2.0",
        }
    finally:
        conn.close()


def call_mcp_tool(server_name: str, tool_name: str, arguments: dict[str, Any], workspace_dir: str = ".") -> dict[str, Any]:
    """Invoke an MCP tool over real stdio JSON-RPC 2.0 or built-in read-only sqlite3."""
    servers = load_mcp_servers(workspace_dir)
    if server_name not in servers:
        return {
            "error": f"MCP server '{server_name}' not registered in mcp_config.json",
            "status": "failed",
        }

    # Built-in read-only SQLite tool (real sqlite3 execution, no fake rows)
    if server_name == "sqlite" and tool_name in ("sqlite_query", "sqlite_schema"):
        try:
            return _run_sqlite_readonly(tool_name, arguments or {}, workspace_dir)
        except Exception as exc:
            return {
                "status": "error",
                "server": server_name,
                "tool": tool_name,
                "error": str(exc),
                "protocol": "mcp/json-rpc-2.0",
            }

    # External MCP server: require explicit opt-in via BAIZE_MCP_ENABLED=1 or custom mcp_config.json
    cfg = load_config()
    has_custom_cfg = any(
        (Path(workspace_dir).resolve() / rel).exists()
        for rel in ("mcp_config.json", ".agents/mcp_config.json")
    )
    if cfg.get("BAIZE_MCP_ENABLED", "0") != "1" and not has_custom_cfg:
        return {
            "status": "unavailable",
            "server": server_name,
            "tool": tool_name,
            "error": (
                f"external MCP server '{server_name}' is not enabled; set BAIZE_MCP_ENABLED=1 "
                "and configure mcp_config.json to execute real JSON-RPC 2.0 stdio calls"
            ),
            "protocol": "mcp/json-rpc-2.0",
        }

    server_cfg = servers[server_name]
    cmd = server_cfg.get("command")
    if not cmd:
        return {"status": "failed", "error": f"MCP server '{server_name}' missing command"}

    try:
        real_cls, spec_cls = _load_mcp_client_cls()
        spec = spec_cls(
            name=server_name,
            command=str(cmd),
            args=[str(a) for a in server_cfg.get("args", [])],
            env={str(k): str(v) for k, v in (server_cfg.get("env") or {}).items()},
        )
        client = real_cls(spec)
        try:
            client.connect()
            out = client.call_tool(tool_name, arguments or {})
        finally:
            try:
                client.close()
            except Exception:
                pass
        return {
            "status": "success",
            "server": server_name,
            "tool": tool_name,
            "result": out,
            "protocol": "mcp/json-rpc-2.0",
        }
    except Exception as exc:
        return {
            "status": "error",
            "server": server_name,
            "tool": tool_name,
            "error": f"MCP stdio invocation failed: {exc}",
            "protocol": "mcp/json-rpc-2.0",
        }
