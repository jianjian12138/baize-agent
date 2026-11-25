"""Configuration loader, typed schema validation, and structured logging setup."""

from __future__ import annotations

# ===========================================================================
# Section: config.py
# ===========================================================================

import os
import threading
from pathlib import Path

# Repo root = parent of the baize/ package directory.
ROOT = Path(__file__).resolve().parents[2]

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
    # Coverage floor enforced by scripts/coverage_gate.py - and read by CI, which
    # used to hardcode its own 80 while this file said 85 (the exact "two sources
    # of truth" drift the gate exists to prevent). One number now, here.
    # tests/test_config.py:39 pins this value; a test that disagrees with an edit
    # to this line is telling you the edit changed the contract, not that the test
    # is stale. Fix the coverage, do not edit the test.
    #
    # Do not record the current coverage percentage here. It was recorded here
    # once ("KNOWN GAP: actual coverage is 77.4%, the gate is therefore RED") and
    # the number was true when measured and false within the same day: committing
    # the 24 files that had been left untracked moved coverage to 86.6% and turned
    # the gate green, while this comment went on announcing a red gate to every
    # reader. A percentage in prose is a measurement wearing a claim's clothes.
    # The floor is the promise; the current value is whatever `make cov` prints.
    # Never lower this floor to make the gate pass.
    "TEST_COVERAGE_THRESHOLD": "85",
    # --- Agent runtime (V19) ---
    "BAIZE_MODEL_BASE_URL": "",          # OpenAI-compatible endpoint base
    "BAIZE_MODEL_API_KEY": "",
    "BAIZE_MODEL_NAME": "",
    "BAIZE_LLM_MAX_RETRIES": "3",            # deprecated alias for BAIZE_LLM_RETRY_MAX
    "BAIZE_AGENT_MAX_STEPS": "24",       # hard cap per agent run
    "BAIZE_WORKSPACE_DIR": str(ROOT),    # tool sandbox root
    "BAIZE_ALLOW_OUTSIDE_WORKSPACE": "0",
    "BAIZE_SANDBOX_ENABLED": "1",        # V21 P0-1 optional OS-level sandbox (off by default)
    # --- V40 industrial upgrade (tiered sandbox, checkpoints, diagnostics, jobs) ---
    "BAIZE_SANDBOX_MODE": "",                  # "" | local-hardened | docker | auto
    "BAIZE_SANDBOX_DOCKER_IMAGE": "python:3.11-slim",
    "BAIZE_SANDBOX_CPU_LIMIT_S": "60",
    "BAIZE_SANDBOX_MEM_LIMIT_MB": "1024",
    "BAIZE_CHECKPOINT": "0",                   # auto Git tree checkpoint per agent run
    "BAIZE_AUTO_ROLLBACK": "0",                # auto rollback workspace on failed run
    "BAIZE_AUTO_DIAGNOSTICS": "1",             # automatic post-edit diagnostics
    "BAIZE_LSP_CMD": "",                       # optional stdio LSP server command
    "BAIZE_HTTP_RPM": "0",                     # per-client HTTP requests/min (0=disabled)
    "BAIZE_JOB_WORKERS": "2",                  # persistent SQLite async job workers
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
    "BAIZE_TEAM_MEMORY_BACKEND": "local",    # local | shared | sqlite (V42 SQLite WAL)
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
    "BAIZE_QUALITY_THRESHOLD": "0.8",        # V25 release quality score floor
    # --- V37.1 security: service auth (fail-closed) ---
    # These three exist so the auth control is DISCOVERABLE. Previously
    # BAIZE_AUTH_TOKEN was read by serve.py but declared nowhere - not here, not
    # in .env.example, not in config_schema - so no user ever set it and
    # _is_authorized() fell through to its "no token -> allow everyone" branch.
    "BAIZE_AUTH_TOKEN": "",                  # empty = writes denied (see ALLOW_NO_AUTH)
    "BAIZE_ALLOW_NO_AUTH": "0",              # "1" = explicit local single-user opt-out
    "BAIZE_CORS_ORIGINS": "",                # comma-separated allowlist; empty = no CORS header
    "BAIZE_ENABLE_SYNTHESIS_API": "0",       # "1" = enable the exec-backed /v30 endpoints
    "BAIZE_GIT_EXE": "",                     # serve.py: explicit git path; empty = search PATH
    # --- V37.1 swarm: real git-worktree speculation ---
    # Executed with shell=True inside each branch's worktree, so it is a TRUSTED
    # value: treat it as code the operator wrote, and never splice request data
    # into it. The `goal` from POST /v30/swarm/speculate is carried for reporting
    # only and is not joined to this command - pinned by
    # tests/test_swarm_worktree.py::test_the_request_goal_cannot_reach_a_shell.
    "BAIZE_SWARM_VERIFY_CMD": "",            # shell command run inside each worktree; empty = no verification
    "BAIZE_SWARM_ARTIFACT": "baize_swarm_candidate.py",   # filename each branch writes into its worktree
    "BAIZE_SWARM_GIT_REF": "HEAD",           # commit the worktrees are checked out at
    # --- V37.1: keys that were referenced by code but never declared ---
    # Defaults below are copied from each call site's own fallback, NOT invented,
    # so declaring them is behaviour-preserving. BAIZE_AUTO_HARVEST_SKILLS is the
    # one to watch: its call site defaults to "1" (enabled), so declaring "0"
    # here would have silently disabled skill harvesting.
    "BAIZE_ALLOW_FETCH_URL": "0",            # tools.py: opt-in HTTP retrieval
    "BAIZE_AUTONOMY_LEVEL": "2",             # serve.py: numeric slider (1-3)
    "BAIZE_AUTO_HARVEST_SKILLS": "1",        # agent.py: call site defaults to ON
    "BAIZE_COVERAGE_DATA": ".coverage",      # gate.py: coverage data file
    "BAIZE_FORCE_COLOR": "0",                # ui.py: ANSI colour even when not a tty
    "BAIZE_MANIFEST": "baize.manifest.json", # gate.py: manifest path
    "BAIZE_MAX_TOKENS": "",                  # llm.py: empty = provider/model default
    "BAIZE_MCP_SPEC": "",                    # ext/mcp: empty = no external MCP spec
    "BAIZE_MODEL_PROVIDER": "",              # llm.py: empty = infer from base_url
    "BAIZE_ORCHESTRATOR_WORKERS": "4",       # orchestrator.py: parallel worker count
    "BAIZE_TOOL_RETRY_MAX": "2",             # agent.py: tool retry budget
    "BAIZE_YOLO_MODE": "0",                  # serve.py: reported by /api/status
    # V41 Polaris: tiered tools, interactive Diff approval, context governance, bounded memory & channels
    "BAIZE_TOOL_PROFILE": "tiered",          # context_engine.py: minimal (4) | tiered (6+tool_search) | full
    "BAIZE_APPROVAL_MODE": "tiered",         # approval.py: tiered (diff+cmd confirm) | auto | strict
    "BAIZE_SPILLOVER_BYTES": "8192",         # context_engine.py: spill oversized tool outputs to file
    "BAIZE_COMPACT_RATIO": "0.75",           # context_engine.py: auto-compact trigger ratio of budget
    "BAIZE_CONTEXT_BUDGET_TOKENS": "64000",  # context_engine.py: token budget for auto-compaction
    "BAIZE_MEMORY_MAX_CHARS": "2400",        # memory.py: bounded MEMORY.md snapshot character cap
    "BAIZE_USER_PROFILE_MAX_CHARS": "1400",  # memory.py: bounded USER.md snapshot character cap
    "BAIZE_CHANNEL_ALLOWLIST": "",           # channels.py: comma-separated allowed IM sender IDs
    # --- V42.0.0 Helios (Worktree Parallelism, Cost Breaker, Hybrid FTS5 & CDP) ---
    "BAIZE_WORKTREE_PARALLEL": "0",          # orchestrator.py: 1 = run parallel DAG subtasks in isolated git worktrees
    "BAIZE_MAX_SESSION_USD": "0",            # cost_ledger.py: hard USD cap per session (0 = unlimited)
    "BAIZE_MAX_SESSION_TOKENS": "0",         # cost_ledger.py: hard token cap per session (0 = unlimited)
    "BAIZE_BUDGET_WARN_RATIO": "0.8",        # cost_ledger.py: soft warning ratio (default 80%)
    "BAIZE_HYBRID_INDEX_PATH": "",           # hybrid_index.py: optional SQLite FTS5 index path override
    "BAIZE_CDP_BINARY": "",                  # cdp_browser.py: optional Chrome/Chromium/Edge binary path
    "BAIZE_CDP_TIMEOUT": "15",               # cdp_browser.py: CDP command timeout seconds
    "BAIZE_MULTIMODAL_MAX_BYTES": "4194304", # llm.py: max inline image attachment size (4 MB)
    # --- V43.0.0 Aegis (Production Security, Approval Bridge, Multi-Tenant & Resilience) ---
    "BAIZE_APPROVAL_BRIDGE": "",             # agent.py: "queue" bridges Agent approvals to ApprovalQueue
    "BAIZE_APPROVAL_TIMEOUT": "300",         # approval.py: seconds before pending approval fails closed
    "BAIZE_PROMPT_INJECTION_GUARD": "1",     # dlp.py: tag untrusted tool outputs matching injection rules
    "BAIZE_EGRESS_ALLOWLIST": "",            # dlp.py: comma-separated outbound host allowlist (empty=unrestricted)
    "BAIZE_TENANT_TOKENS": "",               # security.py: multi-tenant tokens (JSON or tenant:token:role list)
    "BAIZE_CB_FAILURE_THRESHOLD": "3",       # llm.py: provider circuit breaker consecutive failures to open
    "BAIZE_CB_COOLDOWN_S": "30",             # llm.py: provider circuit breaker open cooldown seconds
    "BAIZE_SHUTDOWN_GRACE_S": "10",          # serve.py: graceful shutdown drain timeout seconds
    # --- V44.0.0 Atlas (Git-Delta RAG, Auto-Diagnose Edit & OpenTelemetry OTLP) ---
    "BAIZE_HYBRID_MAX_FILES": "5000",        # hybrid_index.py: max workspace files indexed per scan
    "BAIZE_AUTO_DIAGNOSE_ON_EDIT": "1",      # tools.py: run fast AST diagnostics after write_file/patch_file
    "BAIZE_OTLP_ENDPOINT": "",               # telemetry.py: optional OTLP/HTTP JSON trace endpoint
    "BAIZE_OTLP_HEADERS": "",                # telemetry.py: optional comma-separated OTLP headers (k=v)
    # --- V45.0.0 Nexus & V46.0.0 Sovereign (Polyglot LSP Pool, Native Sandbox, Spec Gate & Visual Verify) ---
    "BAIZE_SANDBOX_NET": "allow",            # sandbox.py: local OS sandbox network policy ("allow" | "none")
    "BAIZE_LSP_IDLE_TIMEOUT": "300",         # diagnostics.py: pooled LSP server idle eviction seconds
    "BAIZE_LSP_AUTO_DIAGNOSE": "0",          # tools.py: also query pooled LSP after write_file/patch_file
    "BAIZE_SPEC_MODE": "0",                  # spec_workflow.py: default enable spec-first read-only hard-gate
    "BAIZE_DOCKER_SESSION_POOL": "1",        # docker_sandbox.py: reuse warm per-session Docker container via exec
    "BAIZE_VISUAL_VERIFY_VIEWPORTS": "desktop,mobile",  # visual_verify.py: default viewports for verify_ui
    # --- V47.0.0 Horizon & V48.0.0 Apex (Interactive CDP E2E, Mobile Bridge, Compose Stack & Win Job Sandbox) ---
    "BAIZE_BROWSER_IDLE_TIMEOUT": "300",     # cdp_browser.py: idle eviction seconds for stateful browser sessions
    "BAIZE_MOBILE_FALLBACK_WEB_URL": "",     # mobile_bridge.py: optional fallback Web/PWA URL when simulator absent
    "BAIZE_COMPOSE_FILE": "",                # compose_stack.py: optional explicit docker-compose file path
    "BAIZE_COMPOSE_TIMEOUT": "60",           # compose_stack.py: default compose up/port-wait timeout seconds
    "BAIZE_WIN_SANDBOX_RESTRICTED_TOKEN": "0",  # sandbox.py: 1 = also drop Win32 privileges via CreateRestrictedToken
    # --- V49.0.0 Zenith (Context Isolation, File Locks, Permissions Engine, Retry & Streaming) ---
    "BAIZE_REQUIRE_READ_BEFORE_EDIT": "0",   # tools.py: 1 = strictly require read_file before editing existing files
    "BAIZE_PERMISSIONS_FILE": "",            # permissions.py: optional explicit path to permissions.json
    "BAIZE_LLM_RETRY_MAX": "3",              # llm.py: max transient retry attempts (honoring Retry-After)
    "BAIZE_LLM_RETRY_BASE_S": "1.0",         # llm.py: base exponential backoff seconds for transient LLM errors
    "BAIZE_STREAM_TOOL_OUTPUT": "1",         # tools.py: 1 = stream live stdout chunks via ExecutionContext callback
}


_ENV_CACHE_LOCK = threading.Lock()
_ENV_CACHE: dict[Path, tuple[int, int, dict[str, str]]] = {}


def _parse_env_file(path: Path) -> dict:
    """Parse a .env style file with (mtime_ns, size) caching. Ignores comments/blanks."""
    try:
        st = path.stat()
    except OSError:
        with _ENV_CACHE_LOCK:
            _ENV_CACHE.pop(path, None)
        return {}
    sig_mtime, sig_size = st.st_mtime_ns, st.st_size
    with _ENV_CACHE_LOCK:
        cached = _ENV_CACHE.get(path)
        if cached is not None and cached[0] == sig_mtime and cached[1] == sig_size:
            return dict(cached[2])
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"').strip("'")
    with _ENV_CACHE_LOCK:
        _ENV_CACHE[path] = (sig_mtime, sig_size, dict(data))
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

# ===========================================================================
# Section: config_schema.py
# ===========================================================================

import json
import re


__all__ = ["ConfigError", "validate", "SCHEMA"]

# BAIZE_COMPONENTS token formats (structural only; semantic validity of a
# module:Class override is enforced by the composition kernel at assembly).
_COMPONENT_TOKEN = re.compile(r"^[\w.]+:[\w]+$|^[\w]+$")


class ConfigError(Exception):
    """Raised when configuration is invalid (fail-fast at startup)."""


# field -> (kind, spec)
# kinds: int_range(lo,hi) | float_range(lo,hi) | bool | enum([...])
#        | json_or_empty | path | any
SCHEMA: dict[str, tuple[str, object]] = {
    # --- V19 baseline ---
    "BAIZE_PERSISTENCE_DIR": ("path", None),
    "BAIZE_PROJECTS_DIR": ("path", None),
    "BAIZE_ASSETS_DIR": ("path", None),
    "BAIZE_INDEX_FILE": ("path", None),
    "SKILL_LIBRARY_PATHS": ("any", None),
    "TEST_COVERAGE_THRESHOLD": ("int_range", (0, 100)),
    "BAIZE_MODEL_BASE_URL": ("any", None),
    "BAIZE_MODEL_API_KEY": ("any", None),
    "BAIZE_MODEL_NAME": ("any", None),
    "BAIZE_LLM_MAX_RETRIES": ("int_range", (0, 10)),
    "BAIZE_AGENT_MAX_STEPS": ("int_range", (1, 200)),
    "BAIZE_WORKSPACE_DIR": ("path", None),
    "BAIZE_ALLOW_OUTSIDE_WORKSPACE": ("bool", None),
    "BAIZE_SESSIONS_DIR": ("path", None),
    # --- V20 ---
    "BAIZE_PLUGINS_ENABLED": ("bool", None),
    "BAIZE_OBSERVABILITY": ("bool", None),
    "BAIZE_METRICS_PORT": ("int_range", (0, 65535)),
    "BAIZE_MODEL_ROUTER": ("json_or_empty", None),
    "BAIZE_RATE_LIMIT_RPM": ("int_range", (0, 100000)),
    "BAIZE_RATE_LIMIT_TPM": ("int_range", (0, 100000000)),
    "BAIZE_SERVE_HOST": ("any", None),
    "BAIZE_SERVE_PORT": ("int_range", (0, 65535)),
    "BAIZE_VECTOR_BACKEND": ("enum", ["tfidf", "embedding"]),
    "BAIZE_EMBEDDING_URL": ("any", None),
    "BAIZE_DASHBOARD_HOST": ("any", None),
    "BAIZE_DASHBOARD_PORT": ("int_range", (0, 65535)),
    "BAIZE_TEAM_MEMORY_BACKEND": ("enum", ["local", "shared", "sqlite"]),
    "BAIZE_VAULT_URL": ("any", None),
    # --- V22 composition kernel (plugin architecture) ---
    "BAIZE_COMPONENTS": ("components", None),
    "BAIZE_MODE": ("mode", ["coding", "eval", "autonomous", "safe-review"]),
    # --- V20 agent enhancement ---
    "BAIZE_REFLECT_EVERY": ("int_range", (0, 100)),
    "BAIZE_LOOP_DETECT_WINDOW": ("int_range", (2, 20)),
    "BAIZE_CONTEXT_COMPRESS_CHARS": ("int_range", (1000, 10000000)),
    "BAIZE_MEMORY_COMPRESS_DAYS": ("int_range", (1, 3650)),
    # --- V20 engineering ---
    "BAIZE_LOG_LEVEL": ("enum", ["DEBUG", "INFO", "WARNING", "ERROR",
                                 "CRITICAL"]),
    "BAIZE_LOG_FORMAT": ("enum", ["text", "json"]),
    "BAIZE_CHAOS_ENABLED": ("bool", None),
    "BAIZE_CHAOS_FAILURE_RATE": ("float_range", (0.0, 1.0)),
    "BAIZE_CHAOS_SEED": ("any", None),
    # --- V21/V22 security + trust-boundary settings (F2: previously unvalidated,
    #     silent fail-open). Kind choices: bool / enum / path / int_range /
    #     json_or_empty / any (empty-allowed). ---
    "BAIZE_SANDBOX_ENABLED": ("bool", None),
    "BAIZE_PLUGINS_DIR": ("any", None),          # may be empty (no extra root)
    "BAIZE_HOOKS_FILE": ("any", None),           # may be empty (off by default)
    "BAIZE_MCP_ENABLED": ("bool", None),
    "BAIZE_MCP_SERVERS": ("json_or_empty", None),  # JSON array, may be empty
    "BAIZE_PLAN_MODE": ("bool", None),
    "BAIZE_AUTONOMY": ("enum", ["supervised", "balanced", "autonomous"]),
    "BAIZE_AUTONOMY_COST_CAP": ("int_range", (0, 100000000)),
    "BAIZE_PROMPT_CACHE": ("bool", None),
    "BAIZE_AUTOMATIONS_FILE": ("path", None),
    "BAIZE_AUTOMATIONS_POLL_SECONDS": ("int_range", (1, 3600)),
    # --- V37.1 service auth (fail-closed) ---
    # Validating these closes the second half of the old fail-open: a key that is
    # neither declared nor schema-checked cannot be misconfigured loudly.
    "BAIZE_AUTH_TOKEN": ("any", None),           # may be empty (= writes denied)
    "BAIZE_ALLOW_NO_AUTH": ("bool", None),
    "BAIZE_CORS_ORIGINS": ("any", None),         # may be empty (no CORS header)
    "BAIZE_ENABLE_SYNTHESIS_API": ("bool", None),
    "BAIZE_GIT_EXE": ("any", None),
    "BAIZE_SWARM_VERIFY_CMD": ("any", None),
    "BAIZE_SWARM_ARTIFACT": ("any", None),
    "BAIZE_SWARM_GIT_REF": ("any", None),
    # --- V37.1: previously referenced-but-undeclared keys, now validated ---
    "BAIZE_ALLOW_FETCH_URL": ("bool", None),
    "BAIZE_AUTONOMY_LEVEL": ("int_range", (1, 3)),
    "BAIZE_AUTO_HARVEST_SKILLS": ("bool", None),
    "BAIZE_COVERAGE_DATA": ("any", None),
    "BAIZE_FORCE_COLOR": ("bool", None),
    "BAIZE_MANIFEST": ("any", None),
    "BAIZE_MAX_TOKENS": ("any", None),           # empty = model default
    "BAIZE_MCP_SPEC": ("any", None),
    "BAIZE_MODEL_PROVIDER": ("any", None),
    "BAIZE_ORCHESTRATOR_WORKERS": ("int_range", (1, 64)),
    "BAIZE_TOOL_RETRY_MAX": ("int_range", (0, 10)),
    "BAIZE_YOLO_MODE": ("bool", None),
    # --- V43.0.0 Aegis & V44.0.0 Atlas ---
    "BAIZE_APPROVAL_BRIDGE": ("enum", ("", "queue", "terminal")),
    "BAIZE_APPROVAL_TIMEOUT": ("int_range", (1, 86400)),
    "BAIZE_PROMPT_INJECTION_GUARD": ("bool", None),
    "BAIZE_EGRESS_ALLOWLIST": ("any", None),
    "BAIZE_TENANT_TOKENS": ("any", None),
    "BAIZE_CB_FAILURE_THRESHOLD": ("int_range", (1, 50)),
    "BAIZE_CB_COOLDOWN_S": ("float_range", (0.01, 3600.0)),
    "BAIZE_SHUTDOWN_GRACE_S": ("int_range", (0, 300)),
    "BAIZE_HYBRID_MAX_FILES": ("int_range", (10, 200000)),
    "BAIZE_AUTO_DIAGNOSE_ON_EDIT": ("bool", None),
    "BAIZE_OTLP_ENDPOINT": ("any", None),
    "BAIZE_OTLP_HEADERS": ("any", None),
    # --- V45.0.0 Nexus & V46.0.0 Sovereign ---
    "BAIZE_SANDBOX_NET": ("enum", ("allow", "none")),
    "BAIZE_LSP_IDLE_TIMEOUT": ("int_range", (10, 3600)),
    "BAIZE_LSP_AUTO_DIAGNOSE": ("bool", None),
    "BAIZE_SPEC_MODE": ("bool", None),
    "BAIZE_DOCKER_SESSION_POOL": ("bool", None),
    "BAIZE_VISUAL_VERIFY_VIEWPORTS": ("any", None),
    # --- V47.0.0 Horizon & V48.0.0 Apex ---
    "BAIZE_BROWSER_IDLE_TIMEOUT": ("int_range", (10, 3600)),
    "BAIZE_MOBILE_FALLBACK_WEB_URL": ("any", None),
    "BAIZE_COMPOSE_FILE": ("any", None),
    "BAIZE_COMPOSE_TIMEOUT": ("int_range", (5, 600)),
    "BAIZE_WIN_SANDBOX_RESTRICTED_TOKEN": ("bool", None),
    # --- V49.0.0 Zenith ---
    "BAIZE_REQUIRE_READ_BEFORE_EDIT": ("bool", None),
    "BAIZE_PERMISSIONS_FILE": ("any", None),
    "BAIZE_LLM_RETRY_MAX": ("int_range", (0, 10)),
    "BAIZE_LLM_RETRY_BASE_S": ("float_range", (0.05, 30.0)),
    "BAIZE_STREAM_TOOL_OUTPUT": ("bool", None),
}


def _require_path(val: str) -> None:
    # Existence is enforced lazily at runtime (dirs are created on first write).
    # Here we only ensure the value is a non-empty, syntactically valid path.
    if not str(val).strip():
        raise ConfigError("path value is empty")


def validate(cfg: dict | None = None) -> dict:
    """Validate config; raise ConfigError on first violation set."""
    cfg = cfg if cfg is not None else load_config()
    errors: list[str] = []
    for key, (kind, spec) in SCHEMA.items():
        if key not in cfg:
            errors.append(f"missing config key: {key}")
            continue
        val = cfg[key]
        try:
            if kind == "int_range":
                lo, hi = spec  # type: ignore[misc]
                iv = int(val)
                if not (lo <= iv <= hi):
                    errors.append(f"{key}={val} out of range [{lo},{hi}]")
            elif kind == "float_range":
                lo, hi = spec  # type: ignore[misc]
                fv = float(val)
                if not (lo <= fv <= hi):
                    errors.append(f"{key}={val} out of range [{lo},{hi}]")
            elif kind == "bool":
                if str(val).lower() not in ("0", "1", "true", "false"):
                    errors.append(f"{key}={val} not a bool")
            elif kind == "enum":
                if val not in spec:  # type: ignore[operator]
                    errors.append(f"{key}={val} not in {spec}")
            elif kind == "json_or_empty":
                if str(val).strip():
                    json.loads(str(val))
            elif kind == "components":
                for tok in str(val).split(","):
                    tok = tok.strip()
                    if not tok:
                        continue
                    if not _COMPONENT_TOKEN.match(tok):
                        errors.append(
                            f"{key} token {tok!r} is not "
                            f"'module.path:ClassName' or a builtin kind name")
            elif kind == "mode":
                if val and val not in spec:  # type: ignore[operator]
                    errors.append(f"{key}={val} not in {spec}")
            elif kind == "path":
                _require_path(str(val))
        except ValueError as e:
            errors.append(f"{key}={val!r} invalid int ({e})")
        except json.JSONDecodeError as e:
            errors.append(f"{key} invalid JSON ({e})")
    if errors:
        raise ConfigError("; ".join(errors))
    return cfg


if __name__ == "__main__":
    try:
        validate()
        print("CONFIG: VALID")
    except ConfigError as e:
        print(f"CONFIG: INVALID — {e}")
        raise SystemExit(1)

# ===========================================================================
# Section: logging_setup.py
# ===========================================================================

import json
import logging
import re
import sys


__all__ = ["setup_logging", "get_logger", "JsonFormatter", "TextFormatter",
           "redact", "SECRET_PATTERNS"]

LOGGER_NAME = "baize"

# Patterns whose *values* must never appear in a log line.
SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(gh[pousr]_[A-Za-z0-9]{16,})"),
    re.compile(r"((?i:bearer)\s+)([A-Za-z0-9._\-]{12,})"),
    re.compile(r"((?i:api[_-]?key|token|secret|password)[\"']?\s*[:=]\s*[\"']?)"
               r"([^\s\"',}]{6,})"),
]


def redact(text: str) -> str:
    """Mask credential-looking substrings. Cheap, best-effort, always on."""
    if not text:
        return text
    out = text
    for pat in SECRET_PATTERNS:
        if pat.groups >= 2:
            out = pat.sub(lambda m: m.group(1) + "***REDACTED***", out)
        else:
            out = pat.sub("***REDACTED***", out)
    return out


class JsonFormatter(logging.Formatter):
    """One JSON object per line - ready for log shipping."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for key in ("session_id", "role", "tool", "step", "event"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable single line, with redaction applied."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                         datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(cfg: dict | None = None, stream=None) -> logging.Logger:
    """Configure the 'baize' logger. Idempotent - safe to call repeatedly."""
    cfg = cfg or load_config()
    level_name = str(cfg.get("BAIZE_LOG_LEVEL", "INFO")).upper()
    fmt = str(cfg.get("BAIZE_LOG_FORMAT", "text")).lower()

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    logger.propagate = False           # don't double-log through the root
    for h in list(logger.handlers):    # idempotency: replace, never stack
        logger.removeHandler(h)

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    logger.addHandler(handler)
    return logger


def get_logger(name: str = "") -> logging.Logger:
    """Child logger under the 'baize' namespace."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)
