import subprocess, sys, json, threading
LOG = r"D:\tc\baize-agent\examples\_probe5.log"
def log(s):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")
# Test 1: bufsize=0 exact mimic of StdioTransport, child reads ALL not read(1)
log("=== TEST A: child reads full frame via read(65536) loop, bufsize=0 ===")
p = subprocess.Popen([sys.executable, r"D:\tc\baize-agent\examples\mcp_reference_server.py"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                     bufsize=0)
msg = {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"baize","version":"25.0.0"}}}
body = json.dumps(msg).encode()
frame = b"Content-Length: %d\r\n\r\n" % len(body) + body
# mimic StdioTransport._write_frame
nwritten = p.stdin.write(frame)
p.stdin.flush()
log("wrote %s bytes (bufsize=0)" % nwritten)
result = {}
def reader():
    data = b""
    try:
        while b"\r\n\r\n" not in data:
            c = p.stdout.read(65536)
            if not c: result["eof"]=True; return
            data += c
        header = data.split(b"\r\n\r\n")[0]
        length = 0
        for line in header.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":",1)[1].strip())
        rest = data.split(b"\r\n\r\n",1)[1]
        while len(rest) < length:
            rest += p.stdout.read(length-len(rest))
        result["resp"] = json.loads(rest[:length].decode())
    except Exception as e:
        result["err"] = repr(e)
t = threading.Thread(target=reader); t.start(); t.join(6)
log("A resp=%s err=%s eof=%s timeout=%s" % (result.get("resp","-"), result.get("err","-"), result.get("eof",False), "timeout" not in result))
p.terminate()
log("done A")
