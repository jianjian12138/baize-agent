"""Autonomy policy levels and execution mode resolution (plan / act / autonomous)."""

from __future__ import annotations

# ===========================================================================
# Section: autonomy.py
# ===========================================================================

from ..execution.tools import command_allowed

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


_LEVEL_NUM_MAP = {
    "1": "supervised",
    "2": "balanced",
    "3": "autonomous",
}


def resolve_autonomy_level(cfg: dict | None = None) -> str:
    """Resolve effective autonomy level from BAIZE_YOLO_MODE / BAIZE_AUTONOMY / BAIZE_AUTONOMY_LEVEL."""
    cfg = cfg or {}
    if str(cfg.get("BAIZE_YOLO_MODE", "0")).strip() == "1":
        return "autonomous"
    explicit = (cfg.get("BAIZE_AUTONOMY") or "").strip()
    if explicit in ("supervised", "autonomous"):
        return explicit
    numeric = str(cfg.get("BAIZE_AUTONOMY_LEVEL", "")).strip()
    if numeric in _LEVEL_NUM_MAP:
        return _LEVEL_NUM_MAP[numeric]
    return explicit if explicit in VALID_LEVELS else "balanced"


def build_policy(cfg: dict | None = None, level: str | None = None,
                 cost_cap: int | None = None) -> AutonomyPolicy:
    """Construct a policy from config (BAIZE_AUTONOMY / BAIZE_AUTONOMY_LEVEL / BAIZE_YOLO_MODE)."""
    from .config import load_config
    cfg = cfg or load_config()
    lvl = level or resolve_autonomy_level(cfg)
    cap = cost_cap if cost_cap is not None else \
        int(cfg.get("BAIZE_AUTONOMY_COST_CAP", str(DEFAULT_COST_CAP)))
    return AutonomyPolicy(level=lvl, cost_cap=cap)

# ===========================================================================
# Section: modes.py
# ===========================================================================

# mode name -> bundle. ``loop`` is "default" or "programmatic".
MODES: dict[str, dict] = {
    "coding":      {"autonomy": "balanced",   "plan_mode": False, "loop": "default"},
    "eval":        {"autonomy": "supervised", "plan_mode": False, "loop": "programmatic"},
    "autonomous":  {"autonomy": "autonomous", "plan_mode": False, "loop": "default"},
    "safe-review": {"autonomy": "supervised", "plan_mode": True,  "loop": "default"},
}

VALID_MODES = tuple(MODES)


def resolve_mode(cfg: dict | None = None) -> dict:
    """Return the effective bundle, honoring BAIZE_MODE authority.

    When ``BAIZE_MODE`` is set and known, its bundle wins. Otherwise we fall
    back to the scalar sliders (BAIZE_AUTONOMY / BAIZE_PLAN_MODE). Always
    returns ``{"autonomy": str, "plan_mode": bool, "loop": str}``.
    """
    cfg = cfg or {}
    mode = (cfg.get("BAIZE_MODE", "") or "").strip()
    if mode and mode in MODES:
        return dict(MODES[mode])
    level = resolve_autonomy_level(cfg)
    if level not in VALID_LEVELS:  # defensive: unknown level -> balanced
        level = "balanced"
    plan_mode = str(cfg.get("BAIZE_PLAN_MODE", "0")) == "1"
    return {"autonomy": level, "plan_mode": plan_mode, "loop": "default"}
