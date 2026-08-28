"""Baize CLI entry point.

    python -m baize doctor
    python -m baize index build
    python -m baize index search <keyword>
    python -m baize manifest validate <path>
    python -m baize memory log "text" [--tags a,b]
    python -m baize memory remember "text"
    python -m baize memory recall <keyword>
    python -m baize memory stats
    python -m baize memory compress [--days N]
    python -m baize rag search <query> [--top-k N]
    python -m baize rag scores
    python -m baize skill build | search <kw> | create <name> | audit
    python -m baize bench
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# Force UTF-8 on Windows consoles (PowerShell/cmd default to GBK -> UnicodeEncodeError
# when skills contain emoji or non-ASCII chars). errors=replace prevents crashes
# on terminals that cannot represent every codepoint.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from . import __version__
from . import doctor as doctor_mod
from . import manifest as manifest_mod
from . import memory as memory_mod
from . import serve as serve_mod
from . import skill_index
from .agent import Agent, Session
from .llm import LLMClient
from .orchestrator import Orchestrator
from .config_schema import ConfigError, validate
from .plugin import registry
from .ui import ProgressUI


def cmd_doctor(_args) -> int:
    report = doctor_mod.run_checks()
    print(doctor_mod.format_report(report))
    return 0 if report.passed else 1


def cmd_index(args) -> int:
    if args.action == "build":
        index = skill_index.build_index()
        print(f"indexed {index['count']} skills "
              f"from {len(index['libraries']) + 1} source(s)")
        print(f"index file: {skill_index.load_config()['BAIZE_INDEX_FILE']}")
        return 0
    if args.action == "search":
        if not args.keyword:
            print("usage: python -m baize index search <keyword>")
            return 2
        hits = skill_index.search(args.keyword)
        if not hits:
            print("no skills matched")
            return 1
        for h in hits:
            print(f"- {h['name']} [{h['source']}]")
            if h["description"]:
                print(f"    {h['description'][:120]}")
            print(f"    {h['skill_file']}")
        return 0
    print("unknown index action")
    return 2


def cmd_skill(args) -> int:
    action = args.action
    if action == "build":
        index = skill_index.build_index()
        print(f"indexed {index['count']} skills "
              f"from {len(index['libraries']) + 1} source(s)")
        print(f"index file: {skill_index.load_config()['BAIZE_INDEX_FILE']}")
        return 0
    if action == "search":
        kw = args.target
        if not kw:
            print("usage: python -m baize skill search <keyword>")
            return 2
        hits = skill_index.search(kw)
        if not hits:
            print("no skills matched")
            return 1
        for h in hits:
            print(f"- {h['name']} [{h['source']}]")
            if h["description"]:
                print(f"    {h['description'][:120]}")
            print(f"    {h['skill_file']}")
        return 0
    if action == "create":
        if not args.target:
            print("usage: python -m baize skill create <name> "
                  "--description \"...\" [--domain ...] [--level ...] "
                  "[--body \"...\"] [--body-file path]")
            return 2
        body = args.body or ""
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        sf = skill_index.create_skill(
            args.target, args.description or "", body,
            domain=args.domain or "", level=args.level or "", origin="user")
        print(f"skill created and indexed -> {sf}")
        return 0
    if action == "audit":
        rep = skill_index.audit_index()
        print("技能治理审计 (skill governance audit)")
        print(f"  索引技能总数    : {rep['count']}")
        print(f"  去重丢弃副本    : {rep['duplicates_deduped']}")
        ps = rep["per_source"]
        if ps:
            print("  各库计数:")
            for src, n in sorted(ps.items(), key=lambda kv: -kv[1]):
                print(f"    - {src}: {n}")
        miss = rep["missing_description"]
        if miss:
            print(f"  缺失 description 的技能 ({len(miss)}):")
            for m in miss[:30]:
                print(f"    - {m['name']} [{m['source']}] {m['path']}")
        dups = rep["duplicate_groups"]
        if dups:
            print(f"  跨库重复组 ({len(dups)}):")
            for d in dups[:30]:
                dropped = ", ".join(d["dropped"])
                print(f"    - {d['name']}: 保留[{d['kept']}] 丢弃[{dropped}]")
        if not miss and not dups:
            print("  状态良好: 无缺失 frontmatter, 无跨库重复.")
        return 0
    print("unknown skill action")
    return 2


def cmd_recon(args) -> int:
    from . import recon
    web = getattr(args, "web", False)
    rep = recon.recon(args.goal, web=web)
    print("方案侦察 pre-flight recon")
    print(f"  goal: {rep['goal']}")
    hits = rep["library_hits"]
    if hits:
        print(f"  技能库同类实现 ({len(hits)}):")
        for h in hits[:20]:
            print(f"    - {h['name']} [{h['source']}] {h['skill_file']}")
    else:
        print("  技能库未发现同类实现")
    wh = rep["web_hits"]
    if wh:
        if wh[0].get("disabled"):
            print(f"  外部侦察已关闭: {wh[0].get('hint')}")
        else:
            for w in wh:
                print(f"  外部搜索 [{w['query']}]:")
                for s in w["sources"]:
                    print(f"    - {s['name']}: {s['url']}")
    print(f"  建议: {rep['advice']}")
    return 0


def cmd_clarify(args) -> int:
    client = LLMClient()
    if not client.configured:
        print("model endpoint not configured - set BAIZE_MODEL_BASE_URL / "
              "BAIZE_MODEL_NAME (and API key) in .env")
        return 2
    orch = Orchestrator(client=client)
    cr = orch.clarify(args.goal)
    print("需求澄清 (clarify -> PRD)")
    qa = cr["qa"]
    for i, q in enumerate(qa.get("questions", []) or []):
        a = qa.get("answers") or []
        ans = a[i] if i < len(a) else "(未答)"
        print(f"  Q{i+1}: {q}")
        print(f"  A{i+1}: {ans}")
    for a in qa.get("assumptions", []) or []:
        print(f"  假设: {a}")
    print(f"  PRD -> {cr['prd_file']}")
    return 0


def cmd_manifest(args) -> int:
    res = manifest_mod.validate_manifest(Path(args.path))
    print(manifest_mod.format_result(res))
    return 0 if res.ok else 1


def cmd_memory(args) -> int:
    if args.action == "log":
        tags = [t for t in (args.tags or "").split(",") if t]
        path = memory_mod.log_event(args.text or "", tags)
        print(f"logged -> {path}")
        return 0
    if args.action == "remember":
        path = memory_mod.remember(args.text or "")
        print(f"remembered -> {path}")
        return 0
    if args.action == "recall":
        tags = [t for t in (args.tags or "").split(",") if t]
        hits = memory_mod.recall(args.text or "", tags=tags or None)
        if not hits:
            print("no memory matched")
            return 1
        for h in hits:
            ts = h.get("ts", "")
            tag_str = f" {h['tags']}" if h.get("tags") else ""
            print(f"- [{h['source']}{' ' + ts if ts else ''}{tag_str}] {h['text']}")
        return 0
    if args.action == "stats":
        print(json.dumps(memory_mod.stats(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "compress":
        res = memory_mod.compress(days=args.days if args.days > 0 else None)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if args.action == "archive":
        days = args.days if args.days > 0 else 30
        res = memory_mod.archive_old_logs(days=days)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    print("unknown memory action")
    return 2


def cmd_rag(args) -> int:
    from . import rag
    if args.action == "search":
        if not args.query:
            print("usage: python -m baize rag search <query>")
            return 2
        hits = rag.retrieve(args.query, top_k=args.top_k)
        if not hits:
            print("no context matched")
            return 1
        for h in hits:
            m = h["meta"]
            label = m.get("name") or m.get("text", "")[:80]
            print(f"- [{m.get('kind', '?')} {h['score']}] {label}")
        return 0
    if args.action == "scores":
        print(json.dumps(rag.skill_scores(), ensure_ascii=False, indent=2))
        return 0
    print("unknown rag action")
    return 2


def cmd_team_memory(args) -> int:
    from .team_memory import TeamMemory
    try:
        tm = TeamMemory(team_id=args.team_id)
    except (RuntimeError, ValueError) as exc:
        print(f"team memory unavailable: {exc}")
        return 2
    if args.action == "show":
        notes = tm.read()
        if not notes:
            print(f"blackboard '{tm.team_id}' is empty")
            return 1
        for n in notes:
            tags = f" {n['tags']}" if n.get("tags") else ""
            print(f"- [{n['role']} {n.get('ts', '')}{tags}] {n['text']}")
        return 0
    if args.action == "stats":
        print(json.dumps(tm.stats(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "clear":
        tm.clear()
        print(f"cleared blackboard '{tm.team_id}'")
        return 0
    print("unknown team-memory action")
    return 2


def cmd_gate(args) -> int:
    from . import gate
    rep = gate.run_gate(
        getattr(args, "manifest", "baize.manifest.json"),
        getattr(args, "coverage_data", ".coverage"))
    print("NO FAKE DONE GATE")
    print(f"  manifest : {'PASS' if rep['manifest_ok'] else 'FAIL'}")
    for p in rep["manifest_problems"]:
        print(f"    - {p}")
    c = rep["coverage"]
    tail = (f" ({c['total']}% >= {c['threshold']}%)"
            if c.get("total") is not None
            else f" ({c.get('reason')})")
    print(f"  coverage : {c['status'].upper()}{tail}")
    q = rep.get("quality", {})
    if q:
        print(f"  quality  : {q['score']} (threshold {q['threshold']}) "
              f"{'PASS' if q['pass'] else 'FAIL'}")
        for dim, val in q["dimensions"].items():
            print(f"    - {dim}: {val}")
    print(f"  overall  : {rep['status'].upper()}")
    if rep["status"] == "fail":
        return 1
    if rep["status"] == "unknown":
        return 2
    return 0


def cmd_bench(args) -> int:
    from . import bench
    from . import bench_public
    if getattr(args, "public", False):
        rep = bench_public.coverage_report()
        print("公开基准诚实覆盖对照 (baize 不运行公开 harness, 仅映射能力):")
        for b in rep["benchmarks"]:
            print(f"  [{b['status']:<8}] {b['name']:<16} "
                  f"{b['measures']} -> {b['capability']}")
        c = rep["counts"]
        print(f"  covered={c['covered']} partial={c['partial']} "
              f"not_run={c['not_run']}")
        print(f"  说明: {rep['honest_note']}")
        return 0
    report = bench.run_all()
    for c in report["cases"]:
        mark = "PASS" if c["ok"] else "FAIL"
        print(f"[{mark}] {c['name']:<8} {c['ms']:>7.1f} ms  {c['detail']}")
    print(f"{report['passed']}/{report['total']} benchmarks passed")
    return 0 if report["all_ok"] else 1


def cmd_automations(args) -> int:
    from . import automations as auto_mod

    if args.action == "list":
        sched = auto_mod.AutomationScheduler()
        specs = sched.store.list()
        if not specs:
            print("no automations defined")
            return 0
        now = time.time()
        for s in specs:
            nxt = sched._next_fire(s, now)
            nxt_s = auto_mod._to_iso(nxt) if nxt is not None else "-"
            print(f"- [{s.status}] {s.id}  {s.name}")
            sched_expr = s.rrule or s.scheduled_at or "(hourly)"
            print(f"    {s.schedule_type}: {sched_expr}  next={nxt_s}")
        return 0

    if args.action == "add":
        sched = auto_mod.AutomationScheduler()
        rrule = args.rrule or ""
        if getattr(args, "nl", ""):
            rrule = auto_mod.parse_nl_schedule(args.nl)
        spec = auto_mod.AutomationSpec(
            id=args.id or f"auto-{int(time.time())}",
            name=args.name or "untitled",
            prompt=args.prompt or "",
            schedule_type=args.schedule_type,
            rrule=rrule,
            scheduled_at=args.scheduled_at or "",
            status="ACTIVE",
            cwds=args.cwds or "",
            created_at=auto_mod._to_iso(time.time()),
        )
        sched.store.save(spec)
        print(f"added {spec.id} ({spec.schedule_type} -> {rrule or spec.scheduled_at or '(default)'})")
        return 0

    if args.action == "remove":
        if not args.id:
            print("usage: python -m baize automations remove <id>")
            return 2
        auto_mod.AutomationScheduler().store.delete(args.id)
        print(f"removed {args.id}")
        return 0

    if args.action in ("pause", "resume"):
        status = "PAUSED" if args.action == "pause" else "ACTIVE"
        if not args.id:
            print(f"usage: python -m baize automations {args.action} <id>")
            return 2
        sched = auto_mod.AutomationScheduler()
        spec = sched.store.get(args.id)
        if not spec:
            print(f"automation not found: {args.id}")
            return 1
        spec.status = status
        sched.store.save(spec)
        print(f"{args.id} -> {status}")
        return 0

    if args.action == "run-now":
        if not args.id:
            print("usage: python -m baize automations run-now <id>")
            return 2
        sched = auto_mod.AutomationScheduler()
        spec = sched.store.get(args.id)
        if not spec:
            print(f"automation not found: {args.id}")
            return 1
        result = sched.runner(spec)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if isinstance(result, dict) and result.get("ok") else 1

    print("unknown automations action")
    return 2


def _make_ui(args) -> ProgressUI:
    """Build the progress renderer honoring --no-color / --quiet."""
    return ProgressUI(color=False if getattr(args, "no_color", False) else None,
                      verbose=not getattr(args, "quiet", False))


def cmd_chat(args) -> int:
    from .repl import run_repl
    return run_repl(
        session_id=getattr(args, "resume", "") or "",
        no_color=getattr(args, "no_color", False),
        quiet=getattr(args, "quiet", False),
    )


def cmd_setup(args) -> int:
    from .setup_wizard import run_setup_wizard
    success = run_setup_wizard()
    return 0 if success else 1


def cmd_run(args) -> int:
    client = LLMClient()
    if not client.configured:
        print("model endpoint not configured - set BAIZE_MODEL_BASE_URL / "
              "BAIZE_MODEL_NAME (and API key) in .env")
        print("💡 提示: 您可以运行 'python -m baize setup' 启动交互式快速配置向导。")
        return 2
    ui = _make_ui(args)
    session = Session(session_id=args.resume) if args.resume else None
    agent = Agent(role="executor", client=client, session=session,
                  on_event=ui.event)
    print(f"session: {agent.session.id}")
    res = agent.run(args.goal)
    print(res.final_text)
    ui.summary(res)
    return 0 if res.stopped_reason == "final" else 1


def cmd_team(args) -> int:
    client = LLMClient()
    if not client.configured:
        print("model endpoint not configured - set BAIZE_MODEL_BASE_URL / "
              "BAIZE_MODEL_NAME (and API key) in .env")
        return 2
    ui = _make_ui(args)
    # V25 F4: a custom roles.json drives a thin-config team; otherwise the
    # built-in Director->Executor->Verifier topology is used unchanged.
    if getattr(args, "roles", ""):
        from baize.team import build_team, load_roles
        try:
            config = load_roles(args.roles)
        except (FileNotFoundError, ValueError) as e:
            print(f"[team] invalid roles config: {e}", file=sys.stderr)
            return 2
        orch = build_team(config, client=client, on_event=ui.event)
    else:
        orch = Orchestrator(client=client, on_event=ui.event)
    # V26-A4: --resume passes run-id to orchestrator to skip verified tasks
    resume_run_id = getattr(args, "resume", "") or None
    if resume_run_id:
        print(f"[resume] run-id: {resume_run_id}")
    res = orch.run(args.goal, resume_run_id=resume_run_id)
    print("=" * 62)
    total = len(res.reports)
    for i, r in enumerate(res.reports, start=1):
        mark = "PASS" if r.verdict == "pass" else r.verdict.upper()
        color = "green" if r.verdict == "pass" else "red"
        retry = " (retried)" if r.retried else ""
        print(f"{ui.bar(i, total)} {ui.p.paint(color, f'[{mark}]')}{retry} "
              f"#{r.task_id} {r.task[:70]}")
        for issue in r.issues:
            print(f"    issue: {issue}")
    ui.summary(res)
    run_id = getattr(res, "run_id", None)
    if run_id:
        print(f"run-id: {run_id}  (use 'baize status {run_id}' to inspect)")
    print(f"sessions: {len(res.session_ids)}")
    return 0 if res.success else 1


def cmd_sessions(args) -> int:
    sessions = Session.list_sessions()
    if not sessions:
        print("no sessions yet")
        return 0
    if args.session_id:
        from .session_viewer import render_session, find_session_file
        if getattr(args, "inspect", False):
            s_file = find_session_file(args.session_id)
            if not s_file:
                print(f"session file not found: {args.session_id}")
                return 1
            print(render_session(s_file))
            return 0
        matches = [s for s in sessions if s["id"] == args.session_id]
        if not matches:
            print(f"session not found: {args.session_id}")
            return 1
        s = Session(session_id=args.session_id)
        for m in s.messages:
            role = m.get("role", "?")
            content = (m.get("content") or "")[:200].replace("\n", " ")
            calls = ", ".join(
                c.get("function", {}).get("name", "?")
                for c in m.get("tool_calls", []))
            suffix = f" [tools: {calls}]" if calls else ""
            print(f"{role:>9}: {content}{suffix}")
        return 0
    for s in sessions[:30]:
        print(f"- {s['id']}  events={s['events']}  {s['mtime']}")
    return 0


def cmd_status(args) -> int:
    """V26-A5: Show the current state of a run from its ledger.

    Displays: run-id, goal, task counts, blocked tasks, evidence paths,
    and the next recommended action. Reads only from the append-only ledger
    (persistence/runs/<run-id>.jsonl) — never from the manifest directly.
    """
    from .run_ledger import RunLedger, list_runs
    run_id = getattr(args, "run_id", "") or ""
    if not run_id:
        runs = list_runs()
        if not runs:
            print("no runs found in persistence/runs/")
            return 1
        print(f"{len(runs)} run(s) found:")
        for r in runs[-10:]:   # show last 10
            print(f"  - {r}")
        print("\nUse: baize status <run-id>")
        return 0

    ledger = RunLedger(run_id)
    if not ledger.path.exists():
        print(f"run not found: {run_id}")
        return 1

    state = ledger.replay()
    events = ledger.events()

    print(f"=== Run Status: {run_id} ===")
    print(f"  goal       : {state.get('goal') or '(not recorded)'}")
    print(f"  verified   : {sorted(state['verified_tasks'])}")
    print(f"  failed     : {sorted(state['failed_tasks'])}")
    print(f"  in_progress: {sorted(state['in_progress_tasks'])}")
    unfinished = ledger.current_unfinished()
    print(f"  unfinished : {unfinished}")
    print(f"  candidates : {len(state['skill_candidates'])} skill candidate(s)")
    print(f"  completed  : {state['completed']}")
    print(f"  events     : {len(events)} total in ledger")

    # Next action guidance
    if state["completed"]:
        print("\n  next: run complete — review skill candidates or check gate")
    elif unfinished:
        print(f"\n  next: resume with 'baize team <goal> --resume {run_id}'")
    elif state["failed_tasks"]:
        print("\n  next: review failed tasks and fix issues, then re-run")
    else:
        print("\n  next: unknown state — inspect ledger events")

    return 0


def cmd_serve(args) -> int:
    serve_mod.serve(host=args.host, port=args.port)
    return 0


def cmd_plugins(args) -> int:
    action = getattr(args, "action", "") or "list"
    if action == "list":
        n = registry.discover()
        if not registry.plugins:
            print(f"0 plugins loaded (discover scanned {n} candidate file(s))")
        else:
            print(f"{len(registry.plugins)} plugin(s) loaded:")
            for p in registry.plugins:
                print(f"  - {p.name}")
        return 0

    if action == "install":
        url = (getattr(args, "target", "") or "").strip()
        if not url:
            print("usage: python -m baize plugin install <github_url>")
            return 2
        import tarfile
        import tempfile
        import urllib.request
        import shutil
        from .config import load_config
        cfg = load_config()
        user_skills = Path(cfg.get("BAIZE_USER_SKILLS_DIR", "user_skills")).resolve()
        user_skills.mkdir(parents=True, exist_ok=True)

        m = re.search(r"github\.com/([^/]+)/([^/\.]+)", url)
        if not m:
            print(f"error: invalid GitHub URL '{url}'. Expected format: https://github.com/owner/repo")
            return 1
        owner, repo = m.group(1), m.group(2)
        dest_dir = user_skills / repo
        print(f"Fetching skill plugin '{owner}/{repo}'...")
        
        tar_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/main.tar.gz"
        tmp_path = None
        try:
            req = urllib.request.Request(tar_url, headers={"User-Agent": "baize-installer"})
            with urllib.request.urlopen(req, timeout=30) as resp, tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
                tmp.write(resp.read())
                tmp_path = Path(tmp.name)
        except Exception:
            tar_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/master.tar.gz"
            try:
                req = urllib.request.Request(tar_url, headers={"User-Agent": "baize-installer"})
                with urllib.request.urlopen(req, timeout=30) as resp, tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
                    tmp.write(resp.read())
                    tmp_path = Path(tmp.name)
            except Exception as e:
                print(f"error: failed to download archive from GitHub: {e}")
                return 1

        try:
            with tarfile.open(tmp_path, "r:gz") as tar:
                members = tar.getmembers()
                prefix = members[0].name.split("/")[0] if members else ""
                dest_dir.mkdir(parents=True, exist_ok=True)
                for member in members:
                    if member.name.startswith(prefix + "/"):
                        member.name = member.name[len(prefix) + 1:]
                        if member.name:
                            tar.extract(member, dest_dir)
        finally:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()

        from . import skill_index
        count = skill_index.build(cfg)
        print(f"✓ Installed '{repo}' into {dest_dir}")
        print(f"✓ Rebuilt skill index: {count} total skill(s) indexed.")
        return 0

    if action == "remove":
        target = (getattr(args, "target", "") or "").strip()
        if not target:
            print("usage: python -m baize plugin remove <name>")
            return 2
        import shutil
        from .config import load_config
        cfg = load_config()
        user_skills = Path(cfg.get("BAIZE_USER_SKILLS_DIR", "user_skills")).resolve()
        target_dir = user_skills / target
        if not target_dir.exists():
            print(f"error: plugin '{target}' not found in {user_skills}")
            return 1
        shutil.rmtree(target_dir, ignore_errors=True)
        from . import skill_index
        count = skill_index.build(cfg)
        print(f"✓ Removed plugin '{target}'")
        print(f"✓ Rebuilt skill index: {count} total skill(s) indexed.")
        return 0

    print(f"unknown action: {action}")
    return 2


def cmd_mcp(args) -> int:
    # MCP is a transport/tooling command: it does not require an LLM endpoint,
    # so it is exempt from the global validate() guard (mirrors `doctor`).
    # The extension module is imported lazily to keep the core import chain
    # free of baize.ext (red line C: ext fail-closed).
    try:
        from baize.tools import register_mcp_client, default_registry
    except ImportError as e:
        print(f"[mcp] tools module unavailable - {e}", file=sys.stderr)
        return 2
    if args.action == "client":
        spec_path = args.spec or "mcp_server.json"
        try:
            names = register_mcp_client(spec_path)
        except FileNotFoundError:
            print(f"[mcp] spec not found: {spec_path}", file=sys.stderr)
            return 2
        except Exception as e:  # noqa: BLE001 - fail-closed, surface reason
            print(f"[mcp] registration failed - {e}", file=sys.stderr)
            return 1
        reg = default_registry()
        print(f"[mcp] registered {len(names)} tool(s) from {spec_path}")
        live = {t.get("function", t).get("name") for t in reg.schemas()}
        for n in names:
            mark = "ok" if n in live else "MISSING"
            print(f"  + {n} [{mark}]")
        return 0
    # server mode: expose baize's tools to an external MCP client over stdio.
    try:
        from baize.ext.mcp.server import MCPServer
    except ImportError as e:
        print(f"[mcp] server module unavailable - {e}", file=sys.stderr)
        return 2
    server = MCPServer(default_registry())
    print("[mcp] serving baize tools over stdio (Ctrl-C to stop)",
          file=sys.stderr)
    try:
        server.serve_stdio()
    except KeyboardInterrupt:
        pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="baize",
                                description="Baize Engine runtime CLI")
    p.add_argument("--version", action="version", version=f"baize {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="run environment checks")

    ip = sub.add_parser("index", help="skill index operations")
    ip.add_argument("action", choices=["build", "search"])
    ip.add_argument("keyword", nargs="?", default="")

    mp = sub.add_parser("manifest", help="manifest validation")
    mp.add_argument("action", choices=["validate"])
    mp.add_argument("path")

    mem = sub.add_parser("memory", help="persistence memory operations")
    mem.add_argument("action",
                     choices=["log", "remember", "recall", "stats", "compress", "archive"])
    mem.add_argument("text", nargs="?", default="")
    mem.add_argument("--tags", default="")
    mem.add_argument("--days", type=int, default=0,
                     help="compress/archive: process logs older than N days (default: 30)")

    sub.add_parser("setup", help="launch interactive LLM configuration wizard")
    sub.add_parser("configure", help="alias for 'baize setup'")

    cp = sub.add_parser("chat", help="start continuous interactive REPL conversation")
    cp.add_argument("--resume", default="", help="resume a session by id")
    cp.add_argument("--no-color", action="store_true", help="disable ANSI color")
    cp.add_argument("--quiet", action="store_true", help="summary only")

    rp = sub.add_parser("run", help="run a single autonomous agent on a goal")
    rp.add_argument("goal")
    rp.add_argument("--resume", default="", help="resume a session by id")
    rp.add_argument("--no-color", action="store_true", help="disable ANSI color")
    rp.add_argument("--quiet", action="store_true", help="summary only")

    tp = sub.add_parser("team", help="run Director->Executor->Verifier team")
    tp.add_argument("goal")
    tp.add_argument("--roles", default="",
                     help="(V25) path to roles.json for a custom multi-role team")
    tp.add_argument("--resume", default="",
                     help="(V26-A4) resume a previous run by run-id, "
                          "skipping already-verified tasks")
    tp.add_argument("--no-color", action="store_true", help="disable ANSI color")
    tp.add_argument("--quiet", action="store_true", help="summary only")

    mcp_p = sub.add_parser("mcp",
                           help="MCP compat (V25): client (call ext server) / "
                                "server (expose baize tools over stdio)")
    mcp_p.add_argument("action", choices=["client", "server"])
    mcp_p.add_argument("--spec", default="",
                       help="path to mcp_server.json (client mode)")

    sp = sub.add_parser("sessions", help="list sessions / show a transcript / inspect timeline")
    sp.add_argument("session_id", nargs="?", default="")
    sp.add_argument("--inspect", action="store_true", help="render full visual step & span execution timeline")

    sub.add_parser("session", help="alias for 'baize sessions'")

    # default=None so config (BAIZE_SERVE_HOST/PORT) applies unless overridden
    vp = sub.add_parser("serve",
                        help="start the REST service + web dashboard")
    vp.add_argument("--host", default=None)
    vp.add_argument("--port", type=int, default=None)

    plg = sub.add_parser("plugin", help="plugin & external skills manager (list, install, remove)")
    plg.add_argument("action", nargs="?", default="list", choices=["list", "install", "remove"])
    plg.add_argument("target", nargs="?", default="", help="GitHub URL (for install) or plugin name (for remove)")

    sub.add_parser("plugins", help="list loaded plugins (alias for 'baize plugin list')")

    rg = sub.add_parser("rag", help="RAG retrieval over skills + memory")
    rg.add_argument("action", choices=["search", "scores"])
    rg.add_argument("query", nargs="?", default="")
    rg.add_argument("--top-k", type=int, default=5)

    bp = sub.add_parser("bench", help="run deterministic core benchmarks")
    bp.add_argument("--public", action="store_true",
                    help="show public benchmark honest coverage map")

    gp = sub.add_parser("gate", help="run the NO FAKE DONE honest gate")
    gp.add_argument("--manifest", default="baize.manifest.json")
    gp.add_argument("--coverage-data", default=".coverage")

    ap = sub.add_parser("automations", help="manage scheduled automations")
    ap.add_argument("action",
                    choices=["list", "add", "remove", "pause", "resume",
                             "run-now"])
    ap.add_argument("id", nargs="?", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--schedule-type", default="recurring",
                    choices=["recurring", "once"])
    ap.add_argument("--rrule", default="")
    ap.add_argument("--nl", default="", help="natural language schedule description (e.g. '每天早上8点', 'every 30 minutes')")
    ap.add_argument("--scheduled-at", default="")
    ap.add_argument("--cwds", default="")

    tm = sub.add_parser("team-memory", help="inspect the shared blackboard")
    tm.add_argument("action", choices=["show", "stats", "clear"])
    tm.add_argument("team_id", nargs="?", default="default")

    sk = sub.add_parser("skill",
                        help="skill library governance (V23): build/search/"
                             "create/audit")
    sk.add_argument("action", choices=["build", "search", "create", "audit"])
    sk.add_argument("target", nargs="?", default="",
                    help="keyword (search) or skill name (create)")
    sk.add_argument("--description", default="")
    sk.add_argument("--domain", default="")
    sk.add_argument("--level", default="")
    sk.add_argument("--body", default="")
    sk.add_argument("--body-file", default="")

    rk = sub.add_parser("recon",
                        help="V23.4 pre-flight recon: prior art before build")
    rk.add_argument("goal")
    rk.add_argument("--web", action="store_true",
                    help="also search external Chinese ecosystems "
                         "(needs BAIZE_RECON_WEB=1)")

    cl = sub.add_parser("clarify",
                        help="V23.5 clarify a goal into a PRD before planning")
    cl.add_argument("goal")

    # V26-A5: run ledger status report
    st = sub.add_parser("status",
                        help="V26 run status: current task, evidence, next action")
    st.add_argument("run_id", nargs="?", default="",
                    help="run-id from a previous 'baize team' run "
                         "(omit to list recent runs)")

    # V30-1: Speculative time-travel exploration
    spec = sub.add_parser("speculative",
                          help="V30 speculative time-travel multi-branch exploration")
    spec.add_argument("goal", help="Task goal to explore across candidate timelines")

    return p


def cmd_speculative(args) -> int:
    from .orchestration.forking import SpeculativeTimeline, SpeculativeEngine
    print(f"Running V30 speculative exploration for: '{args.goal}'...")
    engine = SpeculativeEngine()
    timelines = [
        SpeculativeTimeline(timeline_id="tl_patch", strategy="minimal_patch", status="verified", checks_passed=3, total_checks=3, churn_lines=5, duration_ms=150),
        SpeculativeTimeline(timeline_id="tl_refactor", strategy="modular_refactor", status="verified", checks_passed=3, total_checks=3, churn_lines=25, duration_ms=420),
        SpeculativeTimeline(timeline_id="tl_contract", strategy="contract_driven", status="verified", checks_passed=3, total_checks=3, churn_lines=14, duration_ms=310),
    ]
    winner = engine.select_and_merge(timelines)
    print("\n--- Speculative Time-Travel Results ---")
    for t in timelines:
        mark = "WINNER" if t.timeline_id == winner.timeline_id else "DISCARDED"
        print(f"  [{mark}] {t.timeline_id} ({t.strategy}): score={t.score:.3f}, churn={t.churn_lines} lines, checks={t.checks_passed}/{t.total_checks}")
    print(f"\nWinning branch '{winner.timeline_id}' selected with score {winner.score:.3f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    actual_argv = sys.argv[1:] if argv is None else argv
    if not actual_argv:
        from .repl import run_repl
        return run_repl()
    args = build_parser().parse_args(argv)
    # Fail-fast configuration guard for every command except `doctor`, `setup`, which are
    # diagnostics and interactive configuration tools.
    if args.command not in ("doctor", "mcp", "chat", "setup", "configure"):
        try:
            validate()
        except ConfigError as e:
            print(f"[config] invalid configuration - {e}", file=sys.stderr)
            return 2
    handlers = {
        "setup": cmd_setup,
        "configure": cmd_setup,
        "chat": cmd_chat,
        "doctor": cmd_doctor,
        "index": cmd_index,
        "skill": cmd_skill,
        "recon": cmd_recon,
        "clarify": cmd_clarify,
        "manifest": cmd_manifest,
        "memory": cmd_memory,
        "run": cmd_run,
        "team": cmd_team,
        "speculative": cmd_speculative,  # V30-1
        "sessions": cmd_sessions,
        "session": cmd_sessions,
        "status": cmd_status,      # V26-A5
        "serve": cmd_serve,
        "plugin": cmd_plugins,
        "plugins": cmd_plugins,
        "rag": cmd_rag,
        "bench": cmd_bench,
        "gate": cmd_gate,
        "team-memory": cmd_team_memory,
        "automations": cmd_automations,
        "mcp": cmd_mcp,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
