"""Deterministic assertion oracles, SQL invariants, log checks, and Python hook loader."""
from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path
from typing import Any

from .drivers import json_extract


def evaluate_http_expect(resp: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    """Evaluate declarative expectations on an HTTP response dict."""
    errors: list[str] = []
    if not expect:
        return errors

    if "status" in expect:
        wanted = expect["status"]
        allowed = wanted if isinstance(wanted, list) else [wanted]
        if resp["status"] not in allowed:
            errors.append(f"HTTP status expected {wanted}, got {resp['status']} (body={resp.get('json') or resp.get('text', '')[:200]})")

    if "max_latency_ms" in expect:
        limit = float(expect["max_latency_ms"])
        if resp["elapsed_ms"] > limit:
            errors.append(f"Latency {resp['elapsed_ms']}ms exceeded budget {limit}ms")

    body_json = resp.get("json")
    for path_expr, expected_val in (expect.get("json_equals") or {}).items():
        actual = json_extract(body_json, path_expr)
        if actual != expected_val:
            errors.append(f"JSON mismatch at {path_expr}: expected {expected_val!r}, got {actual!r}")

    for path_expr in (expect.get("json_exists") or []):
        actual = json_extract(body_json, path_expr)
        if actual is None:
            errors.append(f"JSON missing required path {path_expr} in {body_json}")

    for path_expr, min_len in (expect.get("json_min_length") or {}).items():
        actual = json_extract(body_json, path_expr)
        if not isinstance(actual, (list, dict, str)) or len(actual) < int(min_len):
            errors.append(f"JSON path {path_expr} expected length >= {min_len}, got {actual!r}")

    for substr in (expect.get("text_contains") or []):
        if str(substr) not in str(resp.get("text", "")):
            errors.append(f"Response text missing expected substring: {substr!r}")

    for hdr_k, hdr_sub in (expect.get("header_contains") or {}).items():
        actual_h = str((resp.get("headers") or {}).get(hdr_k.lower(), ""))
        if str(hdr_sub).lower() not in actual_h.lower():
            errors.append(f"Header {hdr_k!r} expected to contain {hdr_sub!r}, got {actual_h!r}")

    return errors


def evaluate_sql_invariants(db_path: Path | None, checks: list[dict[str, Any]]) -> list[str]:
    """Run deterministic SQLite invariant queries (each query must return expected scalar or 0 violating rows)."""
    if not checks:
        return []
    if db_path is None or not db_path.is_file():
        return [f"SQL invariant requested but db_path not found: {db_path}"]
    errors: list[str] = []
    conn = sqlite3.connect(str(db_path))
    try:
        for chk in checks:
            name = str(chk.get("name") or "sql_invariant")
            query = str(chk.get("query") or "").strip()
            if not query:
                continue
            rows = conn.execute(query).fetchall()
            if "expect_zero_rows" in chk and chk["expect_zero_rows"]:
                if rows:
                    errors.append(f"SQL invariant '{name}' failed: found {len(rows)} violating row(s): {rows[:3]}")
            elif "expect_scalar" in chk:
                actual = rows[0][0] if rows and rows[0] else None
                if actual != chk["expect_scalar"]:
                    errors.append(f"SQL invariant '{name}' failed: expected {chk['expect_scalar']!r}, got {actual!r}")
    finally:
        conn.close()
    return errors


def evaluate_log_invariants(logs: str, forbidden_markers: list[str] | None = None) -> list[str]:
    if not logs:
        return []
    markers = forbidden_markers if forbidden_markers is not None else ["Traceback (most recent call last)", "INTERNAL_ERROR", " 500 "]
    return [f"Service log contains forbidden error marker: {m!r}" for m in markers if m in logs]


def run_python_oracle_hook(hook_spec: str, *, world: Any, context: dict[str, Any], config_dir: Path) -> list[str]:
    """Invoke a custom business invariant hook 'module.path:func_name' returning list[str] of violations."""
    if ":" not in hook_spec:
        return [f"Invalid oracle hook format {hook_spec!r}; expected 'module.path:function_name'"]
    mod_name, fn_name = hook_spec.split(":", 1)
    if str(config_dir) not in sys.path:
        sys.path.insert(0, str(config_dir))
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, fn_name)
    res = fn(world=world, context=context)
    if not res:
        return []
    if isinstance(res, list):
        return [str(x) for x in res]
    return [str(res)]
