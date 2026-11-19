"""Zero-dependency LSP stdio client and fast compiler/linter diagnostic bridge.

Provides immediate post-edit syntax, import, and static diagnostics without
requiring any third-party Python dependencies:
1. Instant built-in Python AST + ``compile()`` diagnostics (always available).
2. Fast local compiler/linter adapters (``ruff``, ``node --check``, ``tsc``,
   ``go vet``, ``cargo check``) when installed on PATH.
3. Optional pure-stdlib JSON-RPC 2.0 ``Content-Length`` framed stdio LSP client
   (compatible with ``pyright-langserver``, ``pylsp``, ``typescript-language-server``,
   ``gopls``, ``rust-analyzer``, or any command configured via ``BAIZE_LSP_CMD``).
"""
from __future__ import annotations

import ast
import json
import os
import re
import select
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "Diagnostic",
    "DiagnosticReport",
    "LspClient",
    "diagnose_file",
    "diagnose_workspace",
]


@dataclass
class Diagnostic:
    file: str
    line: int
    col: int
    severity: str  # "error" | "warning" | "info"
    message: str
    code: str = ""
    source: str = "compiler"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiagnosticReport:
    file: str
    backend: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    elapsed_ms: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity == "warning")

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "backend": self.backend,
            "ok": self.ok,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "notes": list(self.notes),
        }

    def format_for_agent(self, max_items: int = 12) -> str:
        if not self.diagnostics:
            return f"[diagnostics:{self.backend}] OK (0 errors, 0 warnings)"
        lines = [
            f"[diagnostics:{self.backend}] {self.error_count} error(s), "
            f"{self.warning_count} warning(s) in {self.file}:"
        ]
        for d in self.diagnostics[:max_items]:
            code_part = f" [{d.code}]" if d.code else ""
            lines.append(
                f"  - {d.severity.upper()} L{d.line}:{d.col}{code_part}: {d.message}"
            )
        if len(self.diagnostics) > max_items:
            lines.append(f"  ... and {len(self.diagnostics) - max_items} more")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pure-stdlib JSON-RPC 2.0 Content-Length framed stdio LSP Client
# ---------------------------------------------------------------------------
_LSP_SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "info"}

_LANG_ID_BY_EXT = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}


class LspClient:
    """Minimal pure-stdlib JSON-RPC 2.0 stdio LSP client for single-file diagnostics."""

    def __init__(self, cmd: list[str], workspace: str | Path = ".",
                 timeout: float = 5.0) -> None:
        self.cmd = list(cmd)
        self.workspace = Path(workspace).resolve()
        self.timeout = timeout
        self._proc: subprocess.Popen[bytes] | None = None
        self._seq = 0

    def _send(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("LSP process not started")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self._proc.stdin.write(header + body)
        self._proc.stdin.flush()

    def _read_message(self, deadline: float) -> dict[str, Any] | None:
        if self._proc is None or self._proc.stdout is None:
            return None
        fd = self._proc.stdout.fileno()
        headers: dict[str, str] = {}
        line_buf = b""

        while time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            if os.name != "nt":
                ready, _, _ = select.select([fd], [], [], min(0.2, remaining))
                if not ready:
                    if self._proc.poll() is not None:
                        return None
                    continue
            ch = os.read(fd, 1)
            if not ch:
                return None
            line_buf += ch
            if line_buf.endswith(b"\r\n"):
                line = line_buf[:-2].decode("ascii", errors="replace")
                line_buf = b""
                if line == "":
                    break
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

        length = int(headers.get("content-length", "0") or "0")
        if length <= 0:
            return None

        chunks = bytearray()
        while len(chunks) < length and time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            if os.name != "nt":
                ready, _, _ = select.select([fd], [], [], min(0.2, remaining))
                if not ready:
                    if self._proc.poll() is not None:
                        break
                    continue
            piece = os.read(fd, length - len(chunks))
            if not piece:
                break
            chunks.extend(piece)

        if len(chunks) < length:
            return None
        try:
            return json.loads(chunks.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None

    def diagnose_file(self, file_path: str | Path) -> list[Diagnostic]:
        """Open ``file_path`` in the LSP server and collect published diagnostics."""
        target = Path(file_path).resolve()
        text = target.read_text(encoding="utf-8", errors="replace")
        lang_id = _LANG_ID_BY_EXT.get(target.suffix.lower(), "plaintext")
        uri = target.as_uri()
        root_uri = self.workspace.as_uri()

        self._proc = subprocess.Popen(
            self.cmd,
            cwd=str(self.workspace),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + self.timeout
        collected: list[Diagnostic] = []
        try:
            self._seq += 1
            init_id = self._seq
            self._send({
                "jsonrpc": "2.0",
                "id": init_id,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": root_uri,
                    "capabilities": {"textDocument": {"publishDiagnostics": {}}},
                },
            })
            # Wait for initialize response
            while time.monotonic() < deadline:
                msg = self._read_message(deadline)
                if msg is None:
                    break
                if msg.get("id") == init_id:
                    break

            self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
            self._send({
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": lang_id,
                        "version": 1,
                        "text": text,
                    }
                },
            })

            while time.monotonic() < deadline:
                msg = self._read_message(deadline)
                if msg is None:
                    break
                if msg.get("method") == "textDocument/publishDiagnostics":
                    params = msg.get("params") or {}
                    for item in params.get("diagnostics") or []:
                        rng = (item.get("range") or {}).get("start") or {}
                        sev = _LSP_SEVERITY.get(int(item.get("severity", 1)), "error")
                        collected.append(Diagnostic(
                            file=str(file_path),
                            line=int(rng.get("line", 0)) + 1,
                            col=int(rng.get("character", 0)) + 1,
                            severity=sev,
                            message=str(item.get("message", "")),
                            code=str(item.get("code", "")),
                            source=str(item.get("source") or "lsp"),
                        ))
                    break
        finally:
            try:
                self._seq += 1
                self._send({"jsonrpc": "2.0", "id": self._seq, "method": "shutdown", "params": None})
                self._send({"jsonrpc": "2.0", "method": "exit"})
            except Exception:
                pass
            if self._proc is not None:
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=1.0)
                except Exception:
                    try:
                        self._proc.kill()
                        self._proc.wait(timeout=0.5)
                    except Exception:
                        pass
                for stream in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except Exception:
                            pass
                self._proc = None
        return collected


# ---------------------------------------------------------------------------
# Fast Built-in & Compiler Fallback Adapters
# ---------------------------------------------------------------------------

def _diagnose_python(target: Path, display_path: str) -> tuple[str, list[Diagnostic]]:
    diags: list[Diagnostic] = []
    source = target.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=display_path)
        compile(tree, display_path, "exec")
    except SyntaxError as exc:
        diags.append(Diagnostic(
            file=display_path,
            line=int(exc.lineno or 1),
            col=int(exc.offset or 1),
            severity="error",
            message=exc.msg or str(exc),
            code="SyntaxError",
            source="python-ast",
        ))
        return "python-ast", diags

    # Optional ruff fast linter when installed on PATH
    ruff = shutil.which("ruff")
    if ruff:
        try:
            proc = subprocess.run(
                [ruff, "check", "--output-format=json", "--no-fix", str(target)],
                capture_output=True, text=True, timeout=8,
            )
            if proc.stdout.strip().startswith("["):
                for item in json.loads(proc.stdout):
                    loc = item.get("location") or {}
                    code = str(item.get("code") or "")
                    sev = "error" if code.startswith(("E9", "F82", "F63")) else "warning"
                    diags.append(Diagnostic(
                        file=display_path,
                        line=int(loc.get("row", 1)),
                        col=int(loc.get("column", 1)),
                        severity=sev,
                        message=str(item.get("message", "")),
                        code=code,
                        source="ruff",
                    ))
                return "python-ast+ruff", diags
        except Exception:
            pass
    return "python-ast", diags


def _diagnose_js_ts(target: Path, display_path: str, workspace: Path) -> tuple[str, list[Diagnostic]]:
    diags: list[Diagnostic] = []
    ext = target.suffix.lower()
    if ext in (".js", ".mjs", ".cjs") and shutil.which("node"):
        proc = subprocess.run(
            ["node", "--check", str(target)],
            capture_output=True, text=True, timeout=8,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip().splitlines()
            line_no = 1
            for l in err:
                m = re.search(r":(\d+)$", l.strip())
                if m:
                    line_no = int(m.group(1))
                    break
            diags.append(Diagnostic(
                file=display_path, line=line_no, col=1, severity="error",
                message=" | ".join(err[-2:]) if err else "JS syntax error",
                code="SyntaxError", source="node-check",
            ))
        return "node-check", diags

    if ext in (".ts", ".tsx") and shutil.which("tsc"):
        proc = subprocess.run(
            ["tsc", "--noEmit", "--pretty", "false"],
            cwd=str(workspace), capture_output=True, text=True, timeout=20,
        )
        pat = re.compile(r"^(.+?)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.*)$")
        target_name = target.name
        for line in (proc.stdout + "\n" + proc.stderr).splitlines():
            m = pat.match(line.strip())
            if m and (m.group(1).endswith(target_name) or target_name in m.group(1)):
                diags.append(Diagnostic(
                    file=display_path, line=int(m.group(2)), col=int(m.group(3)),
                    severity=m.group(4), message=m.group(6), code=m.group(5), source="tsc",
                ))
        return "tsc", diags
    return "none", diags


def _diagnose_go(target: Path, display_path: str) -> tuple[str, list[Diagnostic]]:
    if not shutil.which("go"):
        return "none", []
    proc = subprocess.run(
        ["go", "vet", str(target)],
        cwd=str(target.parent), capture_output=True, text=True, timeout=15,
    )
    diags: list[Diagnostic] = []
    pat = re.compile(r"^.+?:(\d+):(\d+):\s+(.*)$")
    for line in (proc.stderr or "").splitlines():
        m = pat.match(line.strip())
        if m:
            diags.append(Diagnostic(
                file=display_path, line=int(m.group(1)), col=int(m.group(2)),
                severity="error", message=m.group(3), source="go-vet",
            ))
    return "go-vet", diags


def _diagnose_json(target: Path, display_path: str) -> tuple[str, list[Diagnostic]]:
    try:
        json.loads(target.read_text(encoding="utf-8"))
        return "json-parser", []
    except json.JSONDecodeError as exc:
        return "json-parser", [Diagnostic(
            file=display_path, line=exc.lineno, col=exc.colno,
            severity="error", message=exc.msg, code="JSONDecodeError", source="json-parser",
        )]


def _resolve_lsp_cmd(ext: str) -> list[str] | None:
    env_cmd = os.environ.get("BAIZE_LSP_CMD", "").strip()
    if env_cmd:
        return env_cmd.split()
    candidates = {
        ".py": [("pyright-langserver", ["--stdio"]), ("pylsp", [])],
        ".ts": [("typescript-language-server", ["--stdio"])],
        ".tsx": [("typescript-language-server", ["--stdio"])],
        ".go": [("gopls", ["serve"])],
        ".rs": [("rust-analyzer", [])],
    }
    for exe, args in candidates.get(ext, []):
        found = shutil.which(exe)
        if found:
            return [found, *args]
    return None


def diagnose_file(
    file_path: str | Path,
    workspace: str | Path = ".",
    *,
    use_lsp: bool = False,
    lsp_timeout: float = 4.0,
) -> DiagnosticReport:
    """Run immediate diagnostics on a single file (compiler + optional LSP)."""
    t0 = time.perf_counter()
    ws = Path(workspace).resolve()
    target = Path(file_path)
    if not target.is_absolute():
        target = (ws / target).resolve()
    try:
        display = target.relative_to(ws).as_posix()
    except ValueError:
        display = str(target)

    if not target.is_file():
        return DiagnosticReport(
            file=display, backend="missing",
            diagnostics=[Diagnostic(display, 1, 1, "error", f"file not found: {display}", source="fs")],
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        )

    ext = target.suffix.lower()
    backend = "none"
    diags: list[Diagnostic] = []
    notes: list[str] = []

    if ext == ".py":
        backend, diags = _diagnose_python(target, display)
    elif ext in (".js", ".mjs", ".cjs", ".ts", ".tsx"):
        backend, diags = _diagnose_js_ts(target, display, ws)
    elif ext == ".go":
        backend, diags = _diagnose_go(target, display)
    elif ext == ".json":
        backend, diags = _diagnose_json(target, display)

    if use_lsp or os.environ.get("BAIZE_LSP_CMD", "").strip():
        lsp_cmd = _resolve_lsp_cmd(ext)
        if lsp_cmd:
            try:
                lsp_diags = LspClient(lsp_cmd, workspace=ws, timeout=lsp_timeout).diagnose_file(target)
                diags.extend(lsp_diags)
                backend = f"{backend}+lsp" if backend != "none" else "lsp"
            except Exception as exc:
                notes.append(f"LSP unavailable ({exc})")

    return DiagnosticReport(
        file=display,
        backend=backend,
        diagnostics=diags,
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        notes=notes,
    )


def diagnose_workspace(
    workspace: str | Path = ".",
    paths: list[str] | None = None,
    max_files: int = 50,
) -> dict[str, Any]:
    """Run fast syntax/compiler diagnostics across a list of files or Python workspace files."""
    ws = Path(workspace).resolve()
    if paths:
        targets = [Path(p) if Path(p).is_absolute() else ws / p for p in paths]
    else:
        targets = [
            p for p in sorted(ws.rglob("*.py"))
            if not any(part in {".git", "__pycache__", ".venv", "venv", "node_modules", ".baize_checkpoints"}
                       for part in p.parts)
        ][:max_files]

    reports = [diagnose_file(t, workspace=ws) for t in targets]
    total_errors = sum(r.error_count for r in reports)
    total_warnings = sum(r.warning_count for r in reports)
    return {
        "ok": total_errors == 0,
        "files_checked": len(reports),
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "reports": [r.to_dict() for r in reports if not r.ok or r.warning_count > 0],
    }
