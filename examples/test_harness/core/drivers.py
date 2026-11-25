"""Thin protocol-native HTTP & Web UI/ARIA drivers (zero external deps)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def json_extract(obj: Any, expr: str) -> Any:
    """Extract a value using dot-path syntax like '$.order.id' or 'products[0].sku'."""
    path = expr.strip()
    if path.startswith("$."):
        path = path[2:]
    elif path == "$":
        return obj
    cur = obj
    for token in re.split(r"\.(?![^\[]*\])", path):
        if not token:
            continue
        m = re.fullmatch(r"([^\[\]]+)\[(\d+)\]", token)
        if m:
            key, idx = m.group(1), int(m.group(2))
            if not isinstance(cur, dict) or key not in cur:
                return None
            seq = cur[key]
            if not isinstance(seq, list) or idx >= len(seq):
                return None
            cur = seq[idx]
        else:
            if isinstance(cur, dict) and token in cur:
                cur = cur[token]
            elif isinstance(cur, list) and token.isdigit() and int(token) < len(cur):
                cur = cur[int(token)]
            else:
                return None
    return cur


class HttpDriver:
    def __init__(self, base_url: str, default_headers: dict[str, str] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_headers = dict(default_headers or {})
        self.transcript: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        hdrs = {"Accept": "application/json, text/html"}
        hdrs.update(self.default_headers)
        if headers:
            hdrs.update(headers)
        data = None
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")

        req = urllib.request.Request(url, data=data, headers=hdrs, method=method.upper())
        t0 = time.monotonic()
        resp_headers: dict[str, str] = {}
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = int(resp.status)
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                raw_text = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            resp_headers = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
            raw_text = exc.read().decode("utf-8", errors="replace")

        elapsed_ms = round((time.monotonic() - t0) * 1000.0, 2)
        try:
            parsed_json = json.loads(raw_text)
        except Exception:
            parsed_json = None

        entry = {
            "method": method.upper(),
            "path": path,
            "request_body": json_body,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "headers": resp_headers,
            "json": parsed_json,
            "text": raw_text,
        }
        # Store compact transcript without huge HTML bodies
        self.transcript.append({
            "method": entry["method"],
            "path": entry["path"],
            "request_body": entry["request_body"],
            "status": entry["status"],
            "elapsed_ms": entry["elapsed_ms"],
            "json": entry["json"],
            "text_preview": raw_text[:300] if parsed_json is None else "",
        })
        return entry


def check_ui_contract(
    *,
    html: str,
    required_markers: list[str] | None = None,
    js_file: Path | None = None,
    node_eval: str = "",
) -> list[str]:
    """Verify HTML/ARIA semantic markers and optional JS syntax/runtime contract."""
    issues: list[str] = []
    for marker in (required_markers or []):
        if marker not in html:
            issues.append(f"UI HTML missing required marker: {marker!r}")

    if js_file is not None:
        if not js_file.is_file():
            issues.append(f"UI JS file not found: {js_file}")
        else:
            node_bin = shutil.which("node")
            if not node_bin:
                issues.append("Node.js unavailable on PATH to verify UI JS contract")
            else:
                syn = subprocess.run([node_bin, "--check", str(js_file)], capture_output=True, text=True)
                if syn.returncode != 0:
                    issues.append(f"JS syntax check failed: {syn.stderr.strip()}")
                elif node_eval:
                    env_code = f"const JS_FILE = {json.dumps(str(js_file))};\n{node_eval}"
                    run = subprocess.run([node_bin, "-e", env_code], capture_output=True, text=True)
                    if run.returncode != 0:
                        issues.append(f"JS runtime check failed: {run.stderr.strip() or run.stdout.strip()}")
    return issues
