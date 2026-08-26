"""V25 评审 E-01/M-05 真实 MCP 联调 (StdioTransport 真实子进程, 非 mock).

Connects to examples/mcp_reference_server.py via StdioTransport (real subprocess
+ Content-Length framing, with the Windows-safe byte-accumulator read loop),
performs the initialize handshake, lists tools, and calls echo_upper through the
core ToolRegistry. Prints a deterministic evidence trail and exits 0 on success.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from baize.tools import default_registry
from baize.ext.mcp.client import MCPClient, MCPServerSpec
from baize.ext.mcp.transport import StdioTransport


def main() -> int:
    server = ROOT / "examples" / "mcp_reference_server.py"
    spec = MCPServerSpec(
        name="refserver",
        command=sys.executable,
        args=[str(server)],
        env={"MCP_REF_DBG": str(ROOT / "examples" / "mcp_ref_dbg.log")},
        protocol_version="2024-11-05",
    )

    # Hard timeout so a transport hang fails loudly instead of blocking forever.
    timed_out = threading.Event()

    def _timeout():
        timed_out.set()
        transport.close()
    timer = threading.Timer(15.0, _timeout)
    timer.start()
    registry = default_registry()
    transport = StdioTransport(spec.command, spec.args, spec.env or None, timeout=15.0)
    client = MCPClient(spec, transport=transport)

    print("== [1] connect (initialize handshake over real subprocess) ==")
    try:
        client.connect()
    finally:
        timer.cancel()
    if timed_out.is_set():
        raise TimeoutError("MCP initialize timed out after 15 seconds")
    print("   handshake OK", flush=True)

    print("== [2] list_tools ==")
    tools = client.list_tools()
    names = [t.name for t in tools]
    print("   tools:", names, flush=True)
    assert names == ["echo_upper"], f"unexpected tools: {names}"

    print("== [3] register_into core ToolRegistry (reuse, no new table) ==")
    registered = client.register_into(registry)
    print("   registered:", registered, flush=True)

    print("== [4] tools/call echo_upper via registry.execute ==")
    out = registry.execute("refserver__echo_upper", {"text": "baize-agent v25"})
    print("   result:", out, flush=True)
    assert out == "BAIZE-AGENT V25", f"unexpected call result: {out!r}"

    print("== [5] fail-closed: unknown tool returns ERROR ==")
    bad = client.call_tool("does_not_exist", {})
    print("   bad call result:", bad, flush=True)
    assert bad.startswith("ERROR"), "expected ERROR for unknown tool"

    client.close()
    print("\nEVIDENCE: real MCP subprocess handshake + tools/list + tools/call = PASS",
          flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover
        import traceback
        sys.stderr.write(f"FATAL: {exc!r}\n")
        sys.stderr.write(traceback.format_exc())
        raise SystemExit(1)
