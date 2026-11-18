"""GET route handlers for the Baize HTTP server."""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..config import load_config
from .security import INERT_SETTINGS_NOTE, SAFE_NAME_RE

_SKIP_SCAN_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", "persistence", ".venv", "venv", "dist", "build",
})


def handle_export_session(handler, sid: str, deps: dict[str, Any]) -> None:
    sessions_mod = deps["sessions_mod"]
    version = deps["version"]
    try:
        recs = sessions_mod._read_records(sid)
    except ValueError:
        return handler._send(400, {"error": "invalid session id"})
    except FileNotFoundError:
        return handler._send(404, {"error": "session not found"})

    msgs = [r.get("message", r) for r in recs if r.get("kind") == "message"]
    lines = [
        "# 白泽智能体执行轨迹与审计报告",
        "",
        f"- **会话 ID**: `{sid}`",
        f"- **导出时间**: `{time.strftime('%Y-%m-%d %H:%M:%S')}`",
        f"- **执行内核**: Baize Agent V{version} (NO FAKE DONE Physical Gate Certified)",
        "",
        "---",
        "",
        "## 📋 对话与执行记录明细",
        "",
    ]
    for idx, m in enumerate(msgs, 1):
        role = "🧑 User" if m.get("role") == "user" else "🤖 Baize Agent"
        lines.append(f"### {idx}. {role}")
        lines.append(m.get("content", ""))
        lines.append("")
    return handler._send_text(200, "\n".join(lines), "text/markdown; charset=utf-8")


def handle_git_status_or_diff(handler, req_path: str, deps: dict[str, Any]) -> None:
    """Serve /api/git/status and /api/git/diff honestly."""
    git_exe = deps["resolve_git"]()
    if not git_exe:
        return handler._send(503, {
            "error": "git_unavailable",
            "git_available": False,
            "message": "no usable git executable found (looked on PATH and at "
                       "BAIZE_GIT_EXE); cannot report repository state",
        })
    cwd = load_config().get("BAIZE_WORKSPACE_DIR", ".")
    proc_mod = deps["proc_mod"]
    try:
        if req_path == "/api/git/status":
            res = proc_mod.run([git_exe, "status", "-s"], timeout=30, cwd=cwd)
            branch_res = proc_mod.run([git_exe, "branch", "--show-current"], timeout=30, cwd=cwd)
            if res.timed_out or branch_res.timed_out:
                return handler._send(503, {
                    "error": "git_timeout",
                    "git_available": True,
                    "message": "git did not respond in 30s",
                })
            return handler._send(200, {
                "git_available": True,
                "branch": branch_res.stdout.strip(),
                "status_output": res.stdout,
                "clean": len(res.stdout.strip()) == 0,
            })
        res = proc_mod.run([git_exe, "diff"], timeout=60, cwd=cwd)
        if res.timed_out:
            return handler._send(503, {
                "error": "git_timeout",
                "git_available": True,
                "message": "git diff did not respond in 60s",
            })
        return handler._send(200, {"git_available": True, "diff": res.stdout})
    except Exception as exc:  # noqa: BLE001
        return handler._send(503, {
            "error": "git_failed",
            "git_available": False,
            "message": f"git could not be run: {exc}",
        })


def dispatch_get(handler, req_path: str, deps: dict[str, Any]) -> None:
    dashboard = deps["dashboard"]
    obs = deps["obs"]
    sessions_mod = deps["sessions_mod"]
    session_cls = deps["Session"]
    bench_mod = deps["bench_mod"]
    bench_public_mod = deps["bench_public_mod"]
    gate_mod = deps["gate_mod"]
    version = deps["version"]
    server_start_time = deps["SERVER_START_TIME"]

    # Public routes (UI, static assets, health, metrics)
    if req_path in ("/", "/dashboard", "/index.html"):
        return handler._send_text(200, dashboard.render(), "text/html; charset=utf-8")

    if req_path in ("/studio/styles.css", "/studio/app.js"):
        from ..desktop_ui import read_studio_asset
        asset_name = req_path.rsplit("/", 1)[-1]
        content = read_studio_asset(asset_name)
        if content is None:
            return handler._send(404, {"error": "asset not found"})
        ctype = (
            "text/css; charset=utf-8"
            if asset_name.endswith(".css")
            else "application/javascript; charset=utf-8"
        )
        etag = '"' + hashlib.sha256(content.encode("utf-8")).hexdigest()[:16] + '"'
        if handler.headers.get("If-None-Match") == etag:
            handler.send_response(304)
            handler.send_header("ETag", etag)
            handler.end_headers()
            return
        body = content.encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", ctype)
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", "public, max-age=300")
        handler._emit_cors()
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return

    if req_path == "/health":
        from ..tools import EXECUTION_BOUNDARY
        return handler._send(200, {
            "status": "ok",
            "version": version,
            "execution_boundary": EXECUTION_BOUNDARY,
        })

    if req_path == "/metrics":
        return handler._send_text(200, obs.prometheus(), "text/plain; version=0.0.4; charset=utf-8")

    if req_path == "/api/metrics/summary":
        cfg = load_config()
        runs = obs.counter("serve_run", 0)
        team_runs = obs.counter("serve_team", 0)
        tool_calls = obs.counter("tool_calls", 0)
        est_tokens = (runs + team_runs) * 1250 + 1500
        from ..llm import get_http_pool_stats
        from ..arch_cache import get_arch_cache_stats
        return handler._send(200, {
            "uptime_seconds": int(time.time() - server_start_time),
            "total_runs": runs,
            "total_team_runs": team_runs,
            "total_tool_calls": tool_calls,
            "estimated_tokens": est_tokens,
            "estimated_cost_cny": round(est_tokens * 0.000014, 4),
            "active_model": cfg.get("BAIZE_MODEL_NAME", "deepseek-chat"),
            "http_pool": get_http_pool_stats(),
            "arch_cache": get_arch_cache_stats(),
            "status": "healthy",
        })

    # Authenticated routes
    if not handler._is_authorized():
        return handler._send(401, {"error": "unauthorized: invalid or missing bearer token"})

    if req_path == "/bench":
        return handler._send(200, {
            "bench": bench_mod.run_all(),
            "public": bench_public_mod.coverage_report(),
        })

    if req_path == "/gate":
        return handler._send(200, gate_mod.run_gate())

    if req_path == "/sessions":
        return handler._send(200, {"sessions": session_cls.list_sessions()})

    if req_path == "/sessions/lineage/tree":
        lineages = sessions_mod.list_lineage()
        sessions = session_cls.list_sessions()
        tree = []
        for s in sessions:
            sid = s["id"]
            lin = lineages.get(sid) or {}
            tree.append({
                "id": sid,
                "parent": lin.get("parent"),
                "fork_at_index": lin.get("at_index"),
                "created_at": s.get("created_at"),
                "messages_count": s.get("messages_count", 0),
            })
        return handler._send(200, {"nodes": tree})

    if req_path == "/api/tools/hub":
        return handler._send(200, {
            "tools": [
                {"name": "hex_encoder", "desc": "高阶十六进制安全编解码器", "version": "1.0.0", "author": "Darwin Synthesizer", "gene": "GENE-HEX-9821"},
                {"name": "json_canonicalizer", "desc": "规范化 JSON 键值对排序器", "version": "1.1.0", "author": "Darwin Synthesizer", "gene": "GENE-JSON-7412"},
                {"name": "path_sanitizer", "desc": "POSIX 与 Windows 路径穿越防御过滤", "version": "2.0.0", "author": "Baize Security", "gene": "GENE-PATH-3309"},
            ]
        })

    if req_path.startswith("/sessions/") and req_path.endswith("/export"):
        sid = req_path[len("/sessions/"):len(req_path) - len("/export")].strip()
        return handle_export_session(handler, sid, deps)

    if req_path.startswith("/sessions/"):
        sid = req_path[len("/sessions/"):]
        if not sid or not SAFE_NAME_RE.match(sid) or ".." in sid:
            return handler._send(400, {"error": "bad session id"})
        try:
            recs = sessions_mod._read_records(sid)
        except (FileNotFoundError, ValueError):
            return handler._send(404, {"error": "session not found"})
        lineage = sessions_mod.list_lineage().get(sid)
        return handler._send(200, {
            "session_id": sid,
            "messages": [r.get("message", r) for r in recs if r.get("kind") == "message"],
            "fork_of": lineage.get("parent") if lineage else None,
            "fork_at_index": lineage.get("at_index") if lineage else None,
        })

    if req_path == "/api/workspace/files":
        root_str = str(Path(load_config().get("BAIZE_WORKSPACE_DIR", ".")).resolve())
        files: list[str] = []
        stack = [root_str]
        try:
            while stack and len(files) < 500:
                cur = stack.pop()
                with os.scandir(cur) as it:
                    for entry in it:
                        if entry.is_dir(follow_symlinks=False):
                            if not entry.name.startswith(".") and entry.name not in _SKIP_SCAN_DIRS:
                                stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            files.append(os.path.relpath(entry.path, root_str).replace("\\", "/"))
                            if len(files) >= 500:
                                break
        except Exception:
            pass
        return handler._send(200, {"files": files})

    if req_path == "/api/workspace/search":
        params = parse_qs(urlparse(handler.path).query)
        q = (params.get("q", [""])[0] or "").strip()
        if not q:
            return handler._send(400, {"error": "q parameter required"})
        glob_pat = params.get("glob", [""])[0]
        use_regex = params.get("regex", ["1"])[0] != "0"
        case_sensitive = params.get("case", ["1"])[0] != "0"
        from ..tools import _tool_grep_search
        output = _tool_grep_search(
            pattern=q,
            glob=glob_pat,
            regex=use_regex,
            case_sensitive=case_sensitive,
            max_results=int(params.get("limit", ["50"])[0] or 50),
        )
        return handler._send(200, {"query": q, "output": output})

    if req_path == "/api/perf/profile":
        params = parse_qs(urlparse(handler.path).query)
        include_cp = params.get("cprofile", ["0"])[0] == "1"
        from ..perf import profile_workspace
        return handler._send(200, profile_workspace(include_cprofile=include_cp))

    if req_path == "/api/commands":
        cmds = [
            {"name": "/help", "desc": "查看全部可用指令与技能列表"},
            {"name": "/grill-with-docs", "desc": "[Matt Pocock] 深度盘问与暴露隐藏假设 (Grill Interview)"},
            {"name": "/to-spec", "desc": "[Matt Pocock] 将方案讨论沉淀为形式化 Spec 规范"},
            {"name": "/to-tickets", "desc": "[Matt Pocock] 将 Spec 规范拆解为上下文安全的小工单"},
            {"name": "/implement", "desc": "[Matt Pocock] 严格执行 TDD 先测后写实施"},
            {"name": "/code-review", "desc": "[Matt Pocock] 对标 Spec 规范进行自动化代码评审"},
            {"name": "/doctor", "desc": "运行系统与环境健康体检诊断"},
            {"name": "/audit", "desc": "对当前工作区进行架构与安全审计"},
            {"name": "/trace", "desc": "查看上一次运行的毫秒级 Trace 链路与 Span 耗时"},
            {"name": "/cost", "desc": "查看 Token 消耗统计与成本预估"},
            {"name": "/fork", "desc": "从当前步骤平行分叉出新实验分支"},
            {"name": "/rewind", "desc": "时间旅行回退会话历史状态"},
            {"name": "/clear", "desc": "清空当前会话屏幕输出"},
            {"name": "/setup", "desc": "重新启动大模型配置向导"},
        ]
        return handler._send(200, {"commands": cmds})

    if req_path == "/api/windows/status":
        from ..powershell import get_powershell_status
        return handler._send(200, get_powershell_status())

    if req_path == "/api/mcp/tools":
        from ..mcp import list_all_mcp_tools, load_mcp_config
        ws = load_config().get("BAIZE_WORKSPACE_DIR", ".")
        cfg = load_mcp_config(ws)
        tools = list_all_mcp_tools(ws)
        return handler._send(200, {
            "status": "ready",
            "servers_count": len(cfg.get("mcpServers", {})),
            "tools": tools,
            "protocol": "mcp/2024-11-05",
        })

    if req_path == "/api/symbols/graph":
        from ..arch_cache import get_cached_symbol_graph
        cfg = load_config()
        graph = get_cached_symbol_graph(cfg.get("BAIZE_WORKSPACE_DIR", "."), cfg=cfg)
        return handler._send(200, graph.get_summary())

    if req_path == "/api/symbols/search":
        params = parse_qs(urlparse(handler.path).query)
        q = params.get("q", [""])[0]
        from ..arch_cache import get_cached_symbol_graph
        cfg = load_config()
        graph = get_cached_symbol_graph(cfg.get("BAIZE_WORKSPACE_DIR", "."), cfg=cfg)
        return handler._send(200, {"query": q, "results": graph.search_symbols(q)})

    if req_path == "/api/market/tools":
        from ..tool_market import list_market_tools
        return handler._send(200, {"status": "ready", "tools": list_market_tools()})

    if req_path == "/api/repomap":
        from ..repo_map import generate_workspace_repo_map
        return handler._send(200, {"status": "ready", "repo_map": generate_workspace_repo_map()})

    if req_path == "/api/docs/list":
        from ..doc_crawler import DocCrawlerRegistry
        return handler._send(200, {"status": "ready", "docs": DocCrawlerRegistry.list_indexed_docs()})

    if req_path == "/api/models":
        cfg = load_config()
        return handler._send(200, {
            "active_model": cfg.get("BAIZE_MODEL_NAME", "deepseek-chat"),
            "base_url": cfg.get("BAIZE_MODEL_BASE_URL", "https://api.deepseek.com"),
            "models": [
                {"id": "deepseek-chat", "name": "DeepSeek V3 (Chat)", "provider": "DeepSeek"},
                {"id": "deepseek-reasoner", "name": "DeepSeek R1 (Reasoner)", "provider": "DeepSeek"},
                {"id": "gpt-4o", "name": "OpenAI GPT-4o", "provider": "OpenAI"},
                {"id": "gpt-4o-mini", "name": "OpenAI GPT-4o Mini", "provider": "OpenAI"},
                {"id": "claude-3-7-sonnet", "name": "Claude 3.7 Sonnet", "provider": "Anthropic"},
                {"id": "qwen2.5-coder:latest", "name": "Qwen 2.5 Coder (Local)", "provider": "Ollama"},
                {"id": "llama3.3:latest", "name": "Llama 3.3 (Local)", "provider": "Ollama"},
            ],
        })

    if req_path == "/api/skills":
        from .. import skill_index
        from ..skills_catalog import get_full_skills_catalog
        idx = skill_index.build_index()
        skills = list(idx.get("skills", []))
        existing_names = {s.get("name") for s in skills}
        for cat_skill in get_full_skills_catalog():
            if cat_skill["name"] not in existing_names:
                skills.append(cat_skill)
        return handler._send(200, {"skills": skills, "total": len(skills), "libraries": idx.get("libraries", [])})

    if req_path.startswith("/api/skills/"):
        sname = req_path[len("/api/skills/"):].strip()
        from ..skills_catalog import get_skill_content
        return handler._send(200, {"name": sname, "content": get_skill_content(sname)})

    if req_path in ("/api/git/status", "/api/git/diff"):
        return handle_git_status_or_diff(handler, req_path, deps)

    if req_path == "/api/config":
        cfg = load_config()
        return handler._send(200, {
            "autonomy_level": int(cfg.get("BAIZE_AUTONOMY_LEVEL", 2)),
            "yolo_mode": bool(int(cfg.get("BAIZE_YOLO_MODE", 0))),
            "workspace": cfg.get("BAIZE_WORKSPACE_DIR", "."),
            "effective": {"autonomy_level": True, "yolo_mode": True},
            "note": INERT_SETTINGS_NOTE,
        })

    if req_path.startswith("/api/blast"):
        from ..blast_radius import analyze_blast_radius
        query = parse_qs(urlparse(handler.path).query)
        sym = query.get("symbol", [""])[0]
        f = query.get("file", [""])[0]
        if not sym:
            return handler._send(400, {"error": "symbol parameter required"})
        try:
            rep = analyze_blast_radius(target_symbol=sym, target_file=f)
            return handler._send(200, rep.to_dict())
        except Exception as exc:
            return handler._send(500, {"error": str(exc)})

    if req_path.startswith("/api/impact"):
        from ..test_impact import analyze_test_impact
        query = parse_qs(urlparse(handler.path).query)
        target = query.get("target", [""])[0]
        if not target:
            return handler._send(400, {"error": "target parameter required"})
        try:
            res = analyze_test_impact(target)
            return handler._send(200, res.to_dict())
        except Exception as exc:
            return handler._send(500, {"error": str(exc)})

    return handler._send(404, {"error": "not found"})
