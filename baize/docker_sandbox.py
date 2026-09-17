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
from typing import Any
from pathlib import Path

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
    ):
        self.image = image
        self.workspace = str(Path(workspace).resolve())
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.docker_available = is_docker_available()

    def _run_local_fallback(self, command: str) -> dict[str, Any]:
        """Actually run ``command`` through the local OS sandbox.

        Returns the real exit code and real output. The degraded notice goes to
        ``stderr`` so it can never be mistaken for the command's own stdout.
        """
        from .sandbox import run as sandbox_run

        note = (
            "[degraded] Docker daemon unreachable; running through the local OS "
            "sandbox (baize.sandbox) instead. Isolation is weaker than a "
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
            return self._run_local_fallback(command)

        # Build docker run invocation
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{self.workspace}:/workspace",
            "-w", "/workspace",
            f"--memory={self.memory_limit}",
            f"--cpus={self.cpu_limit}",
            self.image,
            "sh", "-c", command,
        ]

        try:
            res = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                encoding="utf-8",
                errors="replace",
            )
            return {
                "returncode": res.returncode,
                "stdout": res.stdout or "",
                "stderr": res.stderr or "",
                "degraded": False,
                "driver": "docker_container",
                "image": self.image,
            }
        except subprocess.TimeoutExpired:
            return {
                "returncode": 124,
                "stdout": "",
                "stderr": f"ERROR: Command timed out after {self.timeout}s inside Docker sandbox.",
                "degraded": False,
                "driver": "docker_container",
            }
        except Exception as exc:
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": f"ERROR: Failed to run in Docker sandbox: {exc}",
                "degraded": True,
                "driver": "docker_error",
            }
