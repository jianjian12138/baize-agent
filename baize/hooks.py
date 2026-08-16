"""V21 P1-1: lifecycle hook bus + pre_tool_use gate (stdlib-only, fail-closed).

Hooks are the "rules the model cannot violate" layer (Claude Code's
PreToolUse analog, hardened). They are loaded from a committable
``.baize/hooks.json``, or supplied in-process as inline callables (tests /
embedding).

Handler types (zero third-party deps):
  - ``command``: shell out, pass JSON on stdin, read the exit code:
        0  -> allow
        2  -> deny  (BLOCK for pre_tool_use)
      other -> non-blocking error (allow but record in observability)
      crash / timeout -> fail-closed: treated as deny for pre_tool_use,
                         recorded (never silently ignored) for other events.
  - ``inline``: a python callable(payload) -> bool | (bool, reason) | dict |
        HookDecision.

HTTP / MCP handlers are intentionally NOT implemented (they would pull
network/deps); the ``Hook`` schema stays stable for future optional adapters
that default to OFF.

Fail-closed is the whole point: a hook that throws or times out must never
result in a silently-permitted tool call.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .observability import obs

# --- lifecycle event names (first batch, extensible) -----------------------
EVENT_SESSION_START = "session_start"
EVENT_USER_PROMPT_SUBMIT = "user_prompt_submit"
EVENT_PRE_TOOL_USE = "pre_tool_use"
EVENT_POST_TOOL_USE = "post_tool_use"
EVENT_POST_TOOL_USE_FAILURE = "post_tool_use_failure"
EVENT_PRE_SUBTASK = "pre_subtask"
EVENT_POST_SUBTASK = "post_subtask"
EVENT_PRE_COMPACT = "pre_compact"
EVENT_SESSION_END = "session_end"

# Events whose hooks may return a *blocking* decision. Everything else fires
# for side effects / observability only and never gates the flow.
_GATING_EVENTS = frozenset({EVENT_PRE_TOOL_USE})

# Events that consume a ``matcher`` (tool name / regex / "*").
_MATCHING_EVENTS = frozenset({
    EVENT_PRE_TOOL_USE, EVENT_POST_TOOL_USE, EVENT_POST_TOOL_USE_FAILURE,
})


@dataclass
class Hook:
    """A single hook declaration.

    For ``command`` handlers ``command`` is a shell string; for ``inline``
    handlers ``callable`` is a python callable. ``matcher`` is only meaningful
    for the tool-use events.
    """
    event: str
    matcher: str = "*"                 # tool name (exact), regex, or "*"
    handler_type: str = "command"      # command | inline
    command: str = ""
    callable: object = None            # inline only
    timeout: float = 5.0


@dataclass
class HookDecision:
    allow: bool
    reason: str = ""
    decision: str = "allow"            # allow | deny | non_blocking_error | fail_closed


def _matcher_matches(matcher: str, tool: str) -> bool:
    """Match a tool name against a hook matcher (exact, regex, or '*')."""
    if matcher in ("*", "", None):
        return True
    if matcher == tool:
        return True
    try:
        if re.fullmatch(matcher, tool):
            return True
    except re.error:
        pass
    return matcher in tool             # gentle substring fallback


class HookRegistry:
    """A collection of hooks with dispatch + lifecycle helpers."""

    def __init__(self, hooks: list[Hook] | None = None):
        self._hooks: list[Hook] = list(hooks or [])

    # -- loading ------------------------------------------------------------
    @classmethod
    def from_config(cls, cfg: dict | None = None) -> "HookRegistry":
        cfg = cfg or {}
        path = cfg.get("BAIZE_HOOKS_FILE", "")
        if path:
            return cls.from_file(path)
        return cls([])

    @classmethod
    def from_file(cls, path) -> "HookRegistry":
        p = Path(path)
        if not p.exists():
            return cls([])
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            obs.record_error("hooks_load_failed")
            return cls([])
        if not isinstance(data, dict):
            obs.record_error("hooks_load_failed")
            return cls([])
        hs: list[Hook] = []
        for h in data.get("hooks", []):
            if not isinstance(h, dict):
                continue
            try:
                hs.append(Hook(
                    event=str(h.get("event", "")),
                    matcher=str(h.get("matcher", "*")),
                    handler_type=str(h.get("handler", "command")),
                    command=str(h.get("command", "")),
                    timeout=float(h.get("timeout", 5.0)),
                ))
            except (ValueError, TypeError):
                obs.record_error("hooks_entry_invalid")
        return cls(hs)

    def register(self, hook: Hook) -> None:
        self._hooks.append(hook)

    def __len__(self) -> int:
        return len(self._hooks)

    def __iter__(self):
        return iter(self._hooks)

    # -- dispatch -----------------------------------------------------------
    def dispatch(self, event: str, payload: dict | None = None) -> list[HookDecision]:
        payload = dict(payload or {})
        payload["event"] = event
        out: list[HookDecision] = []
        for hook in self._hooks:
            if hook.event != event:
                continue
            if event in _MATCHING_EVENTS:
                if not _matcher_matches(hook.matcher, payload.get("tool", "")):
                    continue
            out.append(self._run(hook, payload))
        return out

    def _run(self, hook: Hook, payload: dict) -> HookDecision:
        try:
            if hook.handler_type == "inline":
                if hook.callable is None:
                    return HookDecision(False, "inline handler missing callable",
                                        "fail_closed")
                return self._normalize(hook.callable(payload))
            if hook.handler_type == "command":
                return self._run_command(hook, payload)
            return HookDecision(False, f"unknown handler_type {hook.handler_type!r}",
                                "fail_closed")
        except Exception as e:  # noqa: BLE001 - fail-closed, never crash the caller
            obs.record_error("hook_crashed")
            return HookDecision(False, f"hook crashed (fail-closed): {e}",
                                "fail_closed")

    def _run_command(self, hook: Hook, payload: dict) -> HookDecision:
        if not hook.command:
            return HookDecision(False, "command hook missing command", "fail_closed")
        try:
            proc = subprocess.run(
                hook.command, shell=True, input=json.dumps(payload),
                capture_output=True, encoding="utf-8", errors="replace",
                timeout=hook.timeout)
        except subprocess.TimeoutExpired:
            obs.record_error("hook_timeout")
            return HookDecision(False, f"hook timed out after {hook.timeout}s",
                                "fail_closed")
        except Exception as e:  # noqa: BLE001
            obs.record_error("hook_exec_failed")
            return HookDecision(False, f"hook exec failed (fail-closed): {e}",
                                "fail_closed")
        rc = proc.returncode
        stderr = (proc.stderr or "").strip()
        if rc == 0:
            return HookDecision(True, stderr or "allowed", "allow")
        if rc == 2:
            return HookDecision(False, stderr or "blocked by hook (exit 2)", "deny")
        # Any other non-zero exit is a *non-blocking* error: allow but record,
        # so a misconfigured hook cannot silently break the run.
        obs.record_error("hook_non_blocking_error")
        return HookDecision(
            True, f"hook returned {rc} (non-blocking): {stderr}",
            "non_blocking_error")

    @staticmethod
    def _normalize(res) -> HookDecision:
        """Coerce an inline handler's return value into a HookDecision."""
        if isinstance(res, HookDecision):
            return res
        if isinstance(res, bool):
            return HookDecision(res, "" if res else "inline denied",
                                "allow" if res else "deny")
        if isinstance(res, tuple) and len(res) == 2:
            allow, reason = res
            return HookDecision(bool(allow), str(reason),
                                "allow" if allow else "deny")
        if isinstance(res, dict):
            allow = bool(res.get("allow", True))
            return HookDecision(allow, str(res.get("reason", "")),
                                "allow" if allow else "deny")
        return HookDecision(True, "", "allow")

    # -- gating helpers -----------------------------------------------------
    def pre_tool_use(self, tool_name: str, args: dict) -> HookDecision:
        """Gate a tool call. Returns the first blocking decision (if any)."""
        for d in self.dispatch(EVENT_PRE_TOOL_USE,
                               {"tool": tool_name, "args": args}):
            if not d.allow:
                return d
        return HookDecision(True, "no blocking hook", "allow")

    def post_tool_use(self, tool_name: str, args: dict,
                      observation: str) -> list[HookDecision]:
        return self.dispatch(EVENT_POST_TOOL_USE,
                             {"tool": tool_name, "args": args,
                              "observation": observation[:2000]})

    def post_tool_use_failure(self, tool_name: str, args: dict,
                              error: str) -> list[HookDecision]:
        return self.dispatch(EVENT_POST_TOOL_USE_FAILURE,
                             {"tool": tool_name, "args": args,
                              "error": str(error)[:1000]})

    # -- lifecycle shortcuts (fire-and-forget; errors are recorded, not fatal)
    def session_start(self, goal: str) -> list[HookDecision]:
        return self.dispatch(EVENT_SESSION_START, {"goal": goal})

    def user_prompt_submit(self, text: str) -> list[HookDecision]:
        return self.dispatch(EVENT_USER_PROMPT_SUBMIT, {"text": text})

    def pre_subtask(self, sub: dict) -> list[HookDecision]:
        return self.dispatch(EVENT_PRE_SUBTASK, {"subtask": sub})

    def post_subtask(self, report) -> list[HookDecision]:
        return self.dispatch(EVENT_POST_SUBTASK, {"report": report})

    def pre_compact(self, n: int) -> list[HookDecision]:
        return self.dispatch(EVENT_PRE_COMPACT, {"n": n})

    def session_end(self, result) -> list[HookDecision]:
        return self.dispatch(EVENT_SESSION_END, {"result": result})
