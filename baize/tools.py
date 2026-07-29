"""Tool registry - primitives, not baked-in features (pi philosophy).

Every tool is a plain Python function registered with a JSON schema.
Extensions can register their own tools at runtime via `register()`.
Execution is sandbox-aware: file tools are confined to the workspace
root unless BAIZE_ALLOW_OUTSIDE_WORKSPACE=1, and bash commands pass a
deny-list gate (hermes-style command approval, fail-closed).
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import ROOT, load_config
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

    def execute(self, name: str, arguments: dict) -> str:
        if name not in self._tools:
            return f"ERROR: unknown tool '{name}'"
        try:
            return self._tools[name].fn(**arguments)
        except TypeError as exc:
            return f"ERROR: bad arguments for '{name}': {exc}"
        except Exception as exc:  # noqa: BLE001 - observation, not crash
            return f"ERROR: tool '{name}' failed: {exc}"


# ---------------------------------------------------------------------------
# Sandbox helpers
# ---------------------------------------------------------------------------

DENY_PATTERNS = [
    r"\brm\s+-rf\s+/", r"\brm\s+-rf\s+[A-Za-z]:", r"\bformat\b",
    r"\bmkfs\b", r"\bdel\s+/s\b", r"\bshutdown\b", r"\breboot\b",
    r">\s*/dev/sd", r"\bdd\s+if=",
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


def _tool_read_file(path: str, max_lines: int = 400) -> str:
    p = _resolve_in_workspace(path)
    if not p.is_file():
        return f"ERROR: file not found: {p}"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    body = "\n".join(lines[:max_lines])
    suffix = f"\n... ({len(lines) - max_lines} more lines)" if len(lines) > max_lines else ""
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
    ok, reason = command_allowed(command)
    if not ok:
        return f"ERROR: command rejected - {reason}"
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(_workspace_root()),
            encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s"
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    return f"exit={proc.returncode}\n{out[:8000]}"


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


def _tool_save_skill(name: str, description: str, body_markdown: str) -> str:
    """Self-evolving skill loop (hermes trait): the agent persists a new
    skill learned from experience into assets/skills/learned/."""
    cfg = load_config()
    safe = re.sub(r"[^a-z0-9_-]", "-", name.lower()).strip("-") or "unnamed"
    skill_dir = Path(cfg["BAIZE_ASSETS_DIR"]) / "skills" / "learned" / safe
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        f"---\nname: {safe}\ndescription: {description}\n"
        f"origin: agent-learned\n---\n\n{body_markdown}\n",
        encoding="utf-8")
    skill_index.build_index(cfg)  # re-index so it is immediately findable
    return f"skill saved and indexed -> {skill_file}"


def default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    _s = lambda **props: {  # noqa: E731 - tiny schema helper
        "type": "object",
        "properties": props,
        "required": [k for k, v in props.items() if not v.pop("_opt", False)],
    }
    reg.register("read_file", "Read a text file from the workspace.",
                 _s(path={"type": "string"}), _tool_read_file)
    reg.register("write_file", "Write/overwrite a text file in the workspace.",
                 _s(path={"type": "string"}, content={"type": "string"}),
                 _tool_write_file)
    reg.register("list_dir", "List entries of a workspace directory.",
                 _s(path={"type": "string", "_opt": True}), _tool_list_dir)
    reg.register("bash", "Run a shell command inside the workspace "
                 "(deny-list gated, 60s timeout).",
                 _s(command={"type": "string"}), _tool_bash)
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
                 "(self-evolving loop).",
                 _s(name={"type": "string"}, description={"type": "string"},
                    body_markdown={"type": "string"}), _tool_save_skill)
    return reg
