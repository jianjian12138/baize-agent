import subprocess, sys
LOG = r"D:\tc\baize-agent\examples\_probe_basic.log"
try:
    p = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdout.write('hi'); sys.stdout.flush()"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate(timeout=10)
    with open(LOG, "w") as f:
        f.write("OUT=%r ERR=%r RC=%s\n" % (out, err, p.returncode))
except Exception as e:
    with open(LOG, "w") as f:
        f.write("ERR: " + repr(e) + "\n")
