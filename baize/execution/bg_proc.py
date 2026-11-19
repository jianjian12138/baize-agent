"""V41 Background Process & Optional PTY Manager (Pure Python Standard Library).

Enables long-running services (dev servers, test watchers, local API servers) to be
started, monitored non-blockingly via bounded ring-buffer logs, and cleanly torn down
(process-group kill) on stop or session exit with zero orphaned processes.
"""

from __future__ import annotations

import atexit
import collections
import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BackgroundProcess:
    proc_id: str
    command: str
    cwd: str
    pid: int
    started_at: float
    process: subprocess.Popen
    ring_lines: collections.deque = field(default_factory=lambda: collections.deque(maxlen=400))
    lock: threading.Lock = field(default_factory=threading.Lock)
    read_cursor: int = 0
    total_lines: int = 0
    stopped_by_user: bool = False

    def status(self) -> str:
        rc = self.process.poll()
        if rc is None:
            return "running"
        return "killed" if self.stopped_by_user else "exited"

    def to_summary(self) -> dict[str, Any]:
        rc = self.process.poll()
        return {
            "proc_id": self.proc_id,
            "pid": self.pid,
            "command": self.command,
            "cwd": self.cwd,
            "status": self.status(),
            "returncode": rc,
            "uptime_s": round(time.time() - self.started_at, 2),
            "buffered_lines": len(self.ring_lines),
            "total_lines": self.total_lines,
        }


class BackgroundProcessManager:
    """Thread-safe manager for background shell commands bound to a workspace/session."""

    def __init__(self, max_procs: int = 8) -> None:
        self.max_procs = max(1, int(max_procs))
        self._lock = threading.Lock()
        self._procs: dict[str, BackgroundProcess] = {}

    def start(
        self,
        command: str,
        *,
        cwd: str = ".",
        env: dict[str, str] | None = None,
        use_pty: bool = False,
    ) -> dict[str, Any]:
        from .tools import command_allowed
        from .sandbox import scrub_environment

        ok, reason = command_allowed(command)
        if not ok:
            return {"ok": False, "error": "command_blocked", "message": f"Blocked by guardrail: {reason}"}

        with self._lock:
            running = [p for p in self._procs.values() if p.process.poll() is None]
            if len(running) >= self.max_procs:
                return {
                    "ok": False,
                    "error": "max_procs_reached",
                    "message": f"Background process limit ({self.max_procs}) reached; stop an existing process first.",
                }

        work_dir = str(Path(cwd).resolve())
        child_env = scrub_environment(env or dict(os.environ))
        popen_kwargs: dict[str, Any] = {
            "shell": True,
            "cwd": work_dir,
            "env": child_env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
            "text": True,
            "bufsize": 1,
        }
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True

        master_fd: int | None = None
        if use_pty and os.name == "posix":
            try:
                import pty  # stdlib on POSIX

                master_fd, slave_fd = pty.openpty()
                popen_kwargs["stdout"] = slave_fd
                popen_kwargs["stderr"] = slave_fd
                popen_kwargs["stdin"] = slave_fd
                popen_kwargs.pop("text", None)
                popen_kwargs.pop("bufsize", None)
                proc = subprocess.Popen(command, **popen_kwargs)
                os.close(slave_fd)
            except Exception:
                if master_fd is not None:
                    try:
                        os.close(master_fd)
                    except OSError:
                        pass
                    master_fd = None
                proc = subprocess.Popen(command, **popen_kwargs)
        else:
            proc = subprocess.Popen(command, **popen_kwargs)

        proc_id = f"bg-{uuid.uuid4().hex[:8]}"
        entry = BackgroundProcess(
            proc_id=proc_id,
            command=command,
            cwd=work_dir,
            pid=proc.pid,
            started_at=time.time(),
            process=proc,
        )

        def _reader() -> None:
            if master_fd is not None:
                try:
                    buf = b""
                    while True:
                        try:
                            chunk = os.read(master_fd, 4096)
                        except OSError:
                            break
                        if not chunk:
                            break
                        buf += chunk
                        while b"\n" in buf:
                            line_b, buf = buf.split(b"\n", 1)
                            line = line_b.decode("utf-8", errors="replace").rstrip("\r")
                            with entry.lock:
                                entry.ring_lines.append(line)
                                entry.total_lines += 1
                    if buf:
                        with entry.lock:
                            entry.ring_lines.append(buf.decode("utf-8", errors="replace").rstrip("\r"))
                            entry.total_lines += 1
                finally:
                    try:
                        os.close(master_fd)
                    except OSError:
                        pass
            elif proc.stdout is not None:
                try:
                    for raw_line in proc.stdout:
                        with entry.lock:
                            entry.ring_lines.append(raw_line.rstrip("\r\n"))
                            entry.total_lines += 1
                except Exception:
                    pass
                finally:
                    try:
                        proc.stdout.close()
                    except Exception:
                        pass

        t = threading.Thread(target=_reader, name=f"baize-{proc_id}", daemon=True)
        t.start()

        with self._lock:
            self._procs[proc_id] = entry

        return {"ok": True, **entry.to_summary()}

    def read_output(self, proc_id: str, *, tail_lines: int = 60, wait_ms: int = 0) -> dict[str, Any]:
        with self._lock:
            entry = self._procs.get(proc_id)
        if entry is None:
            return {"ok": False, "error": "not_found", "message": f"Unknown background process: {proc_id}"}
        if wait_ms > 0:
            time.sleep(min(wait_ms, 5000) / 1000.0)
        with entry.lock:
            lines = list(entry.ring_lines)
            if tail_lines > 0:
                lines = lines[-tail_lines:]
            output = "\n".join(lines)
        return {"ok": True, **entry.to_summary(), "output": output}

    def stop(self, proc_id: str, *, timeout: float = 3.0) -> dict[str, Any]:
        with self._lock:
            entry = self._procs.get(proc_id)
        if entry is None:
            return {"ok": False, "error": "not_found", "message": f"Unknown background process: {proc_id}"}
        entry.stopped_by_user = True
        proc = entry.process
        if proc.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                else:
                    proc.terminate()
                proc.wait(timeout=timeout)
            except Exception:
                try:
                    if os.name == "posix":
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
        return {"ok": True, **entry.to_summary()}

    def list_procs(self) -> list[dict[str, Any]]:
        with self._lock:
            entries = list(self._procs.values())
        return [e.to_summary() for e in entries]

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for e in self._procs.values() if e.process.poll() is None)

    def stop_all(self) -> int:
        with self._lock:
            ids = list(self._procs.keys())
        stopped = 0
        for pid in ids:
            res = self.stop(pid, timeout=1.5)
            if res.get("ok"):
                stopped += 1
        return stopped


_DEFAULT_BG_MANAGER = BackgroundProcessManager()
atexit.register(_DEFAULT_BG_MANAGER.stop_all)


def get_bg_manager() -> BackgroundProcessManager:
    return _DEFAULT_BG_MANAGER
