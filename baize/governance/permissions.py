"""V49.0.0 Zenith: Three-State Fine-Grained Permission Rules Engine (.baize/permissions.json)."""
from __future__ import annotations

import fnmatch
import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.config import load_config

_TOOL_ALIASES: dict[str, frozenset[str]] = {
    "bash": frozenset({"bash", "bash_bg_start", "bg_start"}),
    "shell": frozenset({"bash", "bash_bg_start", "bg_start"}),
    "bg": frozenset({"bash_bg_start", "bash_bg_read", "bash_bg_stop", "bash_bg_send_input"}),
    "read": frozenset({"read_file", "list_dir", "grep_search", "find_files"}),
    "write": frozenset({"write_file"}),
    "patch": frozenset({"patch_file"}),
    "edit": frozenset({"write_file", "patch_file"}),
    "git": frozenset({"git"}),
    "browser": frozenset({"browser_action", "verify_ui"}),
    "mobile": frozenset({"mobile_verify"}),
    "compose": frozenset({"compose_stack"}),
    "web": frozenset({"fetch_url", "browser_action", "verify_ui"}),
    "*": frozenset({"*"}),
}

_RULE_RE = re.compile(r"^\s*([A-Za-z0-9_*:-]+?)(?:\((.*)\))?\s*$")


@dataclass(frozen=True)
class PermissionRule:
    raw: str
    effect: str  # "allow" | "ask" | "deny"
    tool_spec: str
    pattern: str = ""

    def matches_tool(self, tool_name: str) -> bool:
        t = (tool_name or "").strip().lower()
        spec = self.tool_spec.strip().lower()
        if spec == "*" or spec == t:
            return True
        aliases = _TOOL_ALIASES.get(spec)
        if aliases is not None and ("*" in aliases or t in aliases):
            return True
        return fnmatch.fnmatch(t, spec)

    def matches_target(self, target: str) -> bool:
        pat = self.pattern.strip()
        if not pat or pat == "*":
            return True
        tgt = (target or "").strip().replace("\\", "/")
        if pat.endswith(":*"):
            prefix = pat[:-2].strip()
            if tgt == prefix or tgt.startswith(prefix + " ") or tgt.startswith(prefix + "/"):
                return True
            return fnmatch.fnmatch(tgt, prefix + "*")
        norm_pat = pat.replace("\\", "/").replace("**/", "*")
        if fnmatch.fnmatch(tgt, norm_pat) or fnmatch.fnmatch(tgt, pat.replace("\\", "/")):
            return True
        if "/" not in norm_pat and "/" in tgt:
            base = tgt.rsplit("/", 1)[-1]
            if fnmatch.fnmatch(base, norm_pat):
                return True
        return False


@dataclass(frozen=True)
class PermissionDecision:
    action: str  # "allow" | "ask" | "deny" | "default"
    tool: str = ""
    matched_rule: str = ""
    reason: str = ""
    target: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "tool": self.tool,
            "matched_rule": self.matched_rule,
            "reason": self.reason,
            "target": self.target,
        }


def parse_permission_rule(raw: str, effect: str) -> PermissionRule | None:
    s = str(raw or "").strip()
    if not s:
        return None
    eff = effect.strip().lower()
    if eff not in ("allow", "ask", "deny"):
        raise ValueError(f"invalid permission effect: {effect!r}")
    m = _RULE_RE.match(s)
    if not m:
        return None
    return PermissionRule(
        raw=s,
        effect=eff,
        tool_spec=m.group(1).strip(),
        pattern=(m.group(2) or "").strip(),
    )


def _extract_target(tool_name: str, args: dict[str, Any] | None, workspace: str | Path = ".") -> str:
    a = args or {}
    t = (tool_name or "").strip().lower()
    if t in ("bash", "bash_bg_start", "bg_start"):
        return str(a.get("command") or "").strip()
    if t == "git":
        return str(a.get("args") or "").strip()
    if t in ("read_file", "write_file", "patch_file", "list_dir", "grep_search", "find_files"):
        raw_p = str(a.get("path") or "").strip()
        if not raw_p:
            return ""
        try:
            ws = Path(workspace).resolve()
            p = Path(raw_p)
            if p.is_absolute():
                rel = p.resolve().relative_to(ws)
                return str(rel).replace("\\", "/")
        except Exception:
            pass
        norm_p = raw_p.replace("\\", "/")
        while norm_p.startswith("./"):
            norm_p = norm_p[2:]
        return norm_p
    if t in ("browser_action", "verify_ui", "fetch_url"):
        act = str(a.get("action") or "").strip()
        url = str(a.get("url") or "").strip()
        return f"{act} {url}".strip() if act else url
    if t in ("mobile_verify", "compose_stack"):
        act = str(a.get("action") or "").strip()
        sub = str(a.get("service") or a.get("device_id") or a.get("compose_file") or "").strip()
        return f"{act} {sub}".strip() if sub else act
    if t in ("bash_bg_send_input", "bg_send_input"):
        return str(a.get("text") or a.get("proc_id") or "").strip()
    return str(a.get("command") or a.get("path") or a.get("url") or a.get("action") or "").strip()


@dataclass
class PermissionRuleSet:
    source: str = ""
    allow: list[PermissionRule] = field(default_factory=list)
    ask: list[PermissionRule] = field(default_factory=list)
    deny: list[PermissionRule] = field(default_factory=list)

    def evaluate(self, tool_name: str, args: dict[str, Any] | None = None, *, workspace: str | Path = ".") -> PermissionDecision:
        target = _extract_target(tool_name, args, workspace=workspace)
        for effect, bucket in (("deny", self.deny), ("ask", self.ask), ("allow", self.allow)):
            for rule in bucket:
                if rule.matches_tool(tool_name) and rule.matches_target(target):
                    return PermissionDecision(
                        action=effect,
                        tool=tool_name,
                        matched_rule=rule.raw,
                        reason=f"matched {effect} rule '{rule.raw}' for {tool_name}({target or '*'})",
                        target=target,
                    )
        return PermissionDecision(
            action="default",
            tool=tool_name,
            matched_rule="",
            reason="no explicit permission rule matched; using autonomy policy default",
            target=target,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "allow": [r.raw for r in self.allow],
            "ask": [r.raw for r in self.ask],
            "deny": [r.raw for r in self.deny],
            "total_rules": len(self.allow) + len(self.ask) + len(self.deny),
        }


_PERM_CACHE_LOCK = threading.Lock()
_PERM_CACHE: dict[str, tuple[int, int, PermissionRuleSet]] = {}


def discover_permissions_file(workspace: str | Path = ".", cfg: dict[str, Any] | None = None) -> Path | None:
    c = cfg if cfg is not None else load_config()
    explicit = str((c or {}).get("BAIZE_PERMISSIONS_FILE") or "").strip()
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = Path(workspace).resolve() / p
        return p if p.exists() and p.is_file() else None
    ws = Path(workspace).resolve()
    for rel in (".baize/permissions.json", ".baize/permissions.local.json"):
        cand = ws / rel
        if cand.exists() and cand.is_file():
            return cand
    return None


def load_permissions(workspace: str | Path = ".", cfg: dict[str, Any] | None = None) -> PermissionRuleSet:
    p = discover_permissions_file(workspace, cfg)
    if p is None:
        return PermissionRuleSet(source="")
    key = str(p.resolve())
    try:
        st = p.stat()
    except OSError:
        return PermissionRuleSet(source="")
    with _PERM_CACHE_LOCK:
        cached = _PERM_CACHE.get(key)
        if cached is not None and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
            return cached[2]
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return PermissionRuleSet(source=key)
    if not isinstance(raw, dict):
        return PermissionRuleSet(source=key)
    body = raw.get("permissions") if isinstance(raw.get("permissions"), dict) else raw
    rs = PermissionRuleSet(source=key)
    for effect, target_list in (("allow", rs.allow), ("ask", rs.ask), ("deny", rs.deny)):
        items = body.get(effect) or []
        if isinstance(items, list):
            for entry in items:
                rule = parse_permission_rule(str(entry), effect)
                if rule is not None:
                    target_list.append(rule)
    with _PERM_CACHE_LOCK:
        _PERM_CACHE[key] = (st.st_mtime_ns, st.st_size, rs)
    return rs


def evaluate_tool_permission(
    tool_name: str,
    args: dict[str, Any] | None = None,
    *,
    workspace: str | Path = ".",
    cfg: dict[str, Any] | None = None,
) -> PermissionDecision:
    ruleset = load_permissions(workspace, cfg)
    return ruleset.evaluate(tool_name, args, workspace=workspace)
