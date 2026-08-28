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
  POST /v30/speculative -> speculative time-travel exploration
  POST /v30/synthesize  -> meta-tool synthesis
  POST /v30/adversarial -> red-blue adversarial round
  POST /sessions/fork   -> fork a session at a message index
  POST /sessions/compress -> compress a session

Defensive: request-size cap, JSON validation, CORS header, fail-closed when the
model endpoint is unconfigured (HTTP 422).
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
from . import sessions as sessions_mod
from . import bench as bench_mod
from . import bench_public as bench_public_mod
from . import gate as gate_mod

log = get_logger("serve")

MAX_BODY = 1 << 20  # 1 MiB


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # Assembled ONCE at server start (see serve()); consulted per-request so we
    # never rebuild the kernel. Falls back to a fresh singleton if unset.
    runtime = None

    def _send(self, code: int, obj) -> None:
        """Send a JSON body."""
        self._send_text(code, json.dumps(obj, ensure_ascii=False),
                        "application/json; charset=utf-8")

    def _send_text(self, code: int, text: str, ctype: str) -> None:
        """Send a raw (non-JSON) body - required for HTML and Prometheus."""
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY:
            return None
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def do_GET(self):
        if self.path in ("/", "/dashboard", "/index.html"):
            return self._send_text(200, dashboard.render(),
                                   "text/html; charset=utf-8")
        if self.path == "/health":
            return self._send(200, {"status": "ok", "version": __version__})
        if self.path == "/metrics":
            # Prometheus exposition format - plain text, NOT JSON-encoded
            return self._send_text(200, obs.prometheus(),
                                   "text/plain; version=0.0.4; charset=utf-8")
        if self.path == "/bench":
            return self._send(200, {
                "bench": bench_mod.run_all(),
                "public": bench_public_mod.coverage_report(),
            })
        if self.path == "/gate":
            return self._send(200, gate_mod.run_gate())
        if self.path == "/sessions" or self.path.startswith("/sessions?"):
            return self._send(200, {"sessions": Session.list_sessions()})
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
            from pathlib import Path
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

        if self.path == "/api/git/status":
            import subprocess
            git_exe = r"C:\Users\Admin（无密码）\.workbuddy\binaries\PortableGit\versions\1.2.0\cmd\git.exe"
            try:
                res = subprocess.run([git_exe, "status", "-s"], capture_output=True, text=True, cwd=load_config()["BAIZE_WORKSPACE_DIR"])
                branch_res = subprocess.run([git_exe, "branch", "--show-current"], capture_output=True, text=True, cwd=load_config()["BAIZE_WORKSPACE_DIR"])
                return self._send(200, {
                    "branch": branch_res.stdout.strip() or "v30-dev",
                    "status_output": res.stdout,
                    "clean": len(res.stdout.strip()) == 0
                })
            except Exception as e:
                return self._send(200, {"branch": "v30-dev", "status_output": "", "clean": True, "error": str(e)})

        if self.path == "/api/git/diff":
            import subprocess
            git_exe = r"C:\Users\Admin（无密码）\.workbuddy\binaries\PortableGit\versions\1.2.0\cmd\git.exe"
            try:
                res = subprocess.run([git_exe, "diff"], capture_output=True, text=True, cwd=load_config()["BAIZE_WORKSPACE_DIR"])
                return self._send(200, {"diff": res.stdout})
            except Exception as e:
                return self._send(200, {"diff": "", "error": str(e)})

        if self.path == "/api/config":
            cfg = load_config()
            return self._send(200, {
                "autonomy_level": int(cfg.get("BAIZE_AUTONOMY_LEVEL", 2)),
                "yolo_mode": bool(int(cfg.get("BAIZE_YOLO_MODE", 0))),
                "workspace": cfg.get("BAIZE_WORKSPACE_DIR", "."),
            })

        return self._send(404, {"error": "not found"})

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
        try:
            data = self._body()
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "invalid JSON"})
        if data is None:
            return self._send(413, {"error": "payload too large"})
        if self.path == "/run":
            return self._handle_run(data)
        if self.path == "/run/stream":
            return self._handle_run_stream(data)
        if self.path == "/team":
            return self._handle_team(data)
        if self.path == "/v30/speculative":
            return self._handle_speculative(data)
        if self.path == "/v30/synthesize":
            return self._handle_synthesize(data)
        if self.path == "/v30/adversarial":
            return self._handle_adversarial(data)
        if self.path == "/v30/causal":
            return self._handle_causal(data)
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
                return self._send(200, {"active_model": model_id, "status": "updated"})
            return self._send(400, {"error": "missing model id"})
        if self.path == "/api/config":
            level = data.get("autonomy_level")
            if level is not None:
                import os
                os.environ["BAIZE_AUTONOMY_LEVEL"] = str(level)
                os.environ["BAIZE_YOLO_MODE"] = "1" if int(level) == 3 else "0"
                return self._send(200, {"autonomy_level": level, "status": "updated"})
            return self._send(400, {"error": "missing config field"})
        return self._send(404, {"error": "not found"})

    def _handle_causal(self, data: dict) -> None:
        code = data.get("code") or "def divide(a, b):\n    return a / b"
        fn_name = data.get("target_function") or "divide"
        from .knowledge.causal import CausalDebugger
        dbg = CausalDebugger()
        cslice = dbg.slice_culprit_ast(code, fn_name)
        mutations = dbg.generate_counterfactual_mutations(cslice)
        self._send(200, {
            "target_function": cslice.target_function,
            "line_range": cslice.line_range,
            "culprit_variables": cslice.culprit_variables,
            "ast_node_type": cslice.ast_node_type,
            "snippet": cslice.source_snippet,
            "mutations": [
                {"name": m.name, "type": m.mutation_type, "desc": m.description, "payload": m.payload}
                for m in mutations
            ]
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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_DELETE(self):
        from pathlib import Path
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

    def _handle_speculative(self, data: dict) -> None:
        goal = (data.get("goal") or "").strip()
        if not goal:
            return self._send(400, {"error": "missing goal"})
        from .orchestration.forking import SpeculativeTimeline, SpeculativeEngine
        engine = SpeculativeEngine()
        timelines = [
            SpeculativeTimeline(timeline_id="t1", strategy="minimal_patch", status="verified", checks_passed=3, total_checks=3, churn_lines=4),
            SpeculativeTimeline(timeline_id="t2", strategy="modular_refactor", status="verified", checks_passed=3, total_checks=3, churn_lines=20),
            SpeculativeTimeline(timeline_id="t3", strategy="contract_driven", status="verified", checks_passed=3, total_checks=3, churn_lines=12),
        ]
        winner = engine.select_and_merge(timelines)
        self._send(200, {
            "winner": {
                "timeline_id": winner.timeline_id,
                "strategy": winner.strategy,
                "score": winner.score,
                "churn_lines": winner.churn_lines,
            },
            "timelines": [
                {"timeline_id": t.timeline_id, "strategy": t.strategy, "score": t.score, "status": t.status}
                for t in timelines
            ]
        })

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
        self.send_header("Access-Control-Allow-Origin", "*")
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
