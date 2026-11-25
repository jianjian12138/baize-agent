"""Isolated SUT environment adapters: external URL, local command, or Docker Compose."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_http_health(url: str, timeout_s: float, proc: subprocess.Popen | None = None) -> None:
    deadline = time.monotonic() + timeout_s
    last_err = ""
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"Target process exited early with code {proc.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if 200 <= resp.status < 500:
                    return
        except Exception as exc:
            last_err = str(exc)
        time.sleep(0.08)
    raise RuntimeError(f"Healthcheck failed for {url} within {timeout_s}s: {last_err}")


def _wait_tcp_port(host: str, port: int, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"TCP port {host}:{port} not reachable within {timeout_s}s")


class HarnessWorld:
    """Lifecycle-managed test world supporting external, command, and compose targets."""

    def __init__(
        self,
        *,
        target_cfg: dict[str, Any],
        config_dir: Path,
        artifacts_dir: Path,
        override_base_url: str = "",
    ) -> None:
        self.target_cfg = dict(target_cfg or {})
        self.config_dir = Path(config_dir).resolve()
        self.artifacts_dir = Path(artifacts_dir).resolve()
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="baize_harness_world_"))
        self.log_path = self.artifacts_dir / "service.log"
        self.mode = "external" if override_base_url else str(self.target_cfg.get("mode", "external")).strip().lower()
        self.port = int(self.target_cfg.get("port") or 0) or find_free_port()
        self.base_url = (override_base_url or str(self.target_cfg.get("base_url") or "")).rstrip("/")
        self.db_path: Path | None = None
        self._proc: subprocess.Popen | None = None
        self._log_fp = None
        self._compose_cmd: list[str] | None = None
        self._compose_project: str = ""

        # Optional per-world SQLite DB path for local DB invariant checks
        db_tpl = str(self.target_cfg.get("db_path") or "").strip()
        if db_tpl:
            rendered = db_tpl.format(tmp_dir=str(self.tmp_dir), port=self.port, config_dir=str(self.config_dir))
            p = Path(rendered)
            self.db_path = p if p.is_absolute() else (self.config_dir / p).resolve()

    def _fmt(self, text: str) -> str:
        return text.format(
            python=sys.executable,
            port=self.port,
            tmp_dir=str(self.tmp_dir),
            db_path=str(self.db_path or (self.tmp_dir / "sut.sqlite3")),
            config_dir=str(self.config_dir),
            base_url=self.base_url,
        )

    def start(self) -> None:
        timeout_s = float(self.target_cfg.get("health_timeout_s", 15.0))
        health_path = str(self.target_cfg.get("health_path", "/health") or "")

        if self.mode == "external":
            if not self.base_url:
                raise RuntimeError("External target mode requires 'base_url' (or --base-url).")
            if health_path:
                _wait_http_health(f"{self.base_url}{health_path}", timeout_s=timeout_s)
            return

        if self.mode == "command":
            raw_cmd = self.target_cfg.get("start_cmd")
            if not isinstance(raw_cmd, list) or not raw_cmd:
                raise RuntimeError("Command target mode requires non-empty 'start_cmd' list.")
            if not self.base_url:
                host = str(self.target_cfg.get("host", "127.0.0.1"))
                self.base_url = f"http://{host}:{self.port}"
            cmd = [self._fmt(str(part)) for part in raw_cmd]
            cwd_raw = str(self.target_cfg.get("cwd") or ".").strip()
            cwd = Path(self._fmt(cwd_raw))
            if not cwd.is_absolute():
                cwd = (self.config_dir / cwd).resolve()

            env = dict(os.environ)
            env["PYTHONUNBUFFERED"] = "1"
            for k, v in (self.target_cfg.get("env") or {}).items():
                env[str(k)] = self._fmt(str(v))

            self._log_fp = open(self.log_path, "w", encoding="utf-8")
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=env,
                stdout=self._log_fp,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if health_path:
                _wait_http_health(f"{self.base_url}{health_path}", timeout_s=timeout_s, proc=self._proc)
            else:
                _wait_tcp_port("127.0.0.1", self.port, timeout_s=timeout_s)
            return

        if self.mode == "compose":
            compose_file = str(self.target_cfg.get("compose_file") or "docker-compose.yml")
            cf_path = Path(compose_file)
            if not cf_path.is_absolute():
                cf_path = (self.config_dir / cf_path).resolve()
            if not cf_path.is_file():
                raise RuntimeError(f"Compose file not found: {cf_path}")
            if shutil.which("docker"):
                self._compose_cmd = ["docker", "compose"]
            elif shutil.which("docker-compose"):
                self._compose_cmd = ["docker-compose"]
            else:
                raise RuntimeError("Docker Compose CLI ('docker compose' / 'docker-compose') is not installed on this host.")
            self._compose_project = f"baize-harness-{self.port}"
            up = subprocess.run(
                [*self._compose_cmd, "-p", self._compose_project, "-f", str(cf_path), "up", "-d"],
                cwd=str(cf_path.parent),
                capture_output=True,
                text=True,
            )
            if up.returncode != 0:
                raise RuntimeError(f"docker compose up failed: {up.stderr.strip() or up.stdout.strip()}")
            for wp in self.target_cfg.get("wait_ports") or []:
                _wait_tcp_port("127.0.0.1", int(wp), timeout_s=timeout_s)
            if self.base_url and health_path:
                _wait_http_health(f"{self.base_url}{health_path}", timeout_s=timeout_s)
            return

        raise RuntimeError(f"Unsupported target.mode: {self.mode!r} (expected external|command|compose)")

    def read_logs(self) -> str:
        if self._log_fp is not None:
            try:
                self._log_fp.flush()
            except Exception:
                pass
        if self.log_path.is_file():
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        return ""

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self._log_fp is not None:
            try:
                self._log_fp.close()
            except Exception:
                pass
            self._log_fp = None
        if self.mode == "compose" and self._compose_cmd and self._compose_project:
            compose_file = str(self.target_cfg.get("compose_file") or "docker-compose.yml")
            cf_path = Path(compose_file)
            if not cf_path.is_absolute():
                cf_path = (self.config_dir / cf_path).resolve()
            subprocess.run(
                [*self._compose_cmd, "-p", self._compose_project, "-f", str(cf_path), "down", "--remove-orphans"],
                cwd=str(cf_path.parent),
                capture_output=True,
                text=True,
            )

    def __enter__(self) -> "HarnessWorld":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
