"""Coverage expansion for baize.orchestrator - deterministic checks, the retry
loop, plan fallback, and every TeamMemory init / error branch.

The LLM is scripted (transport injected), so Orchestrator.run exercises its
real planning/execute/verify/retry logic deterministically.
"""
from __future__ import annotations

import json
from pathlib import Path

from baize.config import load_config
from baize.llm import LLMClient
from baize.orchestrator import Orchestrator, run_checks, _extract_json


def _cfg(tmp_path: Path, monkeypatch, **extra) -> dict:
    pdir = tmp_path / "persistence"
    sdir = tmp_path / "persistence" / "sessions"
    wdir = tmp_path / "workspace"
    adir = tmp_path / "assets"
    for d in (pdir, sdir, wdir, adir):
        d.mkdir(parents=True, exist_ok=True)
    (adir / "skills").mkdir(exist_ok=True)
    monkeypatch.setenv("BAIZE_PERSISTENCE_DIR", str(pdir))
    monkeypatch.setenv("BAIZE_SESSIONS_DIR", str(sdir))
    monkeypatch.setenv("BAIZE_WORKSPACE_DIR", str(wdir))
    monkeypatch.setenv("BAIZE_ASSETS_DIR", str(adir))
    monkeypatch.setenv("BAIZE_INDEX_FILE", str(pdir / "skill_index.json"))
    monkeypatch.setenv("SKILL_LIBRARY_PATHS", "")
    backend = extra.get("BAIZE_TEAM_MEMORY_BACKEND", "local")
    monkeypatch.setenv("BAIZE_TEAM_MEMORY_BACKEND", backend)
    monkeypatch.setenv("BAIZE_MODEL_BASE_URL", "http://x/v1")
    monkeypatch.setenv("BAIZE_MODEL_NAME", "m")
    monkeypatch.setenv("BAIZE_LLM_MAX_RETRIES", "0")
    # Build the cfg from load_config() so every key the Agent/LLM read
    # directly from the dict is present (inherits all defaults + env).
    c = load_config()
    c.update(extra)
    return c


def _scripted_client(replies, cfg):
    queue = list(replies)

    def transport(url, headers, payload):
        return {"choices": [{"message": {"content": queue.pop(0)}}]}

    return LLMClient(cfg=cfg, transport=transport)


# ---------------------------------------------------------------------------
# run_checks: every deterministic gate type + the fail-closed branches
# ---------------------------------------------------------------------------

def test_run_checks_file_and_cmd(tmp_path, monkeypatch):
    from baize.tools import default_registry
    # run_checks reads the workspace from the *global* load_config(), so point
    # the workspace at tmp_path and write the probe file inside it.
    monkeypatch.setenv("BAIZE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("BAIZE_ALLOW_OUTSIDE_WORKSPACE", "0")
    reg = default_registry()
    f = tmp_path / "exists.txt"
    f.write_text("hello world", encoding="utf-8")

    assert run_checks([{"type": "file_exists", "path": str(f)}], reg)[0]["ok"]
    # A non-existent file inside the workspace must fail closed.
    assert not run_checks(
        [{"type": "file_exists", "path": str(tmp_path / "nope.txt")}], reg)[0]["ok"]

    assert run_checks(
        [{"type": "file_contains", "path": str(f), "text": "world"}], reg)[0]["ok"]
    assert not run_checks(
        [{"type": "file_contains", "path": str(f), "text": "zzz"}], reg)[0]["ok"]

    assert run_checks([{"type": "cmd_ok", "cmd": "echo hi"}], reg)[0]["ok"]
    assert not run_checks([{"type": "cmd_ok", "cmd": "exit 1"}], reg)[0]["ok"]


def test_run_checks_unknown_type_fail_closed():
    from baize.tools import default_registry
    res = run_checks([{"type": "bogus"}], default_registry())
    assert res[0]["ok"] is False
    assert "unknown" in res[0]["detail"]


def test_run_checks_handles_exceptions():
    class BoomReg:
        def execute(self, name, args):
            raise RuntimeError("boom")

    res = run_checks([{"type": "file_exists", "path": "x"}], BoomReg())
    assert res[0]["ok"] is False
    assert "crashed" in res[0]["detail"]


# ---------------------------------------------------------------------------
# Orchestrator.run: retry, plan fallback, TeamMemory branches
# ---------------------------------------------------------------------------

def test_orchestrator_retries_after_verifier_fail(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    plan = json.dumps(
        {"plan": [{"id": 1, "task": "do X", "verify": "works", "checks": []}]})
    replies = [
        plan,
        "executor did X",
        json.dumps({"verdict": "fail", "issues": ["not working"]}),
        "executor fixed X",
        json.dumps({"verdict": "pass", "evidence": "works now"}),
    ]
    orch = Orchestrator(cfg=cfg, client=_scripted_client(replies, cfg),
                        max_retries_per_task=1)
    res = orch.run("make X work")
    assert res.success is True
    r = res.reports[0]
    assert r.retried is True
    assert r.verdict == "pass"


def test_orchestrator_plan_fallback(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    replies = [
        "I cannot produce a structured plan",   # director garbage -> fallback
        "executor did it",
        json.dumps({"verdict": "pass", "evidence": "ok"}),
    ]
    orch = Orchestrator(cfg=cfg, client=_scripted_client(replies, cfg),
                        max_retries_per_task=0)
    res = orch.run("goal")
    assert len(res.plan) == 1          # single-task fallback
    assert res.success is True


class _BoomTeamMemory:
    """A blackboard whose context()/post() raise, to exercise error branches."""
    team_id = "boom"

    def context(self):
        raise RuntimeError("ctx boom")

    def post(self, *a, **k):
        raise RuntimeError("post boom")

    def claim(self, *a, **k):
        return True

    def read(self, *a, **k):
        return []

    def stats(self, *a, **k):
        return {}

    def clear(self, *a, **k):
        pass


def test_orchestrator_team_memory_error_paths(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    plan = json.dumps(
        {"plan": [{"id": 1, "task": "X", "verify": "v", "checks": []}]})
    replies = [plan, "exec did",
               json.dumps({"verdict": "pass", "evidence": "ok"})]
    orch = Orchestrator(cfg=cfg, client=_scripted_client(replies, cfg),
                        team_memory=_BoomTeamMemory())
    res = orch.run("goal")
    assert res.success is True


def test_orchestrator_team_memory_init_failure(tmp_path, monkeypatch):
    """shared backend raises -> team_memory stays None; run still works."""
    cfg = _cfg(tmp_path, monkeypatch, BAIZE_TEAM_MEMORY_BACKEND="shared")
    plan = json.dumps(
        {"plan": [{"id": 1, "task": "X", "verify": "v", "checks": []}]})
    replies = [plan, "exec", json.dumps({"verdict": "pass", "evidence": "ok"})]
    orch = Orchestrator(cfg=cfg, client=_scripted_client(replies, cfg))
    assert orch.team_memory is None
    res = orch.run("goal")
    assert res.success is True


def test_orchestrator_default_team_memory_init(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch, BAIZE_TEAM_MEMORY_BACKEND="local")
    plan = json.dumps(
        {"plan": [{"id": 1, "task": "X", "verify": "v", "checks": []}]})
    replies = [plan, "exec", json.dumps({"verdict": "pass", "evidence": "ok"})]
    orch = Orchestrator(cfg=cfg, client=_scripted_client(replies, cfg))
    assert orch.team_memory is not None
    res = orch.run("goal")
    assert res.success is True


def test_orchestrator_custom_verify_hook_failure(tmp_path, monkeypatch):
    """A failing injected verify_hook must hard-fail the subtask."""
    cfg = _cfg(tmp_path, monkeypatch)
    plan = json.dumps(
        {"plan": [{"id": 1, "task": "X", "verify": "v", "checks": []}]})
    # Plan (director) + executor reply. The hook gates before the LLM
    # verifier, so the verifier chat is never called - the queue just keeps
    # one unconsumed reply, which is harmless.
    replies = [plan, "exec did X"]
    hooks = [(lambda sub, summary: (False, "hook says no"))]
    orch = Orchestrator(cfg=cfg, client=_scripted_client(replies, cfg),
                        verify_hooks=hooks, max_retries_per_task=0)
    res = orch.run("goal")
    assert res.success is False
    r = res.reports[0]
    assert r.verdict == "fail"
    assert any("hook says no" in i for i in r.issues)


def test_orchestrator_plan_with_malformed_items(tmp_path, monkeypatch):
    """Director emits non-dict items and a bad checks type -> cleaned safely."""
    cfg = _cfg(tmp_path, monkeypatch)
    # A plan whose items are not all dicts and whose checks is not a list.
    messy = json.dumps({"plan": [
        "not a dict at all",
        {"task": "real", "verify": "v", "checks": "oops-not-a-list"},
    ]})
    replies = [messy, "exec", json.dumps({"verdict": "pass", "evidence": "ok"})]
    orch = Orchestrator(cfg=cfg, client=_scripted_client(replies, cfg),
                        max_retries_per_task=0)
    res = orch.run("goal")
    # Only the well-formed dict survives the cleaning pass.
    assert len(res.plan) == 1
    assert res.plan[0]["task"] == "real"
    assert res.plan[0]["checks"] == []
    assert res.success is True


def test_orchestrator_plan_fenced_json_fallback(tmp_path, monkeypatch):
    """Director wraps JSON in markdown fences -> _extract_json still parses."""
    cfg = _cfg(tmp_path, monkeypatch)
    fenced = "Sure, here is the plan:\n```json\n" + json.dumps(
        {"plan": [{"id": 1, "task": "Y", "verify": "v", "checks": []}]}
    ) + "\n```\nDone."
    replies = [fenced, "exec", json.dumps({"verdict": "pass", "evidence": "ok"})]
    orch = Orchestrator(cfg=cfg, client=_scripted_client(replies, cfg),
                        max_retries_per_task=0)
    res = orch.run("goal")
    assert len(res.plan) == 1
    assert res.plan[0]["task"] == "Y"
    assert res.success is True


def test_orchestrator_verify_hook_crash_is_fail_closed(tmp_path, monkeypatch):
    """A verify_hook that raises must be treated as a hard failure."""
    cfg = _cfg(tmp_path, monkeypatch)
    plan = json.dumps(
        {"plan": [{"id": 1, "task": "X", "verify": "v", "checks": []}]})
    replies = [plan, "exec did X"]
    def boom(sub, summary):
        raise RuntimeError("hook blew up")
    orch = Orchestrator(cfg=cfg, client=_scripted_client(replies, cfg),
                        verify_hooks=[boom], max_retries_per_task=0)
    res = orch.run("goal")
    assert res.success is False
    assert any("hook blew up" in i or "crashed" in i
               for i in res.reports[0].issues)


def test_extract_json_returns_none_on_garbage():
    """No JSON object anywhere -> _extract_json returns None (no fake parse)."""
    assert _extract_json("just some text, no braces") is None
    assert _extract_json("") is None
    # Braces present but the inner content is not valid JSON -> still None.
    assert _extract_json("prefix {this is not json} suffix") is None


def test_orchestrator_passing_verify_hook_allows_subtask(tmp_path, monkeypatch):
    """A passing verify_hook must not block an otherwise-passing subtask."""
    cfg = _cfg(tmp_path, monkeypatch)
    plan = json.dumps(
        {"plan": [{"id": 1, "task": "X", "verify": "v", "checks": []}]})
    replies = [plan, "exec", json.dumps({"verdict": "pass", "evidence": "ok"})]
    hooks = [(lambda sub, summary: (True, "looks good"))]
    orch = Orchestrator(cfg=cfg, client=_scripted_client(replies, cfg),
                        verify_hooks=hooks, max_retries_per_task=0)
    res = orch.run("goal")
    assert res.success is True
    assert res.reports[0].verdict == "pass"
