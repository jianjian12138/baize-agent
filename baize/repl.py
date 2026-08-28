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

from . import __version__
from .agent import Agent, Session, AgentResult
from .config import ROOT, load_config
from .llm import LLMClient
from .ui import ProgressUI
from .logging_setup import get_logger

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
  /rewind [N]          Time-travel rewind last N turns (default: 1 turn)
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

    def __init__(self, session_id: str = "", no_color: bool = False, quiet: bool = False):
        self.cfg = load_config()
        self.client = LLMClient(self.cfg)
        self.ui = ProgressUI(color=False if no_color else None, verbose=not quiet)
        self.session_id = session_id
        self.session: Session | None = None
        self.agent: Agent | None = None
        self.running = True

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
        )

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
            self.agent = Agent(
                role="executor",
                client=self.client,
                session=self.session,
                on_event=self.ui.event,
            )
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
                self.agent = Agent(
                    role="executor",
                    client=self.client,
                    session=self.session,
                    on_event=self.ui.event,
                )
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

        if cmd == "/rewind":
            if not self.session or not self.session.messages:
                print(p.paint("dim", "No messages in active session to rewind."))
                return
            turns = int(arg) if arg.isdigit() and int(arg) > 0 else 1
            # A turn consists of user message + assistant response + any tool observations
            # Find turn boundaries (role == 'user')
            user_indices = [i for i, m in enumerate(self.session.messages) if m.get("role") == "user"]
            if not user_indices:
                self.session.messages.clear()
            else:
                cutoff_turn = max(0, len(user_indices) - turns)
                cutoff_idx = user_indices[cutoff_turn] if cutoff_turn < len(user_indices) else 0
                self.session.messages = self.session.messages[:cutoff_idx]

            # Re-write session ledger file on disk atomically
            s_file = self.session.file
            if s_file.exists():
                lines = [json.dumps(m, ensure_ascii=False) for m in self.session.messages]
                s_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

            self._init_agent()
            print(p.paint("green", f"✓ Rewound {turns} turn(s). Active session now has {len(self.session.messages)} messages."))
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
            from .session_viewer import render_session, find_session_file
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
            from . import skill_index
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
            from . import memory as memory_mod
            if not arg:
                stats = memory_mod.stats()
                print(p.paint("bold", "\nMemory Stats:"))
                print(f"  • Notes size: {stats.get('notes_bytes', 0)} bytes ({stats.get('notes_lines', 0)} lines)")
                print(f"  • Log entries: {stats.get('log_entries', 0)}")
                print(f"  • Total storage: {stats.get('total_bytes', 0)} bytes\n")
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
            from .setup_wizard import run_setup_wizard
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

        # 1. Check for @file inclusions
        cleaned_goal, attached_files = _extract_at_files(user_goal, ROOT)
        final_prompt = user_goal

        if attached_files:
            context_blocks = []
            for f in attached_files:
                print(p.paint("cyan", f"  📎 [Context Ingested] {f['header']}"))
                context_blocks.append(f"### Context File: `{f['path']}`\n```\n{f['snippet']}\n```")
            final_prompt = f"{user_goal}\n\n" + "\n\n".join(context_blocks)

        # 2. Execute agent turn
        try:
            res = self.agent.run(final_prompt)
            if res.stopped_reason == "error":
                friendly = _format_user_friendly_error(res.final_text)
                print(p.paint("red", f"\n❌ {friendly}\n"))
            else:
                print(f"\n{res.final_text}\n")
            self.ui.summary(res)
            print()
        except KeyboardInterrupt:
            print(p.paint("yellow", "\n[Interrupted by user] Current execution stopped."))
        except Exception as e:
            print(p.paint("red", f"\nExecution error: {e}\n"))

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
                    from .setup_wizard import run_setup_wizard
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


def run_repl(session_id: str = "", no_color: bool = False, quiet: bool = False) -> int:
    repl = BaizeREPL(session_id=session_id, no_color=no_color, quiet=quiet)
    return repl.run()
