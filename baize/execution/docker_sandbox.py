"""Enterprise Optional Docker / Container Sandbox Driver (V37.0.0 Prometheus).

Pure Python standard library — zero third-party dependencies (subprocess + docker CLI).
Inspired by OpenHands / OpenDevin containerized runtime:
1. Provides hardware-isolated container execution for untrusted multi-tenant or enterprise environments.
2. Adheres strictly to Baize's SandboxComponent contract.
3. Automatically falls back to native sandboxed execution if Docker is unavailable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any
from pathlib import Path

from . import proc as proc_mod

__all__ = [
    "DockerSandboxDriver",
    "is_docker_available",
]


def is_docker_available() -> bool:
    """Whether a Docker *daemon* is reachable, not merely whether the CLI exists.

    ``docker --version`` succeeds with no daemon running - the CLI is just a
    client. Gating on it meant the driver took the container path, got exit 127
    from ``docker run``, and never reached the fallback it advertises. ``docker
    info`` is the cheapest call that actually talks to the daemon.
    """
    docker_exe = shutil.which("docker")
    if not docker_exe:
        return False
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False


class DockerSandboxDriver:
    """Runs commands within isolated disposable Docker containers."""
    def __init__(
        self,
        image: str = "python:3.11-slim",
        workspace: str = ".",
        timeout: int = 60,
        memory_limit: str = "1g",
        cpu_limit: str = "2.0",
        network_mode: str = "none",
        pids_limit: int = 128,
        strict: bool = False,
        session_id: str = "",
        use_session_pool: bool = False,
    ):
        self.image = image
        self.workspace = str(Path(workspace).resolve())
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.network_mode = network_mode
        self.pids_limit = pids_limit
        self.strict = strict
        self.session_id = session_id
        self.use_session_pool = use_session_pool
        self.docker_available = is_docker_available()

    def _run_local_fallback(self, command: str) -> dict[str, Any]:
        """Actually run ``command`` through the local OS sandbox.

        Returns the real exit code and real output. The degraded notice goes to
        ``stderr`` so it can never be mistaken for the command's own stdout.
        """
        from .sandbox import run as sandbox_run

        note = (
            "[degraded] Docker daemon unreachable; running through the local OS "
            "sandbox (baize.execution.sandbox) instead. Isolation is weaker than a "
            "container: no image pinning, no memory/cpu cgroup limits.\n"
        )
        try:
            res = sandbox_run(command, cwd=self.workspace, timeout=self.timeout)
        except Exception as exc:  # pragma: no cover - defensive
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": f"{note}ERROR: local sandbox fallback failed: {exc}",
                "degraded": True,
                "driver": "fallback_local_sandbox",
                "mechanism": "none",
            }
        return {
            "returncode": res.returncode,
            "stdout": res.stdout,
            "stderr": note + res.stderr,
            "degraded": True,
            "driver": "fallback_local_sandbox",
            "mechanism": res.mechanism,
        }

    def run(self, command: str) -> dict[str, Any]:
        """Execute ``command`` in a container, or degrade to the local sandbox.

        The fallback genuinely executes the command and reports its real exit
        code. An earlier version returned ``returncode: 0`` without running
        anything and echoed the command text back as ``stdout`` - a placeholder
        presented as an implementation, which is exactly the kind of fabricated
        evidence the honesty rule forbids. If we cannot run it, we say so.
        """
        if not self.docker_available:
            if self.strict:
                return {
                    "returncode": 126,
                    "stdout": "",
                    "stderr": (
                        "ERROR: strict Docker sandbox mode requested, but Docker daemon "
                        "is unavailable. Failing closed without running on host."
                    ),
                    "degraded": True,
                    "driver": "docker_unavailable",
                    "mechanism": "docker_unavailable",
                }
            return self._run_local_fallback(command)

        # Fast path: reuse warm session container via docker exec when enabled
        if self.use_session_pool and self.session_id:
            return get_docker_pool().exec_in_session(
                session_id=self.session_id,
                command=command,
                workspace=self.workspace,
                image=self.image,
                timeout=self.timeout,
                memory_limit=self.memory_limit,
                cpu_limit=self.cpu_limit,
                network_mode=self.network_mode,
                pids_limit=self.pids_limit,
            )

        # Build docker run invocation. The container gets an explicit unique name
        # so the timeout path can remove *the container* rather than only the
        # client. `--rm` fires when the container exits on its own; a timed-out
        # container is not in that category, so without a name the client dying
        # left the workload running (the same "timeout not actually enforced"
        # defect class as baize/proc.py, one level up).
        container_name = f"baize-sbx-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        docker_cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "-v", f"{self.workspace}:/workspace",
            "-w", "/workspace",
            f"--memory={self.memory_limit}",
            f"--cpus={self.cpu_limit}",
            f"--network={self.network_mode}",
            f"--pids-limit={self.pids_limit}",
            self.image,
            "sh", "-c", command,
        ]

        try:
            res = proc_mod.run(docker_cmd, timeout=self.timeout, encoding="utf-8")
        except Exception as exc:
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": f"ERROR: Failed to run in Docker sandbox: {exc}",
                "degraded": True,
                "driver": "docker_error",
                "container": container_name,
            }

        if res.timed_out:
            cleanup_rc, cleanup_err = self._force_remove_container(container_name)
            note = (
                f"ERROR: Command timed out after {self.timeout}s inside Docker "
                f"sandbox. Container {container_name} force-removed "
                f"(docker rm -f rc={cleanup_rc})"
            )
            if cleanup_err:
                note += f": {cleanup_err}"
            if res.stderr:
                note += f"\n{res.stderr}"
            return {
                "returncode": 124,
                "stdout": res.stdout,
                "stderr": note,
                "degraded": False,
                "driver": "docker_container",
                "image": self.image,
                "container": container_name,
                "container_removed": cleanup_rc == 0,
            }

        return {
            "returncode": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "degraded": False,
            "driver": "docker_container",
            "image": self.image,
            "container": container_name,
        }

    def _force_remove_container(self, name: str) -> tuple[int, str]:
        """``docker rm -f <name>``, best effort. Returns ``(returncode, stderr)``.

        The return code is the *real* one: ``0`` only when Docker confirmed the
        container is gone. A failed cleanup is reported to the caller instead of
        being swallowed, so "we timed out and cleaned up" cannot be printed for a
        cleanup that never happened.

        "No such container" is folded into success: ``--rm`` had already
        collected it, which is the outcome this call wanted.
        """
        try:
            res = subprocess.run(
                ["docker", "rm", "-f", name],
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            return 1, f"{type(exc).__name__}: {exc}"
        err = (res.stderr or "").strip()
        if res.returncode != 0 and "No such container" in err:
            return 0, f"already gone ({err})"
        return res.returncode, err


# ---------------------------------------------------------------------------
# V45.0.0 Nexus: Warm Per-Session Docker Container Pool (docker exec reuse)
# ---------------------------------------------------------------------------

class SessionDockerPool:
    """Reuses a single warm Docker container per ``(session_id, workspace, image)``.

    Avoids cold container startup overhead on every tool call by keeping a
    detached container running ``sleep infinity`` and dispatching commands via
    ``docker exec``. All pooled containers are force-removed on ``stop_all()``.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # key -> {"container": str, "image": str, "workspace": str, "started_at": float, "exec_count": int}
        self._containers: dict[str, dict[str, Any]] = {}

    def _pool_key(self, session_id: str, workspace: str, image: str) -> str:
        return f"{session_id}::{workspace}::{image}"

    def _ensure_container(
        self,
        session_id: str,
        workspace: str,
        image: str,
        memory_limit: str,
        cpu_limit: str,
        network_mode: str,
        pids_limit: int,
    ) -> tuple[str | None, str]:
        key = self._pool_key(session_id, workspace, image)
        with self._lock:
            entry = self._containers.get(key)
            if entry is not None:
                return entry["container"], ""
            safe_sid = "".join(ch for ch in session_id if ch.isalnum() or ch in ("-", "_"))[:18] or "default"
            cname = f"baize-pool-{safe_sid}-{uuid.uuid4().hex[:6]}"
            start_cmd = [
                "docker", "run", "-d", "--rm",
                "--name", cname,
                "-v", f"{workspace}:/workspace",
                "-w", "/workspace",
                f"--memory={memory_limit}",
                f"--cpus={cpu_limit}",
                f"--network={network_mode}",
                f"--pids-limit={pids_limit}",
                image,
                "sleep", "infinity",
            ]
            try:
                res = subprocess.run(
                    start_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception as exc:
                return None, f"Failed to start session container: {exc}"
            if res.returncode != 0:
                return None, (res.stderr or res.stdout or "docker run -d failed").strip()
            self._containers[key] = {
                "container": cname,
                "session_id": session_id,
                "image": image,
                "workspace": workspace,
                "started_at": time.time(),
                "exec_count": 0,
            }
            return cname, ""

    def exec_in_session(
        self,
        *,
        session_id: str,
        command: str,
        workspace: str,
        image: str = "python:3.11-slim",
        timeout: int = 60,
        memory_limit: str = "1g",
        cpu_limit: str = "2.0",
        network_mode: str = "none",
        pids_limit: int = 128,
    ) -> dict[str, Any]:
        """Execute ``command`` inside a warm pooled session container via ``docker exec``."""
        cname, err = self._ensure_container(
            session_id, workspace, image, memory_limit, cpu_limit, network_mode, pids_limit
        )
        if not cname:
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": f"ERROR: {err}",
                "degraded": True,
                "driver": "docker_error",
            }
        key = self._pool_key(session_id, workspace, image)
        exec_cmd = ["docker", "exec", "-w", "/workspace", cname, "sh", "-c", command]
        try:
            res = proc_mod.run(exec_cmd, timeout=timeout, encoding="utf-8")
        except Exception as exc:
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": f"ERROR: Failed to exec in session Docker container: {exc}",
                "degraded": True,
                "driver": "docker_error",
                "container": cname,
            }
        with self._lock:
            if key in self._containers:
                self._containers[key]["exec_count"] += 1
        if res.timed_out:
            # Tear down tainted container so next command gets a clean state
            self.stop_session(session_id)
            return {
                "returncode": 124,
                "stdout": res.stdout,
                "stderr": f"ERROR: Command timed out after {timeout}s in pooled Docker container {cname} (recycled).",
                "degraded": False,
                "driver": "docker_session_pool",
                "image": image,
                "container": cname,
            }
        return {
            "returncode": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "degraded": False,
            "driver": "docker_session_pool",
            "image": image,
            "container": cname,
        }

    def stop_session(self, session_id: str) -> int:
        """Stop and remove all pooled containers belonging to ``session_id``."""
        removed = 0
        with self._lock:
            keys = [k for k, v in self._containers.items() if v.get("session_id") == session_id]
            entries = [self._containers.pop(k) for k in keys]
        for entry in entries:
            try:
                subprocess.run(["docker", "rm", "-f", entry["container"]], capture_output=True, timeout=15)
            except Exception:
                pass
            removed += 1
        return removed

    def stop_all(self) -> int:
        """Stop and remove all pooled containers across all sessions."""
        with self._lock:
            entries = list(self._containers.values())
            self._containers.clear()
        for entry in entries:
            try:
                subprocess.run(["docker", "rm", "-f", entry["container"]], capture_output=True, timeout=15)
            except Exception:
                pass
        return len(entries)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active_containers": len(self._containers),
                "containers": [dict(v) for v in self._containers.values()],
            }


_DOCKER_POOL_LOCK = threading.Lock()
_GLOBAL_DOCKER_POOL: SessionDockerPool | None = None


def get_docker_pool() -> SessionDockerPool:
    """Return the singleton :class:`SessionDockerPool`."""
    global _GLOBAL_DOCKER_POOL
    with _DOCKER_POOL_LOCK:
        if _GLOBAL_DOCKER_POOL is None:
            _GLOBAL_DOCKER_POOL = SessionDockerPool()
        return _GLOBAL_DOCKER_POOL
