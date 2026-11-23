"""V48.0.0 Apex Multi-Service Docker Compose Test Stack Orchestrator.

Pure Python standard library — zero third-party dependencies.
Manages isolated per-workspace Docker Compose dependency stacks (Postgres, Redis,
Mock APIs, message brokers) under deterministic project names
(``baize-stack-<hash8>``) with TCP port readiness polling, service log inspection,
and idempotent ``down --remove-orphans`` teardown on exit.

Honest Failure (NO FAKE DONE):
When Docker / Docker Compose is unavailable on the host, every mutating action
returns ``ok=False, degraded=True`` with actionable remediation instead of
simulating running services.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..core.config import load_config

__all__ = [
    "ComposeStackInfo",
    "ComposeStackManager",
    "detect_compose_cmd",
    "discover_compose_file",
    "get_compose_manager",
]

_COMPOSE_FILENAMES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yml",
    "docker-compose.yaml",
)


@dataclass
class ComposeStackInfo:
    project_name: str
    workspace: str
    compose_file: str
    started_at: float
    services: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_compose_cmd() -> list[str] | None:
    """Return ``['docker', 'compose']`` or ``['docker-compose']`` when available."""
    docker = shutil.which("docker")
    if docker:
        try:
            r = subprocess.run(
                [docker, "compose", "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0:
                return [docker, "compose"]
        except Exception:
            pass
    legacy = shutil.which("docker-compose")
    if legacy:
        return [legacy]
    return None


def discover_compose_file(workspace: str | Path = ".", override: str = "") -> Path | None:
    """Locate a Compose YAML file inside ``workspace`` (or explicit ``override``)."""
    ws = Path(workspace).resolve()
    if override.strip():
        cand = Path(override.strip())
        if not cand.is_absolute():
            cand = (ws / cand).resolve()
        return cand if cand.is_file() else None
    for name in _COMPOSE_FILENAMES:
        cand = ws / name
        if cand.is_file():
            return cand
    return None


def _project_name_for(workspace: Path, compose_file: Path) -> str:
    digest = hashlib.sha256(f"{workspace.as_posix()}::{compose_file.as_posix()}".encode("utf-8")).hexdigest()[:8]
    return f"baize-stack-{digest}"


def _wait_tcp_ports(ports: list[int], timeout: float = 30.0, host: str = "127.0.0.1") -> tuple[bool, list[int]]:
    """Poll localhost TCP ports until all accept connections or timeout expires."""
    if not ports:
        return True, []
    deadline = time.monotonic() + max(1.0, float(timeout))
    pending = set(int(p) for p in ports if int(p) > 0)
    while pending and time.monotonic() < deadline:
        for port in list(pending):
            try:
                with socket.create_connection((host, port), timeout=0.6):
                    pending.discard(port)
            except OSError:
                pass
        if pending:
            time.sleep(0.35)
    return len(pending) == 0, sorted(pending)


class ComposeStackManager:
    """Thread-safe lifecycle manager for isolated Docker Compose test stacks."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stacks: dict[str, ComposeStackInfo] = {}

    def _resolve(self, workspace: str | Path, compose_file: str = "", cfg: dict[str, Any] | None = None) -> tuple[Path, Path | None, list[str] | None]:
        ws = Path(workspace).resolve()
        eff_cfg = cfg if cfg is not None else load_config()
        override = compose_file.strip() or str(eff_cfg.get("BAIZE_COMPOSE_FILE", "") or "").strip()
        cfile = discover_compose_file(ws, override=override)
        cmd = detect_compose_cmd()
        return ws, cfile, cmd

    def _run_compose(self, base_cmd: list[str], project: str, cfile: Path, subargs: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        argv = [*base_cmd, "-p", project, "-f", str(cfile), *subargs]
        return subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )

    def up(
        self,
        workspace: str | Path = ".",
        *,
        compose_file: str = "",
        services: list[str] | None = None,
        wait_ports: list[int] | None = None,
        timeout: int | None = None,
        cfg: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Start an isolated Compose dependency stack and optionally wait for TCP ports."""
        eff_cfg = cfg if cfg is not None else load_config()
        eff_timeout = int(timeout or eff_cfg.get("BAIZE_COMPOSE_TIMEOUT", "60") or 60)
        ws, cfile, cmd = self._resolve(workspace, compose_file, eff_cfg)
        if cfile is None:
            return {
                "ok": False,
                "degraded": True,
                "error": f"No compose.yaml / docker-compose.yml found in {ws}.",
            }
        if cmd is None:
            return {
                "ok": False,
                "degraded": True,
                "compose_file": str(cfile),
                "error": "Docker Compose CLI ('docker compose' / 'docker-compose') is not available on this host.",
            }

        project = _project_name_for(ws, cfile)
        subargs = ["up", "-d", "--remove-orphans"]
        svc_list = [s.strip() for s in (services or []) if s.strip()]
        subargs.extend(svc_list)

        try:
            res = self._run_compose(cmd, project, cfile, subargs, cwd=ws, timeout=eff_timeout)
        except Exception as exc:
            return {"ok": False, "degraded": True, "project_name": project, "error": str(exc)}

        if res.returncode != 0:
            return {
                "ok": False,
                "project_name": project,
                "compose_file": str(cfile),
                "returncode": res.returncode,
                "stderr": (res.stderr or res.stdout).strip()[:1200],
            }

        info = ComposeStackInfo(
            project_name=project,
            workspace=str(ws),
            compose_file=str(cfile),
            started_at=time.time(),
            services=svc_list,
        )
        with self._lock:
            self._stacks[project] = info

        ports_ready, unready_ports = _wait_tcp_ports(list(wait_ports or []), timeout=min(eff_timeout, 45))
        return {
            "ok": ports_ready,
            "project_name": project,
            "compose_file": str(cfile),
            "services": svc_list,
            "ports_ready": ports_ready,
            "unready_ports": unready_ports,
            "stdout": (res.stdout or "").strip()[:800],
            "stderr": (res.stderr or "").strip()[:800],
        }

    def status(
        self,
        workspace: str | Path = ".",
        *,
        compose_file: str = "",
        cfg: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Inspect active managed stacks and live Compose service status."""
        ws, cfile, cmd = self._resolve(workspace, compose_file, cfg)
        with self._lock:
            managed = [s.to_dict() for s in self._stacks.values()]
        if cfile is None or cmd is None:
            return {
                "ok": True,
                "compose_available": cmd is not None,
                "compose_cmd": " ".join(cmd) if cmd else "",
                "compose_file": str(cfile) if cfile else "",
                "project_name": _project_name_for(ws, cfile) if cfile else "",
                "managed_stacks": managed,
                "services": [],
            }
        project = _project_name_for(ws, cfile)
        services_out: list[dict[str, Any]] = []
        try:
            res = self._run_compose(cmd, project, cfile, ["ps", "--format", "json"], cwd=ws, timeout=15)
            raw = (res.stdout or "").strip()
            if res.returncode == 0 and raw:
                if raw.startswith("["):
                    parsed = json.loads(raw)
                    services_out = [x for x in parsed if isinstance(x, dict)]
                else:
                    for line in raw.splitlines():
                        line = line.strip()
                        if line.startswith("{"):
                            services_out.append(json.loads(line))
        except Exception:
            pass
        return {
            "ok": True,
            "compose_available": True,
            "compose_cmd": " ".join(cmd),
            "compose_file": str(cfile),
            "project_name": project,
            "managed_stacks": managed,
            "services": services_out,
        }

    def logs(
        self,
        workspace: str | Path = ".",
        *,
        compose_file: str = "",
        service: str = "",
        tail: int = 80,
        cfg: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read recent logs from a managed Compose stack."""
        ws, cfile, cmd = self._resolve(workspace, compose_file, cfg)
        if cfile is None or cmd is None:
            return {"ok": False, "degraded": True, "error": "Compose file or Docker Compose CLI unavailable."}
        project = _project_name_for(ws, cfile)
        subargs = ["logs", "--no-color", "--tail", str(max(1, min(int(tail), 500)))]
        if service.strip():
            subargs.append(service.strip())
        try:
            res = self._run_compose(cmd, project, cfile, subargs, cwd=ws, timeout=20)
            return {
                "ok": res.returncode == 0,
                "project_name": project,
                "logs": ((res.stdout or "") + "\n" + (res.stderr or "")).strip()[:6000],
            }
        except Exception as exc:
            return {"ok": False, "project_name": project, "error": str(exc)}

    def down(
        self,
        workspace: str | Path = ".",
        *,
        compose_file: str = "",
        volumes: bool = False,
        cfg: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Tear down an isolated Compose stack and remove orphan containers."""
        ws, cfile, cmd = self._resolve(workspace, compose_file, cfg)
        if cfile is None or cmd is None:
            return {"ok": False, "degraded": True, "error": "Compose file or Docker Compose CLI unavailable."}
        project = _project_name_for(ws, cfile)
        subargs = ["down", "--remove-orphans"]
        if volumes:
            subargs.append("-v")
        try:
            res = self._run_compose(cmd, project, cfile, subargs, cwd=ws, timeout=45)
        except Exception as exc:
            return {"ok": False, "project_name": project, "error": str(exc)}
        with self._lock:
            self._stacks.pop(project, None)
        return {
            "ok": res.returncode == 0,
            "project_name": project,
            "compose_file": str(cfile),
            "stdout": (res.stdout or "").strip()[:800],
            "stderr": (res.stderr or "").strip()[:800],
        }

    def down_all(self) -> int:
        """Tear down every managed Compose stack (called during graceful shutdown)."""
        with self._lock:
            items = list(self._stacks.values())
            self._stacks.clear()
        cmd = detect_compose_cmd()
        if not cmd:
            return 0
        stopped = 0
        for st in items:
            try:
                self._run_compose(
                    cmd,
                    st.project_name,
                    Path(st.compose_file),
                    ["down", "--remove-orphans"],
                    cwd=Path(st.workspace),
                    timeout=30,
                )
                stopped += 1
            except Exception:
                pass
        return stopped


_COMPOSE_LOCK = threading.Lock()
_GLOBAL_COMPOSE_MGR: ComposeStackManager | None = None


def get_compose_manager() -> ComposeStackManager:
    """Return the singleton :class:`ComposeStackManager`."""
    global _GLOBAL_COMPOSE_MGR
    with _COMPOSE_LOCK:
        if _GLOBAL_COMPOSE_MGR is None:
            _GLOBAL_COMPOSE_MGR = ComposeStackManager()
        return _GLOBAL_COMPOSE_MGR
