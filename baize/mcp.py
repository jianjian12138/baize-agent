"""MCP (Model Context Protocol) client — pure stdlib, fail-closed.

This is the *client* side only, over the **stdio** transport. It speaks
JSON-RPC 2.0 over newline-delimited JSON (NDJSON) with a child process:

    initialize -> notifications/initialized -> tools/list -> tools/call

No third-party SDK is used (``import mcp`` is forbidden by the zero-dependency
discipline). HTTP/SSE transports are intentionally left as a reserved
interface and raise ``NotImplementedError`` if requested.

Hard trust boundary (expert-review risk #1): an MCP server is untrusted code
that runs as a child process. The client therefore:
  * captures the server's stderr in a drain thread (never deadlocks),
  * turns a dead/crashed server into an ``ERROR`` observation, never an
    Agent crash,
  * enforces a per-call timeout (fail-closed: a hung server yields ERROR),
  * is opt-in via ``BAIZE_MCP_ENABLED`` with an explicit server whitelist
    (``BAIZE_MCP_SERVERS``) — default is OFF and the whitelist is empty.

The discovered tools are registered into a ``ToolRegistry`` under the prefix
``mcp__<server>__<tool>`` so the Agent/Orchestrator can call them exactly like
built-ins.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from .config import load_config
from .tools import ToolRegistry


class MCPError(Exception):
    """Raised on protocol/handshake/transport failure (fail-closed surface)."""


# Protocol versions the client is willing to speak. We advertise the newest;
# the server echoes back the version it selected in `initialize`.
_PROTOCOL_VERSION = "2025-03-26"


class MCPClient:
    """A single MCP server connection over stdio (one server == one process)."""

    def __init__(self, name: str = "default", transport: str = "stdio",
                 timeout: float = 30.0):
        if transport != "stdio":
            raise NotImplementedError(
                f"MCP transport '{transport}' is reserved (only 'stdio' "
                "is implemented; http/sse require an optional adapter layer)")
        self.name = name
        self.transport = transport
        self.timeout = float(timeout)
        self._proc: subprocess.Popen | None = None
        self._next_id = 1
        self._queue: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_buf: list[str] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start(self, command, args=None) -> "MCPClient":
        """Spawn the server subprocess and complete the initialize handshake.

        ``command`` is a string (shell) or a list. ``args`` are appended.
        On any handshake failure the child is stopped and the error re-raised.
        """
        if isinstance(command, (list, tuple)):
            cmd = list(command)
        else:
            cmd = [command]
        if args:
            cmd.extend(args)

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                # Restricted-ish environment: we forward a copy of the current
                # env. True OS-level sandboxing (Landlock/Seatbelt) is reserved
                # behind BAIZE_SANDBOX_ENABLED; the trust boundary here is
                # crash isolation + stderr capture + whitelist, not OS policy.
                env=dict(os.environ),
            )
        except (OSError, ValueError) as exc:
            raise MCPError(f"failed to spawn MCP server '{self.name}': {exc}")

        self._start_reader()
        self._start_stderr_drain()
        try:
            self._handshake()
        except Exception as exc:  # noqa: BLE001 - translate to MCPError
            self.stop()
            raise MCPError(f"handshake failed for '{self.name}': {exc}") from exc
        return self

    def _handshake(self) -> None:
        self._request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "baize", "version": "21"},
        })
        # notifications/initialized is a notification (no response expected).
        self._notify("notifications/initialized", {})

    def stop(self) -> None:
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:  # noqa: BLE001 - best effort
            pass
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # transport primitives
    # ------------------------------------------------------------------
    def _ensure_alive(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            raise MCPError(f"MCP server '{self.name}' is not running")

    def _send(self, obj: dict) -> None:
        with self._lock:
            if self._proc is None or self._proc.stdin is None:
                raise MCPError(f"MCP server '{self.name}' stdin closed")
            self._proc.stdin.write(json.dumps(obj) + "\n")
            self._proc.stdin.flush()

    def _notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _request(self, method: str, params: dict | None = None,
                 timeout: float | None = None) -> dict:
        self._ensure_alive()
        rid = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": rid,
                    "method": method, "params": params or {}})
        msg = self._recv(rid, timeout if timeout is not None else self.timeout)
        if msg is None:
            # Distinguish a dead server from a genuine timeout — both are
            # fail-closed, but the message should be honest.
            if self._proc is not None and self._proc.poll() is not None:
                raise MCPError(
                    f"MCP server '{self.name}' died during '{method}'")
            raise MCPError(
                f"timeout ({timeout or self.timeout}s) waiting for '{method}' "
                f"from server '{self.name}'")
        if "error" in msg:
            err = msg["error"]
            raise MCPError(f"{method} error from '{self.name}': {err}")
        return msg.get("result", {}) or {}

    def _recv(self, expected_id: int, timeout: float) -> dict | None:
        """Read responses until one matches ``expected_id`` or we time out.

        Unsolicited notifications (no ``id``) and stray messages are skipped.
        A process death is detected via the EOF sentinel and surfaced as a
        None so the caller raises a timeout/failure rather than hanging.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = self._queue.get(timeout=0.2)
            except queue.Empty:
                # Re-check liveness — the EOF sentinel may have just arrived.
                if self._proc is None or self._proc.poll() is not None:
                    # drain any remaining queued sentinel
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    return None
                continue
            if raw is None:  # EOF sentinel from the reader thread
                return None
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue  # ignore malformed line, keep waiting
            if "id" not in msg:
                continue  # notification — not ours
            if msg.get("id") == expected_id:
                return msg
            # stray response for another request; ignore
        return None

    def _start_reader(self) -> None:
        def _reader():
            try:
                assert self._proc is not None and self._proc.stdout is not None
                for line in iter(self._proc.stdout.readline, ""):
                    line = line.strip()
                    if not line:
                        continue
                    self._queue.put(line)
            except Exception:  # noqa: BLE001 - EOF or closed pipe
                pass
            finally:
                self._queue.put(None)  # EOF sentinel

        self._reader = threading.Thread(target=_reader, daemon=True)
        self._reader.start()

    def _start_stderr_drain(self) -> None:
        def _drain():
            try:
                assert self._proc is not None and self._proc.stderr is not None
                for line in iter(self._proc.stderr.readline, ""):
                    if not line:
                        break
                    self._stderr_buf.append(line.rstrip("\n"))
            except Exception:  # noqa: BLE001
                pass

        self._stderr_thread = threading.Thread(target=_drain, daemon=True)
        self._stderr_thread.start()

    # ------------------------------------------------------------------
    # MCP surface
    # ------------------------------------------------------------------
    def list_tools(self) -> list[dict]:
        """Return the server's tool list (each: name/description/inputSchema)."""
        result = self._request("tools/list", {})
        return result.get("tools", []) or []

    def call_tool(self, name: str, arguments: dict | None = None) -> str:
        """Call a tool and return its text output (ERROR string on failure).

        This raises ``MCPError`` on transport/protocol failure; the wrapper
        produced by ``register_tools`` catches that and returns an ERROR
        observation instead of crashing the Agent.
        """
        result = self._request("tools/call",
                               {"name": name, "arguments": arguments or {}})
        return self._format_result(name, result)

    @staticmethod
    def _format_result(name: str, result: dict) -> str:
        is_error = bool(result.get("isError", False))
        parts: list[str] = []
        for block in result.get("content", []) or []:
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(f"[{btype}] {json.dumps(block, ensure_ascii=False)}")
        text = "\n".join(parts).strip()
        if is_error:
            return f"ERROR: MCP tool '{name}' returned error: {text}"
        return text or "(no output)"

    # ------------------------------------------------------------------
    # registration into the baize tool registry
    # ------------------------------------------------------------------
    def register_tools(self, registry: ToolRegistry,
                       server_name: str | None = None) -> list[str]:
        """Discover tools and register them as ``mcp__<server>__<tool>``.

        Each registered callable is fail-closed: a transport/protocol failure
        becomes an ``ERROR`` observation, never an unhandled exception.
        """
        server = server_name or self.name
        registered: list[str] = []
        for tool in self.list_tools():
            tname = tool.get("name")
            if not tname:
                continue
            full = f"mcp__{server}__{tname}"
            schema = tool.get("inputSchema") or {
                "type": "object", "properties": {}}
            desc = tool.get("description") or f"MCP tool '{tname}' from '{server}'"
            registry.register(full, desc, schema, self._make_fn(tname))
            registered.append(full)
        return registered

    def _make_fn(self, tname: str):
        client = self

        def fn(**kwargs) -> str:
            try:
                return client.call_tool(tname, kwargs)
            except MCPError as exc:
                return f"ERROR: MCP tool '{tname}' failed: {exc}"
            except Exception as exc:  # noqa: BLE001 - observation, not crash
                return f"ERROR: MCP tool '{tname}' crashed: {exc}"
        return fn


# ---------------------------------------------------------------------------
# Config-driven bootstrap (opt-in, whitelist)
# ---------------------------------------------------------------------------

def _parse_servers(raw: str) -> list[dict]:
    """Parse BAIZE_MCP_SERVERS JSON; tolerate empty/invalid (fail safe)."""
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for entry in data:
        if isinstance(entry, dict) and entry.get("command"):
            out.append(entry)
    return out


def connect_mcp_servers(registry: ToolRegistry | None = None,
                        cfg: dict | None = None) -> list[MCPClient]:
    """Connect every whitelisted MCP server and register its tools.

    Returns the list of started clients (caller is responsible for ``stop()``).
    When ``BAIZE_MCP_ENABLED`` is not ``"1"`` this is a no-op (returns []), so
    the feature is truly opt-in and off by default.
    """
    cfg = cfg or load_config()
    registry = registry or _default_registry_silent()
    if cfg.get("BAIZE_MCP_ENABLED", "0") != "1":
        return []
    servers = _parse_servers(cfg.get("BAIZE_MCP_SERVERS", ""))
    clients: list[MCPClient] = []
    for spec in servers:
        try:
            client = MCPClient(
                name=spec.get("name", "mcp"),
                transport=spec.get("transport", "stdio"),
                timeout=float(spec.get("timeout", 30)),
            ).start(spec["command"], spec.get("args"))
            client.register_tools(registry, server_name=spec.get("name", "mcp"))
            clients.append(client)
        except MCPError as exc:
            # fail-closed at boot: log and skip this server, do not abort boot
            import sys
            print(f"[mcp] skipping server '{spec.get('name', '?')}': {exc}",
                  file=sys.stderr)
    return clients


def _default_registry_silent() -> ToolRegistry:
    """Import-time-safe accessor to avoid a hard import cycle with tools.py."""
    from .tools import default_registry
    return default_registry()


# Convenience for tests / direct use: a stdlib-only in-process mock server
# script path is provided under tests/mock_mcp_server.py.
MOCK_SERVER_HELPER = Path(__file__).resolve().parent.parent / "tests" / "mock_mcp_server.py"
