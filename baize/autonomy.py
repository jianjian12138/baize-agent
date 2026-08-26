"""V21 P2-1 Plan Mode + autonomy slider.

Two independent, fail-closed guards layered on top of the existing
``pre_tool_use`` hook gate:

  * **Plan Mode** - when on, only read-only tools may run. The agent may
    explore freely but cannot mutate anything until the plan is approved.
    (Claude Code-style read-only exploration before a user sign-off.)

  * **Autonomy slider** - a gradient of how freely the agent may act:
      - ``supervised``  : read-only tools only (every mutating op needs review)
      - ``balanced``    : mutating ops allowed, but the most dangerous ones
                          (deny-listed bash, executing learned skills) stay
                          blocked by default
      - ``autonomous``  : everything allowed (hook + fail-closed still apply)

  A **cost cap** (expert-review risk: token runaway) forces a downgrade to
  ``supervised`` once estimated spend exceeds the budget - the agent cannot
  silently burn unbounded resources.

Honesty: a denied action is reported as an ``ERROR`` observation and the loop
continues; it never silently succeeds (NO FAKE DONE).
"""
from __future__ import annotations

from .tools import command_allowed

# Tools that never mutate the workspace / environment.
READONLY_TOOLS = {
    "read_file", "list_dir", "search_skills", "load_skill",
    "memory_recall",
}

# Tools that can irreversibly change state / run untrusted logic.
DANGEROUS_TOOLS = {"bash", "run_skill"}

VALID_LEVELS = ("supervised", "balanced", "autonomous")

# Estimated token budget at which we force a downgrade (configurable).
DEFAULT_COST_CAP = 200_000


class AutonomyPolicy:
    """Decides whether a tool call is permitted under the current autonomy."""

    def __init__(self, level: str = "balanced", cost_cap: int = DEFAULT_COST_CAP,
                 approver=None):
        if level not in VALID_LEVELS:
            level = "balanced"
        self.level = level
        self.cost_cap = cost_cap
        self._spent = 0
        self.downgraded = False
        # Optional human-in-the-loop approver for supervised mode:
        #   callable(tool, args) -> bool
        self.approver = approver

    # --- cost accounting (token runaway guard) ---------------------------
    def record_cost(self, tokens: int) -> None:
        self._spent += max(0, tokens)
        if self.cost_cap and self._spent > self.cost_cap and self.level != "supervised":
            self.level = "supervised"
            self.downgraded = True

    @property
    def spent(self) -> int:
        return self._spent

    # --- the gate ---------------------------------------------------------
    def allow(self, tool: str, args: dict | None = None) -> tuple[bool, str]:
        args = args or {}
        if self.level == "supervised":
            if tool in READONLY_TOOLS:
                return True, ""
            if self.approver and self.approver(tool, args):
                return True, ""
            return False, "supervised mode allows read-only tools only"
        if self.level == "balanced":
            if tool == "run_skill":
                return False, "balanced mode blocks 'run_skill' (needs review)"
            if tool == "bash":
                ok, reason = command_allowed(args.get("command", ""))
                if not ok:
                    return False, f"balanced mode: {reason}"
                return True, ""
            return True, ""
        # autonomous: everything permitted (hooks/fail-closed still apply)
        return True, ""


def build_policy(cfg: dict | None = None, level: str | None = None,
                 cost_cap: int | None = None) -> AutonomyPolicy:
    """Construct a policy from config (BAIZE_AUTONOMY / BAIZE_AUTONOMY_COST_CAP)."""
    from .config import load_config
    cfg = cfg or load_config()
    lvl = level or cfg.get("BAIZE_AUTONOMY", "balanced")
    cap = cost_cap if cost_cap is not None else \
        int(cfg.get("BAIZE_AUTONOMY_COST_CAP", str(DEFAULT_COST_CAP)))
    return AutonomyPolicy(level=lvl, cost_cap=cap)
