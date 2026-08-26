import subprocess, sys, json, threading, time
LOG = r"D:\tc\baize-agent\examples\_probe3.log"
def log(s):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")
log("start")
p = subprocess.Popen([sys.executable, r"D:\tc\baize-agent\examples\mcp_reference_server.py"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     bufsize=0)
log("spawned pid=%s" % p.pid)
# drain stderr in a thread
def err_reader():
    try:
        for line in iter(p.stderr.readline, b""):
            log("CHILD STDERR: " + line.decode("utf-8", "replace").rstrip())
    except Exception as e:
        log("err_reader done: " + repr(e))
te = threading.Thread(target=err_reader, daemon=True); te.start()
time.sleep(0.5)
msg = {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"baize","version":"25.0.0"}}}
body = json.dumps(msg).encode()
frame = b"Content-Length: %d\r\n\r\n" % len(body) + body
n = p.stdin.write(frame); p.stdin.flush()
log("sent init bytes=%s" % n)
time.sleep(2)
# peek pipe
log("poll stdout readable?")
result = p.poll()
log("child poll rc=%s" % result)
p.terminate()
log("done")
