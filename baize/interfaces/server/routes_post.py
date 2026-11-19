"""POST route dispatch and handlers for the Baize HTTP server."""
from __future__ import annotations

import os
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


def _handle_causal(handler, data: dict) -> None:
    code = data.get("code") or "def divide(a, b):\n    return a / b"
    fn_name = data.get("target_function") or "divide"
    error_context = data.get("error_context") or ""
    from ...labs.causal import ASTCausalTracker, MutationFuzzer
    cslice = ASTCausalTracker().extract_slice(code, fn_name, error_context)
    mutations = MutationFuzzer().generate_mutations(fn_name, cslice.culprit_variables)
    handler._send(200, {
        "target_function": cslice.target_function,
        "line_range": cslice.line_range,
        "culprit_variables": cslice.culprit_variables,
        "ast_node_type": cslice.ast_node_type,
        "snippet": cslice.source_snippet,
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


def _handle_synthesize(handler, data: dict) -> None:
    name = (data.get("name") or "").strip()
    code = data.get("code") or ""
    test = data.get("test") or ""
    if not name or not code:
        return handler._send(400, {"error": "missing name or code"})
    from ...labs.synthesizer import MetaToolSynthesizer
    tool = MetaToolSynthesizer().certify_tool(
        name=name, description=data.get("description", ""), code_source=code, test_source=test,
    )
    handler._send(200, {"name": tool.name, "certified": tool.certified, "gene_signature": tool.gene_signature})


def _handle_adversarial(handler, data: dict) -> None:
    blue_code = data.get("blue_code") or ""
    red_input = data.get("red_input") or {}
    if not blue_code:
        return handler._send(400, {"error": "missing blue_code"})
    from ...labs.adversarial import ByzantineJudge
    round_res = ByzantineJudge().arbitrate(1, blue_code, red_input)
    handler._send(200, {"verdict": round_res.verdict, "attack_succeeded": round_res.attack_succeeded})


def dispatch_post(handler, req_path: str, data: dict, deps: dict[str, Any]) -> None:
    stub_routes = deps["STUB_ROUTES"]
    if req_path in stub_routes:
        return handler._send(501, deps["stub_body"](req_path))

    if req_path == "/api/mcp/call":
        server = data.get("server") or "sqlite"
        tool = data.get("tool") or "sqlite_query"
        args = data.get("arguments") or {}
        from ...ext.mcp.dispatcher import call_mcp_tool
        return handler._send(200, call_mcp_tool(server, tool, args, load_config().get("BAIZE_WORKSPACE_DIR", ".")))

    if req_path == "/v30/swarm/speculate":
        from ...labs.swarm import run_parallel_swarm_speculation
        return handler._send(200, run_parallel_swarm_speculation(data.get("goal") or "优化系统并发安全性"))

    if req_path == "/api/context/slice":
        from ...codebase.repo_map import slice_code_context
        return handler._send(200, slice_code_context(data.get("code") or "", data.get("focus_symbol") or ""))

    if req_path == "/api/market/publish":
        from ...labs.tool_market import publish_market_tool
        return handler._send(200, publish_market_tool(data))

    if req_path == "/api/causal/mutation_test":
        code = data.get("code") or "def add(a, b):\n    return a + b if a > 0 else 0"
        fn = data.get("target_function") or "add"
        from ...governance.mutation import run_ast_mutation_arena
        return handler._send(200, run_ast_mutation_arena(code, fn))

    if req_path == "/api/byzantine/arbitrate":
        from ...labs.byzantine import DEFAULT_QUORUM, run_byzantine_consensus
        verdicts = data.get("verdicts") or None
        quorum = int(data.get("quorum") or DEFAULT_QUORUM)
        return handler._send(200, run_byzantine_consensus(
            data.get("code") or "", data.get("goal") or "核心支付状态机发布评审",
            verdicts=verdicts, quorum=quorum,
        ))

    if req_path == "/api/invariants/anchor":
        goal = data.get("goal") or "长期重构任务"
        constraints = data.get("constraints") or None
        from ...orchestration.invariants_anchor import create_invariants_anchor
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
        from ...execution.interactive_detector import detect_interactive_prompt
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

    if req_path == "/run":
        return _handle_run(handler, data, deps)
    if req_path == "/run/stream":
        return handle_run_stream(handler, data, deps)
    if req_path == "/team":
        return _handle_team(handler, data, deps)

    if req_path == "/v30/synthesize":
        if code_exec_gate(handler) is not None:
            return
        return _handle_synthesize(handler, data)
    if req_path == "/v30/adversarial":
        if code_exec_gate(handler) is not None:
            return
        return _handle_adversarial(handler, data)
    if req_path == "/v30/causal":
        return _handle_causal(handler, data)

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
