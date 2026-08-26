import subprocess, sys, json, threading
LOG = r"D:/tc/baize-agent/examples/_probe6.log"
def log(s):
    open(LOG,"a",encoding="utf-8").write(s+"\n")
log("bufsize=-1 + stderr=DEVNULL")
p = subprocess.Popen([sys.executable, r"D:/tc/baize-agent/examples/mcp_reference_server.py"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=-1)
msg={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"baize","version":"25.0.0"}}}
body=json.dumps(msg).encode()
frame=b"Content-Length: %d\r\n\r\n"%len(body)+body
p.stdin.write(frame); p.stdin.flush()
log("wrote %s"%len(frame))
res={}
def r():
    data=b""
    try:
        while b"\r\n\r\n" not in data:
            c=p.stdout.read(65536)
            if not c: res["eof"]=True; return
            data+=c
        h=data.split(b"\r\n\r\n")[0]; ln=0
        for l in h.split(b"\r\n"):
            if l.lower().startswith(b"content-length:"): ln=int(l.split(b":",1)[1].strip())
        rest=data.split(b"\r\n\r\n",1)[1]
        while len(rest)<ln: rest+=p.stdout.read(ln-len(rest))
        res["resp"]=json.loads(rest[:ln].decode())
    except Exception as e: res["err"]=repr(e)
t=threading.Thread(target=r); t.start(); t.join(6)
log("resp=%s err=%s eof=%s timeout=%s"%(res.get("resp","-"),res.get("err","-"),res.get("eof",False),"timeout" not in res))
p.terminate()
