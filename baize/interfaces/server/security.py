"""HTTP authentication, CORS allowlist, path safety, and posture checks."""
from __future__ import annotations

import hmac
import re
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ...core.config import load_config

MAX_BODY = 1 << 20  # 1 MiB
ENV_WRITE_LOCK = threading.Lock()
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

INERT_SETTINGS_NOTE = (
    "autonomy_level (1=supervised, 2=balanced, 3=autonomous) and yolo_mode "
    "are stored in the server process environment under a lock and honored by "
    "baize/core/autonomy.py when BAIZE_MODE is unset."
)


def safe_child_path(base_dir: Path, name: str, suffix: str = "") -> Path | None:
    """Resolve a single child entry strictly inside ``base_dir`` (no traversal)."""
    cleaned = (name or "").strip()
    if not cleaned or cleaned in (".", "..") or not SAFE_NAME_RE.match(cleaned) or ".." in cleaned:
        return None
    root = base_dir.resolve()
    cand = (root / f"{cleaned}{suffix}").resolve()
    if root not in cand.parents:
        return None
    return cand


def req_path(raw_path: str) -> str:
    return urlparse(raw_path).path


def emit_cors(handler) -> bool:
    """Emit CORS headers only for explicitly allowlisted origins."""
    origin = handler.headers.get("Origin", "")
    allowed = [
        o.strip()
        for o in load_config().get("BAIZE_CORS_ORIGINS", "").split(",")
        if o.strip()
    ]
    if not origin or origin not in allowed:
        return False
    handler.send_header("Access-Control-Allow-Origin", origin)
    handler.send_header("Vary", "Origin")
    return True


def is_authorized(handler, *, require_token: bool = False) -> bool:
    """Decide whether this request may proceed (FAIL-CLOSED)."""
    cfg = load_config()
    token = (cfg.get("BAIZE_AUTH_TOKEN") or "").strip()
    if not token:
        if require_token:
            return False
        return cfg.get("BAIZE_ALLOW_NO_AUTH", "0") == "1"
    auth = handler.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].strip(), token):
        return True
    supplied = (parse_qs(urlparse(handler.path).query).get("token") or [""])[0]
    if supplied and hmac.compare_digest(supplied, token):
        return True
    return False


def code_exec_gate(handler) -> bool | None:
    """Guard for endpoints that exec caller-supplied code."""
    if not is_authorized(handler, require_token=True):
        handler._send(403, {
            "error": "this endpoint executes caller-supplied code and requires "
                     "a configured BAIZE_AUTH_TOKEN; BAIZE_ALLOW_NO_AUTH does "
                     "not apply here",
        })
        return True
    if load_config().get("BAIZE_ENABLE_SYNTHESIS_API", "0") != "1":
        handler._send(501, {
            "error": "code-execution endpoints are disabled by default; "
                     "set BAIZE_ENABLE_SYNTHESIS_API=1 to enable",
        })
        return True
    return None


def has_real_key(client) -> bool:
    """Reject placeholder keys like __FILL_YOUR_DEEPSEEK_KEY__."""
    models = getattr(client, "models", None)
    if not models:
        return True
    for m in models:
        key = getattr(m, "api_key", "")
        if key and not key.startswith("__FILL"):
            return True
    return False


def warn_about_auth_posture(cfg: dict, log) -> None:
    """Print the auth posture once at startup so it can never be a surprise."""
    token = (cfg.get("BAIZE_AUTH_TOKEN") or "").strip()
    no_auth = cfg.get("BAIZE_ALLOW_NO_AUTH", "0") == "1"
    if not token and not no_auth:
        log.warning(
            "No BAIZE_AUTH_TOKEN configured - all write operations will be "
            "rejected with 401. Set BAIZE_AUTH_TOKEN, or set "
            "BAIZE_ALLOW_NO_AUTH=1 for single-user localhost use."
        )
    elif not token and no_auth:
        log.warning(
            "BAIZE_ALLOW_NO_AUTH=1 - the service accepts UNAUTHENTICATED writes. "
            "This is intended for a single user on localhost. Do not use it on a "
            "shared or network-reachable host."
        )
    if cfg.get("BAIZE_ENABLE_SYNTHESIS_API", "0") == "1":
        log.warning(
            "/v30/synthesize and /v30/adversarial are ENABLED: they execute "
            "Python supplied in the request body. Keep the bearer token secret."
        )
    if cfg.get("BAIZE_CORS_ORIGINS", "").strip():
        log.info("CORS allowlist: %s", cfg["BAIZE_CORS_ORIGINS"])
