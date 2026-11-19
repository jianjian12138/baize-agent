"""POST route dispatch and handlers for the Baize HTTP server."""
from __future__ import annotations

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

    return handler._send(404, {"error": "not found"})
