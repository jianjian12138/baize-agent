"""MCP client — connect to an external MCP server and wrap its tools.

Part of ``baize.ext.mcp``; imported lazily by ``baize.execution.tools.register_mcp_client``
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
        """Wrap every discovered MCP tool as a :class:`baize.execution.tools.Tool` in the
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


# ===========================================================================
# V46.0.0 Sovereign: Zero-Secret Curated MCP Template Catalog & Health Check
# ===========================================================================

MCP_TEMPLATES: dict[str, dict] = {
    "filesystem": {
        "id": "filesystem",
        "name": "filesystem",
        "category": "workspace",
        "description": "Read/write local workspace files via @modelcontextprotocol/server-filesystem",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "${WORKSPACE_DIR}"],
        "env": {},
        "required_env": [],
        "required_binary": "npx",
        "install_hint": "Install Node.js 18+ (provides npx).",
    },
    "github": {
        "id": "github",
        "name": "github",
        "category": "vcs",
        "description": "Issues, PRs, branches, and repository search via @modelcontextprotocol/server-github",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"},
        "required_env": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        "required_binary": "npx",
        "install_hint": "Set GITHUB_PERSONAL_ACCESS_TOKEN in .env and install Node.js 18+.",
    },
    "postgres": {
        "id": "postgres",
        "name": "postgres",
        "category": "database",
        "description": "Read-only PostgreSQL schema inspection and SQL queries",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres", "${DATABASE_URL}"],
        "env": {"DATABASE_URL": "${DATABASE_URL}"},
        "required_env": ["DATABASE_URL"],
        "required_binary": "npx",
        "install_hint": "Set DATABASE_URL (postgres://...) and install Node.js 18+.",
    },
    "sqlite": {
        "id": "sqlite",
        "name": "sqlite",
        "category": "database",
        "description": "Local SQLite database inspection via uvx mcp-server-sqlite",
        "command": "uvx",
        "args": ["mcp-server-sqlite", "--db-path", "${SQLITE_DB_PATH}"],
        "env": {},
        "required_env": ["SQLITE_DB_PATH"],
        "required_binary": "uvx",
        "install_hint": "Install uv (provides uvx) and set SQLITE_DB_PATH.",
    },
    "figma": {
        "id": "figma",
        "name": "figma",
        "category": "design",
        "description": "Read Figma design tokens, frames, and component specs",
        "command": "npx",
        "args": ["-y", "figma-developer-mcp", "--stdio"],
        "env": {"FIGMA_API_KEY": "${FIGMA_API_KEY}"},
        "required_env": ["FIGMA_API_KEY"],
        "required_binary": "npx",
        "install_hint": "Set FIGMA_API_KEY in .env and install Node.js 18+.",
    },
    "browser-cdp": {
        "id": "browser-cdp",
        "name": "browser-cdp",
        "category": "browser",
        "description": "Playwright / Chrome DevTools MCP bridge for browser automation & screenshots",
        "command": "npx",
        "args": ["-y", "@playwright/mcp@latest"],
        "env": {},
        "required_env": [],
        "required_binary": "npx",
        "install_hint": "Install Node.js 18+ and Chrome/Chromium.",
    },
    "fetch": {
        "id": "fetch",
        "name": "fetch",
        "category": "web",
        "description": "Fetch web pages and convert HTML to clean markdown via uvx mcp-server-fetch",
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "env": {},
        "required_env": [],
        "required_binary": "uvx",
        "install_hint": "Install uv (provides uvx).",
    },
    "slack": {
        "id": "slack",
        "name": "slack",
        "category": "collaboration",
        "description": "Read/post Slack channels and threads via @modelcontextprotocol/server-slack",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "env": {"SLACK_BOT_TOKEN": "${SLACK_BOT_TOKEN}", "SLACK_TEAM_ID": "${SLACK_TEAM_ID}"},
        "required_env": ["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
        "required_binary": "npx",
        "install_hint": "Set SLACK_BOT_TOKEN and SLACK_TEAM_ID in .env and install Node.js 18+.",
    },
}


def list_mcp_templates() -> list[dict]:
    """Return metadata for all built-in zero-secret MCP server templates."""
    import shutil
    out: list[dict] = []
    for tid in sorted(MCP_TEMPLATES.keys()):
        tpl = dict(MCP_TEMPLATES[tid])
        binary = tpl.get("required_binary") or tpl.get("command") or ""
        tpl["binary_available"] = bool(shutil.which(binary)) if binary else True
        out.append(tpl)
    return out


def render_mcp_template(template_id: str, overrides: dict | None = None) -> dict:
    """Render an MCP server spec dict from a built-in template without persisting secrets."""
    key = template_id.strip().lower()
    if key not in MCP_TEMPLATES:
        available = ", ".join(sorted(MCP_TEMPLATES.keys()))
        raise KeyError(f"Unknown MCP template '{template_id}'. Available: {available}")
    tpl = MCP_TEMPLATES[key]
    ov = dict(overrides or {})

    def _subst(val: str) -> str:
        out = str(val)
        for k, v in ov.items():
            out = out.replace(f"${{{k}}}", str(v))
        return out

    args = [_subst(a) for a in tpl.get("args", [])]
    env = {k: _subst(v) for k, v in (tpl.get("env") or {}).items()}
    return {
        "name": str(ov.get("name") or tpl["name"]),
        "command": str(ov.get("command") or tpl["command"]),
        "args": args,
        "env": env,
        "protocol_version": "2024-11-05",
        "template_id": key,
        "required_env": list(tpl.get("required_env", [])),
    }


def check_mcp_health(
    specs: list[dict] | None = None,
    *,
    cfg: dict | None = None,
    live_probe: bool = False,
) -> dict:
    """Audit configured or template MCP servers for binary availability, required env vars, and optional stdio handshake."""
    import os as _os
    import shutil

    env_src = dict(_os.environ)
    if cfg:
        for k, v in cfg.items():
            if v:
                env_src[k] = str(v)

    targets: list[dict] = []
    if specs is not None:
        targets = list(specs)
    else:
        raw_cfg = (cfg or {}).get("BAIZE_MCP_SERVERS") or _os.environ.get("BAIZE_MCP_SERVERS", "")
        if str(raw_cfg).strip():
            try:
                parsed = json.loads(str(raw_cfg))
                if isinstance(parsed, list):
                    targets = [x for x in parsed if isinstance(x, dict)]
            except Exception:
                pass
        if not targets:
            # Default audit against built-in templates so users see environment readiness
            targets = [render_mcp_template(tid) for tid in sorted(MCP_TEMPLATES.keys())]

    results: list[dict] = []
    healthy = 0
    for sp in targets:
        name = str(sp.get("name") or sp.get("id") or "unnamed")
        cmd = str(sp.get("command") or "").strip()
        cmd_path = shutil.which(cmd) if cmd else None
        req_env = list(sp.get("required_env") or [])
        missing_env = []
        for var in req_env:
            spec_val = str((sp.get("env") or {}).get(var, ""))
            resolved = env_src.get(var, "")
            if (not resolved) and (not spec_val or spec_val.startswith("${")):
                missing_env.append(var)

        issues: list[str] = []
        if not cmd:
            issues.append("missing command")
        elif not cmd_path:
            issues.append(f"binary '{cmd}' not found on PATH")
        if missing_env:
            issues.append(f"missing env var(s): {', '.join(missing_env)}")

        probe_status = "skipped"
        if live_probe and not issues:
            try:
                spec_obj = MCPServerSpec(
                    name=name,
                    command=cmd_path or cmd,
                    args=list(sp.get("args") or []),
                    env={k: v for k, v in (sp.get("env") or {}).items() if not str(v).startswith("${")},
                )
                cli = MCPClient(spec_obj)
                try:
                    cli.connect()
                    tools = cli.list_tools()
                    probe_status = f"ok ({len(tools)} tools)"
                finally:
                    cli.close()
            except Exception as exc:
                probe_status = f"failed: {exc}"
                issues.append(f"handshake failed: {exc}")

        ok = len(issues) == 0
        if ok:
            healthy += 1
        tpl_meta = MCP_TEMPLATES.get(str(sp.get("template_id") or name), {})
        results.append({
            "name": name,
            "command": cmd,
            "binary_found": bool(cmd_path),
            "missing_env": missing_env,
            "ok": ok,
            "issues": issues,
            "live_probe": probe_status,
            "install_hint": tpl_meta.get("install_hint", ""),
        })

    return {
        "ok": healthy == len(results) and len(results) > 0,
        "total": len(results),
        "healthy": healthy,
        "unhealthy": len(results) - healthy,
        "servers": results,
    }
