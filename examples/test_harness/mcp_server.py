#!/usr/bin/env python3
"""Zero-dependency Streamable HTTP MCP Server exposing the reusable Test Harness to Baize.

Exposes:
  - Tools:     run_harness(suite?, scenario_ids?), list_scenarios()
  - Resources: evidence://latest (JSON evidence bundle from last run)
  - Prompts:   triage_harness_failure(scenario_id)

Usage:
  python3 examples/test_harness/mcp_server.py --config path/to/my-service.harness.json --port 8790
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from core.config import load_harness_config
from core.engine import load_scenarios, run_harness


def make_mcp_handler(config_path: Path, artifacts_dir: Path, override_base_url: str = ""):
    session_id = f"baize-harness-mcp-{uuid.uuid4().hex[:8]}"

    class HarnessMCPHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send_json(self, code: int, payload: dict) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Mcp-Session-Id", session_id)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or 0)
            req = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            rid = req.get("id")
            method = str(req.get("method") or "")
            params = req.get("params") or {}

            if rid is None or method == "notifications/initialized":
                self.send_response(202)
                self.send_header("Mcp-Session-Id", session_id)
                self.end_headers()
                return

            if method == "initialize":
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                        "serverInfo": {"name": "baize-test-harness", "version": "1.0.0"},
                    },
                })
                return

            if method == "tools/list":
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "tools": [
                            {
                                "name": "run_harness",
                                "description": "Run deterministic business Test Harness and return JSON evidence bundle",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "suite": {"type": "string", "description": "Suite filter (all|smoke|e2e|fault)"},
                                        "scenario_ids": {"type": "array", "items": {"type": "string"}},
                                    },
                                },
                            },
                            {
                                "name": "list_scenarios",
                                "description": "List all scenarios configured in this Test Harness",
                                "inputSchema": {"type": "object", "properties": {}},
                            },
                        ]
                    },
                })
                return

            if method == "tools/call":
                tname = str(params.get("name") or "")
                targs = params.get("arguments") or {}
                cfg, cfg_dir = load_harness_config(config_path)
                if tname == "list_scenarios":
                    items = [
                        {"id": s.get("id"), "suite": s.get("suite", "e2e"), "description": s.get("description", "")}
                        for s in load_scenarios(cfg, cfg_dir)
                    ]
                    text = json.dumps(items, ensure_ascii=False)
                elif tname == "run_harness":
                    rep = run_harness(
                        cfg=cfg,
                        config_dir=cfg_dir,
                        artifacts_dir=artifacts_dir,
                        suite=str(targs.get("suite") or "all"),
                        scenario_ids=targs.get("scenario_ids") or None,
                        override_base_url=override_base_url,
                    )
                    text = json.dumps(rep, ensure_ascii=False)
                else:
                    self._send_json(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown tool: {tname}"}})
                    return
                self._send_json(200, {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}]}})
                return

            if method == "resources/list":
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "resources": [
                            {
                                "uri": "evidence://latest",
                                "name": "Latest Test Harness Evidence Bundle",
                                "description": "Most recent structured JSON verification report",
                                "mimeType": "application/json",
                            }
                        ]
                    },
                })
                return

            if method == "resources/read":
                rep_file = artifacts_dir / "latest_report.json"
                txt = rep_file.read_text(encoding="utf-8") if rep_file.is_file() else '{"status":"no_run_yet"}'
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {"contents": [{"uri": params.get("uri", "evidence://latest"), "mimeType": "application/json", "text": txt}]},
                })
                return

            if method == "prompts/list":
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "prompts": [
                            {
                                "name": "triage_harness_failure",
                                "description": "Diagnose and fix a failing Test Harness scenario using evidence://latest",
                                "arguments": [{"name": "scenario_id", "required": True}],
                            }
                        ]
                    },
                })
                return

            if method == "prompts/get":
                sc = (params.get("arguments") or {}).get("scenario_id", "unknown")
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "description": f"Triage failing scenario {sc}",
                        "messages": [
                            {
                                "role": "user",
                                "content": {
                                    "type": "text",
                                    "text": (
                                        f"Read evidence://latest for failing scenario '{sc}', "
                                        "identify the root cause in source code without mocking away business invariants, "
                                        "apply a minimal fix, and re-run run_harness until exit_code == 0."
                                    ),
                                },
                            }
                        ],
                    },
                })
                return

            self._send_json(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Method not found: {method}"}})

    return HarnessMCPHandler


def main() -> None:
    p = argparse.ArgumentParser(description="Streamable HTTP MCP server for Baize Reusable Test Harness")
    p.add_argument("--config", default=str(HERE / "harness.config.json"))
    p.add_argument("--base-url", default="")
    p.add_argument("--artifacts-dir", default="")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8790)
    args = p.parse_args()
    cfg_path = Path(args.config).resolve()
    artifacts = Path(args.artifacts_dir).resolve() if args.artifacts_dir else (cfg_path.parent / ".artifacts")
    srv = ThreadingHTTPServer((args.host, args.port), make_mcp_handler(cfg_path, artifacts, args.base_url.strip()))
    print(f"BAIZE_HARNESS_MCP_READY http://{args.host}:{args.port}/mcp config={cfg_path}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
