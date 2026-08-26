import sys, traceback
sys.path.insert(0, r"D:\tc\baize-agent")
try:
    from baize.ext.mcp.transport import StdioTransport
    print("import ok", flush=True)
    t = StdioTransport(sys.executable, [r"D:\tc\baize-agent\examples\mcp_reference_server.py"], None, timeout=10.0)
    print("spawned ok", flush=True)
    t.send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"baize","version":"25.0.0"}}})
    print("sent init", flush=True)
    resp = t.recv()
    print("recv:", resp, flush=True)
    t.close()
    print("DONE", flush=True)
except Exception as e:
    print("ERR:", repr(e), flush=True)
    traceback.print_exc()
