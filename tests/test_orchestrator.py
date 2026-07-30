"""Tests for baize.orchestrator - plan/execute/verify with scripted models."""
from __future__ import annotations

import json

import pytest

from baize.llm import LLMClient
from baize.orchestrator import Orchestrator, _extract_json
from baize.tools import ToolRegistry


def scripted_client(cfg, replies):
    queue = list(replies)

    def transport(url, headers, payload):
        return {"choices": [{"message": queue.pop(0)}]}

    return LLMClient(cfg=cfg, transport=transport)


def noop_registry():
    reg = ToolRegistry()
    reg.register("noop", "does nothing",
                 {"type": "object", "properties": {}, "required": []},
                 lambda: "ok")
    return reg


def test_extract_json_variants():
    assert _extract_json('{"a": 1}') == {"a": 1}
    fenced = 'Here is the plan:\n```json\n{"plan": []}\n```\nthanks'
    assert _extract_json(fenced) == {"plan": []}
    assert _extract_json("no json at all") is None


def test_plan_fallback_when_director_rambles(env):
    client = scripted_client(env, [{"content": "I cannot produce JSON, sorry"}])
    orch = Orchestrator(cfg=env, client=client, registry=noop_registry())
    plan, _sid = orch.plan("build the thing")
    assert plan == [{"id": 1, "task": "build the thing",
                     "verify": "manual review", "checks": []}]


def test_full_run_all_pass(env):
    plan_json = json.dumps({"plan": [
        {"id": 1, "task": "create file A", "verify": "file A exists"},
        {"id": 2, "task": "create file B", "verify": "file B exists"},
    ]})
    replies = [
        {"content": plan_json},                                   # director
        {"content": "created A"},                                 # executor 1
        {"content": json.dumps({"verdict": "pass",
                                "evidence": "A on disk"})},       # verifier 1
        {"content": "created B"},                                 # executor 2
        {"content": json.dumps({"verdict": "pass",
                                "evidence": "B on disk"})},       # verifier 2
    ]
    orch = Orchestrator(cfg=env, client=scripted_client(env, replies),
                        registry=noop_registry())
    res = orch.run("make A and B")
    assert res.success
    assert [r.verdict for r in res.reports] == ["pass", "pass"]
    assert len(res.plan) == 2
    # orchestration outcome logged to persistent memory
    from baize import memory as memory_mod
    hits = memory_mod.recall("orchestration", cfg=env)
    assert any("OK" in h["text"] for h in hits)


def test_failed_verification_triggers_retry_then_pass(env):
    plan_json = json.dumps({"plan": [
        {"id": 1, "task": "fix the bug", "verify": "tests pass"}]})
    replies = [
        {"content": plan_json},                                   # director
        {"content": "claimed fixed"},                             # executor
        {"content": json.dumps({"verdict": "fail",
                                "evidence": "tests still red",
                                "issues": ["test_x fails"]})},    # verifier
        {"content": "really fixed now"},                          # retry exec
        {"content": json.dumps({"verdict": "pass",
                                "evidence": "tests green"})},     # verifier 2
    ]
    orch = Orchestrator(cfg=env, client=scripted_client(env, replies),
                        registry=noop_registry())
    res = orch.run("fix the bug")
    assert res.success
    assert res.reports[0].retried
    assert res.reports[0].verdict == "pass"


def test_retry_exhausted_marks_failure(env):
    plan_json = json.dumps({"plan": [
        {"id": 1, "task": "impossible task", "verify": "magic happens"}]})
    fail = {"content": json.dumps({"verdict": "fail",
                                   "evidence": "nope",
                                   "issues": ["still broken"]})}
    replies = [
        {"content": plan_json},
        {"content": "try 1"}, fail,
        {"content": "try 2"}, fail,
    ]
    orch = Orchestrator(cfg=env, client=scripted_client(env, replies),
                        registry=noop_registry(), max_retries_per_task=1)
    res = orch.run("impossible")
    assert not res.success
    assert res.reports[0].verdict == "fail"
    assert res.reports[0].retried
