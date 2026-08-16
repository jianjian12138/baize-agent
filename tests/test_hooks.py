"""Tests for baize.hooks - V21 P1-1 lifecycle hook bus + pre_tool_use gate.

Covers the acceptance criteria from the P1-P3 plan:
  ① event bus + all first-batch events
  ② command hook exit-code 3-state semantics (0 allow / 2 deny / other non-block)
  ③ pre_tool_use deny truly blocks a tool (incl. malicious-command interception
     reusing tools.command_allowed / DENY_PATTERNS)
  ④ hook crash / timeout fail-closed
  ⑤ zero third-party dependencies
"""
from __future__ import annotations

import json
from pathlib import Path

from baize.agent import Agent
from baize.config import load_config
from baize.hooks import (
    EVENT_POST_SUBTASK,
    EVENT_PRE_SUBTASK,
    EVENT_PRE_TOOL_USE,
    EVENT_SESSION_END,
    EVENT_SESSION_START,
    EVENT_USER_PROMPT_SUBMIT,
    Hook,
    HookRegistry,
    _matcher_matches,
)
from baize.llm import LLMClient
from baize.orchestrator import Orchestrator
from baize.tools import ToolRegistry, command_allowed


# --- helpers (scripted model + tool-call builder) -------------------------

def scripted_client(cfg, replies):
    queue = list(replies)

    def transport(url, headers, payload):
        msg = queue.pop(0)
        if isinstance(msg, str):        # bare text -> content-wrapped message
            msg = {"content": msg}
        return {"choices": [{"message": msg}]}

    return LLMClient(cfg=cfg, transport=transport)


def tool_call(name, args, call_id="c1"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def register_echo(reg):
    reg.register("echo", "echo text back",
                 {"type": "object",
                  "properties": {"text": {"type": "string"}},
                  "required": ["text"]},
                 lambda text: f"ECHO:{text}")


# --- ② command hook exit-code 3-state semantics ---------------------------

def test_command_hook_allow_on_exit0():
    hooks = HookRegistry([Hook(EVENT_PRE_TOOL_USE, "*", "command",
                               command="exit 0")])
    d = hooks.pre_tool_use("bash", {"command": "ls"})
    assert d.allow and d.decision == "allow"


def test_command_hook_deny_on_exit2():
    hooks = HookRegistry([Hook(EVENT_PRE_TOOL_USE, "*", "command",
                               command="exit 2")])
    d = hooks.pre_tool_use("bash", {"command": "ls"})
    assert not d.allow and d.decision == "deny"


def test_command_hook_nonblocking_on_other_exit():
    hooks = HookRegistry([Hook(EVENT_PRE_TOOL_USE, "*", "command",
                               command="exit 3")])
    # other non-zero exit = allow but record (non-blocking error)
    decisions = hooks.dispatch(
        EVENT_PRE_TOOL_USE, {"tool": "bash", "args": {"command": "ls"}})
    assert len(decisions) == 1
    d = decisions[0]
    assert d.allow and d.decision == "non_blocking_error"
    # and crucially: a non-blocking error does NOT gate the tool call
    assert hooks.pre_tool_use("bash", {"command": "ls"}).allow


def test_command_hook_missing_command_fail_closed():
    hooks = HookRegistry([Hook(EVENT_PRE_TOOL_USE, "*", "command",
                               command="")])
    d = hooks.pre_tool_use("bash", {"command": "ls"})
    assert not d.allow and d.decision == "fail_closed"


# --- inline handler normalization -----------------------------------------

def test_inline_hook_bool_and_tuple_and_dict():
    assert HookRegistry._normalize(True).allow
    nd = HookRegistry._normalize(False)
    assert not nd.allow and nd.decision == "deny"
    t = HookRegistry._normalize((False, "nope"))
    assert not t.allow and t.reason == "nope"
    d = HookRegistry._normalize({"allow": True, "reason": "ok"})
    assert d.allow and d.reason == "ok"


def test_inline_hook_missing_callable_fail_closed():
    hooks = HookRegistry([Hook(EVENT_PRE_TOOL_USE, "*", "inline",
                               callable=None)])
    d = hooks.pre_tool_use("bash", {})
    assert not d.allow and d.decision == "fail_closed"


def test_inline_hook_unknown_handler_type_fail_closed():
    hooks = HookRegistry([Hook(EVENT_PRE_TOOL_USE, "*", "bogus",
                               callable=lambda p: True)])
    d = hooks.pre_tool_use("bash", {})
    assert not d.allow and d.decision == "fail_closed"


# --- matcher ---------------------------------------------------------------

def test_matcher_exact_regex_star():
    assert _matcher_matches("*", "bash")
    assert _matcher_matches("bash", "bash")
    assert not _matcher_matches("bash", "write_file")
    assert _matcher_matches(r"bash|sh", "sh")          # regex
    assert _matcher_matches("write", "write_file")     # substring fallback


# --- ③ pre_tool_use deny blocks + malicious-command interception -----------

def _guard_reusing_deny_patterns(payload):
    """Reuse tools.command_allowed (DENY_PATTERNS) to deny dangerous bash."""
    if payload.get("tool") == "bash":
        cmd = payload.get("args", {}).get("command", "")
        ok, reason = command_allowed(cmd)
        if not ok:
            return False, f"denied: {reason}"
    return True, ""


def test_pre_tool_use_blocks_malicious_bash(env):
    ran = []
    reg = ToolRegistry()
    reg.register("bash", "run a command",
                 {"type": "object",
                  "properties": {"command": {"type": "string"}},
                  "required": ["command"]},
                 lambda command: ran.append(command) or f"ran: {command}")
    hooks = HookRegistry([Hook(EVENT_PRE_TOOL_USE, "*", "inline",
                               callable=_guard_reusing_deny_patterns)])
    client = scripted_client(env, [
        {"content": None,
         "tool_calls": [tool_call("bash", {"command": "rm -rf /"})]},
        {"content": "stopped"},
    ])
    agent = Agent(cfg=env, client=client, registry=reg, hooks=hooks)
    res = agent.run("delete everything")

    # The tool must NOT have executed - the hook blocked it first.
    assert ran == []
    tool_msgs = [m for m in agent.session.messages if m.get("role") == "tool"]
    assert tool_msgs and "blocked by pre_tool_use hook" in tool_msgs[0]["content"]
    assert res.stopped_reason == "final"


def test_pre_tool_use_allows_safe_bash(env):
    ran = []
    reg = ToolRegistry()
    reg.register("bash", "run a command",
                 {"type": "object",
                  "properties": {"command": {"type": "string"}},
                  "required": ["command"]},
                 lambda command: ran.append(command) or f"ran: {command}")
    hooks = HookRegistry([Hook(EVENT_PRE_TOOL_USE, "*", "inline",
                               callable=_guard_reusing_deny_patterns)])
    client = scripted_client(env, [
        {"content": None,
         "tool_calls": [tool_call("bash", {"command": "echo safe"})]},
        {"content": "done"},
    ])
    agent = Agent(cfg=env, client=client, registry=reg, hooks=hooks)
    res = agent.run("run a safe command")
    assert ran == ["echo safe"]
    assert res.stopped_reason == "final"


# --- ④ crash / timeout fail-closed ----------------------------------------

def test_pre_tool_use_crash_fail_closed(env):
    def boom(payload):
        raise RuntimeError("hook exploded")

    ran = []
    reg = ToolRegistry()
    register_echo(reg)
    reg._tools["echo"].fn = lambda text: ran.append(text) or f"ECHO:{text}"
    hooks = HookRegistry([Hook(EVENT_PRE_TOOL_USE, "*", "inline",
                               callable=boom)])
    client = scripted_client(env, [
        {"content": None, "tool_calls": [tool_call("echo", {"text": "x"})]},
        {"content": "done"},
    ])
    agent = Agent(cfg=env, client=client, registry=reg, hooks=hooks)
    res = agent.run("goal")
    # crash => fail-closed => tool blocked
    assert ran == []
    tool_msgs = [m for m in agent.session.messages if m.get("role") == "tool"]
    assert "blocked by pre_tool_use hook" in tool_msgs[0]["content"]


def test_command_hook_timeout_fail_closed():
    # `ping -n 12 127.0.0.1` reliably hangs ~11s on the loopback; we cut it at
    # 0.5s, so this exercises the timeout fail-closed path (not a quick rc).
    hooks = HookRegistry([Hook(EVENT_PRE_TOOL_USE, "*", "command",
                               command="ping -n 12 127.0.0.1", timeout=0.5)])
    d = hooks.pre_tool_use("bash", {"command": "ls"})
    assert not d.allow and d.decision == "fail_closed"


# --- ① lifecycle events fire (Agent) --------------------------------------

def test_agent_fires_lifecycle_events(env):
    fired = []
    rec = lambda payload: (fired.append(payload.get("event")) or (True, ""))
    hooks = HookRegistry([
        Hook(EVENT_SESSION_START, "*", "inline", callable=rec),
        Hook(EVENT_USER_PROMPT_SUBMIT, "*", "inline", callable=rec),
        Hook(EVENT_SESSION_END, "*", "inline", callable=rec),
    ])
    client = scripted_client(env, [{"content": "ok"}])
    agent = Agent(cfg=env, client=client, registry=ToolRegistry(), hooks=hooks)
    agent.run("goal")
    assert EVENT_SESSION_START in fired
    assert EVENT_USER_PROMPT_SUBMIT in fired
    assert EVENT_SESSION_END in fired


# --- post_tool_use / post_tool_use_failure dispatch ------------------------

def test_post_tool_use_failure_variant(env):
    fired = []
    rec = lambda payload: (fired.append(payload.get("event")) or (True, ""))

    reg = ToolRegistry()
    # a tool that always returns an ERROR observation
    reg.register("boom", "always errors",
                 {"type": "object", "properties": {}},
                 lambda: "ERROR: intentional")
    hooks = HookRegistry([
        Hook("post_tool_use", "*", "inline", callable=rec),
        Hook("post_tool_use_failure", "*", "inline", callable=rec),
    ])
    client = scripted_client(env, [
        {"content": None, "tool_calls": [tool_call("boom", {})]},
        {"content": "done"},
    ])
    agent = Agent(cfg=env, client=client, registry=reg, hooks=hooks)
    agent.run("goal")
    assert "post_tool_use" in fired
    assert "post_tool_use_failure" in fired


# --- ① lifecycle events fire (Orchestrator) -------------------------------

def test_orchestrator_fires_subtask_hooks(env):
    fired = []
    rec = lambda payload: (fired.append(payload.get("event")) or (True, ""))
    hooks = HookRegistry([
        Hook(EVENT_PRE_SUBTASK, "*", "inline", callable=rec),
        Hook(EVENT_POST_SUBTASK, "*", "inline", callable=rec),
        Hook(EVENT_SESSION_END, "*", "inline", callable=rec),
    ])
    plan = json.dumps(
        {"plan": [{"id": 1, "task": "X", "verify": "manual", "checks": []}]})
    replies = [plan, "exec", json.dumps({"verdict": "pass", "evidence": "ok"})]
    orch = Orchestrator(cfg=env, client=scripted_client(env, replies),
                        hooks=hooks)
    res = orch.run("goal")
    assert EVENT_PRE_SUBTASK in fired
    assert EVENT_POST_SUBTASK in fired
    assert EVENT_SESSION_END in fired
    assert res.success


# --- hook file loading -----------------------------------------------------

def test_from_config_empty_when_no_file():
    assert len(HookRegistry.from_config({})) == 0
    assert len(HookRegistry.from_file("/no/such/hooks.json")) == 0


def test_from_file_loads_command_hook(tmp_path):
    hooks_file = tmp_path / "hooks.json"
    hooks_file.write_text(json.dumps({
        "hooks": [
            {"event": "pre_tool_use", "handler": "command",
             "command": "exit 2", "matcher": "*"},
        ]
    }), encoding="utf-8")
    hooks = HookRegistry.from_file(hooks_file)
    assert len(hooks) == 1
    d = hooks.pre_tool_use("bash", {"command": "ls"})
    assert not d.allow and d.decision == "deny"


def test_from_file_invalid_json_is_safe(tmp_path):
    hooks_file = tmp_path / "hooks.json"
    hooks_file.write_text("{not valid json", encoding="utf-8")
    # must not raise - fail safe to empty
    assert len(HookRegistry.from_file(hooks_file)) == 0


# --- ⑤ zero third-party dependencies --------------------------------------

def test_hooks_module_is_stdlib_only():
    src = Path(__file__).resolve().parent.parent / "baize" / "hooks.py"
    text = src.read_text(encoding="utf-8")
    for forbidden in ("import requests", "import httpx", "import yaml",
                      "import mcp", "import aiohttp", "from requests",
                      "from httpx"):
        assert forbidden not in text, f"forbidden import in hooks.py: {forbidden}"


# --- additional defensive / edge branches ---------------------------------

def test_matcher_invalid_regex_falls_back_to_substring():
    # an invalid regex ("[") must not raise - it falls back to substring.
    assert _matcher_matches("[", "write_file") == ("[" in "write_file")


def test_from_config_loads_via_env_path(tmp_path):
    hooks_file = tmp_path / "hooks.json"
    hooks_file.write_text(json.dumps({
        "hooks": [{"event": "pre_tool_use", "command": "exit 2"}]
    }), encoding="utf-8")
    reg = HookRegistry.from_config({"BAIZE_HOOKS_FILE": str(hooks_file)})
    assert len(reg) == 1


def test_from_file_non_dict_json_is_safe(tmp_path):
    # valid JSON but not an object -> fail safe to empty
    f = tmp_path / "hooks.json"
    f.write_text("[1, 2, 3]", encoding="utf-8")
    assert len(HookRegistry.from_file(f)) == 0


def test_from_file_skips_invalid_entries(tmp_path):
    f = tmp_path / "hooks.json"
    f.write_text(json.dumps({
        "hooks": [
            "not a dict",                                   # skipped
            {"event": "pre_tool_use", "timeout": "broken"},  # bad timeout -> skipped
            {"event": "session_start"},                     # valid
        ]
    }), encoding="utf-8")
    assert len(HookRegistry.from_file(f)) == 1


def test_register_and_iter():
    reg = HookRegistry()
    h = Hook(EVENT_SESSION_START)
    reg.register(h)
    assert list(reg) == [h]
    assert len(reg) == 1


def test_normalize_passthrough_and_fallback():
    from baize.hooks import HookDecision
    d = HookDecision(False, "x", "deny")
    assert HookRegistry._normalize(d) is d
    # an unexpected return type (None) -> default allow
    assert HookRegistry._normalize(None).allow


def test_pre_compact_dispatch_fires():
    fired = []
    rec = lambda payload: (fired.append(payload.get("event")) or (True, ""))
    hooks = HookRegistry([Hook("pre_compact", "*", "inline", callable=rec)])
    hooks.pre_compact(5)
    assert "pre_compact" in fired


def test_post_tool_use_command_handler_runs():
    # command handler must work on non-gating events too (exit 0 -> allow)
    hooks = HookRegistry([Hook("post_tool_use", "*", "command",
                               command="exit 0")])
    decisions = hooks.dispatch("post_tool_use",
                               {"tool": "bash", "args": {}, "observation": "x"})
    assert len(decisions) == 1 and decisions[0].allow


def test_dispatch_skips_non_matching_tool():
    fired = []
    rec = lambda payload: (fired.append(payload.get("tool")) or (True, ""))
    hooks = HookRegistry([Hook("post_tool_use", "bash", "inline", callable=rec)])
    # matcher "bash" must skip a write_file event
    hooks.dispatch("post_tool_use", {"tool": "write_file", "args": {}})
    assert fired == []
    # and match a bash event
    hooks.dispatch("post_tool_use", {"tool": "bash", "args": {}})
    assert fired == ["bash"]

