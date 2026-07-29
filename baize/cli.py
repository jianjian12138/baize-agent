"""Baize CLI entry point.

    python -m baize doctor
    python -m baize index build
    python -m baize index search <keyword>
    python -m baize manifest validate <path>
    python -m baize memory log "text" [--tags a,b]
    python -m baize memory remember "text"
    python -m baize memory recall <keyword>
    python -m baize memory stats
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
from . import skill_index
from .agent import Agent, Session
from .llm import LLMClient
from .orchestrator import Orchestrator


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
    print("unknown memory action")
    return 2


def _print_event(kind: str, detail: str) -> None:
    print(f"  [{kind}] {detail}")


def cmd_run(args) -> int:
    client = LLMClient()
    if not client.configured:
        print("model endpoint not configured - set BAIZE_MODEL_BASE_URL / "
              "BAIZE_MODEL_NAME (and API key) in .env")
        return 2
    session = Session(session_id=args.resume) if args.resume else None
    agent = Agent(role="executor", client=client, session=session,
                  on_event=_print_event)
    print(f"session: {agent.session.id}")
    res = agent.run(args.goal)
    print("-" * 60)
    print(res.final_text)
    print(f"({res.stopped_reason}, steps={res.steps}, "
          f"tool_calls={res.tool_calls}, session={res.session_id})")
    return 0 if res.stopped_reason == "final" else 1


def cmd_team(args) -> int:
    client = LLMClient()
    if not client.configured:
        print("model endpoint not configured - set BAIZE_MODEL_BASE_URL / "
              "BAIZE_MODEL_NAME (and API key) in .env")
        return 2
    orch = Orchestrator(client=client, on_event=_print_event)
    res = orch.run(args.goal)
    print("=" * 60)
    for r in res.reports:
        mark = "PASS" if r.verdict == "pass" else r.verdict.upper()
        retry = " (retried)" if r.retried else ""
        print(f"[{mark}]{retry} #{r.task_id} {r.task}")
        if r.issues:
            for issue in r.issues:
                print(f"    issue: {issue}")
    print(f"overall: {'SUCCESS' if res.success else 'FAILED'} "
          f"({len(res.session_ids)} sessions)")
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
    mem.add_argument("action", choices=["log", "remember", "recall", "stats"])
    mem.add_argument("text", nargs="?", default="")
    mem.add_argument("--tags", default="")

    rp = sub.add_parser("run", help="run a single autonomous agent on a goal")
    rp.add_argument("goal")
    rp.add_argument("--resume", default="", help="resume a session by id")

    tp = sub.add_parser("team", help="run Director->Executor->Verifier team")
    tp.add_argument("goal")

    sp = sub.add_parser("sessions", help="list sessions / show a transcript")
    sp.add_argument("session_id", nargs="?", default="")

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
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
