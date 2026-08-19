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
    # Dedicated library for agent-learned / user-authored skills (V23.2).
    # Kept separate from assets/skills (built-in methodology) and any external
    # SKILL_LIBRARY_PATHS so "collected" and "autonomously-created" skills stay
    # distinguishable and auditable.
    "BAIZE_USER_SKILLS_DIR": str(ROOT / "user_skills"),
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
    "BAIZE_SANDBOX_ENABLED": "0",        # V21 P0-1 optional OS-level sandbox (off by default)
    "BAIZE_SESSIONS_DIR": str(ROOT / "persistence" / "sessions"),
    # --- V20 runtime ---
    "BAIZE_PLUGINS_ENABLED": "1",
    "BAIZE_PLUGINS_DIR": "",                  # extra plugin/component root (env-var driven)
    "BAIZE_OBSERVABILITY": "1",
    "BAIZE_METRICS_PORT": "9090",
    "BAIZE_MODEL_ROUTER": "",                 # JSON array of {name,base_url,api_key,weight} or empty
    "BAIZE_RATE_LIMIT_RPM": "60",
    "BAIZE_RATE_LIMIT_TPM": "60000",
    "BAIZE_SERVE_HOST": "127.0.0.1",
    "BAIZE_SERVE_PORT": "8787",
    "BAIZE_VECTOR_BACKEND": "tfidf",         # tfidf | embedding(reserved)
    "BAIZE_EMBEDDING_URL": "",               # reserved embedding endpoint
    "BAIZE_DASHBOARD_HOST": "127.0.0.1",
    "BAIZE_DASHBOARD_PORT": "8788",
    "BAIZE_TEAM_MEMORY_BACKEND": "local",    # local | shared(reserved)
    "BAIZE_VAULT_URL": "",                   # reserved secret backend
    # --- V21 P1-1 hooks (lifecycle events, fail-closed) ---
    "BAIZE_HOOKS_FILE": "",                  # path to .baize/hooks.json (off by default)
    # --- V21 P1-2 MCP client (pure stdlib, fail-closed trust boundary) ---
    "BAIZE_MCP_ENABLED": "0",                # MCP client OFF by default (explicit enable)
    "BAIZE_MCP_SERVERS": "",                 # JSON array of {name,command,args,transport}
                                             # whitelist, empty = no servers (reserved)
    # --- V21 P2-1 Plan Mode + autonomy slider (fail-closed) ---
    "BAIZE_PLAN_MODE": "0",                  # plan mode OFF by default
    "BAIZE_AUTONOMY": "balanced",            # supervised|balanced|autonomous
    "BAIZE_AUTONOMY_COST_CAP": "200000",     # est. token cap -> force downgrade
    # --- V21 P3-4 prompt cache (default OFF; explicit opt-in) ---
    "BAIZE_PROMPT_CACHE": "0",               # "1" attaches cache_control (anthropic)
    # --- V21 P2-3 Automations (zero-dep scheduler, fail-closed) ---
    "BAIZE_AUTOMATIONS_FILE": str(ROOT / "persistence" / "automations.json"),
    "BAIZE_AUTOMATIONS_POLL_SECONDS": "60",
    # --- V22 composition kernel (plugin architecture) ---
    "BAIZE_COMPONENTS": "",                  # "module.path:ClassName" overrides
                                             # or builtin kind names; empty=defaults
    "BAIZE_MODE": "",                        # coding|eval|autonomous|safe-review
                                             # (empty = scalar sliders apply)
    # --- V20 agent enhancement ---
    "BAIZE_REFLECT_EVERY": "6",              # self-reflection every N steps (0=off)
    "BAIZE_LOOP_DETECT_WINDOW": "3",         # identical tool-call repeats before warning
    "BAIZE_CONTEXT_COMPRESS_CHARS": "60000", # compress old observations past this size
    "BAIZE_MEMORY_COMPRESS_DAYS": "30",      # distill logs older than N days
    # --- V20 engineering ---
    "BAIZE_LOG_LEVEL": "INFO",               # DEBUG|INFO|WARNING|ERROR|CRITICAL
    "BAIZE_LOG_FORMAT": "text",              # text | json
    "BAIZE_CHAOS_ENABLED": "0",              # fault injection (testing only)
    "BAIZE_CHAOS_FAILURE_RATE": "0.0",       # 0.0-1.0 probability
    "BAIZE_CHAOS_SEED": "",                  # fixed seed = reproducible chaos
    # --- V23.4 pre-flight recon (external search default OFF) ---
    "BAIZE_RECON_WEB": "0",                  # "1" enables outbound web recon
    # --- V23.5 clarify-before-plan (default OFF; opt-in) ---
    "BAIZE_CLARIFY": "0",                    # "1" triggers prior-art clarification
    # --- V23.6 multi-dimensional quality gate ---
    "BAIZE_QUALITY_THRESHOLD": "0.7",        # overall quality score floor
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
