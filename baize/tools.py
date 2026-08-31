"""Tool registry - primitives, not baked-in features (pi philosophy).

Every tool is a plain Python function registered with a JSON schema.
Extensions can register their own tools at runtime via `register()`.
Execution is sandbox-aware: file tools are confined to the workspace
root unless BAIZE_ALLOW_OUTSIDE_WORKSPACE=1, and bash commands pass a
deny-list gate (hermes-style command approval, fail-closed).

V33 additions:
- patch_file: precise diff/replace-based edits (no full-overwrite risk)
- fetch_url:  opt-in HTTP retrieval (BAIZE_ALLOW_FETCH_URL=1)
- run_python: AST-whitelist-guarded in-process Python execution
- Schema validation on all tool arguments before dispatch
- Interruptible bash via Popen + proc.kill() on timeout
"""
from __future__ import annotations

import ast
import difflib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import ROOT, load_config
from .logging_setup import redact
from . import memory as memory_mod
from . import skill_index

# ---------------------------------------------------------------------------
# Registry primitives
# ---------------------------------------------------------------------------


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict          # JSON schema for arguments
    fn: Callable[..., str]    # returns a string observation


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, description: str, parameters: dict,
                 fn: Callable[..., str]) -> None:
        self._tools[name] = Tool(name, description, parameters, fn)

    def unregister(self, name: str) -> None:
        """Remove a previously registered tool (used at runtime and in tests)."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Retrieve a registered Tool by name."""
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict]:
        """OpenAI tools array."""
        return [{
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        } for t in self._tools.values()]

    @staticmethod
    def _validate_args(tool: "Tool", arguments: dict) -> str | None:
        """Lightweight JSON Schema validation (V33-A4). Checks required fields
        and type compatibility. Returns an error string or None if valid.
        Type map: string->str, integer->int, number->(int,float), boolean->bool.
        """
        schema = tool.parameters
        props = schema.get("properties", {})
        required = schema.get("required", [])
        _type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for field in required:
            if field not in arguments:
                return (f"ERROR: tool '{tool.name}' missing required argument "
                        f"'{field}'")
        for field, value in arguments.items():
            if field not in props:
                continue  # allow extra args (forward-compat)
            expected_type_name = props[field].get("type", "")
            expected_type = _type_map.get(expected_type_name)
            if expected_type and not isinstance(value, expected_type):
                return (f"ERROR: tool '{tool.name}' argument '{field}' "
                        f"expected {expected_type_name}, "
                        f"got {type(value).__name__}")
        return None

    def execute(self, name: str, arguments: dict) -> str:
        if name not in self._tools:
            return f"ERROR: unknown tool '{name}'"
        tool = self._tools[name]
        # V33-A4: validate arguments against registered schema
        err = self._validate_args(tool, arguments)
        if err:
            return err
        props = tool.parameters.get("properties", {})
        # Filter extra unrecognized kwargs if schema properties are explicitly defined
        call_args = {k: v for k, v in arguments.items() if k in props} if props else arguments
        try:
            return tool.fn(**call_args)
        except TypeError as exc:
            return f"ERROR: bad arguments for '{name}': {exc}"
        except Exception as exc:  # noqa: BLE001 - observation, not crash
            return f"ERROR: tool '{name}' failed: {exc}"


# ---------------------------------------------------------------------------
# Sandbox helpers
# ---------------------------------------------------------------------------

DENY_PATTERNS = [
    # --- original patterns ---
    r"\brm\s+-rf\s+/", r"\brm\s+-rf\s+[A-Za-z]:", r"\bformat\b",
    r"\bmkfs\b", r"\bdel\s+/s\b", r"\bshutdown\b", r"\breboot\b",
    r">\s*/dev/sd", r"\bdd\s+if=",
    # --- bypass closures (V21 P0-1, expert review) ---
    r"--no-preserve-root",                 # defeats `rm -rf /`
    r"\brm\s+-rf\s+~",                     # rm -rf $HOME
    r"\brm\s+-rf\s+\$HOME",                # rm -rf $HOME (expanded later)
    r"\brm\s+-rf\s+/home",                 # rm -rf /home/*
    r"\bdd\s",                             # dd if= or dd of= (disk wipe)
    r":\(\)\s*\{.*\|:",                    # fork bomb  :(){ :|:& };:
    r"\b(?:curl|wget)\b[^\n|]*\|[^\n]*(?:sh|bash)\b",  # curl|sh / wget|bash
]


def _workspace_root(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    return Path(cfg.get("BAIZE_WORKSPACE_DIR", str(ROOT))).resolve()


def _resolve_in_workspace(path_str: str, cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    root = _workspace_root(cfg)
    p = Path(path_str)
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    allow_outside = cfg.get("BAIZE_ALLOW_OUTSIDE_WORKSPACE", "0") == "1"
    if not allow_outside and root not in p.parents and p != root:
        raise PermissionError(
            f"path {p} is outside workspace {root} "
            "(set BAIZE_ALLOW_OUTSIDE_WORKSPACE=1 to permit)")
    return p


def command_allowed(command: str) -> tuple[bool, str]:
    for pat in DENY_PATTERNS:
        if re.search(pat, command, re.IGNORECASE):
            return False, f"blocked by deny pattern: {pat}"
    return True, ""


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------


def _tool_read_file(path: str, start_line: int = 1, end_line: int | None = None,
                    max_lines: int = 400) -> str:
    p = _resolve_in_workspace(path)
    if not p.is_file():
        return f"ERROR: file not found: {p}"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    if total == 0:
        return ""
    s_idx = max(1, start_line) - 1
    if end_line is not None and end_line >= start_line:
        e_idx = min(total, end_line)
    else:
        e_idx = min(total, s_idx + max_lines)
    selected = lines[s_idx:e_idx]
    body = "\n".join(selected)
    if end_line is not None or start_line > 1:
        return body
    suffix = f"\n... ({total - max_lines} more lines)" if total > max_lines else ""
    return body + suffix


def _tool_write_file(path: str, content: str) -> str:
    p = _resolve_in_workspace(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars -> {p}"


def _tool_list_dir(path: str = ".") -> str:
    p = _resolve_in_workspace(path)
    if not p.is_dir():
        return f"ERROR: not a directory: {p}"
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
    return "\n".join(
        f"{'[d]' if e.is_dir() else '[f]'} {e.name}" for e in entries[:200])


def _tool_bash(command: str, timeout: int = 60) -> str:
    """Run a shell command (V33-D2: interruptible via Popen + proc.kill)."""
    ok, reason = command_allowed(command)
    if not ok:
        return f"ERROR: command rejected - {reason}"
    cfg = load_config()
    workspace = str(_workspace_root(cfg))
    if cfg.get("BAIZE_SANDBOX_ENABLED", "0") == "1":
        # Honor a custom sandbox component (BAIZE_COMPONENTS) without editing
        # agent.py; default path returns the same sandbox.run result.
        from . import component
        result = component.resolve_sandbox(
            command, cwd=workspace, timeout=timeout, cfg=cfg)
        out = (result.stdout or "") + (
            ("\n[stderr]\n" + result.stderr) if result.stderr else "")
        out = redact(out)
        prefix = "[sandbox: degraded to logical-only] " if result.degraded else ""
        return prefix + f"exit={result.returncode}\n{out[:8000]}"
    # V35 Windows Native First-Class & V33-D2: Popen-based execution so the process can be killed on timeout
    # rather than leaving a zombie behind. On Windows, routes through PowerShell with POSIX shim & UTF-8.
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    
    try:
        if sys.platform == "win32":
            from .powershell import build_powershell_invocation
            ps_args = build_powershell_invocation(command)
            proc = subprocess.Popen(
                ps_args, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=workspace, encoding="utf-8", errors="replace", env=env)
        else:
            proc = subprocess.Popen(
                command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=workspace, encoding="utf-8", errors="replace", env=env)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()  # drain to avoid deadlock
            return f"ERROR: command timed out after {timeout}s (process killed)"
    except Exception as exc:
        return f"ERROR: failed to launch command: {exc}"
    out = (stdout or "") + (("\n[stderr]\n" + stderr) if stderr else "")
    out = redact(out)
    return f"exit={proc.returncode}\n{out[:8000]}"


# Safe-subset git primitive (V21 P0-1). Executed with shell=False so there is
# no shell-injection surface; only a whitelist of read/commit ops is permitted,
# and option injection (e.g. `-c`, `--exec-path`) is rejected. Confined to the
# workspace by cwd. This makes karpathy_coding's "Git 纯净化" programmatic.
_GIT_ALLOWED = ("status", "add", "commit", "diff", "log", "show", "branch",
                "tag", "mv", "restore", "stash")


def _tool_git(args: str, timeout: int = 60) -> str:
    tokens = args.split()
    if not tokens:
        return "ERROR: git requires a subcommand"
    sub = tokens[0]
    if sub not in _GIT_ALLOWED:
        return (f"ERROR: git subcommand '{sub}' not permitted "
                f"(allowed: {', '.join(_GIT_ALLOWED)})")
    # Reject option injection that could alter git's execution environment.
    for tok in tokens[1:]:
        if (tok == "-c" or tok.startswith("--upload-pack") or
                tok.startswith("--receive-pack") or tok.startswith("--exec") or
                "core.pager" in tok):
            return f"ERROR: git option injection blocked: {tok}"
    cfg = load_config()
    workspace = str(_workspace_root(cfg))
    try:
        proc = subprocess.run(
            ["git", *tokens], shell=False, capture_output=True, text=True,
            timeout=timeout, cwd=workspace,
            encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return f"ERROR: git timed out after {timeout}s"
    except FileNotFoundError:
        # git is not installed on this host; the tool must degrade honestly
        # instead of crashing the caller (tests already gate on this case).
        return "exit=127\ngit executable not found on PATH"
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    out = redact(out)
    return f"exit={proc.returncode}\n{out[:8000]}"


# ---------------------------------------------------------------------------
# V33-A1: patch_file — precise diff/replace editing
# ---------------------------------------------------------------------------


def _tool_patch_file(path: str, old_content: str, new_content: str,
                     mode: str = "replace") -> str:
    """Apply a precise edit to a workspace file (V33-A1).

    mode="replace" (default): exact string match-and-replace. Fails clearly
        if ``old_content`` is not found (no silent no-op).
    mode="diff": apply a unified diff supplied as ``new_content``
        (old_content is ignored, new_content must be a unified diff string).

    This is deliberately safer than ``write_file`` (full overwrite) because
    the model only specifies the delta, not the entire file.
    """
    p = _resolve_in_workspace(path)
    if not p.is_file():
        return f"ERROR: file not found: {p}"
    current = p.read_text(encoding="utf-8", errors="replace")

    if mode == "replace":
        if old_content not in current:
            # Try newline-normalized fallback matching (\r\n vs \n)
            curr_norm = current.replace("\r\n", "\n")
            old_norm = old_content.replace("\r\n", "\n")
            new_norm = new_content.replace("\r\n", "\n")
            if old_norm in curr_norm:
                count_norm = curr_norm.count(old_norm)
                if count_norm == 1:
                    updated = curr_norm.replace(old_norm, new_norm, 1)
                    if "\r\n" in current:
                        updated = updated.replace("\n", "\r\n")
                    p.write_text(updated, encoding="utf-8")
                    lines_before = current.count("\n") + 1
                    lines_after = updated.count("\n") + 1
                    return (f"patched {path} (applied with newline normalization): "
                            f"{lines_before}→{lines_after} lines "
                            f"({len(new_content) - len(old_content):+d} chars)")
            # Provide helpful context: show first 3 lines of old_content
            preview = old_content[:120].replace("\n", "↵")
            return (f"ERROR: patch_file replace failed — old_content not found "
                    f"in {path}. First 120 chars of old_content: {preview!r}. "
                    f"Use read_file to verify the exact text.")
        count = current.count(old_content)
        if count > 1:
            return (f"ERROR: patch_file replace — old_content appears {count} "
                    f"times in {path}. Make old_content more specific to "
                    f"uniquely identify the target.")
        updated = current.replace(old_content, new_content, 1)
        p.write_text(updated, encoding="utf-8")
        lines_before = current.count("\n") + 1
        lines_after = updated.count("\n") + 1
        return (f"patched {path}: {lines_before}→{lines_after} lines "
                f"({len(new_content) - len(old_content):+d} chars)")

    elif mode == "diff":
        # Apply unified diff supplied in new_content
        diff_lines = new_content.splitlines(keepends=True)
        current_lines = current.splitlines(keepends=True)
        # Extract target lines from diff (lines starting with + or space)
        result_lines = []
        in_hunk = False
        for line in diff_lines:
            if line.startswith("@@"):
                in_hunk = True
                continue
            if not in_hunk:
                continue
            if line.startswith("+"):
                result_lines.append(line[1:])
            elif line.startswith("-"):
                pass  # removed
            elif line.startswith(" "):
                result_lines.append(line[1:])
        if not result_lines:
            return "ERROR: patch_file diff — could not parse any lines from diff"
        updated = "".join(result_lines)
        p.write_text(updated, encoding="utf-8")
        return (f"patched {path} via diff: {updated.count(chr(10)) + 1} lines")
    else:
        return f"ERROR: patch_file — unknown mode {mode!r} (use 'replace' or 'diff')"


# ---------------------------------------------------------------------------
# V33-A2: fetch_url — opt-in HTTP retrieval
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")


def _tool_fetch_url(url: str, max_chars: int = 6000) -> str:
    """Fetch a URL and return plain-text content (V33-A2).

    Strips HTML tags, collapses whitespace, and truncates to max_chars.
    Only enabled when BAIZE_ALLOW_FETCH_URL=1 (set at registration time).
    Rejects non-HTTP(S) schemes to prevent SSRF via file:// etc.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"ERROR: fetch_url only supports http/https, got scheme={parsed.scheme!r}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "baize-agent/33.0.0 (fetch_url)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read(131072)  # max 128 KB raw
        content_type = resp.headers.get("Content-Type", "")
        if "charset=" in content_type:
            enc = content_type.split("charset=")[-1].split(";")[0].strip()
        else:
            enc = "utf-8"
        text = raw.decode(enc, errors="replace")
        # Strip HTML tags
        text = _TAG_RE.sub(" ", text)
        # Collapse whitespace
        text = "\n".join(
            _WHITESPACE_RE.sub(" ", line).strip()
            for line in text.splitlines()
            if line.strip()
        )
        return text[:max_chars]
    except urllib.error.HTTPError as exc:
        return f"ERROR: HTTP {exc.code} fetching {url}"
    except urllib.error.URLError as exc:
        return f"ERROR: URL error fetching {url}: {exc.reason}"
    except Exception as exc:
        return f"ERROR: fetch_url failed: {exc}"


# ---------------------------------------------------------------------------
# V33-A3: run_python — AST-whitelist-guarded code execution
# ---------------------------------------------------------------------------

# Allowed top-level AST node types (whitelist = everything NOT in a blacklist
# actually requires inverting: we block specific dangerous constructs via AST)
_PYTHON_BLOCKED_MODULES = frozenset({
    "os", "subprocess", "socket", "shutil", "ctypes", "multiprocessing",
    "threading", "concurrent", "asyncio", "pty", "signal", "resource",
    "gc", "importlib", "pkgutil", "zipimport", "posix", "winreg",
    "_thread", "builtins", "sys", "_frozen_importlib",
})


def _ast_check_python(code: str) -> str | None:
    """AST-level security check for run_python (V33-A3).

    Blocks:
    - import/from-import of blocked modules (os, subprocess, sys, etc.)
    - __import__() calls
    - exec(), eval(), compile(), open() calls
    - sandbox escape via __subclasses__, __bases__, __globals__, __builtins__
    Returns an error string if blocked, None if safe.
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        return f"SyntaxError: {exc}"

    for node in ast.walk(tree):
        # Block import statements
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _PYTHON_BLOCKED_MODULES:
                    return (f"ERROR: run_python blocked — import of "
                            f"'{alias.name}' is not permitted")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in _PYTHON_BLOCKED_MODULES:
                return (f"ERROR: run_python blocked — from '{node.module}' "
                        f"import is not permitted")
        # Block dangerous builtins
        elif isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in ("__import__", "exec", "eval", "compile",
                        "open", "breakpoint"):
                return (f"ERROR: run_python blocked — '{name}()' call "
                        f"is not permitted")
        # Block introspection / sandbox escape attribute access
        elif isinstance(node, ast.Attribute):
            if node.attr in ("__subclasses__", "__bases__", "__globals__", "__builtins__"):
                return (f"ERROR: run_python blocked — attribute '{node.attr}' "
                        f"access is not permitted")
    return None


def _tool_run_python(code: str, timeout: int = 10) -> str:
    """Execute a Python code snippet in a subprocess with AST whitelist guard (V33-A3).

    The code is checked at the AST level before execution — dangerous imports
    and builtins (os, subprocess, exec, eval, open, ...) are blocked.
    Uses the same Python interpreter that is running baize so the stdlib
    version always matches. Output is capped at 4000 chars.
    """
    check_err = _ast_check_python(code)
    if check_err:
        return check_err
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace",
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return f"ERROR: run_python timed out after {timeout}s"
    except Exception as exc:
        return f"ERROR: run_python launch failed: {exc}"
    out = (stdout or "").strip()
    err = (stderr or "").strip()
    parts = []
    if out:
        parts.append(out[:3800])
    if err:
        parts.append(f"[stderr]\n{err[:200]}")
    return "\n".join(parts) if parts else "(no output)"


def _tool_search_skills(keyword: str) -> str:
    hits = skill_index.search(keyword)
    if not hits:
        return "no skills matched"
    return "\n".join(
        f"- {h['name']} [{h['source']}]: {h['description'][:100]} "
        f"(file: {h['skill_file']})" for h in hits[:10])


def _tool_load_skill(skill_file: str) -> str:
    p = Path(skill_file)
    if not p.is_file():
        return f"ERROR: skill file not found: {p}"
    text = p.read_text(encoding="utf-8", errors="replace")
    return text[:12000]


def _tool_memory_recall(keyword: str, tags: str = "") -> str:
    tag_list = [t for t in tags.split(",") if t] or None
    hits = memory_mod.recall(keyword, tags=tag_list)
    if not hits:
        return "no memory matched"
    return "\n".join(f"- [{h['source']}] {h['text']}" for h in hits[:15])


def _tool_memory_log(text: str, tags: str = "") -> str:
    tag_list = [t for t in tags.split(",") if t]
    path = memory_mod.log_event(text, tag_list)
    return f"logged -> {path}"


def _tool_run_skill(name: str, steps_json: str = "[]",
                    verify_json: str = "[]",
                    dependencies_json: str = "[]") -> str:
    """Execute a learned/declared skill via the honest self-evolution loop.

    Parses a structured skill draft, gates it through ``verify_skill_draft``
    (rejects low-quality drafts), runs its steps through the real tool
    registry, verifies, and records the *actual* outcome via
    ``rag.record_skill_outcome``. This is the real call site the self-evolution
    metrics depend on - no success is ever assumed.
    """
    try:
        steps = json.loads(steps_json)
        verify = json.loads(verify_json)
        deps = json.loads(dependencies_json)
    except json.JSONDecodeError as e:
        return f"ERROR: invalid JSON in skill args: {e}"
    draft = {"name": name, "steps": steps, "verify": verify,
             "dependencies": deps}
    from .skill_runner import verify_skill_draft, SkillRunner
    ok, reasons = verify_skill_draft(draft)
    if not ok:
        return "ERROR: skill draft rejected: " + "; ".join(reasons)
    runner = SkillRunner(cfg=load_config())
    res = runner.run(draft)
    return (f"skill '{name}' executed: success={res['success']} "
            f"evidence={res['evidence']}")


def _tool_save_skill(name: str, description: str, body_markdown: str,
                     domain: str = "", level: str = "") -> str:
    """Self-evolving skill loop (hermes trait): the agent persists a new
    skill learned from experience into the *isolated* user skills library
    (V23.2 — no longer pollutes the built-in assets/skills collection)."""
    cfg = load_config()
    skill_file = skill_index.create_skill(
        name, description, body_markdown, domain=domain, level=level,
        origin="agent", cfg=cfg)
    return f"skill saved and indexed -> {skill_file}"


# Process-wide singleton. The agent loop, the orchestrator, and tools registered
# via the tool_sdk decorator all consult this one registry, so a custom tool
# registered anywhere is visible to every Agent/Orchestrator instance. Building
# built-ins once (lazily) also keeps registration O(1) per call.
_DEFAULT_REGISTRY: ToolRegistry | None = None


def default_registry() -> ToolRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        reg = ToolRegistry()
        _s = lambda **props: {  # noqa: E731 - tiny schema helper
            "type": "object",
            "properties": props,
            "required": [k for k, v in props.items() if not v.pop("_opt", False)],
        }
        reg.register("read_file", "Read a text file from the workspace (supports line range slicing).",
                     _s(path={"type": "string"},
                        start_line={"type": "integer", "_opt": True},
                        end_line={"type": "integer", "_opt": True},
                        max_lines={"type": "integer", "_opt": True}),
                     _tool_read_file)
        reg.register("write_file", "Write/overwrite a text file in the workspace.",
                     _s(path={"type": "string"}, content={"type": "string"}),
                     _tool_write_file)
        # V33-A1: precision editing - prefer this over write_file for partial changes
        reg.register("patch_file",
                     "Apply a precise string-replace or unified-diff patch to a "
                     "workspace file. Safer than write_file because only the delta "
                     "is specified. mode='replace' (default) or mode='diff'.",
                     _s(path={"type": "string"},
                        old_content={"type": "string"},
                        new_content={"type": "string"},
                        mode={"type": "string", "_opt": True}),
                     _tool_patch_file)
        reg.register("list_dir", "List entries of a workspace directory.",
                     _s(path={"type": "string", "_opt": True}), _tool_list_dir)
        reg.register("bash", "Run a shell command inside the workspace "
                     "(deny-list gated, 60s timeout, interruptible).",
                     _s(command={"type": "string"},
                        timeout={"type": "integer", "_opt": True}), _tool_bash)
        reg.register("git", "Run a restricted, safe-subset git command inside "
                     "the workspace (shell=False, whitelist only).",
                     _s(args={"type": "string"},
                        timeout={"type": "integer", "_opt": True}), _tool_git)
        # V33-A3: run_python - AST-whitelist-guarded Python snippet execution
        reg.register("run_python",
                     "Execute a Python code snippet in a sandboxed subprocess. "
                     "Dangerous imports (os, subprocess, socket, etc.) and builtins "
                     "(exec, eval, open) are blocked at AST level before execution. "
                     "Output capped at 4000 chars. Prefer bash for shell tasks.",
                     _s(code={"type": "string"},
                        timeout={"type": "integer", "_opt": True}),
                     _tool_run_python)
        reg.register("search_skills", "Search the baize skill index by keyword.",
                     _s(keyword={"type": "string"}), _tool_search_skills)
        reg.register("load_skill", "Load the full SKILL.md content on demand "
                     "(progressive disclosure).",
                     _s(skill_file={"type": "string"}), _tool_load_skill)
        reg.register("memory_recall", "Search persistent memory.",
                     _s(keyword={"type": "string"},
                        tags={"type": "string", "_opt": True}), _tool_memory_recall)
        reg.register("memory_log", "Persist an event to memory.",
                     _s(text={"type": "string"},
                        tags={"type": "string", "_opt": True}), _tool_memory_log)
        reg.register("save_skill", "Persist a newly learned reusable skill "
                     "(self-evolving loop) into the isolated user skills "
                     "library (never the built-in collection).",
                     _s(name={"type": "string"}, description={"type": "string"},
                        body_markdown={"type": "string"},
                        domain={"type": "string", "_opt": True},
                        level={"type": "string", "_opt": True}),
                     _tool_save_skill)
        reg.register("run_skill", "Execute a declared skill through the honest "
                     "self-evolution loop (verify + record outcome).",
                     _s(name={"type": "string"},
                        steps_json={"type": "string", "_opt": True},
                        verify_json={"type": "string", "_opt": True},
                        dependencies_json={"type": "string", "_opt": True}),
                     _tool_run_skill)
        # V33-A2: fetch_url - opt-in HTTP retrieval (BAIZE_ALLOW_FETCH_URL=1)
        cfg = load_config()
        if cfg.get("BAIZE_ALLOW_FETCH_URL", "0") == "1":
            reg.register("fetch_url",
                         "Fetch a URL and return plain-text content (HTML stripped). "
                         "Only enabled when BAIZE_ALLOW_FETCH_URL=1. "
                         "HTTP/HTTPS only. Output capped at 6000 chars.",
                         _s(url={"type": "string"},
                            max_chars={"type": "integer", "_opt": True}),
                         _tool_fetch_url)
        _DEFAULT_REGISTRY = reg
    return _DEFAULT_REGISTRY


# ---------------------------------------------------------------------------
# MCP tool registration — the SINGLE sanctioned entry point from core baize/
# into baize.ext.mcp. The import below is deferred (inside the function body)
# on purpose: it is the only allowed exception to the static "no top-level
# import baize.ext" gate (plan §3.6 / system-design §3.2.M4). The core runtime
# never imports ext at module load, so the zero-dependency red line (A) and the
# fail-closed red line (C) both hold.
# ---------------------------------------------------------------------------

def register_mcp_client(spec, registry: "ToolRegistry | None" = None,
                        transport=None) -> list[str]:
    """Register an external MCP server's tools into ``registry``.

    ``spec`` may be a path to ``mcp_server.json``, a dict with the same shape,
    or an already-built ``MCPServerSpec``. The MCP protocol details stay behind
    this ACL — the core runtime only ever sees wrapped ``Tool`` primitives.

    Fail-closed: any handshake / transport error propagates (no silent skip).
    """
    from .ext.mcp.client import MCPClient, MCPServerSpec

    if isinstance(spec, MCPServerSpec):
        client_spec = spec
    elif isinstance(spec, str):
        client_spec = MCPClient.from_spec_file(spec, transport=transport).spec
    elif isinstance(spec, dict):
        client_spec = MCPServerSpec(
            name=spec["name"], command=spec["command"],
            args=spec.get("args", []), env=spec.get("env", {}),
            protocol_version=spec.get("protocol_version", "2024-11-05"))
    else:
        raise TypeError(f"unsupported MCP spec type: {type(spec).__name__}")

    reg = registry or default_registry()
    client = MCPClient(client_spec, transport=transport)
    client.connect()
    client.list_tools()
    return client.register_into(reg)
