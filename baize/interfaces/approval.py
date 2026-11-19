"""V41 Tiered Interactive Approval, ANSI Diff Preview & Terminal Status Bar.

Pure Python standard library (difflib + ANSI escape sequences).
Supports three approval policies:
  - ``tiered`` (default interactive): read-only tools auto-allow; file writes/patches
    render a colourised Unified Diff and shell/bg commands display the exact command
    with ``[y] allow once / [a] allow for session / [n] deny (+ optional reason)``.
  - ``auto``: never prompts (guardrails & sandbox still apply).
  - ``strict``: prompts on every mutating or shell tool call.
"""

from __future__ import annotations

import difflib
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ANSI helpers (auto-disabled when not a TTY or NO_COLOR is set)
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"

VALID_APPROVAL_MODES = frozenset({"tiered", "auto", "strict"})

READ_ONLY_APPROVAL_TOOLS = frozenset({
    "read_file",
    "list_dir",
    "find_files",
    "grep_search",
    "blast_radius",
    "diagnostics",
    "search_skills",
    "load_skill",
    "memory_recall",
    "tool_search",
    "bash_bg_output",
})

MUTATING_TOOLS = frozenset({
    "write_file",
    "patch_file",
    "bash",
    "git",
    "run_python",
    "bash_bg_start",
    "bash_bg_stop",
    "save_skill",
    "run_skill",
    "memory_log",
    "memory_profile",
})


def supports_color(stream=None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    s = stream or sys.stdout
    try:
        return bool(s.isatty())
    except Exception:
        return False


def render_unified_diff(
    path: str,
    old_text: str,
    new_text: str,
    *,
    color: bool = True,
    max_lines: int = 80,
) -> str:
    """Render a clean unified diff with optional ANSI red/green highlighting."""
    diff_lines = list(
        difflib.unified_diff(
            (old_text or "").splitlines(),
            (new_text or "").splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
            n=3,
        )
    )
    if not diff_lines:
        return f"(no textual changes to {path})"
    truncated = 0
    if len(diff_lines) > max_lines:
        truncated = len(diff_lines) - max_lines
        diff_lines = diff_lines[:max_lines]

    out: list[str] = []
    for line in diff_lines:
        if not color:
            out.append(line)
        elif line.startswith("+++") or line.startswith("---"):
            out.append(f"{_BOLD}{line}{_RESET}")
        elif line.startswith("@@"):
            out.append(f"{_CYAN}{line}{_RESET}")
        elif line.startswith("+"):
            out.append(f"{_GREEN}{line}{_RESET}")
        elif line.startswith("-"):
            out.append(f"{_RED}{line}{_RESET}")
        else:
            out.append(f"{_DIM}{line}{_RESET}")
    if truncated:
        note = f"... ({truncated} more diff lines omitted)"
        out.append(f"{_DIM}{note}{_RESET}" if color else note)
    return "\n".join(out)


def build_tool_preview(tool_name: str, args: dict[str, Any], workspace: str = ".", *, color: bool = True) -> str:
    """Build a human-readable preview (Unified Diff for edits, command for bash/git)."""
    if tool_name in ("write_file", "patch_file"):
        rel = str(args.get("path") or "")
        target = Path(workspace) / rel
        old_text = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
        if tool_name == "write_file":
            new_text = str(args.get("content") or "")
        else:
            old_snip = str(args.get("old_content") or "")
            new_snip = str(args.get("new_content") or "")
            if old_snip and old_snip in old_text:
                new_text = old_text.replace(old_snip, new_snip, 1)
            else:
                new_text = old_text + ("\n" + new_snip if new_snip else "")
        return render_unified_diff(rel or "file", old_text, new_text, color=color)

    if tool_name in ("bash", "bash_bg_start"):
        cmd = str(args.get("command") or "")
        tag = "BG-CMD" if tool_name == "bash_bg_start" else "BASH"
        return f"{_YELLOW}{_BOLD}[{tag}]{_RESET} {cmd}" if color else f"[{tag}] {cmd}"

    if tool_name == "git":
        return f"{_YELLOW}[GIT]{_RESET} git {args.get('args', '')}" if color else f"[GIT] git {args.get('args', '')}"

    return f"[{tool_name}] {args}"


@dataclass
class ApprovalRequest:
    tool_name: str
    arguments: dict[str, Any]
    preview: str
    risk: str = "medium"
    request_id: str = ""


@dataclass
class ApprovalDecision:
    approved: bool
    scope: str = "once"  # once | session | denied
    reason: str = ""


class TieredApprovalPolicy:
    """Stateful session approval policy implementing tiered read/write gating."""

    def __init__(self, mode: str = "tiered") -> None:
        m = (mode or "tiered").strip().lower()
        self.mode = m if m in VALID_APPROVAL_MODES else "tiered"
        self.session_allowed_tools: set[str] = set()
        self.session_allowed_cmd_prefixes: set[str] = set()

    def requires_approval(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        if self.mode == "auto":
            return False
        if tool_name in READ_ONLY_APPROVAL_TOOLS:
            return False
        if self.mode == "tiered":
            if tool_name in self.session_allowed_tools:
                return False
            if tool_name in ("bash", "bash_bg_start"):
                cmd = str(arguments.get("command") or "").strip()
                prefix = cmd.split()[0] if cmd else ""
                if prefix and prefix in self.session_allowed_cmd_prefixes:
                    return False
        return True

    def record_session_allow(self, tool_name: str, arguments: dict[str, Any]) -> None:
        if tool_name in ("bash", "bash_bg_start"):
            cmd = str(arguments.get("command") or "").strip()
            prefix = cmd.split()[0] if cmd else ""
            if prefix:
                self.session_allowed_cmd_prefixes.add(prefix)
            else:
                self.session_allowed_tools.add(tool_name)
        else:
            self.session_allowed_tools.add(tool_name)


def make_terminal_approval_callback(
    policy: TieredApprovalPolicy,
    *,
    workspace: str = ".",
    input_fn: Callable[[str], str] = input,
    output_stream=None,
) -> Callable[[ApprovalRequest], ApprovalDecision]:
    """Create an interactive terminal approval callback with y/a/n + optional denial feedback."""
    out = output_stream or sys.stdout
    use_color = supports_color(out)

    def _cb(req: ApprovalRequest) -> ApprovalDecision:
        if not policy.requires_approval(req.tool_name, req.arguments):
            return ApprovalDecision(approved=True, scope="session")
        preview = req.preview or build_tool_preview(req.tool_name, req.arguments, workspace, color=use_color)
        header = (
            f"\n{_YELLOW}{_BOLD}[APPROVAL REQUIRED]{_RESET} tool={req.tool_name}\n"
            if use_color
            else f"\n[APPROVAL REQUIRED] tool={req.tool_name}\n"
        )
        out.write(header + preview + "\n")
        out.flush()
        try:
            ans = input_fn("Allow? [y] once / [a] session / [n] deny (or type denial reason): ").strip()
        except (EOFError, KeyboardInterrupt):
            return ApprovalDecision(approved=False, scope="denied", reason="Interrupted by user")

        low = ans.lower()
        if low in ("y", "yes", ""):
            return ApprovalDecision(approved=True, scope="once")
        if low in ("a", "all", "session"):
            policy.record_session_allow(req.tool_name, req.arguments)
            return ApprovalDecision(approved=True, scope="session")
        if low in ("n", "no"):
            return ApprovalDecision(approved=False, scope="denied", reason="Denied by user")
        # Treat free-form text starting with "n " or arbitrary feedback as a guided denial
        reason = ans[2:].strip() if low.startswith("n ") else ans
        return ApprovalDecision(approved=False, scope="denied", reason=reason or "Denied by user")

    return _cb


def format_status_bar(
    *,
    model: str,
    profile: str,
    active_tools: int,
    context_ratio: float,
    cache_hit_ratio: float = 0.0,
    checkpoint_id: str = "",
    bg_procs: int = 0,
    color: bool = True,
) -> str:
    """Format a compact one-line terminal telemetry bar."""
    ctx_pct = int(round(context_ratio * 100))
    cache_pct = int(round(cache_hit_ratio * 100))
    parts = [
        f"model={model or 'unset'}",
        f"tools={profile}({active_tools})",
        f"ctx={ctx_pct}%",
        f"cache={cache_pct}%",
    ]
    if checkpoint_id:
        parts.append(f"ckpt={checkpoint_id[:12]}")
    if bg_procs > 0:
        parts.append(f"bg={bg_procs}")
    bar = " | ".join(parts)
    if not color:
        return f"[{bar}]"
    ctx_col = _RED if ctx_pct >= 85 else (_YELLOW if ctx_pct >= 70 else _CYAN)
    return f"{_DIM}[{_RESET}{ctx_col}{bar}{_RESET}{_DIM}]{_RESET}"
