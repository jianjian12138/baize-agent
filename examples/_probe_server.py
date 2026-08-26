import subprocess, sys, json
LOG = r"D:\tc\baize-agent\examples\_probe_server.log"
try:
    p = subprocess.Popen([sys.executable, r"D:\tc\baize-agent\examples\mcp_reference_server.py"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    msg = {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"baize","version":"25.0.0"}}}
    body = json.dumps(msg).encode()
    frame = b"Content-Length: %d\r\n\r\n" % len(body) + body
    p.stdin.write(frame); p.stdin.flush()
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = p.stdout.read(65536)
        if not chunk:
            break
        data += chunk
    header = data.split(b"\r\n\r\n")[0] if b"\r\n\r\n" in data else data
    length = 0
    for line in header.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    body2 = data.split(b"\r\n\r\n", 1)[1][:length]
    resp = json.loads(body2.decode("utf-8"))
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("SERVER RESPONSE: " + json.dumps(resp, ensure_ascii=False) + "\n")
    p.terminate()
except Exception as e:
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("ERR: " + repr(e) + "\n")
