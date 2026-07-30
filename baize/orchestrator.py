"""Multi-agent orchestration: Director -> Executor(s) -> Verifier.

This makes AGENT.md's role protocol executable instead of documentary:
- Director produces a JSON plan (1-6 subtasks with verify criteria).
- One Executor agent runs per subtask, with full tool access.
- Verifier independently re-checks each result (NO FAKE DONE gate).

A failed verification triggers one bounded retry of the executor with the
verifier's issues injected - a real feedback loop, not a hope loop.

V20 hardening: the Verifier is now a DUAL GATE -
1. Deterministic checks (file_exists / file_contains / cmd_ok) declared in the
   plan run first through the sandboxed tool registry. Any failure = hard fail,
   no LLM opinion can override it.
2. Only when deterministic checks pass does the LLM verifier weigh in.
Custom ``verify_hooks`` callables can be injected for domain-specific gates.

V20 collaboration: all roles share a TeamMemory blackboard, so findings from
the Executor are visible to the Verifier (and to later subtasks) instead of
being lost between phases.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .agent import Agent, Session
from .config import load_config
from .llm import LLMClient
from .observability import obs
from .team_memory import TeamMemory
from .tools import ToolRegistry, default_registry
from . import memory as memory_mod


@dataclass
class SubtaskReport:
    task_id: int
    task: str
    verify: str
    executor_summary: str = ""
    verdict: str = "skipped"          # pass | fail | skipped
    evidence: str = ""
    issues: list[str] = field(default_factory=list)
    retried: bool = False
    checks: list[dict] = field(default_factory=list)   # deterministic results


# -- V20 deterministic checks -------------------------------------------------

def run_checks(checks: list[dict], registry: ToolRegistry) -> list[dict]:
    """Run declared deterministic checks through the sandboxed tool registry.

    Supported check types:
      {"type": "file_exists",   "path": "..."}
      {"type": "file_contains", "path": "...", "text": "..."}
      {"type": "cmd_ok",        "cmd": "..."}     # exit code must be 0

    Returns list of {"check": <spec>, "ok": bool, "detail": str}.
    Unknown types fail closed (ok=False) - a typo must not silently pass.
    """
    results = []
    for chk in checks[:10]:                       # bounded
        ctype = str(chk.get("type", ""))
        ok, detail = False, ""
        try:
            if ctype == "file_exists":
                out = registry.execute("read_file",
                                       {"path": str(chk.get("path", ""))})
                ok = not str(out).startswith("ERROR")
                detail = "exists" if ok else str(out)[:200]
            elif ctype == "file_contains":
                out = registry.execute("read_file",
                                       {"path": str(chk.get("path", ""))})
                text = str(chk.get("text", ""))
                ok = (not str(out).startswith("ERROR")) and text in str(out)
                detail = ("found" if ok else
                          f"text {text[:60]!r} not found")
            elif ctype == "cmd_ok":
                out = registry.execute("bash",
                                       {"command": str(chk.get("cmd", ""))})
                ok = str(out).startswith("exit=0")
                detail = str(out)[:200]
            else:
                detail = f"unknown check type: {ctype!r} (fail closed)"
        except Exception as e:                    # defensive: check crash = fail
            detail = f"check crashed: {e}"
        results.append({"check": chk, "ok": ok, "detail": detail})
    return results


@dataclass
class OrchestrationResult:
    goal: str
    plan: list[dict]
    reports: list[SubtaskReport]
    success: bool
    session_ids: list[str] = field(default_factory=list)


def _extract_json(text: str) -> dict | None:
    """Best-effort JSON extraction (models often wrap JSON in fences)."""
    text = text.strip()
    for candidate in (text,):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


class Orchestrator:
    def __init__(self, cfg: dict | None = None,
                 client: LLMClient | None = None,
                 registry: ToolRegistry | None = None,
                 max_retries_per_task: int = 1,
                 on_event=None,
                 verify_hooks: list | None = None,
                 team_memory: TeamMemory | None = None):
        self.cfg = cfg or load_config()
        self.client = client or LLMClient(self.cfg)
        self.registry = registry or default_registry()
        self.max_retries = max_retries_per_task
        self.on_event = on_event or (lambda *_: None)
        # V20: pluggable custom gates: callable(sub, executor_summary) ->
        # (ok: bool, detail: str). Any hook failing = subtask fails.
        self.verify_hooks = verify_hooks or []
        # V20: shared blackboard. Defensive - a memory backend problem must
        # never prevent the team from running at all.
        if team_memory is not None:
            self.team_memory = team_memory
        else:
            try:
                self.team_memory = TeamMemory(
                    team_id=f"run-{int(time.time())}", cfg=self.cfg)
            except Exception:
                obs.record_error("team_memory_init_failed")
                self.team_memory = None

    def _team_context(self) -> str:
        if not self.team_memory:
            return ""
        try:
            return self.team_memory.context()
        except Exception:
            obs.record_error("team_memory_read_failed")
            return ""

    def _team_post(self, role: str, text: str, tags: list[str]) -> None:
        if not self.team_memory or not text.strip():
            return
        try:
            self.team_memory.post(role, text[:800], tags=tags)
        except Exception:
            obs.record_error("team_memory_post_failed")

    def _spawn(self, role: str) -> Agent:
        return Agent(role=role, cfg=self.cfg, client=self.client,
                     registry=self.registry,
                     session=Session(cfg=self.cfg), on_event=self.on_event)

    # -- phases -------------------------------------------------------------

    def plan(self, goal: str) -> tuple[list[dict], str]:
        director = self._spawn("director")
        res = director.run(goal, extra_system=self._team_context())
        data = _extract_json(res.final_text) or {}
        plan = data.get("plan") or []
        cleaned = []
        for i, item in enumerate(plan[:6], start=1):
            if isinstance(item, dict) and item.get("task"):
                checks = item.get("checks") or []
                if not isinstance(checks, list):
                    checks = []
                cleaned.append({"id": item.get("id", i),
                                "task": str(item["task"]),
                                "verify": str(item.get("verify", "")),
                                "checks": [c for c in checks
                                           if isinstance(c, dict)][:10]})
        if not cleaned:  # director failed to plan -> single-task fallback
            cleaned = [{"id": 1, "task": goal, "verify": "manual review",
                        "checks": []}]
        self._team_post("director",
                        "plan: " + " | ".join(f"#{c['id']} {c['task'][:60]}"
                                              for c in cleaned), ["plan"])
        return cleaned, res.session_id

    def execute_subtask(self, sub: dict) -> tuple[str, str]:
        executor = self._spawn("executor")
        if self.team_memory:
            self.team_memory.claim(str(sub.get("id", "?")), "executor")
        res = executor.run(f"{sub['task']}\n\nSuccess criteria: {sub['verify']}",
                           extra_system=self._team_context())
        self._team_post("executor", res.final_text, ["finding", "executed"])
        return res.final_text, res.session_id

    def verify_subtask(self, sub: dict, executor_summary: str) -> dict:
        # --- Gate 1 (V20): deterministic checks - hard fail, no LLM override
        check_results = run_checks(sub.get("checks") or [], self.registry)
        failed = [c for c in check_results if not c["ok"]]
        hook_issues: list[str] = []
        for hook in self.verify_hooks:
            try:
                ok, detail = hook(sub, executor_summary)
            except Exception as e:                # defensive: hook crash = fail
                ok, detail = False, f"verify hook crashed: {e}"
            if not ok:
                hook_issues.append(str(detail)[:200])
        if failed or hook_issues:
            issues = ([f"check failed: {c['check'].get('type')} - {c['detail']}"
                       for c in failed] + hook_issues)[:10]
            self._team_post("verifier", "; ".join(issues), ["blocker"])
            return {"verdict": "fail",
                    "evidence": "deterministic gate failed "
                                f"({len(failed)} checks, {len(hook_issues)} hooks)",
                    "issues": issues, "session_id": "",
                    "checks": check_results}

        # --- Gate 2: independent LLM verification (NO FAKE DONE)
        verifier = self._spawn("verifier")
        res = verifier.run(
            f"Task: {sub['task']}\nSuccess criteria: {sub['verify']}\n"
            f"Executor claims: {executor_summary}\n"
            "Verify independently with tools.",
            extra_system=self._team_context())
        data = _extract_json(res.final_text) or {}
        if data.get("verdict") != "pass" and data.get("issues"):
            self._team_post("verifier",
                            "; ".join(str(i) for i in data["issues"]),
                            ["blocker"])
        return {
            "verdict": data.get("verdict", "fail"),
            "evidence": str(data.get("evidence", res.final_text))[:1000],
            "issues": [str(i) for i in data.get("issues", [])][:10],
            "session_id": res.session_id,
            "checks": check_results,
        }

    # -- full run -----------------------------------------------------------

    def run(self, goal: str) -> OrchestrationResult:
        self.on_event("phase", "planning")
        plan, director_sid = self.plan(goal)
        session_ids = [director_sid]
        reports: list[SubtaskReport] = []

        for sub in plan:
            self.on_event("phase", f"executing #{sub['id']}: {sub['task'][:80]}")
            report = SubtaskReport(sub["id"], sub["task"], sub["verify"])

            summary, sid = self.execute_subtask(sub)
            session_ids.append(sid)
            report.executor_summary = summary

            self.on_event("phase", f"verifying #{sub['id']}")
            v = self.verify_subtask(sub, summary)
            if v["session_id"]:
                session_ids.append(v["session_id"])
            report.verdict, report.evidence, report.issues = (
                v["verdict"], v["evidence"], v["issues"])
            report.checks = v.get("checks", [])

            retries = 0
            while report.verdict != "pass" and retries < self.max_retries:
                retries += 1
                report.retried = True
                self.on_event("phase", f"retry #{sub['id']} ({retries})")
                fix_goal = (f"{sub['task']}\n\nPrevious attempt failed "
                            f"verification. Issues: {'; '.join(report.issues)}"
                            f"\nFix them. Success criteria: {sub['verify']}")
                summary, sid = self.execute_subtask({**sub, "task": fix_goal})
                session_ids.append(sid)
                report.executor_summary = summary
                v = self.verify_subtask(sub, summary)
                if v["session_id"]:
                    session_ids.append(v["session_id"])
                report.verdict, report.evidence, report.issues = (
                    v["verdict"], v["evidence"], v["issues"])
                report.checks = v.get("checks", [])

            reports.append(report)

        success = all(r.verdict == "pass" for r in reports)
        memory_mod.log_event(
            f"orchestration {'OK' if success else 'FAILED'}: {goal[:120]} "
            f"({sum(1 for r in reports if r.verdict == 'pass')}/{len(reports)} "
            "subtasks passed)",
            tags=["orchestration", "pass" if success else "fail"],
            cfg=self.cfg)
        return OrchestrationResult(goal, plan, reports, success, session_ids)
