"""Multi-agent orchestration: Director -> Executor(s) -> Verifier.

This makes AGENT.md's role protocol executable instead of documentary:
- Director produces a JSON plan (1-6 subtasks with verify criteria).
- One Executor agent runs per subtask, with full tool access.
- Verifier independently re-checks each result (NO FAKE DONE gate).

A failed verification triggers one bounded retry of the executor with the
verifier's issues injected - a real feedback loop, not a hope loop.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .agent import Agent, Session
from .config import load_config
from .llm import LLMClient
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
                 on_event=None):
        self.cfg = cfg or load_config()
        self.client = client or LLMClient(self.cfg)
        self.registry = registry or default_registry()
        self.max_retries = max_retries_per_task
        self.on_event = on_event or (lambda *_: None)

    def _spawn(self, role: str) -> Agent:
        return Agent(role=role, cfg=self.cfg, client=self.client,
                     registry=self.registry,
                     session=Session(cfg=self.cfg), on_event=self.on_event)

    # -- phases -------------------------------------------------------------

    def plan(self, goal: str) -> tuple[list[dict], str]:
        director = self._spawn("director")
        res = director.run(goal)
        data = _extract_json(res.final_text) or {}
        plan = data.get("plan") or []
        cleaned = []
        for i, item in enumerate(plan[:6], start=1):
            if isinstance(item, dict) and item.get("task"):
                cleaned.append({"id": item.get("id", i),
                                "task": str(item["task"]),
                                "verify": str(item.get("verify", ""))})
        if not cleaned:  # director failed to plan -> single-task fallback
            cleaned = [{"id": 1, "task": goal, "verify": "manual review"}]
        return cleaned, res.session_id

    def execute_subtask(self, sub: dict) -> tuple[str, str]:
        executor = self._spawn("executor")
        res = executor.run(f"{sub['task']}\n\nSuccess criteria: {sub['verify']}")
        return res.final_text, res.session_id

    def verify_subtask(self, sub: dict, executor_summary: str) -> dict:
        verifier = self._spawn("verifier")
        res = verifier.run(
            f"Task: {sub['task']}\nSuccess criteria: {sub['verify']}\n"
            f"Executor claims: {executor_summary}\n"
            "Verify independently with tools.")
        data = _extract_json(res.final_text) or {}
        return {
            "verdict": data.get("verdict", "fail"),
            "evidence": str(data.get("evidence", res.final_text))[:1000],
            "issues": [str(i) for i in data.get("issues", [])][:10],
            "session_id": res.session_id,
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
            session_ids.append(v["session_id"])
            report.verdict, report.evidence, report.issues = (
                v["verdict"], v["evidence"], v["issues"])

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
                session_ids.append(v["session_id"])
                report.verdict, report.evidence, report.issues = (
                    v["verdict"], v["evidence"], v["issues"])

            reports.append(report)

        success = all(r.verdict == "pass" for r in reports)
        memory_mod.log_event(
            f"orchestration {'OK' if success else 'FAILED'}: {goal[:120]} "
            f"({sum(1 for r in reports if r.verdict == 'pass')}/{len(reports)} "
            "subtasks passed)",
            tags=["orchestration", "pass" if success else "fail"],
            cfg=self.cfg)
        return OrchestrationResult(goal, plan, reports, success, session_ids)
