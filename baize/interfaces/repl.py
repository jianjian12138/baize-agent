"""Baize Agent — Interactive REPL / TUI Chat Terminal (stdlib, zero dependencies).

Provides a continuous interactive CLI experience ahead of hermes-agent / codex / pi.
Features:
- Multi-turn conversation loop within a persistent or newly created Session
- Full slash-command system (/help, /reset, /skills, /memory, /status, /model, /cost, /fork, /rewind, /paste, /resume, /history, /exit)
- Real-time ProgressUI streaming events for tool execution and thinking phases
- Smart `@` file/snippet context ingestion (`@file.py` or `@file.py:10-30`)
- Multi-line & paste mode (triple quotes or /paste)
- Time-travel session forking & step rewinding (`/fork`, `/rewind`)
- Real-time Token & Cost accounting dashboard (`/cost`)
- Instant model hot-switching (`/model <name>`)
- Graceful double-tap Ctrl+C interruption handling
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

from .. import __version__
from ..core.agent import Agent, Session, AgentResult
from ..core.config import ROOT, load_config
from ..core.llm import LLMClient
from .ui import ProgressUI
from ..core.config import get_logger

log = get_logger("repl")

BANNER = r"""
  ██████╗  █████╗ ██╗███████╗███████╗
  ██╔══██╗██╔══██╗██║╚══███╔╝██╔════╝
  ██████╔╝███████║██║  ███╔╝ █████╗  
  ██╔══██╗██╔══██╗██║ ███╔╝  ██╔══╝  
  ██████╔╝██║  ██║██║███████╗███████╗
  ╚═════╝ ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝
"""

HELP_TEXT = """
Available Slash Commands:
  /help, /?            Show this help message
  /reset, /new         Start a brand new session
  /history, /list      Show recent 10 sessions
  /resume <id>         Switch to and resume an existing session
  /fork [name]         Fork current conversation branch into a new parallel session
  /tree                Display dual-axis session & checkpoint tree
  /rewind [N|id]       Rewind last N turns or jump to checkpoint node (--code restores Git files)
  /profile [mode]      View or switch tool profile (minimal / tiered / full)
  /approval [mode]     View or switch approval policy (tiered / auto / strict)
  /reload [plugin]     Hot-reload plugin with AST + smoke gate & rollback
  /bg [list|output|stop] Manage background shell processes
  /budget [usd|reset]  Inspect session cost/cache ledger or set hard USD cap (V42)
  /worktree [list|cleanup] Inspect or clean up isolated parallel Git worktrees (V42)
  /search <query>      Run persistent SQLite FTS5 + Embedding hybrid search (V42)
  /cost                Inspect session token usage and estimated cost
  /trace               Inspect step-by-step tool execution timeline & latency
  /model [name]        View or instantly switch active LLM model
  /setup, /config      Launch interactive LLM configuration wizard
  /paste               Enter multi-line code/text paste mode (type /end to submit)
  /skills [keyword]    Search or list available skill library entries
  /memory [query]      Search persistent memory records
  /status              Show current session stats (steps, tools, messages)
  /clear               Clear the terminal screen
  /quit, /exit         Exit the interactive REPL

Pro Tips:
  • Reference code with @filepath (e.g. "Fix bug in @baize/agent.py:10-30")
  • Paste multiline code using triple quotes (\"\"\" ... \"\"\")
  • Press Ctrl+C twice within 2s to exit anytime
"""


def _extract_at_files(text: str, root_dir: Path) -> tuple[str, list[dict]]:
    """Parse `@path/to/file` or `@path/to/file:10-30` syntax from user input.

    Reads file content safely and generates structured context snippets.
    Returns: (cleaned_text, list_of_attached_files)
    """
    pattern = r'@([A-Za-z0-9_\-./\\]+(?::\d+(?:-\d+)?)?)'
    matches = re.findall(pattern, text)
    if not matches:
        return text, []

    attached = []
    seen = set()

    for m in matches:
        if m in seen:
            continue
        seen.add(m)

        file_part, _, range_part = m.partition(":")
        rel_path = file_part.strip()
        target_path = (root_dir / rel_path).resolve()

        # Workspace sandbox boundary check
        try:
            target_path.relative_to(root_dir.resolve())
        except ValueError:
            continue

        if not target_path.exists() or not target_path.is_file():
            continue

        try:
            content = target_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            total_lines = len(lines)

            if range_part and "-" in range_part:
                start_s, _, end_s = range_part.partition("-")
                start_l = max(1, int(start_s)) if start_s.isdigit() else 1
                end_l = min(total_lines, int(end_s)) if end_s.isdigit() else total_lines
                selected_lines = lines[start_l - 1:end_l]
                snippet = "\n".join(selected_lines)
                header = f"{rel_path} (lines {start_l}-{end_l})"
            elif range_part and range_part.isdigit():
                idx = int(range_part)
                snippet = lines[idx - 1] if 1 <= idx <= total_lines else ""
                header = f"{rel_path} (line {idx})"
            else:
                snippet = content
                header = f"{rel_path} ({total_lines} lines)"

            attached.append({
                "header": header,
                "path": rel_path,
                "snippet": snippet,
            })
        except Exception:
            continue

    return text, attached


def _format_user_friendly_error(err_text: str) -> str:
    low = err_text.lower()
    if "unknown url type" in low or "invalid url" in low or "nonnumeric port" in low or "nodename nor servname" in low:
        return "大模型服务连接失败：接口 Base URL 格式无效（必须以 http:// 或 https:// 开头）。请检查配置或输入 /setup 重新设置。"
    if "401" in err_text or "unauthorized" in low:
        return "大模型身份认证失败：API Key 无效或未授权。请检查 API Key 或输入 /setup 重新设置。"
    if "404" in err_text or "not found" in low:
        return "大模型接口未找到 (HTTP 404)：模型名称或端点路径不存在。请检查模型名称或输入 /setup 重新设置。"
    if "429" in err_text or "rate limit" in low or "quota" in low:
        return "大模型请求频次超限或账户余额不足 (HTTP 429)。请稍后重试或检查账户额度。"
    if "connection refused" in low or "actively refused" in low or "10061" in err_text:
        return "大模型连接被拒绝：无法连接到目标服务（若使用本地 Ollama 请确保已运行 ollama serve）。"
    if "timed out" in low or "timeout" in low:
        return "大模型请求超时：网络连接缓慢或服务无响应，请检查网络。"

    cleaned = re.sub(r"https?://[^\s\'\",]+", "<api-endpoint>", err_text)
    return f"{cleaned}（可输入 /setup 重新设置）"


class BaizeREPL:
    """Continuous multi-turn interactive conversational REPL for Baize Agent."""

    def __init__(
        self,
        session_id: str = "",
        no_color: bool = False,
        quiet: bool = False,
        tool_profile: str = "",
        approval_mode: str = "",
    ):
        self.cfg = load_config()
        self.client = LLMClient(self.cfg)
        self.ui = ProgressUI(color=False if no_color else None, verbose=not quiet)
        self.no_color = no_color
        self.session_id = session_id
        self.session: Session | None = None
        self.agent: Agent | None = None
        self.tool_profile = (tool_profile or self.cfg.get("BAIZE_TOOL_PROFILE") or "tiered").strip().lower()
        self.approval_mode = (approval_mode or self.cfg.get("BAIZE_APPROVAL_MODE") or "tiered").strip().lower()
        from .approval import TieredApprovalPolicy
        self.approval_policy = TieredApprovalPolicy(mode=self.approval_mode)
        self.running = True

    def _make_approval_cb(self):
        # Only prompt interactively on a real TTY unless user explicitly chose strict/tiered with custom stdin
        if not sys.stdin.isatty():
            return None
        from .approval import make_terminal_approval_callback
        ws = self.cfg.get("BAIZE_WORKSPACE_DIR", ".")
        return make_terminal_approval_callback(self.approval_policy, workspace=ws)

    def _init_agent(self) -> None:
        if self.session is None:
            if self.session_id:
                try:
                    self.session = Session(session_id=self.session_id, cfg=self.cfg)
                except Exception:
                    self.session = Session(cfg=self.cfg)
                    self.session_id = self.session.id
            else:
                self.session = Session(cfg=self.cfg)
                self.session_id = self.session.id

        self.agent = Agent(
            role="executor",
            client=self.client,
            session=self.session,
            on_event=self.ui.event,
            on_token=lambda tok: sys.stdout.write(tok) or sys.stdout.flush(),
            approval_callback=self._make_approval_cb(),
            tool_profile=self.tool_profile,
        )

    def _print_status_bar(self) -> None:
        if not self.agent:
            return
        from .approval import format_status_bar
        from ..execution.bg_proc import get_bg_manager
        st = self.agent.context_status()
        models = getattr(self.client, "models", [])
        model_name = models[0].name if models else (self.cfg.get("BAIZE_MODEL_NAME") or "unconfigured")
        from ..core.cost_ledger import get_cost_ledger
        bstat = get_cost_ledger(self.cfg).check_budget(self.session.id if self.session else "default")
        bar = format_status_bar(
            model=model_name,
            profile=st.get("profile", self.tool_profile),
            active_tools=int(st.get("active_tools", 0)),
            context_ratio=float(st.get("context_ratio", 0.0)),
            cache_hit_ratio=float(bstat.cache_hit_ratio),
            bg_procs=get_bg_manager().active_count(),
            color=not self.no_color,
        )
        print(bar)

    def print_banner(self) -> None:
        p = self.ui.p
        print(p.paint("cyan", BANNER))
        print(p.paint("bold", f"  Baize Agent Autonomous Engine — V{__version__}"))
        print(p.paint("dim", "  Pure Python stdlib · Zero dependencies · NO FAKE DONE verified"))
        if self.client.configured:
            models_info = ", ".join(m.name for m in getattr(self.client, "models", [])) or "configured"
            print(p.paint("green", f"  [Model] {models_info}"))
        else:
            print(p.paint("yellow", "  [Model] WARNING: Endpoint not configured. Set BAIZE_MODEL_BASE_URL & BAIZE_MODEL_API_KEY in .env"))
        print(p.paint("dim", "  Type /help for slash commands, or type your goal to begin.\n"))

    def handle_slash(self, cmd_line: str) -> None:
        p = self.ui.p
        parts = cmd_line.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("/help", "/?"):
            print(p.paint("cyan", HELP_TEXT))
            return

        if cmd in ("/reset", "/new"):
            self.session = Session(cfg=self.cfg)
            self.session_id = self.session.id
            self._init_agent()
            print(p.paint("green", f"✓ Started new session: {self.session_id}"))
            return

        if cmd in ("/history", "/list"):
            sessions = Session.list_sessions()
            if not sessions:
                print(p.paint("dim", "No previous sessions found."))
                return
            print(p.paint("bold", "\nRecent Sessions:"))
            for s in sessions[:10]:
                curr = " (current)" if self.session and s["id"] == self.session.id else ""
                print(f"  • {s['id']}  events={s['events']}  {s['mtime']}{curr}")
            print()
            return

        if cmd == "/resume":
            if not arg:
                print(p.paint("yellow", "Usage: /resume <session_id>"))
                return
            try:
                self.session = Session(session_id=arg, cfg=self.cfg)
                self.session_id = self.session.id
                self._init_agent()
                print(p.paint("green", f"✓ Resumed session: {self.session_id} ({len(self.session.messages)} messages)"))
            except Exception as e:
                print(p.paint("red", f"Failed to resume session '{arg}': {e}"))
            return

        if cmd == "/fork":
            if not self.session:
                print(p.paint("dim", "No active session to fork."))
                return
            target_id = arg.strip() or f"{self.session.id}_fork_{int(time.time()) % 10000}"
            new_session = Session(session_id=target_id, cfg=self.cfg)
            # Copy all message events over
            for m in self.session.messages:
                new_session.append(m)
            self.session = new_session
            self.session_id = target_id
            self._init_agent()
            print(p.paint("green", f"✓ Parallel session forked: {self.session_id} ({len(self.session.messages)} messages)"))
            return

        if cmd == "/tree":
            from ..core.sessions import format_session_tree
            print(p.paint("bold", "\nSession & Checkpoint Tree:"))
            print(format_session_tree(cfg=self.cfg))
            print()
            return

        if cmd == "/rewind":
            if not self.session:
                print(p.paint("dim", "No active session to rewind."))
                return
            tokens = arg.split()
            restore_code = "--code" in tokens
            non_flag = [t for t in tokens if t != "--code"]
            target = non_flag[0] if non_flag else ""
            # Dual-axis checkpoint node rewind when target is a non-numeric node_id
            if target and not target.isdigit():
                from ..core.sessions import rewind_session
                ws = self.cfg.get("BAIZE_WORKSPACE_DIR", ".")
                res = rewind_session(
                    self.session.id,
                    target,
                    restore_code=restore_code,
                    workspace=ws,
                    cfg=self.cfg,
                )
                if not res.get("ok"):
                    print(p.paint("red", f"Rewind failed: {res.get('error', res)}"))
                    return
                new_sid = res.get("new_session_id") or self.session.id
                self.session_id = new_sid
                self.session = Session(session_id=new_sid, cfg=self.cfg)
                self._init_agent()
                code_note = " + Git workspace restored" if res.get("code_restored") else ""
                print(p.paint("green", f"✓ Rewound to node {target}{code_note}. Active messages: {len(self.session.messages)}"))
                return

            if not self.session.messages:
                print(p.paint("dim", "No messages in active session to rewind."))
                return
            turns = int(target) if target.isdigit() and int(target) > 0 else 1
            user_indices = [i for i, m in enumerate(self.session.messages) if m.get("role") == "user"]
            if not user_indices:
                self.session.messages.clear()
            else:
                cutoff_turn = max(0, len(user_indices) - turns)
                cutoff_idx = user_indices[cutoff_turn] if cutoff_turn < len(user_indices) else 0
                self.session.messages = self.session.messages[:cutoff_idx]

            s_file = self.session.file
            if s_file.exists():
                lines = [json.dumps(m, ensure_ascii=False) for m in self.session.messages]
                s_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

            self._init_agent()
            print(p.paint("green", f"✓ Rewound {turns} turn(s). Active session now has {len(self.session.messages)} messages."))
            return

        if cmd == "/profile":
            mode = arg.strip().lower()
            if mode in ("minimal", "tiered", "full"):
                self.tool_profile = mode
                os.environ["BAIZE_TOOL_PROFILE"] = mode
                self._init_agent()
                st = self.agent.context_status() if self.agent else {}
                print(p.paint("green", f"✓ Switched tool profile to '{mode}' "
                              f"(active={st.get('active_tools', 0)}/{st.get('total_tools', 0)}, "
                              f"est_schema_tokens={st.get('schema_tokens', 0)})"))
                return
            st = self.agent.context_status() if self.agent else {}
            print(p.paint("bold", f"\nTool Profile: {self.tool_profile}"))
            print(f"  • Active tools:   {st.get('active_tools', 0)} / {st.get('total_tools', 0)}")
            print(f"  • Schema tokens:  ~{st.get('schema_tokens', 0)}")
            print(p.paint("dim", "  (Use '/profile minimal|tiered|full' to switch)\n"))
            return

        if cmd == "/approval":
            mode = arg.strip().lower()
            if mode in ("tiered", "auto", "strict"):
                self.approval_mode = mode
                from .approval import TieredApprovalPolicy
                self.approval_policy = TieredApprovalPolicy(mode=mode)
                self._init_agent()
                print(p.paint("green", f"✓ Switched approval policy to '{mode}'"))
                return
            print(p.paint("bold", f"\nApproval Policy: {self.approval_mode}"))
            print(p.paint("dim", "  (Use '/approval tiered|auto|strict' to switch)\n"))
            return

        if cmd == "/reload":
            from ..core.plugin_lifecycle import get_plugin_manager
            mgr = get_plugin_manager()
            target = arg.strip()
            if not target:
                loaded = mgr.list_plugins()
                if not loaded:
                    print(p.paint("dim", "No hot-reloadable plugins loaded. Use '/reload <plugin_path_or_id>'."))
                    return
                print(p.paint("bold", f"\nLoaded Hot-Reload Plugins ({len(loaded)}):"))
                for pl in loaded:
                    print(f"  • {pl['plugin_id']}  tools={pl.get('tools', [])}  path={pl.get('source_path', '')}")
                print()
                return
            if Path(target).exists():
                res = mgr.load_plugin(target)
            else:
                res = mgr.reload_plugin(target)
            if res.get("ok"):
                print(p.paint("green", f"✓ Plugin '{res.get('plugin_id')}' reloaded cleanly "
                              f"(tools={res.get('tools', [])})"))
            else:
                print(p.paint("red", f"✗ Plugin reload failed (previous state preserved): {res.get('error')}"))
            return

        if cmd == "/bg":
            from ..execution.bg_proc import get_bg_manager
            mgr = get_bg_manager()
            parts_bg = arg.split(maxsplit=1)
            sub = parts_bg[0].lower() if parts_bg else "list"
            sub_arg = parts_bg[1].strip() if len(parts_bg) > 1 else ""
            if sub == "list":
                procs = mgr.list_procs()
                if not procs:
                    print(p.paint("dim", "No background processes."))
                    return
                print(p.paint("bold", f"\nBackground Processes ({len(procs)}):"))
                for pr in procs:
                    print(f"  • {pr['proc_id']}  [{pr['status']}]  pid={pr.get('pid')}  cmd={pr['command'][:60]}")
                print()
                return
            if sub == "output" and sub_arg:
                res = mgr.read_output(sub_arg)
                print(json.dumps(res, indent=2, ensure_ascii=False))
                return
            if sub == "stop" and sub_arg:
                res = mgr.stop(sub_arg)
                print(p.paint("green" if res.get("ok") else "red", json.dumps(res, ensure_ascii=False)))
                return
            print(p.paint("yellow", "Usage: /bg [list | output <proc_id> | stop <proc_id>]"))
            return

        if cmd == "/budget":
            from ..core.cost_ledger import get_cost_ledger
            ledger = get_cost_ledger(self.cfg)
            sid = self.session.id if self.session else "default"
            sub = arg.strip().lower()
            if sub == "reset":
                n = ledger.reset_session(sid)
                print(p.paint("green", f"✓ Reset cost ledger for session {sid} ({n} records cleared)."))
                return
            if sub:
                try:
                    cap = float(sub)
                    if cap < 0:
                        raise ValueError("negative")
                    os.environ["BAIZE_MAX_SESSION_USD"] = str(cap)
                    self.cfg = load_config()
                    print(p.paint("green", f"✓ Session hard USD budget set to ${cap:.4f} (0 = unlimited)."))
                    return
                except ValueError:
                    print(p.paint("yellow", "Usage: /budget [max_usd | reset]"))
                    return
            st = ledger.check_budget(sid)
            print(p.paint("bold", f"\nSession Cost & Cache Ledger ({sid}):"))
            print(f"  • Prompt / Cached / Output: {st.prompt_tokens:,} / {st.cached_tokens:,} / {st.completion_tokens:,}")
            print(f"  • Cache hit ratio:          {st.cache_hit_ratio * 100:.1f}%")
            print(f"  • Estimated USD:            ${st.estimated_usd:.6f}")
            cap_str = f"${st.max_usd:.4f} ({st.usd_ratio*100:.1f}%)" if st.max_usd > 0 else "unlimited"
            print(f"  • Hard USD budget cap:      {cap_str}\n")
            return

        if cmd == "/worktree":
            from ..execution.worktree import GitWorktreePool
            pool = GitWorktreePool(self.cfg.get("BAIZE_WORKSPACE_DIR", "."))
            sub = (arg.strip().lower() or "list")
            if sub == "cleanup":
                res = pool.cleanup_all()
                print(p.paint("green", f"✓ Cleaned {res.get('count', 0)} worktree(s)."))
                return
            wts = pool.list_worktrees()
            if not wts:
                print(p.paint("dim", "No active or recorded Git worktrees."))
                return
            print(p.paint("bold", f"\nGit Worktrees ({len(wts)}):"))
            for w in wts[:15]:
                print(f"  • {w['worktree_id']} [{w['status']}] branch={w['branch_name']} files={len(w.get('changed_files') or [])}")
            print()
            return

        if cmd == "/search":
            if not arg.strip():
                print(p.paint("yellow", "Usage: /search <query>"))
                return
            from ..knowledge.hybrid_index import HybridSearchIndex
            idx = HybridSearchIndex(cfg=self.cfg)
            if idx.stats()["total_docs"] == 0:
                idx.index_workspace(self.cfg.get("BAIZE_WORKSPACE_DIR", "."))
            hits = idx.search(arg.strip(), mode="hybrid", limit=6)
            if not hits:
                print(p.paint("dim", f"No hybrid matches for '{arg.strip()}'."))
                return
            print(p.paint("bold", f"\nHybrid Search Results ({len(hits)}):"))
            for h in hits:
                print(f"  • [{h.source} {h.score:.4f}] {h.title} — {h.snippet[:90]}")
            print()
            return

        if cmd == "/cost":
            if not self.session:
                print(p.paint("dim", "No active session."))
                return
            total_chars = sum(len(str(m.get("content") or "")) for m in self.session.messages)
            est_tokens = total_chars // 4
            tool_turns = sum(1 for m in self.session.messages if m.get("role") == "tool")
            llm_turns = sum(1 for m in self.session.messages if m.get("role") == "assistant")
            est_cost_usd = (est_tokens / 1_000_000) * 0.14  # DeepSeek average standard rate
            print(p.paint("bold", f"\nSession Resource & Cost Dashboard ({self.session.id}):"))
            print(f"  • Total Messages:    {len(self.session.messages)}")
            print(f"  • LLM Responses:     {llm_turns}")
            print(f"  • Tool Executions:   {tool_turns}")
            print(f"  • Est. Total Tokens: ~{est_tokens:,} tokens ({total_chars:,} chars)")
            print(f"  • Est. Cost (USD):   ~${est_cost_usd:.5f} (DeepSeek baseline)\n")
            return

        if cmd == "/trace":
            from .ui import render_session, find_session_file
            sid = arg.strip() or (self.session.id if self.session else "")
            if not sid:
                print(p.paint("dim", "No active session to trace."))
                return
            s_file = find_session_file(sid, self.cfg)
            if not s_file:
                print(p.paint("red", f"Session file not found for: {sid}"))
                return
            print(p.paint("bold", f"\nTrace Execution Timeline ({sid}):\n"))
            print(render_session(s_file))
            print()
            return

        if cmd == "/model":
            if arg:
                # Hot-switch model name
                os.environ["BAIZE_MODEL_NAME"] = arg.strip()
                self.cfg = load_config()
                self.client = LLMClient(self.cfg)
                self._init_agent()
                print(p.paint("green", f"✓ Switched active model to: {arg.strip()}\n"))
                return

            print(p.paint("bold", "\nLLM Configuration:"))
            print(f"  • Configured: {self.client.configured}")
            models = getattr(self.client, "models", [])
            for m in models:
                masked_key = (m.api_key[:6] + "..." + m.api_key[-4:]) if len(m.api_key) > 10 else ("(set)" if m.api_key else "(none)")
                print(f"  • Model: {m.name} | URL: {m.base_url} | Provider: {m.provider} | Key: {masked_key}")
            print(p.paint("dim", "  (Use '/model <name>' to switch active model instantly)\n"))
            return

        if cmd == "/paste":
            print(p.paint("cyan", "--- Multi-line Paste Mode (type '/end' on a new line to submit) ---"))
            lines = []
            while True:
                try:
                    l = input().rstrip("\r\n")
                    if l.strip() == "/end":
                        break
                    lines.append(l)
                except (KeyboardInterrupt, EOFError):
                    print(p.paint("dim", "\n[Paste mode cancelled]"))
                    return
            content = "\n".join(lines).strip()
            if content:
                self._execute_goal(content)
            return

        if cmd == "/skills":
            from ..knowledge import skills as skill_index
            kw = arg.strip()
            hits = skill_index.search(kw, limit=10)
            if not hits:
                print(p.paint("dim", f"No skills found matching '{kw}'" if kw else "No skills indexed."))
                return
            print(p.paint("bold", f"\nAvailable Skills ({len(hits)} hits):"))
            for h in hits:
                print(f"  • {p.paint('cyan', h.get('name', ''))} [{h.get('source', '')}] - {h.get('description', '')[:70]}")
            print()
            return

        if cmd == "/memory":
            from ..knowledge import memory as memory_mod
            store = memory_mod.BoundedMemoryStore(self.cfg)
            if not arg:
                stats = memory_mod.stats()
                bs = store.stats()
                print(p.paint("bold", "\nMemory Stats:"))
                print(f"  • Notes size: {stats.get('notes_bytes', 0)} bytes ({stats.get('notes_lines', 0)} lines)")
                print(f"  • Log entries: {stats.get('log_entries', 0)}")
                print(f"  • Total storage: {stats.get('total_bytes', 0)} bytes")
                print(f"  • Bounded MEMORY.md: {bs['memory']['chars']}/{bs['memory']['limit']} chars")
                print(f"  • Bounded USER.md:   {bs['user']['chars']}/{bs['user']['limit']} chars\n")
                return
            sub_m = arg.split(maxsplit=1)
            action = sub_m[0].lower()
            rest_m = sub_m[1].strip() if len(sub_m) > 1 else ""
            if action == "show":
                print(store.render_prefix_snapshot() or "(Bounded MEMORY.md / USER.md are empty)")
                return
            if action == "add" and rest_m:
                res = store.update("memory", "add", rest_m)
                print(p.paint("green" if res.get("ok") else "red", json.dumps(res, ensure_ascii=False)))
                return
            if action == "user" and rest_m:
                res = store.update("user", "add", rest_m)
                print(p.paint("green" if res.get("ok") else "red", json.dumps(res, ensure_ascii=False)))
                return
            recs = memory_mod.recall(arg, limit=5)
            if not recs:
                print(p.paint("dim", f"No memory records found for '{arg}'."))
                return
            print(p.paint("bold", f"\nMemory Recall ({len(recs)} matches):"))
            for r in recs:
                tag_str = f" [{','.join(r.get('tags', []))}]" if r.get("tags") else ""
                print(f"  • {r.get('timestamp', '')[:19]}{tag_str}: {r.get('text', '')[:100]}")
            print()
            return

        if cmd == "/status":
            if not self.session:
                print(p.paint("dim", "No active session."))
                return
            print(p.paint("bold", f"\nCurrent Session: {self.session.id}"))
            print(f"  • Total messages: {len(self.session.messages)}")
            tool_turns = sum(1 for m in self.session.messages if m.get("role") == "tool")
            print(f"  • Tool observations recorded: {tool_turns}")
            print()
            return

        if cmd in ("/setup", "/config"):
            from .ui import run_setup_wizard
            success = run_setup_wizard()
            if success:
                self.cfg = load_config()
                self.client = LLMClient(self.cfg)
                self._init_agent()
                print(p.paint("green", "✓ LLM 配置已热更新并重新加载！\n"))
            return

        if cmd == "/clear":
            print("\033[2J\033[H", end="")
            self.print_banner()
            return

        if cmd in ("/quit", "/exit"):
            print(p.paint("cyan", "Goodbye!"))
            self.running = False
            return

        print(p.paint("yellow", f"Unknown command: {cmd}. Type /help for available commands."))

    def _execute_goal(self, user_goal: str) -> None:
        p = self.ui.p
        if not self.client.configured:
            print(p.paint("red", "💡 未配置大模型端点。请输入 /setup 启动快速配置向导。\n"))
            return

        # 1. Check for @file and @image inclusions (V42 multimodal support)
        img_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        img_matches = re.findall(r'@([A-Za-z0-9_\-./\\]+\.(?:png|jpg|jpeg|webp|gif))', user_goal, re.I)
        attached_images: list[str] = []
        for im in img_matches:
            ip = (ROOT / im).resolve()
            if ip.is_file() and ip.suffix.lower() in img_exts:
                attached_images.append(str(ip))
                print(p.paint("cyan", f"  🖼 [Image Attached] {im}"))

        cleaned_goal, attached_files = _extract_at_files(user_goal, ROOT)
        attached_files = [f for f in attached_files if Path(f["path"]).suffix.lower() not in img_exts]
        final_prompt = user_goal

        if attached_files:
            context_blocks = []
            for f in attached_files:
                print(p.paint("cyan", f"  📎 [Context Ingested] {f['header']}"))
                context_blocks.append(f"### Context File: `{f['path']}`\n```\n{f['snippet']}\n```")
            final_prompt = f"{user_goal}\n\n" + "\n\n".join(context_blocks)

        # 2. Execute agent turn (with soft-interrupt steering & status bar)
        prompt_to_run = final_prompt
        images_to_send = attached_images or None
        while True:
            try:
                res = self.agent.run(prompt_to_run, images=images_to_send)
                images_to_send = None
                if res.stopped_reason == "error":
                    friendly = _format_user_friendly_error(res.final_text)
                    print(p.paint("red", f"\n❌ {friendly}\n"))
                else:
                    print(f"\n{res.final_text}\n")
                self.ui.summary(res)
                self._print_status_bar()
                print()
                break
            except KeyboardInterrupt:
                if self.agent is not None:
                    self.agent.request_interrupt()
                print(p.paint("yellow", "\n[Interrupted by user] Current execution paused."))
                if sys.stdin.isatty():
                    try:
                        steer_msg = input(p.paint("cyan", "  ↳ 输入新指令立即转向（直接回车停止本次任务）: ")).strip()
                    except (KeyboardInterrupt, EOFError):
                        steer_msg = ""
                    if steer_msg:
                        if self.agent is not None:
                            self.agent.steer(steer_msg)
                        prompt_to_run = steer_msg
                        continue
                break
            except Exception as e:
                print(p.paint("red", f"\nExecution error: {e}\n"))
                break

    def run(self) -> int:
        self.print_banner()
        self._init_agent()
        p = self.ui.p

        # Load command history
        hist_file = Path.home() / ".baize_history"
        try:
            import readline
            if hist_file.exists():
                readline.read_history_file(str(hist_file))
        except (ImportError, OSError):
            pass

        # Hermes-style first-run setup trigger
        if not self.client.configured and sys.stdin.isatty():
            try:
                ask = input(p.paint("bold", "  💡 未检测到大模型配置。是否现在启动快速配置向导？[Y/n]: ")).strip().lower()
                if ask in ("", "y", "yes"):
                    from .ui import run_setup_wizard
                    if run_setup_wizard():
                        self.cfg = load_config()
                        self.client = LLMClient(self.cfg)
                        self._init_agent()
                        print(p.paint("green", "✓ 配置成功，已连接大模型！\n"))
            except (KeyboardInterrupt, EOFError):
                print()

        last_interrupt_time = 0.0
        try:
            while self.running:
                try:
                    prompt_label = "baize-agent > "
                    user_input = input(p.paint("bold", prompt_label)).strip()
                    last_interrupt_time = 0.0
                except EOFError:
                    print(p.paint("cyan", "\nGoodbye!"))
                    break
                except KeyboardInterrupt:
                    now = time.time()
                    if now - last_interrupt_time < 2.0:
                        print(p.paint("cyan", "\nGoodbye!"))
                        break
                    last_interrupt_time = now
                    print(p.paint("dim", "\n(再次按 Ctrl+C 或输入 /quit 退出)"))
                    continue

                if not user_input:
                    continue

                # Check for triple quote multiline block
                if (user_input.startswith('"""') and not user_input.endswith('"""', 3)) or \
                   (user_input.startswith("'''") and not user_input.endswith("'''", 3)):
                    quote = '"""' if user_input.startswith('"""') else "'''"
                    lines = [user_input[3:]]
                    print(p.paint("dim", "... (multiline input, end with closing quotes) "))
                    while True:
                        try:
                            line = input(p.paint("dim", "... ")).rstrip("\r\n")
                            if line.endswith(quote):
                                lines.append(line[:-3])
                                break
                            lines.append(line)
                        except (KeyboardInterrupt, EOFError):
                            lines = []
                            break
                    user_input = "\n".join(lines).strip()
                    if not user_input:
                        continue

                if user_input.startswith("/"):
                    self.handle_slash(user_input)
                    continue

                self._execute_goal(user_input)
        finally:
            try:
                import readline
                readline.set_history_length(1000)
                readline.write_history_file(str(hist_file))
            except (ImportError, OSError):
                pass

        return 0


def run_repl(
    session_id: str = "",
    no_color: bool = False,
    quiet: bool = False,
    tool_profile: str = "",
    approval_mode: str = "",
) -> int:
    repl = BaizeREPL(
        session_id=session_id,
        no_color=no_color,
        quiet=quiet,
        tool_profile=tool_profile,
        approval_mode=approval_mode,
    )
    return repl.run()
