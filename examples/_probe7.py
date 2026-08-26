import subprocess, sys, json, threading
LOG = r"D:\tc\baize-agent\examples\_probe7.log"
def log(s):
    open(LOG,"a",encoding="utf-8").write(s+"\n")
log("start diag")
p = subprocess.Popen([sys.executable, r"D:\tc\baize-agent\examples\_diag_server.py"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=-1)
# read child stderr to a file live
def errd():
    try:
        for line in iter(p.stderr.readline, b""):
            open(LOG,"a",encoding="utf-8").write("CHILD: "+line.decode("utf-8","replace"))
    except Exception as e:
        open(LOG,"a",encoding="utf-8").write("errd done %r\n"%e)
te=threading.Thread(target=errd, daemon=True); te.start()
msg={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"baize","version":"25.0.0"}}}
body=json.dumps(msg).encode()
frame=b"Content-Length: %d\r\n\r\n"%len(body)+body
p.stdin.write(frame); p.stdin.flush()
log("wrote %s bytes"%len(frame))
res={}
def r():
    try:
        data=p.stdout.read(1000)
        res["raw"]=data
    except Exception as e: res["err"]=repr(e)
t=threading.Thread(target=r); t.start(); t.join(6)
log("resp raw=%s err=%s timeout=%s"%(res.get("raw","-"),res.get("err","-"),"timeout" not in res))
p.terminate()
