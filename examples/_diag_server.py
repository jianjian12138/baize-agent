import sys, json
# Diagnostic server: read byte-by-byte, report progress to stderr.
sys.stderr.write("DIAG SERVER STARTED\n"); sys.stderr.flush()
stdin = sys.stdin.buffer
stdout = sys.stdout.buffer
buf = bytearray()
total_read = 0
# read exactly until header terminator, byte by byte
while b"\r\n\r\n" not in buf:
    b = stdin.read(1)
    if not b:
        sys.stderr.write("DIAG EOF after %d bytes\n" % total_read); sys.stderr.flush()
        sys.exit(0)
    buf.extend(b); total_read += 1
sys.stderr.write("DIAG HEADER DONE total_read=%d buf=%r\n" % (total_read, bytes(buf[:40]))); sys.stderr.flush()
header_blob, _, rest = bytes(buf).partition(b"\r\n\r\n")
length = 0
for line in header_blob.split(b"\r\n"):
    if line.lower().startswith(b"content-length:"):
        length = int(line.split(b":",1)[1].strip())
sys.stderr.write("DIAG length=%d rest_len=%d\n" % (length, len(rest))); sys.stderr.flush()
while len(rest) < length:
    b = stdin.read(1)
    if not b:
        sys.stderr.write("DIAG EOF while reading body at %d/%d\n" % (len(rest), length)); sys.stderr.flush()
        sys.exit(0)
    rest += b
sys.stderr.write("DIAG BODY DONE total=%d\n" % (total_read+len(rest))); sys.stderr.flush()
body = rest[:length]
try:
    msg = json.loads(body.decode("utf-8"))
    sys.stderr.write("DIAG PARSED method=%s\n" % msg.get("method")); sys.stderr.flush()
    # echo a response
    resp = {"jsonrpc":"2.0","id":msg.get("id"),"result":{"ok":True,"method":msg.get("method")}}
    payload = json.dumps(resp).encode()
    stdout.write(b"Content-Length: %d\r\n\r\n" % len(payload) + payload); stdout.flush()
    sys.stderr.write("DIAG RESPONSE SENT\n"); sys.stderr.flush()
except Exception as e:
    sys.stderr.write("DIAG PARSE ERR %r\n" % e); sys.stderr.flush()
