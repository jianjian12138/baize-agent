"""Tests for baize.agent - the autonomous loop with a scripted model.

A scripted transport plays the model role deterministically; the entire
loop (session persistence, tool dispatch, observation feedback, stop
conditions) executes for real.
"""
from __future__ import annotations

import json

import pytest

from baize.agent import Agent, AgentResult, Session, build_system_prompt
from baize.config import load_config
from baize.llm import LLMClient
from baize.tools import ToolRegistry


def scripted_client(cfg, replies):
    """Build an LLMClient whose transport pops scripted assistant messages."""
    queue = list(replies)

    def transport(url, headers, payload):
        msg = queue.pop(0)
        return {"choices": [{"message": msg}]}

    return LLMClient(cfg=cfg, transport=transport)


def echo_registry():
    reg = ToolRegistry()
    reg.register("echo", "echo text back",
                 {"type": "object", "properties": {"text": {"type": "string"}},
                  "required": ["text"]},
                 lambda text: f"ECHO:{text}")
    return reg


def tool_call(name, args, call_id="c1"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def test_direct_final_answer(env):
    client = scripted_client(env, [{"content": "done, nothing to do"}])
    agent = Agent(cfg=env, client=client, registry=echo_registry())
    res = agent.run("trivial goal")
    assert res.stopped_reason == "final"
    assert res.final_text == "done, nothing to do"
    assert res.steps == 1 and res.tool_calls == 0


def test_tool_loop_and_observation_feedback(env):
    client = scripted_client(env, [
        {"content": None, "tool_calls": [tool_call("echo", {"text": "ping"})]},
        {"content": "observed the echo"},
    ])
    agent = Agent(cfg=env, client=client, registry=echo_registry())
    res = agent.run("use the echo tool")
    assert res.stopped_reason == "final" and res.tool_calls == 1
    tool_msgs = [m for m in agent.session.messages if m.get("role") == "tool"]
    assert tool_msgs and tool_msgs[0]["content"] == "ECHO:ping"


def test_session_persisted_and_resumable(env):
    client = scripted_client(env, [{"content": "first answer"}])
    agent = Agent(cfg=env, client=client, registry=echo_registry())
    res = agent.run("goal one")
    assert agent.session.file.exists()

    resumed = Session(session_id=res.session_id, cfg=env)
    assert [m["role"] for m in resumed.messages] == \
        [m["role"] for m in agent.session.messages]

    client2 = scripted_client(env, [{"content": "second answer"}])
    agent2 = Agent(cfg=env, client=client2, registry=echo_registry(),
                   session=resumed)
    res2 = agent2.run("follow-up goal")
    assert res2.session_id == res.session_id
    assert res2.final_text == "second answer"
    # system prompt not duplicated on resume
    assert sum(1 for m in resumed.messages if m["role"] == "system") == 1


def test_max_steps_guard(env, monkeypatch):
    monkeypatch.setenv("BAIZE_AGENT_MAX_STEPS", "3")
    cfg = load_config()
    endless = [{"content": None,
                "tool_calls": [tool_call("echo", {"text": f"n{i}"}, f"c{i}")]}
               for i in range(10)]
    client = scripted_client(cfg, endless)
    agent = Agent(cfg=cfg, client=client, registry=echo_registry())
    res = agent.run("never finishes")
    assert res.stopped_reason == "max_steps"
    assert res.steps == 3 and res.tool_calls == 3


def test_unknown_tool_becomes_observation_not_crash(env):
    client = scripted_client(env, [
        {"content": None, "tool_calls": [tool_call("ghost", {})]},
        {"content": "recovered"},
    ])
    agent = Agent(cfg=env, client=client, registry=echo_registry())
    res = agent.run("call a ghost tool")
    assert res.stopped_reason == "final"
    tool_msgs = [m for m in agent.session.messages if m.get("role") == "tool"]
    assert "unknown tool" in tool_msgs[0]["content"]


def test_memory_injected_into_first_turn(env):
    from baize import memory as memory_mod
    memory_mod.log_event("previous deploy used blue-green strategy",
                         tags=["deploy"], cfg=env)
    client = scripted_client(env, [{"content": "ok"}])
    agent = Agent(cfg=env, client=client, registry=echo_registry())
    agent.run("plan the deploy rollout strategy")
    first_user = next(m for m in agent.session.messages if m["role"] == "user")
    assert "Relevant persistent memory" in first_user["content"]
    assert "blue-green" in first_user["content"]


def test_system_prompt_mentions_tools_and_role(env):
    sp = build_system_prompt("verifier", env, echo_registry())
    assert "VERIFIER" in sp and "echo" in sp and "NO FAKE DONE" in sp
