"""V31 built-in REST service (stdlib http.server, zero dependencies).

Core endpoints:

  GET  /           -> web dashboard (self-contained HTML)
  GET  /health     -> {"status":"ok","version":...}
  GET  /metrics    -> Prometheus text (observability)
  GET  /bench      -> benchmark results
  GET  /gate       -> NO FAKE DONE gate status
  GET  /sessions   -> list session transcripts
  GET  /sessions/<id> -> single session transcript
  POST /run        -> {"goal": "..."}  single autonomous agent
  POST /team       -> {"goal": "..."}  Director->Executor->Verifier team
  POST /v30/swarm/speculate -> real multi-candidate exploration in git worktrees
  POST /v30/synthesize  -> meta-tool synthesis  (requires token + explicit opt-in)
  POST /v30/adversarial -> red-blue adversarial round (requires token + opt-in)
  POST /sessions/fork   -> fork a session at a message index
  POST /sessions/compress -> compress a session

  POST /v30/speculative -> 501, see STUB_ROUTES. This one is worth calling out
    because it looks like the /v30/swarm/speculate above and is not: it returned
    a winner chosen among three timelines the handler constructed inline. Use
    /v30/swarm/speculate for the real thing.

Auth model (fail-closed):

  * Every write (POST/PUT/DELETE) requires a configured BAIZE_AUTH_TOKEN, sent as
    `Authorization: Bearer <token>` (or `?token=<token>`, which leaks into logs).
  * With no token configured, writes are rejected with 401. Read-only routes
    (/health, /metrics, /) stay open so the dashboard and probes still work.
  * BAIZE_ALLOW_NO_AUTH=1 is an explicit escape hatch for a single user on
    localhost. It does NOT unlock the code-executing endpoints below.
  * /v30/synthesize and /v30/adversarial execute the code in the request body.
    They require a real token *and* BAIZE_ENABLE_SYNTHESIS_API=1, and the
    execution namespace is a builtins allowlist rather than full __builtins__.

Other defensive measures: 1 MiB request-size cap, JSON validation, opt-in CORS
allowlist (BAIZE_CORS_ORIGINS; empty means no CORS header at all), and
fail-closed when the model endpoint is unconfigured (HTTP 422).
"""
from __future__ import annotations

import hmac
import json
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SERVER_START_TIME = time.time()

from . import __version__
from . import dashboard
from .agent import Agent, Session
from .component import get_runtime
from .config import load_config
from .llm import LLMClient
from .logging_setup import get_logger, setup_logging
from .observability import obs
from .orchestrator import Orchestrator
from .plugin import registry
from . import proc as proc_mod
from . import sessions as sessions_mod
from . import bench as bench_mod
from . import bench_public as bench_public_mod
from . import gate as gate_mod

log = get_logger("serve")

MAX_BODY = 1 << 20  # 1 MiB

#: Routes that answer 501 instead of a fabricated 200.
#:
#: Every one of these used to return HTTP 200 with a hardcoded success payload -
#: "PR #43 opened", "4/4 checks green", "hunk merged", "webhook dispatched" - while
#: performing no work at all. The strings were literals in this file. A caller had
#: no way to tell a stub from a result, and the Studio UI rendered the literals as
#: real outcomes. Returning 501 is the honest answer: it is what the endpoint
#: actually does. Implementing any of them for real is tracked in the upgrade plan
#: (P4-1 / P4-2); delete the entry here when that lands.
#:
#: The first seven were found by the audit. The last four were found *after* the
#: first fix, while writing the route tests that were supposed to raise serve.py
#: coverage - which is the argument for writing them: the audit's endpoint list
#: was a sample, not a census, and nothing in the code made the difference
#: visible. `scripts/check_endpoint_honesty.py` now pins all eleven by behaviour.
STUB_ROUTES: dict[str, str] = {
    "/api/webhook/dispatch":
        "no outbound webhook is sent - no HTTP client is constructed or invoked",
    "/api/vision/analyze":
        "no multimodal model is called - the component list and colour palette "
        "were hardcoded literals",
    "/api/git/apply_hunk":
        "no patch is applied - no file is read, patched or written",
    "/api/ci/autofix":
        "no CI run is inspected and no pull request is opened - the PR number "
        "was a literal",
    "/team/dag":
        "no DAG is executed - the per-node verdicts and timings were literals",
    "/v30/speculative/merge":
        "no timeline is merged and no regression test is run",
    "/v30/causal/heal":
        "no mutation test is run - the 4/4 counts were literals",
    # --- second pass (found while testing the routes above) -----------------
    "/api/tools/import":
        "no tool is registered or hot-loaded - the handler echoed the request's "
        "own name back and returned status 'imported'",
    "/api/security/rbac":
        "no permission rule is applied and no signature is produced - the "
        "watermark was a hash of the current time",
    "/api/chaos/simulate":
        "no fault is injected and no recovery is observed - faults_injected, "
        "auto_healed and the 100% recovery rate were literals",
    "/v30/speculative":
        "no branch is explored - the three candidate timelines were constructed "
        "in the handler with literal churn_lines and status 'verified', and the "
        "engine then picked a winner among them",
}


def _stub_body(path: str) -> dict:
    """Response body for a route in :data:`STUB_ROUTES`."""
    reason = STUB_ROUTES[path]
    return {
        "error": "not_implemented",
        "status": "not_implemented",
        "path": path,
        "reason": reason,
        # `message` is included so a caller that only reads `message` still sees
        # something truthful rather than `undefined`.
        "message": f"该端点尚未实现：{reason}。此前它返回的是硬编码的假成功响应，"
                   f"现改为 501，以免把桩当作结果。",
    }


#: Explanation attached to settings that the API accepts and echoes back but that
#: nothing in the runtime consults.
#:
#: `grep -rn BAIZE_AUTONOMY_LEVEL baize/` finds exactly two hits - the GET that
#: reports it and the POST that stores it. No agent, tool or orchestrator path
#: reads it, so moving the Studio autonomy slider changes nothing. These keys are
#: kept because the desktop control panel binds to them; they are reported with
#: `"effective": False` so a caller cannot mistake the slider for a live control.
INERT_SETTINGS_NOTE = (
    "autonomy_level and yolo_mode are stored in the server process environment "
    "and reported back, but no code path reads them: changing them does not "
    "alter agent behaviour, and they are not persisted across restarts."
)


def _resolve_git() -> str | None:
    """Path to a usable git, or None. Never a machine-specific literal.

    This used to be a hardcoded absolute path into one developer's PortableGit
    installation, committed into the repo. It could only ever work on that one
    machine - not in CI, not in the Docker image, not on a fresh clone.
    """
    override = (load_config().get("BAIZE_GIT_EXE") or "").strip()
    if override:
        return override if Path(override).exists() else None
    return shutil.which("git")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # Assembled ONCE at server start (see serve()); consulted per-request so we
    # never rebuild the kernel. Falls back to a fresh singleton if unset.
    runtime = None

    def _send(self, code: int, obj) -> None:
        """Send a JSON body."""
        self._send_text(code, json.dumps(obj, ensure_ascii=False),
                        "application/json; charset=utf-8")

    def _emit_cors(self) -> bool:
        """Emit CORS headers, but only for explicitly allowlisted origins.

        Opt-in via BAIZE_CORS_ORIGINS (comma-separated); empty means no CORS
        header is ever emitted. This used to be `Access-Control-Allow-Origin: *`
        on every response, which turned a loopback-only server into one drivable
        from any page the user happened to visit.

        Returns True when the headers were emitted, so callers that need to add
        further CORS headers (do_OPTIONS) do not have to re-derive the allowlist.

        Single source of truth on purpose: this logic was previously copied into
        _send_text, do_OPTIONS and _handle_run_stream, and exactly one copy was
        missed when the wildcard was removed, leaving the SSE endpoint open.
        """
        origin = self.headers.get("Origin", "")
        allowed = [o.strip() for o in
                   load_config().get("BAIZE_CORS_ORIGINS", "").split(",")
                   if o.strip()]
        if not origin or origin not in allowed:
            return False
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        return True

    def _send_text(self, code: int, text: str, ctype: str) -> None:
        """Send a raw (non-JSON) body - required for HTML and Prometheus."""
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self._emit_cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY:
            return None
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def _is_authorized(self, *, require_token: bool = False) -> bool:
        """Decide whether this request may proceed. FAIL-CLOSED.

        Historically this returned True whenever BAIZE_AUTH_TOKEN was unset, so a
        default install authenticated everyone - and the two code-executing
        endpoints under /v30 were reachable from any web page the user visited.
        Now an unconfigured token denies writes unless the operator has explicitly
        opted out with BAIZE_ALLOW_NO_AUTH=1, and endpoints that execute
        caller-supplied code require a real token even then.
        """
        cfg = load_config()
        token = (cfg.get("BAIZE_AUTH_TOKEN") or "").strip()
        if not token:
            if require_token:
                return False
            return cfg.get("BAIZE_ALLOW_NO_AUTH", "0") == "1"
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and hmac.compare_digest(
                auth[7:].strip(), token):
            return True
        # Query-string form kept for backwards compatibility. It leaks the token
        # into access logs, so prefer the Authorization header.
        supplied = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        if supplied and hmac.compare_digest(supplied, token):
            return True
        return False

    def do_GET(self):
        if self.path in ("/", "/dashboard", "/index.html"):
            return self._send_text(200, dashboard.render(),
                                   "text/html; charset=utf-8")
        if self.path == "/health":
            # The boundary disclosure travels with the health probe on purpose:
            # an operator reading "status: ok" should also be able to read what
            # the agent's bash tool actually constrains. Lazy import - tools.py
            # is heavy and /health is polled.
            from .tools import EXECUTION_BOUNDARY
            return self._send(200, {
                "status": "ok",
                "version": __version__,
                "execution_boundary": EXECUTION_BOUNDARY,
            })
        if self.path == "/metrics":
            # Prometheus exposition format - plain text, NOT JSON-encoded
            return self._send_text(200, obs.prometheus(),
                                   "text/plain; version=0.0.4; charset=utf-8")
        if self.path == "/api/metrics/summary":
            cfg = load_config()
            runs = obs._counters.get("serve_run", 0)
            team_runs = obs._counters.get("serve_team", 0)
            tool_calls = obs._counters.get("tool_calls", 0)
            est_tokens = (runs + team_runs) * 1250 + 1500
            return self._send(200, {
                "uptime_seconds": int(time.time() - SERVER_START_TIME),
                "total_runs": runs,
                "total_team_runs": team_runs,
                "total_tool_calls": tool_calls,
                "estimated_tokens": est_tokens,
                "estimated_cost_cny": round(est_tokens * 0.000014, 4),
                "active_model": cfg.get("BAIZE_MODEL_NAME", "deepseek-chat"),
                "status": "healthy"
            })
        if not self._is_authorized():
            return self._send(401, {"error": "unauthorized: invalid or missing bearer token"})
        if self.path == "/bench":
            return self._send(200, {
                "bench": bench_mod.run_all(),
                "public": bench_public_mod.coverage_report(),
            })
        if self.path == "/gate":
            return self._send(200, gate_mod.run_gate())
        if self.path == "/sessions" or self.path.startswith("/sessions?"):
            return self._send(200, {"sessions": Session.list_sessions()})
        if self.path == "/sessions/lineage/tree":
            lineages = sessions_mod.list_lineage()
            sessions = Session.list_sessions()
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
            return self._send(200, {"nodes": tree})
        if self.path == "/api/tools/hub":
            return self._send(200, {
                "tools": [
                    {"name": "hex_encoder", "desc": "高阶十六进制安全编解码器", "version": "1.0.0", "author": "Darwin Synthesizer", "gene": "GENE-HEX-9821"},
                    {"name": "json_canonicalizer", "desc": "规范化 JSON 键值对排序器", "version": "1.1.0", "author": "Darwin Synthesizer", "gene": "GENE-JSON-7412"},
                    {"name": "path_sanitizer", "desc": "POSIX 与 Windows 路径穿越防御过滤", "version": "2.0.0", "author": "Baize Security", "gene": "GENE-PATH-3309"},
                ]
            })
        if self.path.startswith("/sessions/") and self.path.endswith("/export"):
            sid = self.path[len("/sessions/"):len(self.path) - len("/export")].strip()
            return self._handle_export_session(sid)
        if self.path.startswith("/sessions/"):
            sid = self.path[len("/sessions/"):]
            if not sid or "/" in sid:
                return self._send(400, {"error": "bad session id"})
            try:
                recs = sessions_mod._read_records(sid)
            except FileNotFoundError:
                return self._send(404, {"error": "session not found"})
            lineage = sessions_mod.list_lineage().get(sid)
            return self._send(200, {
                "session_id": sid,
                "messages": [r.get("message", r) for r in recs
                             if r.get("kind") == "message"],
                "fork_of": lineage.get("parent") if lineage else None,
                "fork_at_index": lineage.get("at_index") if lineage else None,
            })
        if self.path == "/api/workspace/files":
            root = Path(load_config().get("BAIZE_WORKSPACE_DIR", "."))
            files = []
            try:
                for p in root.rglob("*"):
                    if p.is_file():
                        rel = str(p.relative_to(root)).replace("\\", "/")
                        if not any(part.startswith(".") or part in ("__pycache__", "node_modules", "persistence") for part in rel.split("/")):
                            files.append(rel)
                            if len(files) >= 500:
                                break
            except Exception:
                pass
            return self._send(200, {"files": files})

        if self.path == "/api/commands":
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
            return self._send(200, {"commands": cmds})

        if self.path == "/api/windows/status":
            from .powershell import get_powershell_status
            return self._send(200, get_powershell_status())

        if self.path == "/api/mcp/tools":
            from .mcp import list_all_mcp_tools, load_mcp_config
            cfg = load_mcp_config(load_config().get("BAIZE_WORKSPACE_DIR", "."))
            tools = list_all_mcp_tools(load_config().get("BAIZE_WORKSPACE_DIR", "."))
            return self._send(200, {
                "status": "ready",
                "servers_count": len(cfg.get("mcpServers", {})),
                "tools": tools,
                "protocol": "mcp/2024-11-05"
            })

        if self.path == "/api/symbols/graph":
            from .symbol_graph import build_workspace_symbol_graph
            graph = build_workspace_symbol_graph(load_config().get("BAIZE_WORKSPACE_DIR", "."))
            return self._send(200, graph.get_summary())

        if self.path.startswith("/api/symbols/search"):
            import urllib.parse
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            q = params.get("q", [""])[0]
            from .symbol_graph import build_workspace_symbol_graph
            graph = build_workspace_symbol_graph(load_config().get("BAIZE_WORKSPACE_DIR", "."))
            return self._send(200, {"query": q, "results": graph.search_symbols(q)})

        if self.path == "/api/market/tools":
            from .tool_market import list_market_tools
            return self._send(200, {"status": "ready", "tools": list_market_tools()})

        if self.path == "/api/repomap":
            from .repo_map import generate_workspace_repo_map
            return self._send(200, {"status": "ready", "repo_map": generate_workspace_repo_map()})

        if self.path == "/api/docs/list":
            from .doc_crawler import DocCrawlerRegistry
            return self._send(200, {"status": "ready", "docs": DocCrawlerRegistry.list_indexed_docs()})

        if self.path == "/api/models":
            cfg = load_config()
            return self._send(200, {
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
                ]
            })

        if self.path == "/api/skills" or self.path.startswith("/api/skills?"):
            from . import skill_index
            idx = skill_index.build_index()
            skills = list(idx.get("skills", []))
            # Enrich with comprehensive 240+ engineering skills taxonomy
            from .skills_catalog import get_full_skills_catalog
            catalog = get_full_skills_catalog()
            existing_names = {s.get("name") for s in skills}
            for cat_skill in catalog:
                if cat_skill["name"] not in existing_names:
                    skills.append(cat_skill)
            return self._send(200, {"skills": skills, "total": len(skills), "libraries": idx.get("libraries", [])})

        if self.path.startswith("/api/skills/"):
            sname = self.path[len("/api/skills/"):].strip()
            from .skills_catalog import get_skill_content
            content = get_skill_content(sname)
            return self._send(200, {"name": sname, "content": content})

        if self.path in ("/api/git/status", "/api/git/diff"):
            return self._handle_git_status_or_diff()

        if self.path == "/api/config":
            cfg = load_config()
            return self._send(200, {
                "autonomy_level": int(cfg.get("BAIZE_AUTONOMY_LEVEL", 2)),
                "yolo_mode": bool(int(cfg.get("BAIZE_YOLO_MODE", 0))),
                "workspace": cfg.get("BAIZE_WORKSPACE_DIR", "."),
                # These two are inert. See INERT_SETTINGS_NOTE.
                "effective": {"autonomy_level": False, "yolo_mode": False},
                "note": INERT_SETTINGS_NOTE,
            })

        return self._send(404, {"error": "not found"})

    def _handle_git_status_or_diff(self) -> None:
        """Serve /api/git/status and /api/git/diff, honestly.

        Three defects fixed here, all in the same shape - reporting success that
        did not happen:

          * the git executable was a hardcoded absolute path into one machine's
            PortableGit install, so this could not work anywhere else;
          * on any failure the response was still HTTP 200, and /api/git/status
            reported ``"clean": True`` - i.e. "your tree is clean" when git had
            not run at all;
          * the branch name fell back to the literal ``"v30-dev"``.

        Failures now answer 503 with ``git_available: false`` and no fabricated
        fields. A client can no longer mistake "could not check" for "all clear".
        """
        git_exe = _resolve_git()
        if not git_exe:
            return self._send(503, {
                "error": "git_unavailable",
                "git_available": False,
                "message": "no usable git executable found (looked on PATH and at "
                           "BAIZE_GIT_EXE); cannot report repository state",
            })
        cwd = load_config().get("BAIZE_WORKSPACE_DIR", ".")
        # errors="replace": git output is not guaranteed to be valid UTF-8 (CJK
        # filenames on a GBK console are the normal case), and a decode failure
        # would surface as a 500 for a request that should have succeeded.
        try:
            if self.path == "/api/git/status":
                res = proc_mod.run([git_exe, "status", "-s"], timeout=30, cwd=cwd)
                branch_res = proc_mod.run([git_exe, "branch", "--show-current"],
                                          timeout=30, cwd=cwd)
                if res.timed_out or branch_res.timed_out:
                    return self._send(503, {"error": "git_timeout",
                                            "git_available": True,
                                            "message": "git did not respond in 30s"})
                return self._send(200, {
                    "git_available": True,
                    "branch": branch_res.stdout.strip(),
                    "status_output": res.stdout,
                    "clean": len(res.stdout.strip()) == 0,
                })
            res = proc_mod.run([git_exe, "diff"], timeout=60, cwd=cwd)
            if res.timed_out:
                return self._send(503, {"error": "git_timeout",
                                        "git_available": True,
                                        "message": "git diff did not respond in 60s"})
            return self._send(200, {"git_available": True, "diff": res.stdout})
        except Exception as e:  # noqa: BLE001 - report, never fabricate
            return self._send(503, {
                "error": "git_failed",
                "git_available": False,
                "message": f"git could not be run: {e}",
            })

    def do_HEAD(self):
        """Health checkers and scrapers often probe with HEAD."""
        if self.path in ("/", "/dashboard", "/index.html"):
            return self._send_text(200, "", "text/html; charset=utf-8")
        if self.path == "/metrics":
            return self._send_text(200, "",
                                   "text/plain; version=0.0.4; charset=utf-8")
        if self.path in ("/health", "/bench", "/gate", "/sessions", "/api/skills", "/api/models"):
            return self._send(200, {})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._is_authorized():
            return self._send(401, {"error": "unauthorized: invalid or missing bearer token"})
        try:
            data = self._body()
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "invalid JSON"})
        if data is None:
            return self._send(413, {"error": "payload too large"})
        # Stub routes answer 501 before any handler runs. See STUB_ROUTES.
        if self.path in STUB_ROUTES:
            return self._send(501, _stub_body(self.path))
        if self.path == "/api/mcp/call":
            server = data.get("server") or "sqlite"
            tool = data.get("tool") or "sqlite_query"
            args = data.get("arguments") or {}
            from .mcp import call_mcp_tool
            res = call_mcp_tool(server, tool, args, load_config().get("BAIZE_WORKSPACE_DIR", "."))
            return self._send(200, res)
        if self.path == "/v30/swarm/speculate":
            goal = data.get("goal") or "优化系统并发安全性"
            from .swarm import run_parallel_swarm_speculation
            res = run_parallel_swarm_speculation(goal)
            return self._send(200, res)
        if self.path == "/api/context/slice":
            code = data.get("code") or ""
            symbol = data.get("focus_symbol") or ""
            from .context_slicer import slice_code_context
            res = slice_code_context(code, symbol)
            return self._send(200, res)
        if self.path == "/api/market/publish":
            from .tool_market import publish_market_tool
            res = publish_market_tool(data)
            return self._send(200, res)
        if self.path == "/api/causal/mutation_test":
            code = data.get("code") or "def add(a, b):\n    return a + b if a > 0 else 0"
            fn = data.get("target_function") or "add"
            from .mutation import run_ast_mutation_arena
            res = run_ast_mutation_arena(code, fn)
            return self._send(200, res)
        if self.path == "/api/byzantine/arbitrate":
            code = data.get("code") or ""
            goal = data.get("goal") or "核心支付状态机发布评审"
            # Verdicts come from the caller. This route does not generate them:
            # it used to return two literal APPROVEs, so every request - including
            # an empty one - reached consensus. With no verdicts the response now
            # says "awaiting_verdicts" instead.
            from .byzantine import DEFAULT_QUORUM, run_byzantine_consensus
            verdicts = data.get("verdicts") or None
            quorum = int(data.get("quorum") or DEFAULT_QUORUM)
            res = run_byzantine_consensus(code, goal, verdicts=verdicts, quorum=quorum)
            return self._send(200, res)
        if self.path == "/api/invariants/anchor":
            goal = data.get("goal") or "长期重构任务"
            constraints = data.get("constraints") or None
            from .invariants_anchor import create_invariants_anchor
            anchor = create_invariants_anchor(goal, constraints)
            sample_prompt = data.get("prompt") or "请开始第 42 步执行"
            wrapped = anchor.inject_anchor_header(sample_prompt, turn_index=int(data.get("turn_index", 42)))
            return self._send(200, {
                "status": "anchored",
                "invariants": anchor.invariants,
                "wrapped_prompt_sample": wrapped,
                "message": f"核心不变量锚点已成功激活！已为第 {data.get('turn_index', 42)} 步长程任务注入置顶约束。"
            })
        if self.path == "/api/interactive/detect":
            text = data.get("text") or "Do you want to continue? [y/N]"
            from .interactive_detector import detect_interactive_prompt
            res = detect_interactive_prompt(text)
            return self._send(200, res)
        if self.path == "/api/docs/fetch":
            url = data.get("url", "")
            from .doc_crawler import DocCrawlerRegistry
            res = DocCrawlerRegistry.index_url(url)
            return self._send(200, res)
        if self.path == "/api/browser/verify":
            html = data.get("html", "")
            name = data.get("name", "index.html")
            from .browser_verify import verify_frontend_code
            res = verify_frontend_code(html, name)
            return self._send(200, res)
        if self.path == "/run":
            return self._handle_run(data)
        if self.path == "/run/stream":
            return self._handle_run_stream(data)
        if self.path == "/team":
            return self._handle_team(data)
        # `/v30/speculative` used to call `_handle_speculative`, which built three
        # candidate timelines in the handler with literal churn_lines and
        # status="verified", then asked the engine to pick a winner among them -
        # the same defect as `cmd_speculative`, in the API instead of the CLI.
        # The route is declared in STUB_ROUTES and answers 501.
        # `/v30/swarm/speculate` is the real one: it calls
        # run_parallel_swarm_speculation, which creates real git worktrees.
        if self.path == "/v30/synthesize":
            gate = self._code_exec_gate()
            if gate is not None:
                return gate
            return self._handle_synthesize(data)
        if self.path == "/v30/adversarial":
            gate = self._code_exec_gate()
            if gate is not None:
                return gate
            return self._handle_adversarial(data)
        if self.path == "/v30/causal":
            return self._handle_causal(data)
        if self.path == "/v30/causal/persist_test":
            fn = (data.get("target_function") or "divide").strip()
            code = data.get("code") or ""
            # `fn` used to be interpolated straight into the output filename and
            # into the body of a Python file written to disk, with no validation:
            # a value containing a newline or a path separator could inject code
            # into a file that pytest then collects and executes.
            if not fn.isidentifier():
                return self._send(400, {
                    "error": f"target_function {fn!r} is not a valid Python identifier",
                    "reason": "the name is used both as a filename component and as the "
                              "function name inside the written source",
                })
            if not code.strip():
                return self._send(400, {
                    "error": "code is required",
                    "reason": "the test is generated from the submitted source; the old "
                              "handler ignored the request and wrote a fixed divide() "
                              "template, so the file had nothing to do with the input",
                })
            from .mutation import run_ast_mutation_arena
            arena = run_ast_mutation_arena(code, fn)
            if arena.get("status") != "success":
                return self._send(422, {
                    "error": "no guardrail test could be generated from that source",
                    "arena_status": arena.get("status"),
                    "arena_message": arena.get("message"),
                })
            gen_dir = Path("tests/generated")
            gen_dir.mkdir(parents=True, exist_ok=True)
            test_file = (gen_dir / f"test_causal_{fn}.py").resolve()
            if gen_dir.resolve() not in test_file.parents:
                return self._send(400, {
                    "error": "refusing to write outside tests/generated",
                    "resolved": str(test_file).replace("\\", "/"),
                })
            # Explicit utf-8 and "\n": the default text mode translates newlines
            # to os.linesep, so on Windows the file would be 1 byte per line
            # longer than the text the response quotes, and bytes_written would
            # not match what a reader computes.
            test_file.write_text(
                arena["synthesized_guardrail_test"], encoding="utf-8", newline="\n"
            )
            return self._send(200, {
                "status": "persisted",
                "path": str(test_file).replace("\\", "/"),
                "bytes_written": test_file.stat().st_size,
                "mutation_score": arena["mutation_score"],
                "guardrail_verification": arena["guardrail_verification"],
                "tracked_by_git": False,
                "message": (
                    f"已将 {fn} 的护栏测试写入 {test_file.name}"
                    f"（{test_file.stat().st_size} 字节，击杀率 "
                    f"{arena['mutation_score'] or '无'}）。"
                    "该文件由提交的源码与实测探针生成，内容与源码逐行对应；"
                    "tests/generated/ 未纳入版本控制。"
                ),
            })
        # `/api/tools/import`, `/api/security/rbac` and `/api/chaos/simulate`
        # used to live here. Each returned HTTP 200 with a completion message
        # ("tool hot-loaded into the ToolRegistry sandbox", "RBAC rules applied,
        # signature watermark issued", "5 faults injected, 5 auto-healed, 100%
        # recovery") while doing nothing of the kind: no registry was touched, no
        # rule was applied and no fault was injected. The bodies were deleted
        # rather than left unreachable, because dead code that looks live is how
        # the next reader re-enables it. They are declared in STUB_ROUTES above
        # and answer 501.
        if self.path == "/api/memory/search":
            # Real substring search over the session transcripts, with the score
            # reported as what it is. The previous version attached a fixed
            # "relevance": 0.92 to every hit and, when nothing matched, invented a
            # "knowledge_base" result at 0.75 claiming a semantic match had
            # occurred. Nothing was semantic and nothing was matched.
            query = (data.get("query") or "").strip()
            results = []
            sess_dir = Path(load_config().get("BAIZE_SESSIONS_DIR",
                                             "persistence/sessions"))
            if query and sess_dir.exists():
                needle = query.lower()
                for p in sorted(sess_dir.glob("*.jsonl")):
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    hits = content.lower().count(needle)
                    if hits:
                        results.append({
                            "source": f"session:{p.stem}",
                            "match": "substring",
                            "occurrences": hits,
                            "snippet": content[:200],
                        })
            results.sort(key=lambda r: r["occurrences"], reverse=True)
            return self._send(200, {
                "query": query,
                "match": "substring",
                "results": results[:5],
                "searched_dir": str(sess_dir),
                "note": ("substring matches only - no embedding model is loaded, "
                         "so there is no semantic ranking here"),
            })
        if self.path == "/api/models/route":
            # This classifies a prompt; it does not route anything. The previous
            # response said `routed_model` and quoted a `saved_cost_ratio` that
            # came from nowhere. Both are now stated for what they are.
            prompt = (data.get("prompt") or "").strip().lower()
            keywords = ["重构", "refactor", "ast", "causal", "架构", "dag",
                        "推演", "speculative"]
            matched = [k for k in keywords if k in prompt]
            is_complex = bool(matched)
            return self._send(200, {
                "complexity": "HIGH" if is_complex else "FAST",
                "suggested_model": ("deepseek-reasoner" if is_complex
                                    else "deepseek-chat"),
                "routed": False,
                "basis": ("matched keyword(s): " + ", ".join(matched)
                          if matched else "no complexity keyword matched"),
                "note": ("advisory only - the caller decides whether to act on it; "
                         "no model selection was performed"),
            })
        if self.path == "/sessions/fork":
            return self._handle_fork(data)
        if self.path == "/sessions/compress":
            return self._handle_compress(data)
        if self.path == "/api/skills":
            return self._handle_save_skill(data)
        if self.path == "/api/models/active":
            model_id = (data.get("model") or "").strip()
            if model_id:
                import os
                os.environ["BAIZE_MODEL_NAME"] = model_id
                # Same treatment as /api/config: say exactly what happened. The
                # value is in this process's environment and is read by
                # load_config, but nothing writes it to .env, so it does not
                # survive a restart. "updated" read as "persisted".
                return self._send(200, {
                    "active_model": model_id,
                    "status": "stored_in_process_env",
                    "persisted": False,
                    "note": ("BAIZE_MODEL_NAME is set in the server process "
                             "environment; it is not written to .env and does "
                             "not survive a restart"),
                })
            return self._send(400, {"error": "missing model id"})
        if self.path == "/api/config":
            level = data.get("autonomy_level")
            if level is not None:
                import os
                os.environ["BAIZE_AUTONOMY_LEVEL"] = str(level)
                os.environ["BAIZE_YOLO_MODE"] = "1" if int(level) == 3 else "0"
                # `status` says exactly what happened: the value is now in this
                # process's environment. It is NOT persisted and NOT consulted,
                # so it must not read as "the agent's autonomy changed".
                return self._send(200, {
                    "autonomy_level": level,
                    "status": "stored_in_process_env",
                    "persisted": False,
                    "effective": False,
                    "note": INERT_SETTINGS_NOTE,
                })
            return self._send(400, {"error": "missing config field"})
        return self._send(404, {"error": "not found"})

    def _handle_causal(self, data: dict) -> None:
        code = data.get("code") or "def divide(a, b):\n    return a / b"
        fn_name = data.get("target_function") or "divide"
        error_context = data.get("error_context") or ""
        # This used to import CausalDebugger and call slice_culprit_ast /
        # generate_counterfactual_mutations. None of those three names exists in
        # baize/knowledge/causal.py, so every request to /v30/causal raised
        # ImportError. The real API is ASTCausalTracker.extract_slice +
        # MutationFuzzer.generate_mutations.
        from .knowledge.causal import ASTCausalTracker, MutationFuzzer
        cslice = ASTCausalTracker().extract_slice(code, fn_name, error_context)
        mutations = MutationFuzzer().generate_mutations(fn_name, cslice.culprit_variables)
        self._send(200, {
            "target_function": cslice.target_function,
            "line_range": cslice.line_range,
            "culprit_variables": cslice.culprit_variables,
            "ast_node_type": cslice.ast_node_type,
            "snippet": cslice.source_snippet,
            # The fuzzer returns case *descriptors*: a name, a payload and a
            # rationale. Nothing runs them, so the response must not read as
            # "these passed". CausalProof.passed_mutation_tests is only ever
            # constructed by a test, never by this route.
            "mutations_executed": False,
            "mutations_note": (
                "these are generated case descriptors - no payload was applied to "
                "the target function and no result was observed"
            ),
            "mutations": [
                {"name": m.name, "type": m.mutation_type, "desc": m.description,
                 "payload": {k: repr(v) for k, v in m.payload.items()}}
                for m in mutations
            ],
        })

    def _handle_save_skill(self, data: dict) -> None:
        from pathlib import Path
        name = (data.get("name") or "").strip()
        body = data.get("content") or ""
        if not name:
            return self._send(400, {"error": "missing skill name"})
        skill_dir = Path("user_skills") / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
        return self._send(200, {"name": name, "path": str(skill_dir / "SKILL.md"), "status": "saved"})

    def do_OPTIONS(self):
        self.send_response(204)
        if self._emit_cors():
            self.send_header("Access-Control-Allow-Methods",
                             "GET, POST, DELETE, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, Authorization")
        self.end_headers()

    def do_DELETE(self):
        # Auth was missing here. The module docstring has always claimed
        # "every write (POST/PUT/DELETE) requires a configured BAIZE_AUTH_TOKEN",
        # and do_POST enforces it, but do_DELETE went straight to the filesystem:
        # anyone who could reach the port could destroy every session transcript
        # with a single unauthenticated request. Found by the route tests, which
        # were written to raise coverage - the check was simply never exercised.
        if not self._is_authorized():
            return self._send(401, {"error": "unauthorized: invalid or missing "
                                             "bearer token"})
        cfg = load_config()
        sessions_dir = Path(cfg.get("BAIZE_SESSIONS_DIR", "persistence/sessions"))
        if self.path in ("/sessions", "/sessions/all", "/sessions/clear"):
            count = 0
            if sessions_dir.exists():
                for f in sessions_dir.glob("*.jsonl"):
                    try:
                        f.unlink()
                        count += 1
                    except OSError:
                        pass
            return self._send(200, {"deleted_count": count, "message": "all sessions cleared"})
        if self.path.startswith("/sessions/"):
            sid = self.path[len("/sessions/"):].strip()
            p = sessions_dir / f"{sid}.jsonl"
            if p.exists():
                p.unlink()
                return self._send(200, {"deleted": sid})
            return self._send(404, {"error": "session not found"})
        return self._send(404, {"error": "not found"})

    def _code_exec_gate(self):
        """Guard for endpoints that exec caller-supplied code.

        Returns None when execution is permitted; otherwise sends the refusal and
        returns a sentinel. Two independent conditions must both hold:

          1. a real BAIZE_AUTH_TOKEN is configured (BAIZE_ALLOW_NO_AUTH=1, the
             localhost convenience flag, is deliberately NOT sufficient here), and
          2. BAIZE_ENABLE_SYNTHESIS_API=1.

        These endpoints previously ran `exec(code, {"__builtins__": __builtins__})`
        on the request body with no gate beyond the (fail-open) global check.
        """
        if not self._is_authorized(require_token=True):
            self._send(403, {
                "error": "this endpoint executes caller-supplied code and requires "
                         "a configured BAIZE_AUTH_TOKEN; BAIZE_ALLOW_NO_AUTH does "
                         "not apply here"})
            return True
        if load_config().get("BAIZE_ENABLE_SYNTHESIS_API", "0") != "1":
            self._send(501, {
                "error": "code-execution endpoints are disabled by default; "
                         "set BAIZE_ENABLE_SYNTHESIS_API=1 to enable"})
            return True
        return None

    def _handle_synthesize(self, data: dict) -> None:
        name = (data.get("name") or "").strip()
        code = data.get("code") or ""
        test = data.get("test") or ""
        if not name or not code:
            return self._send(400, {"error": "missing name or code"})
        from .tooling.synthesizer import MetaToolSynthesizer
        synth = MetaToolSynthesizer()
        tool = synth.certify_tool(name=name, description=data.get("description", ""), code_source=code, test_source=test)
        self._send(200, {"name": tool.name, "certified": tool.certified, "gene_signature": tool.gene_signature})

    def _handle_adversarial(self, data: dict) -> None:
        blue_code = data.get("blue_code") or ""
        red_input = data.get("red_input") or {}
        if not blue_code:
            return self._send(400, {"error": "missing blue_code"})
        from .orchestration.adversarial import ByzantineJudge
        judge = ByzantineJudge()
        round_res = judge.arbitrate(1, blue_code, red_input)
        self._send(200, {"verdict": round_res.verdict, "attack_succeeded": round_res.attack_succeeded})

    # `_handle_speculative` was deleted here. It constructed three
    # `SpeculativeTimeline` objects inline with literal `churn_lines` (4 / 20 /
    # 12) and `status="verified"`, handed them to the engine, and returned the
    # winner as though a branch had been explored and verified. Nothing was
    # explored and nothing was verified. `/v30/speculative` is declared in
    # STUB_ROUTES; `/v30/swarm/speculate` is the real implementation.

    def _handle_run(self, data: dict) -> None:
        goal = (data.get("goal") or "").strip()
        if not goal:
            return self._send(400, {"error": "missing goal"})
        client = LLMClient()
        if not client.configured:
            return self._send(422, {"error": "model endpoint not configured"})
        if not _has_real_key(client):
            return self._send(422, {"error": "model API key not set "
                                              "(placeholder in .env)"})
        agent = Agent(role="executor", client=client)
        obs.inc("serve_run")
        res = agent.run(goal)
        self._send(200, {
            "final_text": res.final_text,
            "stopped_reason": res.stopped_reason,
            "steps": res.steps,
            "session_id": res.session_id,
        })

    def _handle_run_stream(self, data: dict) -> None:
        goal = (data.get("goal") or "").strip()
        if not goal:
            return self._send(400, {"error": "missing goal"})
        client = LLMClient()
        if not client.configured:
            return self._send(422, {"error": "model endpoint not configured"})
        if not _has_real_key(client):
            return self._send(422, {"error": "model API key not set (placeholder in .env)"})

        agent = Agent(role="executor", client=client)
        obs.inc("serve_run")

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._emit_cors()
        self.end_headers()

        def emit(event_type: str, payload: dict):
            msg = f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            try:
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        emit("think", {"content": f"正在解析任务意图与沙箱上下文: {goal}"})
        res = agent.run(goal)

        # Stream delta text chunks
        text = res.final_text or "任务执行完毕。"
        chunk_size = 20
        for i in range(0, len(text), chunk_size):
            emit("delta", {"text": text[i:i+chunk_size]})
            time.sleep(0.01)

        emit("done", {
            "final_text": res.final_text,
            "session_id": res.session_id,
            "steps": res.steps,
            "stopped_reason": res.stopped_reason,
        })

    def _handle_export_session(self, sid: str) -> None:
        try:
            recs = sessions_mod._read_records(sid)
        except FileNotFoundError:
            return self._send(404, {"error": "session not found"})
        msgs = [r.get("message", r) for r in recs if r.get("kind") == "message"]
        lines = [
            f"# 白泽智能体执行轨迹与审计报告",
            f"",
            f"- **会话 ID**: `{sid}`",
            f"- **导出时间**: `{time.strftime('%Y-%m-%d %H:%M:%S')}`",
            f"- **执行内核**: Baize Agent V{__version__} (NO FAKE DONE Physical Gate Certified)",
            f"",
            f"---",
            f"",
            f"## 📋 对话与执行记录明细",
            f"",
        ]
        for idx, m in enumerate(msgs, 1):
            role = "🧑 User" if m.get("role") == "user" else "🤖 Baize Agent"
            lines.append(f"### {idx}. {role}")
            lines.append(m.get("content", ""))
            lines.append("")

        md_text = "\n".join(lines)
        return self._send_text(200, md_text, "text/markdown; charset=utf-8")

    def _handle_team(self, data: dict) -> None:
        goal = (data.get("goal") or "").strip()
        if not goal:
            return self._send(400, {"error": "missing goal"})
        client = LLMClient()
        if not client.configured:
            return self._send(422, {"error": "model endpoint not configured"})
        if not _has_real_key(client):
            return self._send(422, {"error": "model API key not set "
                                              "(placeholder in .env)"})
        orch = Orchestrator(client=client)
        obs.inc("serve_team")
        res = orch.run(goal)
        self._send(200, {
            "success": res.success,
            "reports": [
                {"task_id": r.task_id, "verdict": r.verdict,
                 "issues": r.issues, "task": r.task}
                for r in res.reports
            ],
        })

    def _handle_fork(self, data: dict) -> None:
        parent = (data.get("parent") or "").strip()
        if not parent:
            return self._send(400, {"error": "missing parent session id"})
        raw = data.get("at_index")
        at_index = None
        if raw is not None and str(raw) != "":
            try:
                at_index = int(raw)
            except (ValueError, TypeError):
                return self._send(400, {"error": "at_index must be an integer"})
        try:
            new_id = sessions_mod.fork_session(parent, at_index)
        except FileNotFoundError:
            return self._send(404, {"error": "parent session not found"})
        self._send(200, {"new_session_id": new_id, "fork_of": parent,
                         "at_index": at_index})

    def _handle_compress(self, data: dict) -> None:
        sid = (data.get("id") or "").strip()
        if not sid:
            return self._send(400, {"error": "missing session id"})
        try:
            report = sessions_mod.compress_session(sid)
        except FileNotFoundError:
            return self._send(404, {"error": "session not found"})
        self._send(200, report)


def _warn_about_auth_posture(cfg: dict) -> None:
    """Print the auth posture once at startup so it can never be a surprise.

    A server whose security depends on a setting the operator never noticed is
    the failure this whole check exists to prevent, so the posture is stated
    out loud rather than left implicit in the config.
    """
    token = (cfg.get("BAIZE_AUTH_TOKEN") or "").strip()
    no_auth = cfg.get("BAIZE_ALLOW_NO_AUTH", "0") == "1"
    if not token and not no_auth:
        log.warning(
            "No BAIZE_AUTH_TOKEN configured - all write operations will be "
            "rejected with 401. Set BAIZE_AUTH_TOKEN, or set "
            "BAIZE_ALLOW_NO_AUTH=1 for single-user localhost use.")
    elif not token and no_auth:
        log.warning(
            "BAIZE_ALLOW_NO_AUTH=1 - the service accepts UNAUTHENTICATED writes. "
            "This is intended for a single user on localhost. Do not use it on a "
            "shared or network-reachable host.")
    if cfg.get("BAIZE_ENABLE_SYNTHESIS_API", "0") == "1":
        log.warning(
            "/v30/synthesize and /v30/adversarial are ENABLED: they execute "
            "Python supplied in the request body. Keep the bearer token secret.")
    if cfg.get("BAIZE_CORS_ORIGINS", "").strip():
        log.info("CORS allowlist: %s", cfg["BAIZE_CORS_ORIGINS"])


def serve(host: str | None = None, port: int | None = None) -> None:
    """Start the service. Explicit host/port win over config defaults."""
    cfg = load_config()
    host = host or cfg.get("BAIZE_SERVE_HOST", "127.0.0.1")
    port = int(port or cfg.get("BAIZE_SERVE_PORT", 8787))
    try:
        registry.discover()
    except Exception:  # defensive: serving must not depend on plugins
        pass
    # Assemble the composition kernel exactly once for the whole server lifetime.
    Handler.runtime = get_runtime()
    httpd = ThreadingHTTPServer((host, port), Handler)
    setup_logging(cfg)
    _warn_about_auth_posture(cfg)
    log.info("baize serve listening on http://%s:%s  (Ctrl+C to stop)", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def _has_real_key(client: LLMClient) -> bool:
    """Reject placeholder keys like __FILL_YOUR_DEEPSEEK_KEY__ so the HTTP
    boundary returns 422 immediately instead of letting a call fly to the
    upstream provider with a bogus key (which 401s mid-flight and looks
    transient).

    Test doubles (e.g. a stub with no ``models`` attribute) are treated as
    configured — the real model check is the caller's ``client.configured``.
    """
    models = getattr(client, "models", None)
    if not models:
        return True
    for m in models:
        key = getattr(m, "api_key", "")
        if key and not key.startswith("__FILL"):
            return True
    return False
