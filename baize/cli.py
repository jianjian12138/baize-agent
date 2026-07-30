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
    python -m baize bench
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from . import doctor as doctor_mod
from . import manifest as manifest_mod
from . import memory as memory_mod
from . import serve as serve_mod
from . import skill_index
from .agent import Agent, Session
from .llm import LLMClient
from .orchestrator import Orchestrator
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


def cmd_bench(_args) -> int:
    from . import bench
    report = bench.run_all()
    for c in report["cases"]:
        mark = "PASS" if c["ok"] else "FAIL"
        print(f"[{mark}] {c['name']:<8} {c['ms']:>7.1f} ms  {c['detail']}")
    print(f"{report['passed']}/{report['total']} benchmarks passed")
    return 0 if report["all_ok"] else 1


def _make_ui(args) -> ProgressUI:
    """Build the progress renderer honoring --no-color / --quiet."""
    return ProgressUI(color=False if getattr(args, "no_color", False) else None,
                      verbose=not getattr(args, "quiet", False))


def cmd_run(args) -> int:
    client = LLMClient()
    if not client.configured:
        print("model endpoint not configured - set BAIZE_MODEL_BASE_URL / "
              "BAIZE_MODEL_NAME (and API key) in .env")
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
    orch = Orchestrator(client=client, on_event=ui.event)
    res = orch.run(args.goal)
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
    print(f"sessions: {len(res.session_ids)}")
    return 0 if res.success else 1


def cmd_sessions(args) -> int:
    sessions = Session.list_sessions()
    if not sessions:
        print("no sessions yet")
        return 0
    if args.session_id:
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


def cmd_serve(args) -> int:
    serve_mod.serve(host=args.host, port=args.port)
    return 0


def cmd_plugins(args) -> int:
    n = registry.discover()
    if not registry.plugins:
        print(f"0 plugins loaded (discover scanned {n} candidate file(s))")
        return 0
    print(f"{len(registry.plugins)} plugin(s) loaded:")
    for p in registry.plugins:
        print(f"  - {p.name}")
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
                     choices=["log", "remember", "recall", "stats", "compress"])
    mem.add_argument("text", nargs="?", default="")
    mem.add_argument("--tags", default="")
    mem.add_argument("--days", type=int, default=0,
                     help="compress: distill logs older than N days (default: config)")

    rp = sub.add_parser("run", help="run a single autonomous agent on a goal")
    rp.add_argument("goal")
    rp.add_argument("--resume", default="", help="resume a session by id")
    rp.add_argument("--no-color", action="store_true", help="disable ANSI color")
    rp.add_argument("--quiet", action="store_true", help="summary only")

    tp = sub.add_parser("team", help="run Director->Executor->Verifier team")
    tp.add_argument("goal")
    tp.add_argument("--no-color", action="store_true", help="disable ANSI color")
    tp.add_argument("--quiet", action="store_true", help="summary only")

    sp = sub.add_parser("sessions", help="list sessions / show a transcript")
    sp.add_argument("session_id", nargs="?", default="")

    # default=None so config (BAIZE_SERVE_HOST/PORT) applies unless overridden
    vp = sub.add_parser("serve",
                        help="start the REST service + web dashboard")
    vp.add_argument("--host", default=None)
    vp.add_argument("--port", type=int, default=None)

    pp = sub.add_parser("plugins", help="list loaded plugins")

    rg = sub.add_parser("rag", help="RAG retrieval over skills + memory")
    rg.add_argument("action", choices=["search", "scores"])
    rg.add_argument("query", nargs="?", default="")
    rg.add_argument("--top-k", type=int, default=5)

    sub.add_parser("bench", help="run deterministic core benchmarks")

    tm = sub.add_parser("team-memory", help="inspect the shared blackboard")
    tm.add_argument("action", choices=["show", "stats", "clear"])
    tm.add_argument("team_id", nargs="?", default="default")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "doctor": cmd_doctor,
        "index": cmd_index,
        "manifest": cmd_manifest,
        "memory": cmd_memory,
        "run": cmd_run,
        "team": cmd_team,
        "sessions": cmd_sessions,
        "serve": cmd_serve,
        "plugins": cmd_plugins,
        "rag": cmd_rag,
        "bench": cmd_bench,
        "team-memory": cmd_team_memory,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
