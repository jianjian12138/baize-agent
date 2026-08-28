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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .agent import Agent, Session
from pathlib import Path

from .config import load_config, ROOT
from .hooks import HookRegistry
from .llm import LLMClient
from .observability import obs
from .team_memory import TeamMemory
from .tools import ToolRegistry, default_registry
from . import memory as memory_mod
# V26-A2: run ledger for append-only task event audit trail
from .run_ledger import RunLedger


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
                 team_memory: TeamMemory | None = None,
                 hooks: HookRegistry | None = None):
        self.cfg = cfg or load_config()
        self.client = client or LLMClient(self.cfg)
        self.registry = registry or default_registry()
        self.max_retries = max_retries_per_task
        self.on_event = on_event or (lambda *_: None)
        # V21 P1-1: lifecycle hook bus, shared with spawned agents so a
        # pre_tool_use gate applies uniformly across the whole team.
        self.hooks = hooks or HookRegistry.from_config(self.cfg)
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
        # V26-A2: run ledger (created lazily in run())
        self._ledger: RunLedger | None = None

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
        """V26-B1: Spawn an agent with RolePolicy enforcement.

        Reads the matching Role from team_config (if present) and applies:
        - allow_tools: create a filtered subset registry (empty = no restriction)
        - workspace_scope: stored on the agent as _workspace_scope for prompt injection
        - memory_visibility: 'none' / invalid → agent._no_memory = True (fail-closed)

        No team_config or no matching Role → original behaviour (no restriction).
        """
        # --- resolve role policy -------------------------------------------
        role_policy = None
        team_config = getattr(self, "team_config", None)
        if team_config and hasattr(team_config, "roles"):
            for r in team_config.roles:
                if r.name == role:
                    role_policy = r
                    break

        # --- build filtered registry ----------------------------------------
        active_registry = self.registry
        if role_policy is not None:
            effective_tools = role_policy.effective_allow_tools()
            if effective_tools:
                # Build subset: only the tools in the whitelist that actually exist
                from .tools import ToolRegistry
                subset = ToolRegistry()
                for tool_name in effective_tools:
                    tool_obj = self.registry.get(tool_name)
                    if tool_obj is not None:
                        subset.register(tool_obj.name, tool_obj.description,
                                        tool_obj.parameters, tool_obj.fn)
                active_registry = subset

        # --- spawn agent ----------------------------------------------------
        agent = Agent(role=role, cfg=self.cfg, client=self.client,
                      registry=active_registry, session=Session(cfg=self.cfg),
                      on_event=self.on_event, hooks=self.hooks)

        # --- apply workspace_scope ------------------------------------------
        if role_policy is not None:
            agent._workspace_scope = role_policy.workspace_scope
        else:
            agent._workspace_scope = ""

        # --- apply memory_visibility ----------------------------------------
        if role_policy is not None:
            vis = role_policy.effective_memory_visibility()
            agent._no_memory = (vis == "none")
        else:
            agent._no_memory = False

        return agent


    def spawn_subagent(self, defn, goal: str, client=None) -> str:
        """Run an isolated sub-agent (V21 P1-3) as part of a team run.

        The sub-agent gets its own scoped registry + Session (isolation), and
        shares this orchestrator's hooks so a ``pre_tool_use`` gate still
        applies uniformly. Only the final summary is returned - the sub-agent's
        raw transcript never pollutes the parent session. Fail-closed: any
        error surfaces as a summary string, never an unhandled crash.
        """
        try:
            agent = defn.build_agent(cfg=self.cfg, client=client or self.client)
            agent.hooks = self.hooks
            res = agent.run(goal)
            return res.final_text
        except Exception as exc:  # defensive: a sub-agent crash must not kill the team
            obs.record_error("subagent_run_failed")
            return f"[subagent {defn.name} failed] {exc}"

    # -- V23.5 clarify ------------------------------------------------------

    def clarify(self, goal: str, prd_path: str | None = None) -> dict:
        """Clarify scope before planning (grill -> PRD).

        Spawns a clarifier agent, renders a PRD, persists it (default
        ``PRD.md`` at the workspace root), and returns the structured result.
        Fail-closed: if the clarifier yields no JSON we still return a valid
        clarification and the run proceeds (no crash, no fake green).
        """
        clarifier = self._spawn("clarifier")
        res = clarifier.run(goal, extra_system=self._team_context())
        data = _extract_json(res.final_text) or {}
        prd_text = render_prd(goal, data)
        base = self.cfg.get("BAIZE_WORKSPACE_DIR", str(ROOT))
        target = Path(prd_path) if prd_path else Path(base) / "PRD.md"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(prd_text, encoding="utf-8")
        except OSError:
            obs.record_error("prd_write_failed")
        self._team_post("clarifier",
                        "PRD: " + (data.get("prd") or goal)[:300],
                        ["prd", "clarify"])
        return {"goal": goal, "qa": data,
                "prd_file": str(target), "prd": prd_text}

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
                # V33-D1: preserve depends_on for DAG parallel scheduling
                depends_on = item.get("depends_on") or []
                if not isinstance(depends_on, list):
                    depends_on = []
                cleaned.append({"id": item.get("id", i),
                                "task": str(item["task"]),
                                "verify": str(item.get("verify", "")),
                                "checks": [c for c in checks
                                           if isinstance(c, dict)][:10],
                                "depends_on": [int(d) for d in depends_on
                                               if str(d).isdigit()]})
        if not cleaned:  # director failed to plan -> single-task fallback
            cleaned = [{"id": 1, "task": goal, "verify": "manual review",
                        "checks": [], "depends_on": []}]
        self._team_post("director",
                        "plan: " + " | ".join(f"#{c['id']} {c['task'][:60]}"
                                              for c in cleaned), ["plan"])
        return cleaned, res.session_id

    def execute_subtask(self, sub: dict) -> tuple[str, str]:
        task_id = str(sub.get("id", "?"))
        allowed_roles = sub.get("allowed_roles")
        if allowed_roles and "executor" not in allowed_roles:
            err_msg = (f"ERROR: subtask #{task_id} restricted to roles {allowed_roles}, "
                       "executor not permitted (fail-closed).")
            if self._ledger:
                self._ledger.append("task_failed",
                                    {"issues": [err_msg], "retries_used": 0},
                                    task_id=task_id)
            return err_msg, ""

        executor = self._spawn("executor")
        # V26-A3/B2: claim task in run ledger (prevents double-claim)
        if self._ledger:
            self._ledger.append("task_claimed", {"role": "executor"}, task_id=task_id)
            self._ledger.append("task_started", {"role": "executor"}, task_id=task_id)
        if self.team_memory:
            self.team_memory.claim(task_id, "executor")
        res = executor.run(f"{sub['task']}\n\nSuccess criteria: {sub['verify']}",
                           extra_system=self._team_context())
        # V26-A2: log tool result summary to ledger
        if self._ledger:
            self._ledger.append("tool_result",
                                {"tool": "executor_run", "ok": True,
                                 "summary": res.final_text[:200]},
                                task_id=task_id)
        self._team_post("executor", res.final_text, ["finding", "executed"])
        return res.final_text, res.session_id

    def verify_subtask(self, sub: dict, executor_summary: str) -> dict:
        # --- Gate 1 (V20/V26-B3): deterministic checks - hard fail, no LLM override
        check_results = run_checks(sub.get("checks") or [], self.registry)
        failed = [c for c in check_results if not c["ok"]]

        # Check evidence_paths if declared (NO FAKE DONE)
        evidence_issues: list[str] = []
        for ep in sub.get("evidence_paths") or []:
            out = self.registry.execute("read_file", {"path": str(ep)})
            if str(out).startswith("ERROR"):
                evidence_issues.append(f"declared evidence missing: {ep}")
            elif len(str(out).strip()) == 0:
                evidence_issues.append(f"declared evidence empty: {ep}")

        hook_issues: list[str] = []
        for hook in self.verify_hooks:
            try:
                ok, detail = hook(sub, executor_summary)
            except Exception as e:                # defensive: hook crash = fail
                ok, detail = False, f"verify hook crashed: {e}"
            if not ok:
                hook_issues.append(str(detail)[:200])
        if failed or evidence_issues or hook_issues:
            issues = ([f"check failed: {c['check'].get('type')} - {c['detail']}"
                       for c in failed] + evidence_issues + hook_issues)[:10]
            self._team_post("verifier", "; ".join(issues), ["blocker"])
            return {"verdict": "fail",
                    "evidence": "deterministic gate failed "
                                f"({len(failed)} checks, {len(evidence_issues)} evidence, {len(hook_issues)} hooks)",
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

    def run(self, goal: str,
            resume_run_id: str | None = None) -> OrchestrationResult:
        """Run the full Director→Executor→Verifier pipeline.

        V26-A3: Creates a RunLedger for this run. All task events are written
        to persistence/runs/<run-id>.jsonl for audit and resume support.

        V26-A4: If resume_run_id is given, replay the existing ledger and skip
        tasks that have already been verified — no re-execution of done work.
        """
        # V26-A2: initialise run ledger
        run_id = resume_run_id or f"run-{int(time.time())}"
        self._ledger = RunLedger(run_id, cfg=self.cfg)

        # V26-A4: if resuming, read already-verified tasks from ledger
        skip_task_ids: set = set()
        if resume_run_id:
            prior_state = self._ledger.replay()
            skip_task_ids = prior_state.get("verified_tasks", set())
            self.on_event("phase",
                          f"resume {resume_run_id}: "
                          f"skipping {len(skip_task_ids)} verified task(s)")

        # V23.4: pre-flight recon — surface prior art before planning.
        from . import recon as recon_mod
        recon_report = recon_mod.recon(goal, self.cfg)
        self._team_post("recon", recon_report["advice"], ["recon"])
        self.on_event("phase", "recon")

        # V23.5: clarify-before-plan (opt-in; fail-closed).
        if str(self.cfg.get("BAIZE_CLARIFY", "0")) == "1":
            self.clarify(goal)

        self.on_event("phase", "planning")
        plan, director_sid = self.plan(goal)
        session_ids = [director_sid]
        reports: list[SubtaskReport] = []

        # V26-A2: record plan to ledger
        self._ledger.append("plan_created",
                            {"goal": goal, "task_count": len(plan)})

        # V33-D1: parallel DAG execution
        # Build dependency map: task_id -> set of task_ids it must wait for
        workers = int(self.cfg.get("BAIZE_ORCHESTRATOR_WORKERS", "4"))
        reports = self._run_dag(plan, skip_task_ids, session_ids, workers)

        success = all(r.verdict == "pass" for r in reports)
        obs.gauge("orchestration_success", int(success))
        self._ledger.append("run_complete",
                            {"success": success, "tasks": len(reports)})
        res = OrchestrationResult(
            goal=goal, plan=plan, reports=reports,
            success=success, session_ids=list(set(session_ids)))
        res.run_id = run_id
        self.hooks.session_end(res)
        return res

    def _run_one_subtask(self, sub: dict, skip_task_ids: set,
                         session_ids: list) -> "SubtaskReport":
        """Execute + verify a single subtask (called from thread pool or serially)."""
        task_id = str(sub["id"])

        # V26-A4: skip already-verified tasks on resume
        if task_id in skip_task_ids:
            self.on_event("phase",
                          f"skip (already verified) #{task_id}: {sub['task'][:60]}")
            report = SubtaskReport(sub["id"], sub["task"], sub["verify"])
            report.verdict = "pass"
            report.evidence = "[resumed — already verified]"
            return report

        self.on_event("phase", f"executing #{task_id}: {sub['task'][:80]}")
        report = SubtaskReport(sub["id"], sub["task"], sub["verify"])
        self.hooks.pre_subtask(sub)

        summary, sid = self.execute_subtask(sub)
        if sid:
            session_ids.append(sid)
        report.executor_summary = summary

        self.on_event("phase", f"verifying #{task_id}")
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
            self.on_event("phase", f"retry #{task_id} ({retries})")
            fix_goal = (f"{sub['task']}\n\nPrevious attempt failed "
                        f"verification. Issues: {'; '.join(report.issues)}"
                        f"\nFix them. Success criteria: {sub['verify']}")
            summary, sid = self.execute_subtask({**sub, "task": fix_goal})
            if sid:
                session_ids.append(sid)
            report.executor_summary = summary
            v = self.verify_subtask(sub, summary)
            if v["session_id"]:
                session_ids.append(v["session_id"])
            report.verdict, report.evidence, report.issues = (
                v["verdict"], v["evidence"], v["issues"])
            report.checks = v.get("checks", [])

        # V26-A3: state gate
        if self._ledger:
            if report.verdict == "pass":
                self._ledger.append(
                    "task_verified",
                    {"evidence": str(report.evidence)[:300], "verdict": "pass"},
                    task_id=task_id)
                self._ledger.append(
                    "state_transition",
                    {"from_status": "in_progress", "to_status": "verified"},
                    task_id=task_id)
                if sub.get("verify"):
                    self._ledger.append(
                        "skill_candidate",
                        {"task_id": task_id,
                         "candidate_description": sub["verify"][:200]},
                        task_id=task_id)
            else:
                self._ledger.append(
                    "task_failed",
                    {"issues": report.issues[:5], "retries_used": retries},
                    task_id=task_id)

        self.hooks.post_subtask(report)
        return report

    def _run_dag(self, plan: list[dict], skip_task_ids: set,
                 session_ids: list, workers: int) -> list["SubtaskReport"]:
        """V33-D1: Execute plan tasks respecting depends_on DAG with ThreadPoolExecutor.

        Tasks with no pending dependencies are submitted in parallel (up to
        ``workers`` threads). A task is only dispatched once all tasks listed in
        its ``depends_on`` field have completed (regardless of verdict — we always
        attempt downstream tasks so the full picture is surfaced).
        """
        # Build id->sub map and dependency tracking
        id_map = {sub["id"]: sub for sub in plan}
        completed: dict[int, SubtaskReport] = {}   # task_id -> report
        pending = list(plan)  # remaining tasks
        reports_ordered: list[SubtaskReport] = []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            while pending or True:
                # Find tasks whose dependencies are all completed
                ready = [
                    sub for sub in pending
                    if all(dep in completed for dep in sub.get("depends_on", []))
                ]
                if not ready:
                    break  # deadlock guard — all remaining have unresolved deps

                # Submit all ready tasks in parallel
                future_to_sub = {
                    pool.submit(self._run_one_subtask, sub,
                                skip_task_ids, session_ids): sub
                    for sub in ready
                }
                for sub in ready:
                    pending.remove(sub)

                # Collect results as they finish
                for fut in as_completed(future_to_sub):
                    sub = future_to_sub[fut]
                    try:
                        report = fut.result()
                    except Exception as exc:
                        # If a thread crashes, synthesize a fail report
                        report = SubtaskReport(
                            sub["id"], sub["task"], sub["verify"])
                        report.verdict = "fail"
                        report.evidence = f"[thread error] {exc}"
                    completed[sub["id"]] = report
                    reports_ordered.append(report)

                if not pending:
                    break

        # Preserve original plan order in output
        order = {sub["id"]: i for i, sub in enumerate(plan)}
        reports_ordered.sort(key=lambda r: order.get(r.task_id, 999)
                             if hasattr(r, "task_id") else 999)
        # Emit memory summary
        success = all(r.verdict == "pass" for r in reports_ordered)
        memory_mod.log_event(
            f"orchestration {'OK' if success else 'FAILED'}: "
            f"({sum(1 for r in reports_ordered if r.verdict == 'pass')}"
            f"/{len(reports_ordered)} subtasks passed)",
            tags=["orchestration", "pass" if success else "fail"],
            cfg=self.cfg)
        return reports_ordered



def render_prd(goal: str, qa: dict | None) -> str:
    """Render a PRD markdown from a clarification result (pure, testable)."""
    qa = qa or {}
    lines = ["# PRD (clarified before execution)", "",
             f"## Goal\n{goal.strip()}", "", "## Clarifying questions"]
    questions = qa.get("questions") or []
    answers = qa.get("answers") or []
    if questions or answers:
        for i, q in enumerate(questions):
            a = answers[i] if i < len(answers) else "(unanswered)"
            lines.append(f"Q{i+1}. {q}\nA{i+1}. {a}")
    else:
        lines.append("- (none)")
    assumptions = qa.get("assumptions") or []
    lines.append("")
    lines.append("## Assumptions")
    lines.append("\n".join(f"- {a}" for a in assumptions) if assumptions else "- (none)")
    prd = qa.get("prd") or ""
    if prd:
        lines.append("")
        lines.append("## Spec")
        lines.append(prd)
    return "\n".join(lines) + "\n"
