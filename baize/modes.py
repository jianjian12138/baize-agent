"""V22 #97 (review downgrade): named modes as configuration bundles.

A mode packs the existing scalar autonomy slider + plan_mode into a named,
intent-driven configuration (the harness "four modes = preset plugin sets"
idea, localised honestly). The plan's review explicitly downgraded
``mode = plugin set`` to a closing item and fixed the authority rule:

**Authority (review fix #8):** when ``BAIZE_MODE`` is explicitly set and known,
its bundle OVERRIDES the scalar sliders (``BAIZE_AUTONOMY`` / ``BAIZE_PLAN_MODE``).
The scalar sliders remain the fallback when no mode is selected. A bad/unknown
mode name is ignored (fail-closed to the scalar sliders) rather than crashing.

``eval`` is the minimal mode (harness "Minimal" analogue): LLM-free
``ProgrammaticLoop`` + supervised (read-only) tools, for deterministic benches.
"""
from __future__ import annotations

from .autonomy import AutonomyPolicy, VALID_LEVELS

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
    level = cfg.get("BAIZE_AUTONOMY", "balanced")
    if level not in VALID_LEVELS:  # defensive: unknown level -> balanced
        level = "balanced"
    plan_mode = str(cfg.get("BAIZE_PLAN_MODE", "0")) == "1"
    return {"autonomy": level, "plan_mode": plan_mode, "loop": "default"}
