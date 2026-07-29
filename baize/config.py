"""Configuration loader for the Baize runtime.

Reads .env at the repository root (stdlib-only parser, no python-dotenv).
All paths are resolved relative to the repo root so the repo stays portable —
no hardcoded drive letters anywhere in the runtime.
"""
from __future__ import annotations

import os
from pathlib import Path

# Repo root = parent of the baize/ package directory.
ROOT = Path(__file__).resolve().parent.parent

ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

_DEFAULTS = {
    "BAIZE_PERSISTENCE_DIR": str(ROOT / "persistence"),
    "BAIZE_PROJECTS_DIR": str(ROOT / "projects"),
    "BAIZE_ASSETS_DIR": str(ROOT / "assets"),
    "BAIZE_INDEX_FILE": str(ROOT / "persistence" / "skill_index.json"),
    # Comma separated list of external skill library roots.
    "SKILL_LIBRARY_PATHS": "",
    "TEST_COVERAGE_THRESHOLD": "85",
    # --- Agent runtime (V19) ---
    "BAIZE_MODEL_BASE_URL": "",          # OpenAI-compatible endpoint base
    "BAIZE_MODEL_API_KEY": "",
    "BAIZE_MODEL_NAME": "",
    "BAIZE_LLM_MAX_RETRIES": "2",
    "BAIZE_AGENT_MAX_STEPS": "24",       # hard cap per agent run
    "BAIZE_WORKSPACE_DIR": str(ROOT),    # tool sandbox root
    "BAIZE_ALLOW_OUTSIDE_WORKSPACE": "0",
    "BAIZE_SESSIONS_DIR": str(ROOT / "persistence" / "sessions"),
}


def _parse_env_file(path: Path) -> dict:
    """Parse a .env style file. Ignores comments and blank lines."""
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def load_config(env_file: Path | None = None) -> dict:
    """Merged config: defaults < .env file < process environment."""
    cfg = dict(_DEFAULTS)
    cfg.update(_parse_env_file(env_file or ENV_FILE))
    for key in list(cfg.keys()):
        if key in os.environ:
            cfg[key] = os.environ[key]
    return cfg


def skill_library_paths(cfg: dict | None = None) -> list[Path]:
    """Return existing skill library roots declared in SKILL_LIBRARY_PATHS."""
    cfg = cfg or load_config()
    raw = cfg.get("SKILL_LIBRARY_PATHS", "")
    paths = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            paths.append(Path(part))
    return paths
