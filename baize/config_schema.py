"""V20 configuration schema validation (fail-fast).

Validates types, ranges and enums of every BAIZE_* setting after load_config(),
raising ConfigError before the runtime starts. This is the preventive control
that stops misconfiguration from surfacing as cryptic runtime errors.
Zero third-party dependencies.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import load_config

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
    "BAIZE_TEAM_MEMORY_BACKEND": ("enum", ["local", "shared"]),
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
