"""Production operations for enterprise HTTP endpoints (V40.1).

Pure Python standard library implementations replacing former 501 stubs:
  1. POST /api/webhook/dispatch   -> real outbound HTTP POST + HMAC + SSRF guard
  2. POST/GET /api/security/rbac  -> persistent path RBAC policy + real evaluation
  3. POST/GET /api/tools/import   -> real runtime tool registration & workspace plugin loader
  4. POST /api/ci/autofix         -> real reproduction + workspace diagnostics + JobStore autofix
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import hmac
import importlib.util
import ipaddress
import json
import os
import posixpath
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ...core.config import load_config
from ... import __version__

# ---------------------------------------------------------------------------
# 1. Real Outbound Webhook Dispatch (SSRF-guarded + HMAC-SHA256)
# ---------------------------------------------------------------------------

def _is_private_or_reserved_host(host: str) -> tuple[bool, str]:
    """Resolve host and reject loopback/private/link-local/reserved IPs."""
    if not host:
        return True, "empty hostname"
    lower = host.strip().lower()
    if lower in ("localhost", "ip6-localhost", "ip6-loopback"):
        return True, f"host {host!r} is loopback"
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        return True, f"DNS resolution failed for {host!r}: {exc}"
    for info in infos:
        raw_ip = info[4][0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True, f"resolved IP {raw_ip} is non-public"
    return False, ""


def dispatch_webhook(data: dict[str, Any], cfg: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """Send a real outbound HTTP POST webhook with optional HMAC-SHA256 signing."""
    cfg = cfg or load_config()
    target = str(data.get("target") or "generic").strip()
    event = str(data.get("event") or "baize.event").strip()
    url = str(data.get("url") or "").strip()

    if not url:
        env_target_key = f"BAIZE_WEBHOOK_{target.upper().replace('-', '_')}_URL"
        url = str(
            cfg.get(env_target_key)
            or os.environ.get(env_target_key)
            or cfg.get("BAIZE_WEBHOOK_URL")
            or os.environ.get("BAIZE_WEBHOOK_URL")
            or ""
        ).strip()

    if not url:
        return 400, {
            "error": "missing_webhook_url",
            "message": "请提供有效的 Webhook URL（请求体 url 字段，或配置环境变量 BAIZE_WEBHOOK_URL）。",
        }

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return 400, {
            "error": "invalid_webhook_url",
            "message": f"仅支持合法的 http/https Webhook URL，收到：{url!r}",
        }

    allow_private = str(
        cfg.get("BAIZE_WEBHOOK_ALLOW_PRIVATE", os.environ.get("BAIZE_WEBHOOK_ALLOW_PRIVATE", "0"))
    ).strip().lower() in ("1", "true", "yes")
    if not allow_private:
        blocked, reason = _is_private_or_reserved_host(parsed.hostname)
        if blocked:
            return 403, {
                "error": "ssrf_blocked",
                "message": f"Webhook 目标地址被 SSRF 防护拦截（{reason}）。如需允许内网地址，请显式设置 BAIZE_WEBHOOK_ALLOW_PRIVATE=1。",
            }

    timeout = float(data.get("timeout", 10) or 10)
    timeout = max(1.0, min(timeout, 30.0))

    envelope = {
        "event": event,
        "target": target,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": f"baize-agent/{__version__}",
        "payload": data.get("payload") if isinstance(data.get("payload"), dict) else {},
    }
    body_bytes = json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8")

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": f"baize-agent/{__version__}",
        "X-Baize-Event": event,
    }
    secret = str(
        data.get("secret") or cfg.get("BAIZE_WEBHOOK_SECRET") or os.environ.get("BAIZE_WEBHOOK_SECRET") or ""
    ).strip()
    signed = False
    if secret:
        sig = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        headers["X-Baize-Signature"] = f"sha256={sig}"
        signed = True

    req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            http_status = int(getattr(resp, "status", 200))
            resp_preview = resp.read(512).decode("utf-8", errors="replace")
        latency_ms = round((time.monotonic() - t0) * 1000.0, 2)
        return 200, {
            "status": "delivered",
            "delivered": True,
            "http_status": http_status,
            "url": url,
            "target": target,
            "event": event,
            "signed": signed,
            "latency_ms": latency_ms,
            "response_preview": resp_preview,
            "message": f"Webhook 已真实送达（HTTP {http_status}，耗时 {latency_ms} ms）。",
        }
    except urllib.error.HTTPError as exc:
        latency_ms = round((time.monotonic() - t0) * 1000.0, 2)
        preview = ""
        try:
            preview = exc.read(512).decode("utf-8", errors="replace")
        except Exception:
            pass
        return 502, {
            "error": "webhook_http_error",
            "status": "failed",
            "delivered": False,
            "http_status": int(exc.code),
            "url": url,
            "event": event,
            "signed": signed,
            "latency_ms": latency_ms,
            "response_preview": preview,
            "message": f"远端 Webhook 返回错误 HTTP {exc.code}。",
        }
    except Exception as exc:
        latency_ms = round((time.monotonic() - t0) * 1000.0, 2)
        return 502, {
            "error": "webhook_delivery_failed",
            "status": "failed",
            "delivered": False,
            "url": url,
            "event": event,
            "signed": signed,
            "latency_ms": latency_ms,
            "message": f"Webhook 派发失败：{exc}",
        }


# ---------------------------------------------------------------------------
# 2. Persistent Path-Based RBAC Policy & Deterministic Evaluation
# ---------------------------------------------------------------------------

VALID_RBAC_PERMS = frozenset({"rw", "ro", "deny"})
_PERM_PRECEDENCE = {"deny": 3, "ro": 2, "rw": 1}


def _rbac_policy_path(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    pdir = Path(cfg.get("BAIZE_PERSISTENCE_DIR", "persistence"))
    pdir.mkdir(parents=True, exist_ok=True)
    return pdir / "rbac_policy.json"


def _compute_policy_digest(rules: list[dict[str, str]], secret: str = "") -> tuple[str, bool]:
    canonical = json.dumps(rules, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if secret:
        digest = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest[:32]}", True
    digest = hashlib.sha256(canonical).hexdigest()
    return f"sha256:{digest[:32]}", False


def _match_glob(path_str: str, pattern: str) -> bool:
    norm_path = posixpath.normpath(path_str.replace("\\", "/")).lstrip("./")
    norm_pat = pattern.replace("\\", "/").lstrip("./")
    if fnmatch.fnmatch(norm_path, norm_pat):
        return True
    if norm_pat.endswith("/**"):
        prefix = norm_pat[:-3].rstrip("/")
        if norm_path == prefix or norm_path.startswith(prefix + "/"):
            return True
    return False


def evaluate_rbac(rules: list[dict[str, str]], target_path: str, action: str = "read") -> dict[str, Any]:
    """Evaluate path access against RBAC rules (deny > ro > rw precedence)."""
    act = (action or "read").strip().lower()
    if act not in ("read", "write"):
        return {"allowed": False, "error": f"invalid action {action!r}; expected 'read' or 'write'"}
    matched: list[dict[str, str]] = [r for r in rules if _match_glob(target_path, r["path"])]
    if not matched:
        return {
            "path": target_path,
            "action": act,
            "allowed": True,
            "effective_perm": "default_allow",
            "matched_rule": None,
        }
    winning = max(matched, key=lambda r: _PERM_PRECEDENCE.get(r["perm"], 0))
    perm = winning["perm"]
    allowed = (perm == "rw") or (perm == "ro" and act == "read")
    return {
        "path": target_path,
        "action": act,
        "allowed": allowed,
        "effective_perm": perm,
        "matched_rule": winning,
    }


def load_rbac_policy(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    path = _rbac_policy_path(cfg)
    if not path.is_file():
        return {"rules": [], "policy_digest": _compute_policy_digest([])[0], "signed": False, "persisted": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["persisted"] = True
        return data
    except Exception:
        return {"rules": [], "policy_digest": _compute_policy_digest([])[0], "signed": False, "persisted": False}


def apply_and_evaluate_rbac(data: dict[str, Any], cfg: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """Persist validated RBAC rules and/or evaluate a target path against active rules."""
    cfg = cfg or load_config()
    raw_rules = data.get("rules")
    eval_path = data.get("evaluate_path")
    eval_action = str(data.get("action") or "read")

    if raw_rules is None and not eval_path:
        return 400, {
            "error": "missing_rbac_input",
            "message": "请提供 rules 列表（每项含 path 与 perm: rw|ro|deny）或 evaluate_path。",
        }

    policy = load_rbac_policy(cfg)
    if raw_rules is not None:
        if not isinstance(raw_rules, list) or not raw_rules:
            return 400, {"error": "invalid_rules", "message": "rules 必须是非空数组。"}
        cleaned: list[dict[str, str]] = []
        for idx, item in enumerate(raw_rules):
            if not isinstance(item, dict):
                return 400, {"error": "invalid_rule_item", "message": f"rules[{idx}] 必须是对象。"}
            r_path = str(item.get("path") or "").strip()
            r_perm = str(item.get("perm") or "").strip().lower()
            if not r_path:
                return 400, {"error": "empty_rule_path", "message": f"rules[{idx}].path 不能为空。"}
            if r_perm not in VALID_RBAC_PERMS:
                return 400, {
                    "error": "invalid_perm",
                    "message": f"rules[{idx}].perm={r_perm!r} 非法，仅允许 rw / ro / deny。",
                }
            cleaned.append({"path": r_path, "perm": r_perm})

        secret = str(cfg.get("BAIZE_AUTH_TOKEN") or os.environ.get("BAIZE_AUTH_TOKEN") or "").strip()
        digest, signed = _compute_policy_digest(cleaned, secret=secret)
        policy = {
            "rules": cleaned,
            "rules_count": len(cleaned),
            "policy_digest": digest,
            "signed": signed,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        pfile = _rbac_policy_path(cfg)
        tmp = pfile.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, pfile)
        policy["persisted"] = True
        policy["policy_file"] = str(pfile)

    resp: dict[str, Any] = {
        "status": "applied" if raw_rules is not None else "evaluated",
        "rules": policy.get("rules", []),
        "rules_count": len(policy.get("rules", [])),
        "policy_digest": policy.get("policy_digest", ""),
        "signed": bool(policy.get("signed", False)),
        "persisted": bool(policy.get("persisted", False)),
        "message": f"已持久化 {len(policy.get('rules', []))} 条路径 RBAC 策略（摘要 {policy.get('policy_digest', '')}）。",
    }
    if eval_path:
        evaluation = evaluate_rbac(policy.get("rules", []), str(eval_path), eval_action)
        if "error" in evaluation:
            return 400, {"error": "invalid_action", "message": evaluation["error"]}
        resp["evaluation"] = evaluation
    return 200, resp


# ---------------------------------------------------------------------------
# 3. Real Runtime Tool Import & Plugin Registration
# ---------------------------------------------------------------------------

def _builtin_hex_encoder(text: str = "", mode: str = "encode") -> str:
    if mode == "decode":
        return bytes.fromhex(text.strip()).decode("utf-8")
    return text.encode("utf-8").hex()


def _builtin_json_canonicalizer(data: str = "{}") -> str:
    parsed = json.loads(data)
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _builtin_path_sanitizer(path: str = "") -> str:
    norm = posixpath.normpath(path.replace("\\", "/"))
    parts = [p for p in norm.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)


BUILTIN_TOOL_CATALOG: dict[str, dict[str, Any]] = {
    "hex_encoder": {
        "description": "UTF-8 与十六进制安全编解码器",
        "version": "1.0.0",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "mode": {"type": "string", "enum": ["encode", "decode"]},
            },
            "required": ["text"],
        },
        "handler": _builtin_hex_encoder,
    },
    "json_canonicalizer": {
        "description": "规范化 JSON 键值对排序器（确定性紧凑输出）",
        "version": "1.1.0",
        "parameters": {
            "type": "object",
            "properties": {"data": {"type": "string"}},
            "required": ["data"],
        },
        "handler": _builtin_json_canonicalizer,
    },
    "path_sanitizer": {
        "description": "POSIX 与 Windows 路径穿越防御过滤器",
        "version": "2.0.0",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "handler": _builtin_path_sanitizer,
    },
}

_IMPORTED_TOOL_REGISTRY: Any = None


def get_imported_tool_registry():
    global _IMPORTED_TOOL_REGISTRY
    if _IMPORTED_TOOL_REGISTRY is None:
        from ...execution.tools import ToolRegistry

        _IMPORTED_TOOL_REGISTRY = ToolRegistry()
    return _IMPORTED_TOOL_REGISTRY


def _imported_tools_manifest_path(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    pdir = Path(cfg.get("BAIZE_PERSISTENCE_DIR", "persistence"))
    pdir.mkdir(parents=True, exist_ok=True)
    return pdir / "imported_tools.json"


def _persist_imported_tool_meta(meta: dict[str, Any], cfg: dict[str, Any] | None = None) -> Path:
    mpath = _imported_tools_manifest_path(cfg)
    existing: dict[str, Any] = {}
    if mpath.is_file():
        try:
            existing = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    existing[meta["name"]] = meta
    tmp = mpath.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, mpath)
    return mpath


def list_imported_tools(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    mpath = _imported_tools_manifest_path(cfg)
    persisted: dict[str, Any] = {}
    if mpath.is_file():
        try:
            persisted = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            persisted = {}
    return {
        "active_runtime_tools": get_imported_tool_registry().names(),
        "persisted_tools": persisted,
        "catalog": sorted(BUILTIN_TOOL_CATALOG.keys()),
    }


def import_runtime_tool(data: dict[str, Any], cfg: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """Register a verified built-in catalog tool or workspace Python tool into runtime registry."""
    cfg = cfg or load_config()
    name = str(data.get("name") or "").strip()
    module_path = str(data.get("module_path") or "").strip()
    func_name = str(data.get("function") or name).strip()

    if not name:
        return 400, {"error": "missing_tool_name", "message": "请提供要导入的工具名称 name。"}

    reg = get_imported_tool_registry()
    if name in BUILTIN_TOOL_CATALOG and not module_path:
        spec = BUILTIN_TOOL_CATALOG[name]
        reg.register(
            name=name,
            description=spec["description"],
            parameters=spec["parameters"],
            fn=spec["handler"],
        )
        meta = {
            "name": name,
            "source": "builtin_catalog",
            "version": spec["version"],
            "description": spec["description"],
            "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        mpath = _persist_imported_tool_meta(meta, cfg)
        return 200, {
            "status": "registered",
            "tool": meta,
            "active_runtime_tools": reg.names(),
            "manifest_file": str(mpath),
            "message": f"工具 {name} 已真实注册到运行时工具表并持久化。",
        }

    if module_path:
        ws = Path(cfg.get("BAIZE_WORKSPACE_DIR", ".")).resolve()
        target = (ws / module_path).resolve()
        try:
            target.relative_to(ws)
        except ValueError:
            return 403, {"error": "path_outside_workspace", "message": "插件模块路径不允许越出当前工作区。"}
        if not target.is_file() or target.suffix != ".py":
            return 400, {"error": "invalid_module_path", "message": f"找不到合法 Python 插件文件：{module_path}"}
        source_text = target.read_text(encoding="utf-8", errors="replace")
        try:
            ast.parse(source_text, filename=str(target))
        except SyntaxError as exc:
            return 400, {"error": "plugin_syntax_error", "message": f"插件存在语法错误：{exc}"}
        mod_spec = importlib.util.spec_from_file_location(f"baize_imported_{name}", str(target))
        if mod_spec is None or mod_spec.loader is None:
            return 400, {"error": "module_load_failed", "message": f"无法加载模块：{module_path}"}
        mod = importlib.util.module_from_spec(mod_spec)
        try:
            mod_spec.loader.exec_module(mod)
        except Exception as exc:
            return 400, {"error": "module_exec_failed", "message": f"加载插件模块失败：{exc}"}
        fn = getattr(mod, func_name, None)
        if not callable(fn):
            return 400, {"error": "callable_not_found", "message": f"模块中未找到可调用函数 {func_name!r}。"}
        desc = str(data.get("description") or (fn.__doc__ or "").strip() or f"Imported tool {name}")
        params = (
            data.get("parameters")
            if isinstance(data.get("parameters"), dict)
            else {"type": "object", "properties": {}}
        )
        reg.register(name=name, description=desc, parameters=params, fn=fn)
        meta = {
            "name": name,
            "source": "workspace_module",
            "module_path": str(target.relative_to(ws)),
            "function": func_name,
            "description": desc,
            "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        mpath = _persist_imported_tool_meta(meta, cfg)
        return 200, {
            "status": "registered",
            "tool": meta,
            "active_runtime_tools": reg.names(),
            "manifest_file": str(mpath),
            "message": f"工作区插件工具 {name}（{meta['module_path']}:{func_name}）已真实加载并注册。",
        }

    return 400, {
        "error": "unknown_tool",
        "available_catalog": sorted(BUILTIN_TOOL_CATALOG.keys()),
        "message": f"未找到内置目录工具 {name!r}，且未提供 module_path 工作区插件路径。",
    }


# ---------------------------------------------------------------------------
# 4. Real CI Failure Reproduction & Checkpointed Autofix Job Submission
# ---------------------------------------------------------------------------

def trigger_ci_autofix(
    data: dict[str, Any],
    cfg: dict[str, Any] | None,
    deps: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """Reproduce a failing CI command, diagnose workspace, and enqueue a checkpointed autofix job."""
    cfg = cfg or load_config()
    test_cmd = str(data.get("test_command") or "").strip()
    failure_log = str(data.get("failure_log") or "").strip()
    dry_run = bool(data.get("dry_run", False))
    workspace = str(data.get("workspace") or cfg.get("BAIZE_WORKSPACE_DIR") or ".").strip()

    if not test_cmd and not failure_log:
        return 400, {
            "error": "missing_ci_input",
            "message": "请提供 test_command（用于真实复现失败）或 failure_log（CI 失败日志）。",
        }

    reproduction: dict[str, Any] | None = None
    if test_cmd:
        from ...execution.tools import command_allowed

        ok_cmd, cmd_reason = command_allowed(test_cmd)
        if not ok_cmd:
            return 400, {"error": "command_blocked", "message": f"测试命令被安全护栏拦截：{cmd_reason}"}
        from ...execution import sandbox as sandbox_mod

        timeout_s = max(5, min(int(data.get("timeout", 60) or 60), 180))
        res = sandbox_mod.run(test_cmd, cwd=workspace, timeout=timeout_s)
        reproduction = {
            "command": test_cmd,
            "returncode": res.returncode,
            "stdout_tail": (res.stdout or "")[-2000:],
            "stderr_tail": (res.stderr or "")[-2000:],
            "mechanism": getattr(res, "mechanism", "local"),
        }
        if res.returncode == 0 and not failure_log:
            return 200, {
                "status": "already_passing",
                "reproduced": False,
                "reproduction": reproduction,
                "job_id": None,
                "message": "复现命令已通过（exit 0），无需发起自动修复。",
            }

    from ...codebase.diagnostics import diagnose_workspace

    diag_report = diagnose_workspace(workspace)
    diag_summary = {
        "files_checked": int(diag_report.get("files_checked", 0)),
        "errors": int(diag_report.get("total_errors", 0)),
        "warnings": int(diag_report.get("total_warnings", 0)),
        "reports": (diag_report.get("reports") or [])[:15],
    }

    if dry_run:
        return 200, {
            "status": "diagnosed",
            "reproduced": bool(reproduction and reproduction["returncode"] != 0),
            "reproduction": reproduction,
            "diagnostics": diag_summary,
            "job_id": None,
            "message": "已完成真实复现与工作区静态诊断（dry_run=true，未提交修复任务）。",
        }

    llm_probe = deps["LLMClient"](cfg)
    raw_keys = [
        getattr(m, "api_key", "") or ""
        for m in (getattr(llm_probe, "models", None) or [])
    ]
    has_non_placeholder = any(
        k and not k.startswith("__FILL") and "your-api-key" not in k.lower()
        for k in raw_keys
    )
    if not raw_keys or not deps["has_real_key"](llm_probe) or not has_non_placeholder:
        return 503, {
            "error": "llm_not_configured",
            "status": "reproduced_without_llm",
            "reproduced": bool(reproduction and reproduction["returncode"] != 0),
            "reproduction": reproduction,
            "diagnostics": diag_summary,
            "job_id": None,
            "message": "已完成真实故障复现与诊断，但当前未配置真实 LLM API Key，无法启动自动修复 Agent。",
        }

    goal_parts = [str(data.get("goal") or "修复 CI 失败并通过验证测试")]
    if reproduction:
        goal_parts.append(f"失败复现命令：{reproduction['command']} (exit={reproduction['returncode']})")
        if reproduction["stderr_tail"]:
            goal_parts.append(f"stderr 片段：\n{reproduction['stderr_tail']}")
    if failure_log:
        goal_parts.append(f"CI 失败日志：\n{failure_log[:3000]}")
    if diag_summary["errors"]:
        goal_parts.append(f"静态诊断报错数：{diag_summary['errors']}")
    autofix_goal = "\n\n".join(goal_parts)

    store = deps["get_job_store"]()

    def _autofix_worker(job_id: str, payload: dict[str, Any], emit, is_cancelled):
        emit("ci_autofix_started", {"workspace": workspace, "test_command": test_cmd})
        llm = deps["LLMClient"](cfg)
        agent = deps["Agent"](
            llm=llm,
            cfg=cfg,
            on_event=lambda k, p: emit(k, p),
            enable_checkpoint=True,
            auto_rollback=True,
        )
        res = agent.run(autofix_goal)
        return {
            "final_text": res.final_text,
            "stopped_reason": res.stopped_reason,
            "steps": res.steps,
            "session_id": res.session_id,
            "checkpoint_id": getattr(res, "checkpoint_id", ""),
            "rolled_back": getattr(res, "rolled_back", False),
        }

    job = store.enqueue("ci_autofix", {"workspace": workspace, "test_command": test_cmd}, _autofix_worker)
    return 202, {
        "status": "queued",
        "reproduced": bool(reproduction and reproduction["returncode"] != 0),
        "reproduction": reproduction,
        "diagnostics": diag_summary,
        "job_id": job["job_id"],
        "job": job,
        "message": f"已提交带 Git 检查点与自动回滚保护的异步修复作业 {job['job_id']}。",
    }
