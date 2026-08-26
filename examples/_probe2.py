import subprocess, sys, json, threading
LOG = r"D:\tc\baize-agent\examples\_probe2.log"
def log(s):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")
log("start")
p = subprocess.Popen([sys.executable, r"D:\tc\baize-agent\examples\mcp_reference_server.py"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     bufsize=0)
log("spawned")
msg = {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"baize","version":"25.0.0"}}}
body = json.dumps(msg).encode()
frame = b"Content-Length: %d\r\n\r\n" % len(body) + body
p.stdin.write(frame); p.stdin.flush()
log("sent init")
# read with timeout via thread
result = {}
def reader():
    try:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = p.stdout.read(65536)
            if not chunk:
                result["eof"] = True
                return
            data += chunk
        header = data.split(b"\r\n\r\n")[0]
        length = 0
        for line in header.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
        rest = data.split(b"\r\n\r\n", 1)[1]
        while len(rest) < length:
            rest += p.stdout.read(length - len(rest))
        result["resp"] = json.loads(rest[:length].decode("utf-8"))
    except Exception as e:
        result["err"] = repr(e)
t = threading.Thread(target=reader); t.start(); t.join(8)
if "resp" in result:
    log("RESP: " + json.dumps(result["resp"]))
elif "err" in result:
    log("READ ERR: " + result["err"])
elif result.get("eof"):
    log("EOF before full frame")
else:
    log("TIMEOUT reading")
p.terminate()
log("done")
