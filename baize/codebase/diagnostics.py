"""Polyglot Compiler Diagnostics & Persistent LSP Session Pool (V45.0.0 Nexus).

Pure Python standard library — zero third-party dependencies.
Provides:
1. Immediate single-file & polyglot workspace diagnostics after edits via fast
   local compilers / linters (Python ast + ruff, Node/TypeScript tsc, Go vet,
   Rust cargo check, Java javac, Dart analyze, C/C++ clang/gcc -fsyntax-only,
   JSON parser).
2. Persistent pure-stdlib JSON-RPC 2.0 Content-Length framed stdio LSP client
   with ``LspSessionPool`` (lazy startup, workspace+language reuse, idle
   timeout eviction, graceful shutdown) and semantic navigation primitives:
   - ``definition(file, line, col)``
   - ``references(file, line, col)``
   - ``hover(file, line, col)``
   - ``rename(file, line, col, new_name, apply=False)``
"""
from __future__ import annotations

import ast
import json
import os
import re
import select
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

__all__ = [
    "Diagnostic",
    "DiagnosticReport",
    "LspClient",
    "LspSessionPool",
    "get_lsp_pool",
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
# Pure-stdlib JSON-RPC 2.0 Content-Length framed stdio LSP Client & Pool
# ---------------------------------------------------------------------------
_LSP_SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "info"}

_LANG_ID_BY_EXT = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".dart": "dart",
    ".kt": "kotlin",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
}


def _uri_to_path(uri: str, workspace: Path) -> str:
    """Convert a ``file://`` URI to a workspace-relative POSIX path when possible."""
    if not uri.startswith("file://"):
        return uri
    parsed = urlparse(uri)
    raw_path = unquote(parsed.path)
    # Handle Windows file:///C:/... URIs
    if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    try:
        return Path(raw_path).resolve().relative_to(workspace).as_posix()
    except Exception:
        return raw_path


def _normalize_locations(result: Any, workspace: Path) -> list[dict[str, Any]]:
    """Normalize LSP Location | Location[] | LocationLink[] into uniform dicts."""
    if not result:
        return []
    items = result if isinstance(result, list) else [result]
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri") or item.get("targetUri") or ""
        rng = item.get("range") or item.get("targetSelectionRange") or item.get("targetRange") or {}
        start = rng.get("start") or {}
        end = rng.get("end") or {}
        if not uri:
            continue
        out.append({
            "file": _uri_to_path(str(uri), workspace),
            "uri": str(uri),
            "line": int(start.get("line", 0)) + 1,
            "col": int(start.get("character", 0)) + 1,
            "end_line": int(end.get("line", start.get("line", 0))) + 1,
            "end_col": int(end.get("character", start.get("character", 0))) + 1,
        })
    return out


def _apply_workspace_edit(edit: dict[str, Any], workspace: Path) -> list[dict[str, Any]]:
    """Apply an LSP WorkspaceEdit ``changes`` or ``documentChanges`` safely within workspace."""
    changes_map: dict[str, list[dict[str, Any]]] = {}
    if isinstance(edit.get("changes"), dict):
        for uri, edits in edit["changes"].items():
            if isinstance(edits, list):
                changes_map.setdefault(str(uri), []).extend(edits)
    for dc in edit.get("documentChanges") or []:
        if isinstance(dc, dict) and "textDocument" in dc and isinstance(dc.get("edits"), list):
            uri = str((dc.get("textDocument") or {}).get("uri") or "")
            if uri:
                changes_map.setdefault(uri, []).extend(dc["edits"])

    applied: list[dict[str, Any]] = []
    for uri, edits in changes_map.items():
        parsed = urlparse(uri)
        raw_path = unquote(parsed.path) if uri.startswith("file://") else uri
        if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
            raw_path = raw_path[1:]
        fpath = Path(raw_path).resolve()
        try:
            rel = fpath.relative_to(workspace).as_posix()
        except ValueError:
            # Never mutate files outside workspace boundary
            continue
        if not fpath.is_file():
            continue
        text = fpath.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)

        def _offset(line_idx: int, char_idx: int) -> int:
            off = sum(len(l) for l in lines[:max(0, line_idx)])
            if 0 <= line_idx < len(lines):
                off += min(char_idx, len(lines[line_idx]))
            return off

        spans: list[tuple[int, int, str]] = []
        for e in edits:
            rng = e.get("range") or {}
            st = rng.get("start") or {}
            en = rng.get("end") or {}
            s_off = _offset(int(st.get("line", 0)), int(st.get("character", 0)))
            e_off = _offset(int(en.get("line", 0)), int(en.get("character", 0)))
            spans.append((s_off, e_off, str(e.get("newText", ""))))

        # Apply edits from bottom to top so offsets stay valid
        spans.sort(key=lambda x: (x[0], x[1]), reverse=True)
        buf = text
        for s_off, e_off, new_text in spans:
            buf = buf[:s_off] + new_text + buf[e_off:]
        fpath.write_text(buf, encoding="utf-8")
        applied.append({"file": rel, "edits_applied": len(spans)})
    return applied


class LspClient:
    """Pure-stdlib JSON-RPC 2.0 stdio LSP client supporting persistent sessions."""

    def __init__(self, cmd: list[str], workspace: str | Path = ".",
                 timeout: float = 5.0) -> None:
        self.cmd = list(cmd)
        self.workspace = Path(workspace).resolve()
        self.timeout = timeout
        self._proc: subprocess.Popen[bytes] | None = None
        self._seq = 0
        self._lock = threading.RLock()
        self._doc_versions: dict[str, int] = {}
        self._cached_diagnostics: dict[str, list[Diagnostic]] = {}
        self._initialized = False
        self.last_used = time.monotonic()

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

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

    def _record_publish_diagnostics(self, msg: dict[str, Any]) -> None:
        params = msg.get("params") or {}
        uri = str(params.get("uri") or "")
        display = _uri_to_path(uri, self.workspace) if uri else ""
        items: list[Diagnostic] = []
        for item in params.get("diagnostics") or []:
            rng = (item.get("range") or {}).get("start") or {}
            sev = _LSP_SEVERITY.get(int(item.get("severity", 1)), "error")
            items.append(Diagnostic(
                file=display or uri,
                line=int(rng.get("line", 0)) + 1,
                col=int(rng.get("character", 0)) + 1,
                severity=sev,
                message=str(item.get("message", "")),
                code=str(item.get("code", "")),
                source=str(item.get("source") or "lsp"),
            ))
        if uri:
            self._cached_diagnostics[uri] = items

    def start(self) -> None:
        """Start the persistent LSP server and perform the initialize handshake."""
        with self._lock:
            if self.is_alive() and self._initialized:
                self.last_used = time.monotonic()
                return
            self.close()
            self._proc = subprocess.Popen(
                self.cmd,
                cwd=str(self.workspace),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._doc_versions.clear()
            self._cached_diagnostics.clear()
            deadline = time.monotonic() + self.timeout
            self._seq += 1
            init_id = self._seq
            self._send({
                "jsonrpc": "2.0",
                "id": init_id,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": self.workspace.as_uri(),
                    "capabilities": {
                        "textDocument": {
                            "publishDiagnostics": {},
                            "definition": {},
                            "references": {},
                            "hover": {"contentFormat": ["markdown", "plaintext"]},
                            "rename": {"prepareSupport": False},
                        }
                    },
                },
            })
            while time.monotonic() < deadline:
                msg = self._read_message(deadline)
                if msg is None:
                    break
                if msg.get("method") == "textDocument/publishDiagnostics":
                    self._record_publish_diagnostics(msg)
                if msg.get("id") == init_id:
                    break
            self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
            self._initialized = True
            self.last_used = time.monotonic()

    def close(self) -> None:
        """Gracefully shutdown and terminate the LSP subprocess."""
        with self._lock:
            self._initialized = False
            proc = self._proc
            self._proc = None
            if proc is None:
                return
            try:
                if proc.poll() is None and proc.stdin is not None:
                    self._seq += 1
                    body = json.dumps({"jsonrpc": "2.0", "id": self._seq, "method": "shutdown", "params": None}).encode("utf-8")
                    proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
                    body2 = json.dumps({"jsonrpc": "2.0", "method": "exit"}).encode("utf-8")
                    proc.stdin.write(f"Content-Length: {len(body2)}\r\n\r\n".encode("ascii") + body2)
                    proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=0.5)
                except Exception:
                    pass
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass

    def did_open_or_change(self, file_path: str | Path) -> str:
        """Sync ``file_path`` text into the running LSP server via didOpen or didChange."""
        target = Path(file_path)
        if not target.is_absolute():
            target = (self.workspace / target).resolve()
        else:
            target = target.resolve()
        text = target.read_text(encoding="utf-8", errors="replace")
        uri = target.as_uri()
        lang_id = _LANG_ID_BY_EXT.get(target.suffix.lower(), "plaintext")
        with self._lock:
            if not self.is_alive() or not self._initialized:
                self.start()
            ver = self._doc_versions.get(uri, 0) + 1
            self._doc_versions[uri] = ver
            if ver == 1:
                self._send({
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {
                            "uri": uri,
                            "languageId": lang_id,
                            "version": ver,
                            "text": text,
                        }
                    },
                })
            else:
                self._send({
                    "jsonrpc": "2.0",
                    "method": "textDocument/didChange",
                    "params": {
                        "textDocument": {"uri": uri, "version": ver},
                        "contentChanges": [{"text": text}],
                    },
                })
            self.last_used = time.monotonic()
        return uri

    def _request(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        with self._lock:
            if not self.is_alive() or not self._initialized:
                self.start()
            self._seq += 1
            req_id = self._seq
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
            deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
            self.last_used = time.monotonic()
            while time.monotonic() < deadline:
                msg = self._read_message(deadline)
                if msg is None:
                    return None
                if msg.get("method") == "textDocument/publishDiagnostics":
                    self._record_publish_diagnostics(msg)
                    continue
                if msg.get("id") == req_id:
                    if "error" in msg:
                        err = msg["error"]
                        raise RuntimeError(f"LSP error {err.get('code')}: {err.get('message')}")
                    return msg.get("result")
            return None

    def definition(self, file_path: str | Path, line: int, col: int) -> list[dict[str, Any]]:
        """Go-to-definition at 1-based ``(line, col)``."""
        with self._lock:
            uri = self.did_open_or_change(file_path)
            res = self._request("textDocument/definition", {
                "textDocument": {"uri": uri},
                "position": {"line": max(0, line - 1), "character": max(0, col - 1)},
            })
            return _normalize_locations(res, self.workspace)

    def references(
        self, file_path: str | Path, line: int, col: int, *, include_declaration: bool = True
    ) -> list[dict[str, Any]]:
        """Find all references to symbol at 1-based ``(line, col)``."""
        with self._lock:
            uri = self.did_open_or_change(file_path)
            res = self._request("textDocument/references", {
                "textDocument": {"uri": uri},
                "position": {"line": max(0, line - 1), "character": max(0, col - 1)},
                "context": {"includeDeclaration": include_declaration},
            })
            return _normalize_locations(res, self.workspace)

    def hover(self, file_path: str | Path, line: int, col: int) -> dict[str, Any]:
        """Retrieve type signature / docstring hover at 1-based ``(line, col)``."""
        with self._lock:
            uri = self.did_open_or_change(file_path)
            res = self._request("textDocument/hover", {
                "textDocument": {"uri": uri},
                "position": {"line": max(0, line - 1), "character": max(0, col - 1)},
            })
            if not isinstance(res, dict):
                return {"contents": ""}
            contents = res.get("contents")
            if isinstance(contents, dict):
                text = str(contents.get("value", ""))
            elif isinstance(contents, list):
                parts = []
                for c in contents:
                    parts.append(str(c.get("value", "")) if isinstance(c, dict) else str(c))
                text = "\n".join(p for p in parts if p)
            else:
                text = str(contents or "")
            return {"contents": text, "range": res.get("range")}

    def rename(
        self, file_path: str | Path, line: int, col: int, new_name: str, *, apply: bool = False
    ) -> dict[str, Any]:
        """Compute (and optionally apply) a workspace-wide semantic symbol rename."""
        with self._lock:
            uri = self.did_open_or_change(file_path)
            res = self._request("textDocument/rename", {
                "textDocument": {"uri": uri},
                "position": {"line": max(0, line - 1), "character": max(0, col - 1)},
                "newName": new_name,
            })
            if not isinstance(res, dict):
                return {"ok": False, "applied": False, "files": [], "note": "LSP returned no rename edits"}
            preview_files: list[dict[str, Any]] = []
            changes = res.get("changes") or {}
            if isinstance(changes, dict):
                for u, edits in changes.items():
                    preview_files.append({
                        "file": _uri_to_path(str(u), self.workspace),
                        "edits": len(edits) if isinstance(edits, list) else 0,
                    })
            for dc in res.get("documentChanges") or []:
                if isinstance(dc, dict) and "textDocument" in dc:
                    u = str((dc.get("textDocument") or {}).get("uri") or "")
                    preview_files.append({
                        "file": _uri_to_path(u, self.workspace),
                        "edits": len(dc.get("edits") or []),
                    })
            if apply:
                applied = _apply_workspace_edit(res, self.workspace)
                return {"ok": True, "applied": True, "files": applied}
            return {"ok": True, "applied": False, "files": preview_files, "workspace_edit": res}

    def diagnose_file(self, file_path: str | Path, *, keep_alive: bool = False) -> list[Diagnostic]:
        """Open/update ``file_path`` in the LSP server and collect published diagnostics.

        When ``keep_alive=False`` (default for standalone clients), the server is
        started if needed and shut down afterwards for backward compatibility.
        When managed by :class:`LspSessionPool`, pass ``keep_alive=True``.
        """
        was_running = self.is_alive() and self._initialized
        with self._lock:
            try:
                uri = self.did_open_or_change(file_path)
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    msg = self._read_message(deadline)
                    if msg is None:
                        break
                    if msg.get("method") == "textDocument/publishDiagnostics":
                        self._record_publish_diagnostics(msg)
                        if (msg.get("params") or {}).get("uri") == uri:
                            break
                diags = list(self._cached_diagnostics.get(uri, []))
                # Preserve caller's display path format
                for d in diags:
                    if not d.file:
                        d.file = str(file_path)
                return diags
            finally:
                if not keep_alive and not was_running:
                    self.close()


class LspSessionPool:
    """Process-wide persistent LSP session pool keyed by ``(workspace, lang)``."""

    def __init__(self, idle_timeout: float | None = None) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[tuple[str, str], LspClient] = {}
        self._idle_timeout = idle_timeout

    def _effective_idle_timeout(self) -> float:
        if self._idle_timeout is not None:
            return self._idle_timeout
        try:
            return max(10.0, float(os.environ.get("BAIZE_LSP_IDLE_TIMEOUT", "300") or "300"))
        except ValueError:
            return 300.0

    def evict_idle(self) -> int:
        """Close and remove LSP sessions idle beyond ``BAIZE_LSP_IDLE_TIMEOUT``."""
        now = time.monotonic()
        limit = self._effective_idle_timeout()
        evicted = 0
        with self._lock:
            for key in list(self._sessions.keys()):
                client = self._sessions[key]
                if (not client.is_alive()) or (now - client.last_used > limit):
                    self._sessions.pop(key, None)
                    client.close()
                    evicted += 1
        return evicted

    def get_or_start(
        self,
        file_path: str | Path,
        workspace: str | Path = ".",
        *,
        cmd: list[str] | None = None,
        timeout: float = 5.0,
    ) -> LspClient | None:
        """Return a warm persistent :class:`LspClient` for ``file_path``, or ``None``."""
        self.evict_idle()
        ws = Path(workspace).resolve()
        ext = Path(file_path).suffix.lower()
        lang = _LANG_ID_BY_EXT.get(ext, ext or "unknown")
        resolved_cmd = list(cmd) if cmd else _resolve_lsp_cmd(ext)
        if not resolved_cmd:
            return None
        key = (str(ws), lang)
        with self._lock:
            client = self._sessions.get(key)
            if client is not None and client.is_alive() and client.cmd == resolved_cmd:
                client.last_used = time.monotonic()
                return client
            if client is not None:
                client.close()
            client = LspClient(resolved_cmd, workspace=ws, timeout=timeout)
            client.start()
            self._sessions[key] = client
            return client

    def status(self) -> dict[str, Any]:
        """Return live status of all pooled LSP server processes."""
        self.evict_idle()
        now = time.monotonic()
        with self._lock:
            active = []
            for (ws, lang), client in self._sessions.items():
                active.append({
                    "workspace": ws,
                    "language": lang,
                    "cmd": client.cmd,
                    "alive": client.is_alive(),
                    "idle_seconds": round(max(0.0, now - client.last_used), 1),
                    "open_documents": len(client._doc_versions),
                })
            return {
                "active_count": len(active),
                "idle_timeout_s": self._effective_idle_timeout(),
                "sessions": active,
            }

    def shutdown_all(self) -> int:
        """Gracefully close all running LSP sessions."""
        with self._lock:
            items = list(self._sessions.values())
            self._sessions.clear()
        for client in items:
            try:
                client.close()
            except Exception:
                pass
        return len(items)


_LSP_POOL_LOCK = threading.Lock()
_GLOBAL_LSP_POOL: LspSessionPool | None = None


def get_lsp_pool() -> LspSessionPool:
    """Return the singleton :class:`LspSessionPool`."""
    global _GLOBAL_LSP_POOL
    with _LSP_POOL_LOCK:
        if _GLOBAL_LSP_POOL is None:
            _GLOBAL_LSP_POOL = LspSessionPool()
        return _GLOBAL_LSP_POOL


# ---------------------------------------------------------------------------
# Fast Built-in & Polyglot Compiler Fallback Adapters
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


def _diagnose_rust(target: Path, display_path: str, workspace: Path) -> tuple[str, list[Diagnostic]]:
    if not shutil.which("cargo") or not (workspace / "Cargo.toml").is_file():
        return "none", []
    proc = subprocess.run(
        ["cargo", "check", "--message-format=short"],
        cwd=str(workspace), capture_output=True, text=True, timeout=30,
    )
    diags: list[Diagnostic] = []
    pat = re.compile(r"^(.+?):(\d+):(\d+):\s+(error|warning)(?:\[([^\]]+)\])?:\s+(.*)$")
    target_name = target.name
    for line in (proc.stderr + "\n" + proc.stdout).splitlines():
        m = pat.match(line.strip())
        if m and (m.group(1).endswith(target_name) or target_name in m.group(1)):
            diags.append(Diagnostic(
                file=display_path, line=int(m.group(2)), col=int(m.group(3)),
                severity=m.group(4), message=m.group(6), code=m.group(5) or "", source="cargo-check",
            ))
    return "cargo-check", diags


def _diagnose_java(target: Path, display_path: str) -> tuple[str, list[Diagnostic]]:
    if not shutil.which("javac"):
        return "none", []
    proc = subprocess.run(
        ["javac", "-Xlint:all", "-proc:none", "-d", os.devnull if os.name != "nt" else str(target.parent), str(target)],
        capture_output=True, text=True, timeout=20,
    )
    diags: list[Diagnostic] = []
    pat = re.compile(r"^.+?:(\d+):\s+(error|warning):\s+(.*)$")
    for line in (proc.stderr or "").splitlines():
        m = pat.match(line.strip())
        if m:
            diags.append(Diagnostic(
                file=display_path, line=int(m.group(1)), col=1,
                severity=m.group(2), message=m.group(3), source="javac",
            ))
    return "javac", diags


def _diagnose_dart(target: Path, display_path: str, workspace: Path) -> tuple[str, list[Diagnostic]]:
    if not shutil.which("dart"):
        return "none", []
    proc = subprocess.run(
        ["dart", "analyze", "--format=machine", str(target)],
        cwd=str(workspace), capture_output=True, text=True, timeout=20,
    )
    diags: list[Diagnostic] = []
    # dart machine format: SEVERITY|TYPE|ERROR_CODE|FILE|LINE|COL|LEN|MESSAGE
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 8:
            sev_raw = parts[0].upper()
            sev = "error" if sev_raw == "ERROR" else ("warning" if sev_raw == "WARNING" else "info")
            try:
                ln, cl = int(parts[4]), int(parts[5])
            except ValueError:
                ln, cl = 1, 1
            diags.append(Diagnostic(
                file=display_path, line=ln, col=cl,
                severity=sev, message=parts[7], code=parts[2], source="dart-analyze",
            ))
    return "dart-analyze", diags


def _diagnose_c_cpp(target: Path, display_path: str) -> tuple[str, list[Diagnostic]]:
    ext = target.suffix.lower()
    compilers = ("clang++", "g++", "c++") if ext in (".cpp", ".cc", ".hpp") else ("clang", "gcc", "cc")
    exe = next((shutil.which(c) for c in compilers if shutil.which(c)), None)
    if not exe:
        return "none", []
    proc = subprocess.run(
        [exe, "-fsyntax-only", str(target)],
        capture_output=True, text=True, timeout=15,
    )
    diags: list[Diagnostic] = []
    pat = re.compile(r"^.+?:(\d+):(\d+):\s+(fatal error|error|warning):\s+(.*)$")
    for line in (proc.stderr or "").splitlines():
        m = pat.match(line.strip())
        if m:
            sev = "error" if "error" in m.group(3) else "warning"
            diags.append(Diagnostic(
                file=display_path, line=int(m.group(1)), col=int(m.group(2)),
                severity=sev, message=m.group(4), source=Path(exe).name,
            ))
    return Path(exe).name, diags


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
        ".js": [("typescript-language-server", ["--stdio"])],
        ".jsx": [("typescript-language-server", ["--stdio"])],
        ".go": [("gopls", ["serve"])],
        ".rs": [("rust-analyzer", [])],
        ".dart": [("dart", ["language-server", "--protocol=lsp"])],
        ".java": [("jdtls", [])],
        ".c": [("clangd", [])],
        ".cpp": [("clangd", [])],
        ".cc": [("clangd", [])],
        ".h": [("clangd", [])],
        ".hpp": [("clangd", [])],
        ".kt": [("kotlin-language-server", [])],
        ".swift": [("sourcekit-lsp", [])],
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
    """Run immediate diagnostics on a single file (polyglot compiler + optional pooled LSP)."""
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
    elif ext == ".rs":
        backend, diags = _diagnose_rust(target, display, ws)
    elif ext == ".java":
        backend, diags = _diagnose_java(target, display)
    elif ext == ".dart":
        backend, diags = _diagnose_dart(target, display, ws)
    elif ext in (".c", ".cpp", ".cc", ".h", ".hpp"):
        backend, diags = _diagnose_c_cpp(target, display)
    elif ext == ".json":
        backend, diags = _diagnose_json(target, display)

    if use_lsp or os.environ.get("BAIZE_LSP_CMD", "").strip():
        lsp_cmd = _resolve_lsp_cmd(ext)
        if lsp_cmd:
            try:
                client = get_lsp_pool().get_or_start(target, workspace=ws, cmd=lsp_cmd, timeout=lsp_timeout)
                if client is not None:
                    lsp_diags = client.diagnose_file(target, keep_alive=True)
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


_POLYGLOT_SCAN_EXTS = {
    "python": (".py",),
    "typescript": (".ts", ".tsx", ".js", ".jsx"),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "go": (".go",),
    "rust": (".rs",),
    "java": (".java",),
    "dart": (".dart",),
    "flutter": (".dart",),
    "c_cpp": (".c", ".cpp", ".cc", ".h", ".hpp"),
}
_SKIP_DIAG_DIRS = frozenset({
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".baize_checkpoints", "dist", "build", "target", ".dart_tool",
})


def diagnose_workspace(
    workspace: str | Path = ".",
    paths: list[str] | None = None,
    max_files: int = 50,
) -> dict[str, Any]:
    """Run fast syntax/compiler diagnostics across polyglot workspace files."""
    ws = Path(workspace).resolve()
    if paths:
        targets = [Path(p) if Path(p).is_absolute() else ws / p for p in paths]
    else:
        wanted_exts: set[str] = set()
        try:
            from .project_profile import detect_project_profile
            prof = detect_project_profile(ws)
            for lang in prof.languages:
                wanted_exts.update(_POLYGLOT_SCAN_EXTS.get(lang, ()))
        except Exception:
            pass
        if not wanted_exts:
            wanted_exts = {".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java", ".dart"}

        targets = []
        for root, dirs, files in os.walk(ws):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIAG_DIRS and not d.startswith("."))
            for fn in sorted(files):
                p = Path(root) / fn
                if p.suffix.lower() in wanted_exts:
                    targets.append(p)
                    if len(targets) >= max_files:
                        break
            if len(targets) >= max_files:
                break

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
