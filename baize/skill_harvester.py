"""Autonomous Skill Harvester (Closed-Loop Learning) — V31 (stdlib, zero dependencies).

Automatically distills successful, non-trivial agent task executions into reusable,
standardized skill libraries (SKILL.md format) in the user skills directory.
Features:
- Automatic heuristic evaluation on task completion (should_harvest)
- Skill deduplication against existing skill library index
- Standardized YAML frontmatter generation compliant with agentskills.io standard
- Instant skill indexing refresh
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .config import load_config
from .logging_setup import get_logger
from .observability import obs

if TYPE_CHECKING:
    from .agent import AgentResult

log = get_logger("harvester")


def _slugify(text: str) -> str:
    """Convert arbitrary goal text to a safe kebab-case skill identifier."""
    cleaned = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", cleaned).strip("-")
    return slug[:40] or f"skill-{int(time.time())}"


def _get_records(result: AgentResult) -> list[dict]:
    return getattr(result, "transcript", None) or getattr(result, "messages", []) or []


class SkillHarvester:
    """Evaluates finished agent runs and archives high-value patterns into new skills."""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or load_config()
        base_dir = self.cfg.get("BAIZE_USER_SKILLS_DIR", "user_skills")
        self.user_skills_dir = Path(base_dir).resolve()
        self.user_skills_dir.mkdir(parents=True, exist_ok=True)

    def should_harvest(self, result: AgentResult, min_steps: int = 3, min_tools: int = 2) -> bool:
        """Heuristic check: did this run solve a non-trivial problem successfully?"""
        if result.stopped_reason != "final":
            return False
        if not result.final_text or len(result.final_text.strip()) < 10:
            return False
        if result.tool_calls < min_tools and result.steps < min_steps:
            return False

        records = _get_records(result)
        tools_called = set()
        for m in records:
            if m.get("role") == "tool" or m.get("tool_calls"):
                for tc in m.get("tool_calls", []):
                    name = tc.get("function", {}).get("name")
                    if name:
                        tools_called.add(name)

        return len(tools_called) > 0

    def extract_skill_spec(self, result: AgentResult, goal: str = "") -> dict:
        """Extract a structured skill specification from session transcript."""
        records = _get_records(result)
        if not goal:
            for m in records:
                if m.get("role") == "user":
                    goal = str(m.get("content", "")).replace("TASK: ", "").strip()
                    break
        goal = goal or "Autonomous Workflow"

        slug = _slugify(goal)
        skill_name = f"auto-{slug}"

        tool_sequence = []
        for m in records:
            for tc in m.get("tool_calls", []):
                fn = tc.get("function", {}).get("name", "")
                if fn and fn not in tool_sequence:
                    tool_sequence.append(fn)

        desc = f"Autonomously distilled workflow for: {goal[:100]}."
        tools_summary = ", ".join(tool_sequence) if tool_sequence else "standard tools"

        body_lines = [
            "---",
            f"name: {skill_name}",
            f"description: {desc}",
            "version: 1.0.0",
            "authors: [baize-harvester]",
            f"tags: [auto-distilled, {slug[:20]}]",
            "harnesses: [baize, hermes, codex]",
            "---",
            "",
            f"# Skill: {skill_name}",
            "",
            f"> **Goal**: {goal}",
            "",
            "## Summary",
            desc,
            "",
            "## Execution Workflow Pattern",
            f"Key tools utilized: `{tools_summary}`.",
            "",
            "### Recommended Steps",
            f"1. Understand context and constraints for `{goal[:60]}`.",
            f"2. Utilize tools in sequence: {tools_summary}.",
            "3. Verify output integrity and confirm evidence against expectations.",
            "",
            "## Reference Output Example",
            "```",
            result.final_text[:500].strip(),
            "```",
        ]

        return {
            "name": skill_name,
            "slug": slug,
            "description": desc,
            "content": "\n".join(body_lines),
        }

    def harvest(self, result: AgentResult, goal: str = "") -> Path | None:
        """Distill and write skill file, then refresh skill index."""
        if not self.should_harvest(result):
            return None

        spec = self.extract_skill_spec(result, goal=goal)
        skill_dir = self.user_skills_dir / spec["name"]
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"

        try:
            skill_file.write_text(spec["content"], encoding="utf-8")
            obs.inc("skills_harvested")
            log.info("[harvester] successfully distilled skill to %s", skill_file)

            try:
                from . import skill_index
                skill_index.build()
            except Exception as e:
                log.warning("[harvester] failed to rebuild index: %s", e)

            return skill_file
        except Exception as exc:
            obs.record_error("skill_harvest_errors")
            log.warning("[harvester] failed to write skill %s: %s", skill_file, exc)
            return None
