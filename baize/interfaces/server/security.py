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


from dataclasses import dataclass
import json as _json


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    role: str = "admin"
    workspace: str = "."
    max_usd: float = 0.0


def _parse_tenant_registry(raw: str) -> list[tuple[str, TenantContext]]:
    """Parse BAIZE_TENANT_TOKENS from JSON or comma/semicolon-delimited ``tenant:token:role:workspace``."""
    txt = (raw or "").strip()
    if not txt:
        return []
    entries: list[tuple[str, TenantContext]] = []
    if txt.startswith(("{", "[")):
        try:
            obj = _json.loads(txt)
            items = obj if isinstance(obj, list) else [
                {"tenant_id": k, **(v if isinstance(v, dict) else {"token": str(v)})}
                for k, v in obj.items()
            ]
            for it in items:
                tok = str(it.get("token") or "").strip()
                tid = str(it.get("tenant_id") or it.get("id") or "").strip()
                if tok and tid:
                    entries.append((tok, TenantContext(
                        tenant_id=tid,
                        role=str(it.get("role") or "member"),
                        workspace=str(it.get("workspace") or "."),
                        max_usd=float(it.get("max_usd") or 0.0),
                    )))
            return entries
        except Exception:
            return []
    for chunk in re.split(r"[;,]", txt):
        parts = [p.strip() for p in chunk.split(":")]
        if len(parts) >= 2 and parts[0] and parts[1]:
            entries.append((parts[1], TenantContext(
                tenant_id=parts[0],
                role=parts[2] if len(parts) >= 3 and parts[2] else "member",
                workspace=parts[3] if len(parts) >= 4 and parts[3] else ".",
            )))
    return entries


def resolve_tenant(handler, cfg: dict | None = None) -> TenantContext | None:
    """Match Bearer / query token against BAIZE_TENANT_TOKENS or BAIZE_AUTH_TOKEN."""
    cfg = cfg if cfg is not None else load_config()
    auth = handler.headers.get("Authorization", "")
    supplied = auth[7:].strip() if auth.startswith("Bearer ") else ""
    if not supplied:
        supplied = (parse_qs(urlparse(handler.path).query).get("token") or [""])[0]
    if supplied:
        for tok, ctx in _parse_tenant_registry(cfg.get("BAIZE_TENANT_TOKENS", "")):
            if hmac.compare_digest(supplied, tok):
                return ctx
        global_tok = (cfg.get("BAIZE_AUTH_TOKEN") or "").strip()
        if global_tok and hmac.compare_digest(supplied, global_tok):
            return TenantContext(tenant_id="default", role="admin", workspace=cfg.get("BAIZE_WORKSPACE_DIR", "."))
    return None


def is_authorized(handler, *, require_token: bool = False) -> bool:
    """Decide whether this request may proceed (FAIL-CLOSED, multi-tenant aware)."""
    cfg = load_config()
    tenant = resolve_tenant(handler, cfg)
    if tenant is not None:
        handler.tenant_context = tenant
        return True
    token = (cfg.get("BAIZE_AUTH_TOKEN") or "").strip()
    tenants = _parse_tenant_registry(cfg.get("BAIZE_TENANT_TOKENS", ""))
    if not token and not tenants:
        if require_token:
            return False
        if cfg.get("BAIZE_ALLOW_NO_AUTH", "0") == "1":
            handler.tenant_context = TenantContext(
                tenant_id="local",
                role="admin",
                workspace=cfg.get("BAIZE_WORKSPACE_DIR", "."),
            )
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
