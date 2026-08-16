"""V21 P1-4 Honest skill self-evolution.

The self-evolving skill loop exists (``save_skill`` tool), but until now there
was *no real call site* that fed ``rag.record_skill_outcome`` - so any
"success rate" claim would have been fake green (expert-review blocker).

This module makes the loop honest:
  * ``verify_skill_draft`` - a rubric gate. A skill draft is only accepted if
    it has a safe name, executable steps (or instructions), and *declares its
    dependencies* (even if empty). Low-quality drafts are rejected before they
    can pollute the index.
  * ``SkillRunner`` - executes a skill's structured steps through the real
    tool registry, runs declared verification, and records the *actual*
    outcome via ``rag.record_skill_outcome``. Success is derived from real
    verification, never assumed.

Zero third-party deps. Skills are plain data (name/steps/verify) - there is no
executable code injection, only tool calls the registry already exposes.
"""
from __future__ import annotations

import json

from . import rag
from .config import load_config
from .orchestrator import run_checks
from .tools import ToolRegistry, default_registry

__all__ = ["verify_skill_draft", "SkillRunner"]


def _valid_name(name: str) -> bool:
    return bool(name) and "/" not in name and ".." not in name and "\x00" not in name


def verify_skill_draft(draft: dict) -> tuple[bool, list[str]]:
    """Rubric gate for a proposed skill (returns (ok, reasons)).

    Honesty rules (no fake green):
      - name must be a safe single token (no path separators)
      - it must carry executable steps OR instructions
      - steps (if any) must reference real, registered tools
      - it must declare ``dependencies`` (use [] if none) - a skill cannot
        hide what it needs
    """
    reasons: list[str] = []
    if not isinstance(draft, dict):
        return False, ["draft must be a mapping"]
    name = (draft.get("name") or "").strip()
    if not _valid_name(name):
        reasons.append("name must be a safe single token (no '/' or '..')")
    steps = draft.get("steps")
    instructions = draft.get("instructions") or draft.get("body")
    if not steps and not instructions:
        reasons.append("draft has neither executable steps nor instructions")
    if steps is not None:
        if not isinstance(steps, list) or not steps:
            reasons.append("steps must be a non-empty list")
        else:
            known = default_registry()._tools
            for i, s in enumerate(steps):
                if not isinstance(s, dict) or not s.get("tool"):
                    reasons.append(f"step {i} missing 'tool'")
                elif s["tool"] not in known:
                    reasons.append(f"step {i} references unknown tool '{s['tool']}'")
    if "dependencies" not in draft:
        reasons.append("draft must declare 'dependencies' (use [] if none)")
    return (not reasons), reasons


class SkillRunner:
    """Execute a structured skill and record its real outcome."""

    def __init__(self, cfg: dict | None = None,
                 registry: ToolRegistry | None = None):
        self.cfg = cfg or load_config()
        self.registry = registry or default_registry()

    def run(self, draft: dict, verify=None) -> dict:
        """Run the skill's steps, verify, and record the outcome.

        Returns {"success", "evidence", "observations"}. The outcome is always
        persisted via ``rag.record_skill_outcome`` with the *real* verification
        result - never a hardcoded success.
        """
        observations: list[str] = []
        for step in draft.get("steps", []):
            try:
                obs = self.registry.execute(step["tool"], step.get("args", {}))
            except Exception as exc:  # defensive: one bad step doesn't crash the run
                obs = f"ERROR: step failed: {exc}"
            observations.append(obs)

        verify = draft.get("verify") if verify is None else verify
        success, evidence = self._verify(verify, observations)
        rag.record_skill_outcome(draft.get("name", "unnamed"),
                                  success=success, cfg=self.cfg)
        return {"success": success, "evidence": evidence,
                "observations": observations}

    @staticmethod
    def _verify(verify, observations: list[str]) -> tuple[bool, str]:
        if verify is None:
            # Without declared verification we cannot claim success - honest fail.
            return False, "no verification declared for skill (fail-closed)"
        if callable(verify):
            try:
                ok, detail = verify(observations)
                return bool(ok), str(detail)
            except Exception as exc:
                return False, f"verifier crashed: {exc}"
        # verify is a list of run_checks specs -> real machine verification
        results = run_checks(verify, default_registry())
        ok = all(r.get("ok") for r in results)
        detail = "; ".join(str(r.get("detail", "")) for r in results)
        return ok, (detail or "all checks passed")
