import subprocess, sys, json, threading
LOG = r"D:\tc\baize-agent\examples\_probe8.log"
def log(s):
    with open(LOG,"a",encoding="utf-8") as f:
        f.write(s+"\n"); f.flush()
# Probe: use read(1) accumulation on the PARENT side (mimic fixed StdioTransport)
log("read(1) accumulation on parent, real subprocess")
p = subprocess.Popen([sys.executable, r"D:\tc\baize-agent\examples\mcp_reference_server.py"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=-1)
out = p.stdout
def read_frame():
    buf = bytearray()
    # read until header terminator
    while b"\r\n\r\n" not in buf:
        b = out.read(1)
        if not b: raise RuntimeError("eof")
        buf.extend(b)
    header_blob, _, rest = bytes(buf).partition(b"\r\n\r\n")
    length = 0
    for line in header_blob.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":",1)[1].strip())
    while len(rest) < length:
        rest += out.read(1)
    return json.loads(rest[:length].decode())
msg={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"baize","version":"25.0.0"}}}
body=json.dumps(msg).encode()
frame=b"Content-Length: %d\r\n\r\n"%len(body)+body
p.stdin.write(frame); p.stdin.flush()
log("sent init")
try:
    resp = read_frame()
    log("INIT RESP: "+json.dumps(resp))
    # tools/list
    msg2={"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
    b2=json.dumps(msg2).encode(); p.stdin.write(b"Content-Length: %d\r\n\r\n"%len(b2)+b2); p.stdin.flush()
    resp2=read_frame()
    log("TOOLS/LIST: "+json.dumps(resp2))
    # tools/call
    msg3={"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"echo_upper","arguments":{"text":"baize v25"}}}
    b3=json.dumps(msg3).encode(); p.stdin.write(b"Content-Length: %d\r\n\r\n"%len(b3)+b3); p.stdin.flush()
    resp3=read_frame()
    log("TOOLS/CALL: "+json.dumps(resp3))
    log("EVIDENCE: real subprocess MCP = PASS")
except Exception as e:
    log("ERR: "+repr(e))
p.terminate()
