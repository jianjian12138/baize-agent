"""POST route dispatch and handlers for the Baize HTTP server."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ...core.config import load_config
from .security import ENV_WRITE_LOCK, INERT_SETTINGS_NOTE, code_exec_gate, safe_child_path
from .streaming import handle_run_stream


def _handle_run(handler, data: dict, deps: dict[str, Any]) -> None:
    goal = (data.get("goal") or "").strip()
    if not goal:
        return handler._send(400, {"error": "missing goal"})
    client = deps["LLMClient"]()
    if not client.configured:
        return handler._send(422, {"error": "model endpoint not configured"})
    if not deps["has_real_key"](client):
        return handler._send(422, {"error": "model API key not set (placeholder in .env)"})
    agent = deps["Agent"](role="executor", client=client)
    deps["obs"].inc("serve_run")
    res = agent.run(goal)
    handler._send(200, {
        "final_text": res.final_text,
        "stopped_reason": res.stopped_reason,
        "steps": res.steps,
        "session_id": res.session_id,
    })


def _handle_team(handler, data: dict, deps: dict[str, Any]) -> None:
    goal = (data.get("goal") or "").strip()
    if not goal:
        return handler._send(400, {"error": "missing goal"})
    client = deps["LLMClient"]()
    if not client.configured:
        return handler._send(422, {"error": "model endpoint not configured"})
    if not deps["has_real_key"](client):
        return handler._send(422, {"error": "model API key not set (placeholder in .env)"})
    orch = deps["Orchestrator"](client=client)
    deps["obs"].inc("serve_team")
    res = orch.run(goal)
    handler._send(200, {
        "success": res.success,
        "reports": [
            {"task_id": r.task_id, "verdict": r.verdict, "issues": r.issues, "task": r.task}
            for r in res.reports
        ],
    })



def _handle_save_skill(handler, data: dict) -> None:
    name = (data.get("name") or "").strip()
    body = data.get("content") or ""
    if not name:
        return handler._send(400, {"error": "missing skill name"})
    base = Path("user_skills")
    skill_dir = safe_child_path(base, name)
    if skill_dir is None:
        return handler._send(400, {"error": "invalid skill name (path traversal rejected)"})
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    return handler._send(200, {"name": name, "path": str(skill_dir / "SKILL.md"), "status": "saved"})


def _handle_fork(handler, data: dict, deps: dict[str, Any]) -> None:
    parent = (data.get("parent") or "").strip()
    if not parent:
        return handler._send(400, {"error": "missing parent session id"})
    raw = data.get("at_index")
    at_index = None
    if raw is not None and str(raw) != "":
        try:
            at_index = int(raw)
        except (ValueError, TypeError):
            return handler._send(400, {"error": "at_index must be an integer"})
    try:
        new_id = deps["sessions_mod"].fork_session(parent, at_index)
    except FileNotFoundError:
        return handler._send(404, {"error": "parent session not found"})
    handler._send(200, {"new_session_id": new_id, "fork_of": parent, "at_index": at_index})


def _handle_compress(handler, data: dict, deps: dict[str, Any]) -> None:
    sid = (data.get("id") or "").strip()
    if not sid:
        return handler._send(400, {"error": "missing session id"})
    try:
        report = deps["sessions_mod"].compress_session(sid)
    except FileNotFoundError:
        return handler._send(404, {"error": "session not found"})
    handler._send(200, report)





def _handle_team_dag(handler, data: dict, deps: dict[str, Any]) -> None:
    """Real Director -> Executor -> Verifier DAG planner (and optional executor)."""
    goal = (data.get("goal") or "").strip()
    if not goal:
        return handler._send(400, {"error": "missing goal"})
    execute = bool(data.get("execute", False))
    from ...orchestration.orchestrator import Orchestrator

    if not execute:
        # Honest deterministic task decomposition without claiming code execution
        parts = [p.strip() for p in re.split(r"[;；\n]+|然后|并且|and then", goal) if p.strip()]
        if not parts:
            parts = [goal]
        nodes = [
            {
                "id": f"task-{idx}",
                "role": "director" if idx == 1 else "executor",
                "title": part[:120],
                "depends_on": [f"task-{idx - 1}"] if idx > 1 else [],
                "status": "planned",
            }
            for idx, part in enumerate(parts, 1)
        ]
        nodes.append({
            "id": f"task-{len(nodes) + 1}",
            "role": "verifier",
            "title": "Run physical NO FAKE DONE verification gates",
            "depends_on": [nodes[-1]["id"]],
            "status": "planned",
        })
        return handler._send(200, {
            "mode": "plan_only",
            "executed": False,
            "goal": goal,
            "nodes": nodes,
        })

    client = deps["LLMClient"]()
    if not client.configured:
        return handler._send(422, {"error": "model endpoint not configured"})
    if not deps["has_real_key"](client):
        return handler._send(422, {"error": "model API key not set (placeholder in .env)"})
    orch = deps["Orchestrator"](client=client)
    res = orch.run(goal)
    return handler._send(200, {
        "mode": "executed",
        "executed": True,
        "success": res.success,
        "nodes": [
            {"id": r.task_id, "task": r.task, "verdict": r.verdict, "issues": r.issues}
            for r in res.reports
        ],
    })


def _handle_git_apply_hunk(handler, data: dict, deps: dict[str, Any]) -> None:
    """Apply a unified diff patch safely with pre-flight Git checkpoint & auto-rollback."""
    patch_text = data.get("patch") or data.get("diff") or ""
    if not patch_text.strip():
        return handler._send(400, {"error": "missing unified diff 'patch'"})

    git_bin = deps["resolve_git"]()
    if not git_bin:
        return handler._send(503, {"error": "git executable not available"})

    cfg = load_config()
    ws = cfg.get("BAIZE_WORKSPACE_DIR", ".")
    from ...execution.checkpoint import GitCheckpointManager

    mgr = GitCheckpointManager(ws)
    if not mgr.is_git_repo():
        return handler._send(400, {"error": f"workspace is not a git repository: {ws}"})

    cp = mgr.create(label="api/git/apply_hunk")
    import subprocess
    check = subprocess.run(
        [git_bin, "apply", "--check", "--whitespace=nowarn", "-"],
        input=patch_text, cwd=ws, capture_output=True, text=True, timeout=15,
    )
    if check.returncode != 0:
        mgr.rollback(cp.checkpoint_id)
        return handler._send(422, {
            "error": "patch failed git apply --check",
            "detail": (check.stderr or check.stdout).strip(),
            "checkpoint_id": cp.checkpoint_id,
            "rolled_back": True,
        })

    applied = subprocess.run(
        [git_bin, "apply", "--whitespace=nowarn", "-"],
        input=patch_text, cwd=ws, capture_output=True, text=True, timeout=15,
    )
    if applied.returncode != 0:
        mgr.rollback(cp.checkpoint_id)
        return handler._send(500, {
            "error": "git apply failed",
            "detail": (applied.stderr or applied.stdout).strip(),
            "checkpoint_id": cp.checkpoint_id,
            "rolled_back": True,
        })

    stat = mgr.diff_stat(cp.checkpoint_id)
    mgr.commit(cp.checkpoint_id)
    return handler._send(200, {
        "status": "applied",
        "checkpoint_id": cp.checkpoint_id,
        "diff_stat": stat,
    })


def _handle_enqueue_job(handler, data: dict, deps: dict[str, Any]) -> None:
    kind = (data.get("kind") or "run").strip().lower()
    if kind not in ("run", "team", "eval"):
        return handler._send(400, {"error": f"unsupported job kind: {kind!r} (expected run|team|eval)"})
    if kind in ("run", "team") and not (data.get("goal") or "").strip():
        return handler._send(400, {"error": "missing goal"})

    store = deps["get_job_store"]()

    def _worker(job_id: str, payload: dict[str, Any], cancel_ev, emit_fn) -> dict[str, Any]:
        if kind == "eval":
            from ...governance.eval_harness import run_eval_suite
            mode = (payload.get("mode") or "oracle").strip()
            emit_fn("eval_start", f"running eval suite mode={mode}")
            summary = run_eval_suite(mode=mode, task_ids=payload.get("task_ids"), persist=True)
            return summary.to_dict()

        client = deps["LLMClient"]()
        if not client.configured or not deps["has_real_key"](client):
            raise RuntimeError("model endpoint or API key not configured")

        if kind == "team":
            orch = deps["Orchestrator"](client=client)
            res = orch.run(payload["goal"])
            return {
                "success": res.success,
                "reports": [
                    {"task_id": r.task_id, "verdict": r.verdict, "issues": r.issues, "task": r.task}
                    for r in res.reports
                ],
            }

        agent = deps["Agent"](
            role="executor",
            client=client,
            on_event=lambda k, d: emit_fn(k, str(d)),
        )
        res = agent.run(payload["goal"])
        return {
            "final_text": res.final_text,
            "stopped_reason": res.stopped_reason,
            "steps": res.steps,
            "session_id": res.session_id,
            "checkpoint_id": getattr(res, "checkpoint_id", ""),
            "rolled_back": getattr(res, "rolled_back", False),
        }

    job = store.enqueue(kind, data, _worker)
    return handler._send(202, job)


def dispatch_post(handler, req_path: str, data: dict, deps: dict[str, Any]) -> None:
    stub_routes = deps["STUB_ROUTES"]
    if req_path in stub_routes:
        return handler._send(501, deps["stub_body"](req_path))

    retired_routes = deps.get("RETIRED_ROUTES", {})
    if req_path in retired_routes:
        return handler._send(410, deps["retired_body"](req_path))

    if req_path == "/api/webhook/dispatch":
        from .operations import dispatch_webhook
        code, body = dispatch_webhook(data, load_config())
        return handler._send(code, body)

    if req_path == "/api/security/rbac":
        from .operations import apply_and_evaluate_rbac
        code, body = apply_and_evaluate_rbac(data, load_config())
        return handler._send(code, body)

    if req_path == "/api/tools/import":
        from .operations import import_runtime_tool
        code, body = import_runtime_tool(data, load_config())
        return handler._send(code, body)

    if req_path == "/api/ci/autofix":
        from .operations import trigger_ci_autofix
        code, body = trigger_ci_autofix(data, load_config(), deps)
        return handler._send(code, body)

    if req_path == "/api/mcp/call":
        server = data.get("server") or "sqlite"
        tool = data.get("tool") or "sqlite_query"
        args = data.get("arguments") or {}
        from ...ext.mcp.dispatcher import call_mcp_tool
        return handler._send(200, call_mcp_tool(server, tool, args, load_config().get("BAIZE_WORKSPACE_DIR", ".")))


    if req_path == "/api/context/slice":
        from ...codebase.repo_map import slice_code_context
        return handler._send(200, slice_code_context(data.get("code") or "", data.get("focus_symbol") or ""))


    if req_path == "/api/causal/mutation_test":
        code = data.get("code") or "def add(a, b):\n    return a + b if a > 0 else 0"
        fn = data.get("target_function") or "add"
        from ...governance.mutation import run_ast_mutation_arena
        return handler._send(200, run_ast_mutation_arena(code, fn))


    if req_path == "/api/invariants/anchor":
        goal = data.get("goal") or "长期重构任务"
        constraints = data.get("constraints") or None
        from ...orchestration.contract import create_invariants_anchor
        anchor = create_invariants_anchor(goal, constraints)
        sample_prompt = data.get("prompt") or "请开始第 42 步执行"
        wrapped = anchor.inject_anchor_header(sample_prompt, turn_index=int(data.get("turn_index", 42)))
        return handler._send(200, {
            "status": "anchored",
            "invariants": anchor.invariants,
            "wrapped_prompt_sample": wrapped,
            "message": f"核心不变量锚点已成功激活！已为第 {data.get('turn_index', 42)} 步长程任务注入置顶约束。",
        })

    if req_path == "/api/interactive/detect":
        from ...execution.proc import detect_interactive_prompt
        return handler._send(200, detect_interactive_prompt(data.get("text") or "Do you want to continue? [y/N]"))

    if req_path == "/api/docs/fetch":
        from ...knowledge.doc_crawler import DocCrawlerRegistry
        return handler._send(200, DocCrawlerRegistry.index_url(data.get("url", "")))

    if req_path == "/api/system1/route":
        from ...orchestration.system1 import fast_route_intent
        dec = fast_route_intent(data.get("goal") or "")
        return handler._send(200, {
            "route": dec.route,
            "confidence": dec.confidence,
            "recommended_mode": dec.recommended_mode,
            "complexity_score": dec.complexity_score,
            "provenance": dec.provenance,
            "latency_ms": round(dec.latency_ms, 3),
        })

    if req_path == "/api/system1/guard":
        from ...orchestration.system1 import fast_check_safety
        dec = fast_check_safety(data.get("tool") or "", data.get("args") or {})
        return handler._send(200, {
            "is_safe": dec.is_safe,
            "risk_score": dec.risk_score,
            "blast_radius": dec.blast_radius,
            "veto_reason": dec.veto_reason,
            "provenance": dec.provenance,
            "latency_ms": round(dec.latency_ms, 3),
        })

    if req_path == "/api/browser/verify":
        from ...execution.browser_verify import verify_frontend_code
        return handler._send(200, verify_frontend_code(data.get("html", ""), data.get("name", "index.html")))


    if req_path == "/team/dag":
        return _handle_team_dag(handler, data, deps)
    if req_path == "/api/git/apply_hunk":
        return _handle_git_apply_hunk(handler, data, deps)
    if req_path == "/api/jobs":
        return _handle_enqueue_job(handler, data, deps)
    if req_path.startswith("/api/jobs/") and req_path.endswith("/cancel"):
        jid = req_path[len("/api/jobs/"):-len("/cancel")].strip("/")
        job = deps["get_job_store"]().cancel(jid)
        if not job:
            return handler._send(404, {"error": "job not found"})
        return handler._send(200, job)
    if req_path == "/api/diagnostics":
        from ...codebase.diagnostics import diagnose_file, diagnose_workspace
        cfg = load_config()
        ws = cfg.get("BAIZE_WORKSPACE_DIR", ".")
        fpath = (data.get("path") or "").strip()
        if fpath:
            rep = diagnose_file(fpath, workspace=ws, use_lsp=bool(data.get("use_lsp", False)))
            return handler._send(200, rep.to_dict())
        return handler._send(200, diagnose_workspace(ws, paths=data.get("paths")))
    if req_path == "/api/checkpoints/rollback":
        cp_id = (data.get("checkpoint_id") or "").strip()
        if not cp_id:
            return handler._send(400, {"error": "missing checkpoint_id"})
        from ...execution.checkpoint import GitCheckpointManager
        cfg = load_config()
        res = GitCheckpointManager(cfg.get("BAIZE_WORKSPACE_DIR", ".")).rollback(cp_id)
        return handler._send(200 if res.get("ok") else 404, res)

    if req_path.startswith("/api/channels/") and req_path.endswith("/webhook"):
        parts = [seg for seg in req_path.split("/") if seg]
        if len(parts) != 4:
            return handler._send(404, {"error": "invalid channel webhook path"})
        channel_name = parts[2].strip().lower()
        from ...ext.channels import ChannelGateway, get_adapter
        cfg = load_config()
        try:
            adapter = get_adapter(channel_name, cfg)
        except ValueError as exc:
            return handler._send(404, {"error": str(exc)})
        # If the channel has no signing secret configured, still enforce BAIZE_API_TOKEN when set.
        has_secret = bool(getattr(adapter, "signing_secret", "") or getattr(adapter, "secret", "") or getattr(adapter, "secret_token", ""))
        if not has_secret and not handler._is_authorized():
            return handler._send(401, {"error": "unauthorized: invalid or missing bearer token"})
        raw_body = getattr(handler, "_raw_body", None)
        if raw_body is None:
            raw_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers_dict = {k: v for k, v in handler.headers.items()}
        store = deps["get_job_store"]()
        gw = ChannelGateway(cfg=cfg, job_store=store)
        status_code, resp_body = gw.handle_webhook(channel_name, headers_dict, raw_body)
        return handler._send(status_code, resp_body)

    if req_path == "/run":
        return _handle_run(handler, data, deps)
    if req_path == "/run/stream":
        return handle_run_stream(handler, data, deps)
    if req_path == "/team":
        return _handle_team(handler, data, deps)


    if req_path == "/v30/causal/persist_test":
        fn = (data.get("target_function") or "divide").strip()
        code = data.get("code") or ""
        if not fn.isidentifier():
            return handler._send(400, {
                "error": f"target_function {fn!r} is not a valid Python identifier",
                "reason": "the name is used both as a filename component and as the "
                          "function name inside the written source",
            })
        if not code.strip():
            return handler._send(400, {
                "error": "code is required",
                "reason": "the test is generated from the submitted source",
            })
        from ...governance.mutation import run_ast_mutation_arena
        arena = run_ast_mutation_arena(code, fn)
        if arena.get("status") != "success":
            return handler._send(422, {
                "error": "no guardrail test could be generated from that source",
                "arena_status": arena.get("status"),
                "arena_message": arena.get("message"),
            })
        gen_dir = Path("tests/generated")
        gen_dir.mkdir(parents=True, exist_ok=True)
        test_file = (gen_dir / f"test_causal_{fn}.py").resolve()
        if gen_dir.resolve() not in test_file.parents:
            return handler._send(400, {
                "error": "refusing to write outside tests/generated",
                "resolved": str(test_file).replace("\\", "/"),
            })
        test_file.write_text(arena["synthesized_guardrail_test"], encoding="utf-8", newline="\n")
        return handler._send(200, {
            "status": "persisted",
            "path": str(test_file).replace("\\", "/"),
            "bytes_written": test_file.stat().st_size,
            "mutation_score": arena["mutation_score"],
            "guardrail_verification": arena["guardrail_verification"],
            "tracked_by_git": False,
            "message": (
                f"已将 {fn} 的护栏测试写入 {test_file.name}"
                f"（{test_file.stat().st_size} 字节，击杀率 {arena['mutation_score'] or '无'}）。"
                "该文件由提交的源码与实测探针生成，内容与源码逐行对应；tests/generated/ 未纳入版本控制。"
            ),
        })

    if req_path == "/api/memory/search":
        query = (data.get("query") or "").strip()
        results = []
        sess_dir = Path(load_config().get("BAIZE_SESSIONS_DIR", "persistence/sessions"))
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
        return handler._send(200, {
            "query": query,
            "match": "substring",
            "results": results[:5],
            "searched_dir": str(sess_dir),
            "note": "substring matches only - no embedding model is loaded, so there is no semantic ranking here",
        })

    if req_path == "/api/models/route":
        prompt = (data.get("prompt") or "").strip().lower()
        keywords = ["重构", "refactor", "ast", "causal", "架构", "dag", "推演", "speculative"]
        matched = [k for k in keywords if k in prompt]
        is_complex = bool(matched)
        return handler._send(200, {
            "complexity": "HIGH" if is_complex else "FAST",
            "suggested_model": "deepseek-reasoner" if is_complex else "deepseek-chat",
            "routed": False,
            "basis": "matched keyword(s): " + ", ".join(matched) if matched else "no complexity keyword matched",
            "note": "advisory only - the caller decides whether to act on it; no model selection was performed",
        })

    if req_path == "/sessions/fork":
        return _handle_fork(handler, data, deps)
    if req_path == "/sessions/compress":
        return _handle_compress(handler, data, deps)
    if req_path == "/api/skills":
        return _handle_save_skill(handler, data)

    if req_path == "/api/models/active":
        model_id = (data.get("model") or "").strip()
        if model_id:
            with ENV_WRITE_LOCK:
                os.environ["BAIZE_MODEL_NAME"] = model_id
            return handler._send(200, {
                "active_model": model_id,
                "status": "stored_in_process_env",
                "persisted": False,
                "note": "BAIZE_MODEL_NAME is set in the server process environment; "
                        "it is not written to .env and does not survive a restart",
            })
        return handler._send(400, {"error": "missing model id"})

    if req_path == "/api/config":
        level = data.get("autonomy_level")
        if level is not None:
            try:
                lvl_int = int(level)
            except (ValueError, TypeError):
                return handler._send(400, {"error": "autonomy_level must be an integer (1-3)"})
            if lvl_int not in (1, 2, 3):
                return handler._send(400, {"error": "autonomy_level must be 1, 2, or 3"})
            with ENV_WRITE_LOCK:
                os.environ["BAIZE_AUTONOMY_LEVEL"] = str(lvl_int)
                os.environ["BAIZE_YOLO_MODE"] = "1" if lvl_int == 3 else "0"
            return handler._send(200, {
                "autonomy_level": lvl_int,
                "status": "stored_in_process_env",
                "persisted": False,
                "effective": True,
                "note": INERT_SETTINGS_NOTE,
            })
        return handler._send(400, {"error": "missing config field"})

    if req_path == "/api/sessions/rewind":
        sid = (data.get("session_id") or "").strip()
        node_id = (data.get("node_id") or "").strip()
        if not sid or not node_id:
            return handler._send(400, {"error": "session_id and node_id are required"})
        from ...core.sessions import rewind_session
        cfg = load_config()
        try:
            res = rewind_session(
                sid,
                node_id,
                restore_code=bool(data.get("restore_code", False)),
                workspace=cfg.get("BAIZE_WORKSPACE_DIR", "."),
                cfg=cfg,
            )
            return handler._send(200 if res.get("ok") else 404, res)
        except FileNotFoundError as exc:
            return handler._send(404, {"error": str(exc)})
        except ValueError as exc:
            return handler._send(400, {"error": str(exc)})

    if req_path == "/api/worktrees/cleanup":
        from ...execution.worktree import GitWorktreePool
        cfg = load_config()
        pool = GitWorktreePool(cfg.get("BAIZE_WORKSPACE_DIR", "."))
        wt_id = (data.get("worktree_id") or "").strip()
        if wt_id:
            res = pool.cleanup(wt_id)
            return handler._send(200 if res.get("ok") else 404, res)
        return handler._send(200, pool.cleanup_all())

    if req_path.startswith("/api/approvals/") and req_path.endswith("/resolve"):
        req_id = req_path[len("/api/approvals/"):-len("/resolve")].strip("/")
        if not req_id:
            return handler._send(400, {"error": "missing approval request id"})
        from ..approval import get_approval_queue
        approved = bool(data.get("approved", False))
        scope = (data.get("scope") or ("once" if approved else "deny")).strip()
        reason = (data.get("reason") or "").strip()
        res = get_approval_queue().resolve(req_id, approved=approved, scope=scope, reason=reason)
        return handler._send(200 if res.get("ok") else 404, res)

    if req_path.startswith("/api/bg-procs/") and req_path.endswith("/stop"):
        proc_id = req_path[len("/api/bg-procs/"):-len("/stop")].strip("/")
        if not proc_id:
            return handler._send(400, {"error": "missing process id"})
        from ...execution.bg_proc import get_bg_manager
        res = get_bg_manager().stop(proc_id)
        return handler._send(200 if res.get("ok") else 404, res)

    if req_path == "/api/budget/config":
        from ...core.cost_ledger import get_cost_ledger
        cfg = load_config()
        reset_sid = (data.get("reset_session_id") or "").strip()
        if reset_sid:
            ledger = get_cost_ledger(cfg)
            removed = ledger.reset_session(reset_sid)
            return handler._send(200, {
                "ok": True,
                "reset_session_id": reset_sid,
                "deleted_rows": removed,
                "summary": ledger.summary(),
            })
        updated: dict[str, Any] = {}
        try:
            if "max_session_usd" in data and data["max_session_usd"] is not None:
                val_usd = float(data["max_session_usd"])
                if val_usd < 0:
                    return handler._send(400, {"error": "max_session_usd must be >= 0"})
                updated["BAIZE_MAX_SESSION_USD"] = f"{val_usd:.4f}"
            if "max_session_tokens" in data and data["max_session_tokens"] is not None:
                val_tok = int(data["max_session_tokens"])
                if val_tok < 0:
                    return handler._send(400, {"error": "max_session_tokens must be >= 0"})
                updated["BAIZE_MAX_SESSION_TOKENS"] = str(val_tok)
            if "warn_ratio" in data and data["warn_ratio"] is not None:
                val_ratio = float(data["warn_ratio"])
                if not (0.0 < val_ratio <= 1.0):
                    return handler._send(400, {"error": "warn_ratio must be in (0, 1]"})
                updated["BAIZE_BUDGET_WARN_RATIO"] = f"{val_ratio:.2f}"
        except (TypeError, ValueError) as exc:
            return handler._send(400, {"error": f"invalid budget parameter: {exc}"})
        if not updated:
            return handler._send(400, {"error": "no budget config fields supplied"})
        with ENV_WRITE_LOCK:
            for k, v in updated.items():
                os.environ[k] = v
        persisted = False
        try:
            from ...governance.dlp import RuntimeConfigStore, get_audit_ledger
            RuntimeConfigStore().save_overrides(updated)
            persisted = True
            get_audit_ledger().append(
                "config_updated",
                actor=getattr(getattr(handler, "tenant_context", None), "tenant_id", "api"),
                target="budget_config",
                outcome="ok",
                details=updated,
            )
        except Exception:
            pass
        cfg_now = load_config()
        return handler._send(200, {
            "ok": True,
            "persisted": persisted,
            "updated": updated,
            "config": {
                "max_session_usd": float(cfg_now.get("BAIZE_MAX_SESSION_USD", "0") or 0),
                "max_session_tokens": int(cfg_now.get("BAIZE_MAX_SESSION_TOKENS", "0") or 0),
                "warn_ratio": float(cfg_now.get("BAIZE_BUDGET_WARN_RATIO", "0.8") or 0.8),
            },
            "summary": get_cost_ledger(cfg_now).summary(),
        })

    if req_path == "/api/memory/bounded":
        slot = (data.get("slot") or "memory").strip().lower()
        action = (data.get("action") or "add").strip().lower()
        content = str(data.get("content") or "")
        target = str(data.get("target") or "")
        from ...knowledge.memory import BoundedMemoryStore
        cfg = load_config()
        store = BoundedMemoryStore(cfg)
        res = store.update(slot, action, content=content, target=target)
        status = 200 if res.get("ok") else 400
        return handler._send(status, {
            **res,
            "stats": store.stats(),
            "memory": store.read("memory"),
            "user": store.read("user"),
        })

    if req_path == "/api/search/hybrid":
        query = (data.get("query") or "").strip()
        mode = (data.get("mode") or "hybrid").strip().lower()
        if mode not in ("hybrid", "fts5", "embedding"):
            return handler._send(400, {"error": f"invalid search mode: {mode}"})
        limit = max(1, min(int(data.get("limit", 8) or 8), 50))
        reindex = bool(data.get("reindex", False))
        from ...knowledge.hybrid_index import HybridSearchIndex
        cfg = load_config()
        idx = HybridSearchIndex(cfg=cfg)
        st = idx.stats()
        index_report = None
        if reindex or st.get("total_docs", 0) == 0:
            ws = cfg.get("BAIZE_WORKSPACE_DIR", ".")
            index_report = idx.index_git_delta(ws)
        hits = idx.search(query, mode=mode, limit=limit) if query else []
        return handler._send(200, {
            "query": query,
            "mode": mode,
            "embedding_configured": idx.embedding_configured,
            "indexed": index_report,
            "stats": idx.stats(),
            "hits": [h.to_dict() for h in hits],
        })

    if req_path == "/api/eval/run":
        from ...governance.eval_harness import run_coding_benchmark
        mode = str(data.get("mode") or "offline").strip().lower()
        if mode not in ("offline", "oracle", "live"):
            return handler._send(400, {"error": f"invalid eval mode: {mode}"})
        cfg = load_config()
        rep = run_coding_benchmark(mode=mode, cfg=cfg, persist_history=True)
        return handler._send(200, rep)

    if req_path == "/api/spec":
        from ...orchestration.spec_workflow import get_spec_manager
        cfg = load_config()
        mgr = get_spec_manager(cfg)
        sid = str(data.get("session_id") or "default").strip() or "default"
        action = str(data.get("action") or "status").strip().lower()
        if action == "enable":
            st = mgr.enable(sid, note=str(data.get("note") or ""))
        elif action == "disable":
            st = mgr.disable(sid, note=str(data.get("note") or ""))
        elif action == "draft":
            st = mgr.submit_spec(
                sid,
                summary=str(data.get("summary") or ""),
                content=str(data.get("content") or ""),
                note=str(data.get("note") or ""),
            )
        elif action == "approve":
            st = mgr.approve(sid, actor=str(data.get("actor") or "studio_user"), note=str(data.get("note") or ""))
        elif action == "reject":
            st = mgr.reject(sid, reason=str(data.get("reason") or ""))
        elif action == "verify":
            st = mgr.mark_verified(sid, note=str(data.get("note") or ""))
        elif action == "status":
            st = mgr.get(sid)
        else:
            return handler._send(400, {"error": f"invalid spec action: {action}"})
        return handler._send(200, st.to_dict())

    if req_path == "/api/mcp/health":
        from ...ext.mcp.client import check_mcp_health
        cfg = load_config()
        specs = data.get("specs") if isinstance(data.get("specs"), list) else None
        live_probe = bool(data.get("live_probe", False))
        rep = check_mcp_health(specs=specs, cfg=cfg, live_probe=live_probe)
        return handler._send(200, rep)

    if req_path == "/api/ui/verify":
        url = str(data.get("url") or "").strip()
        if not url:
            return handler._send(400, {"error": "missing required field: url"})
        from ...execution.visual_verify import verify_ui
        cfg = load_config()
        raw_vps = data.get("viewports")
        if isinstance(raw_vps, str):
            vps = [v.strip() for v in raw_vps.split(",") if v.strip()]
        elif isinstance(raw_vps, list):
            vps = [str(v).strip() for v in raw_vps if str(v).strip()]
        else:
            vps = None
        check_visual = bool(data.get("check_visual", False))
        rep = verify_ui(url, viewports=vps, check_visual=check_visual, cfg=cfg)
        return handler._send(200, rep.to_dict())

    return handler._send(404, {"error": "not found"})
