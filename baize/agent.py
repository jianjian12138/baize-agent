"""Autonomous agent loop - the heart of baize (V20).

V20 additions: periodic self-reflection checkpoints, dead-loop detection with
graceful abort, long-horizon context compression, plugin hooks and metrics.

Design synthesis (upgrade, not a re-skin):
- hermes-agent : full autonomy loop (reason -> tool -> observe -> repeat),
  model-agnostic client, self-evolving skills (save_skill tool).
- pi (pi.dev)  : minimal core + primitives; sessions are persisted as
  append-only JSONL with checkpoints so any run can be resumed/inspected;
  progressive disclosure (skills are surfaced as an index, loaded on demand).
- baize legacy : skill index, manifest gate, doctor, persistent memory are
  injected into the loop as first-class context, so the agent starts every
  session with real environment awareness instead of a blank prompt.

Everything is stdlib-only and deterministic-testable: pass a scripted
transport to LLMClient and the whole loop runs for real without network.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import load_config
from .llm import LLMClient, LLMError
from .observability import obs
from .plugin import registry as plugin_registry
from .tools import ToolRegistry, default_registry
from . import memory as memory_mod
from . import skill_index

MAX_OBSERVATION_CHARS = 8000
COMPRESSED_OBSERVATION_CHARS = 400   # size of an observation after compression
KEEP_RECENT_MESSAGES = 8             # never compress the most recent N messages

REFLECTION_PROMPT = (
    "REFLECTION CHECKPOINT - pause and self-assess before continuing:\n"
    "1) Am I measurably closer to the goal than N steps ago?\n"
    "2) Have any actions failed repeatedly? If so, change strategy - do NOT retry the same thing.\n"
    "3) What is the single most valuable next action?\n"
    "Answer in 2-3 short lines, then continue working (or give the final answer if done).")


# ---------------------------------------------------------------------------
# Session persistence (pi-style append-only JSONL)
# ---------------------------------------------------------------------------


class Session:
    """Append-only JSONL session log. Every message and tool observation is
    persisted the moment it happens, so a crash never loses state and any
    session can be resumed by id."""

    def __init__(self, session_id: str | None = None, cfg: dict | None = None):
        self.cfg = cfg or load_config()
        self.id = session_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.dir = Path(self.cfg["BAIZE_SESSIONS_DIR"])
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / f"{self.id}.jsonl"
        self.messages: list[dict] = []
        if self.file.exists():
            self._load()

    def _load(self) -> None:
        for line in self.file.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "message":
                self.messages.append(rec["message"])

    def append(self, message: dict, kind: str = "message") -> None:
        if kind == "message":
            self.messages.append(message)
        rec = {"kind": kind, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "message": message}
        with self.file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    @classmethod
    def list_sessions(cls, cfg: dict | None = None) -> list[dict]:
        cfg = cfg or load_config()
        d = Path(cfg["BAIZE_SESSIONS_DIR"])
        if not d.is_dir():
            return []
        out = []
        for f in sorted(d.glob("*.jsonl"), reverse=True):
            n_lines = sum(1 for _ in f.open(encoding="utf-8"))
            out.append({"id": f.stem, "events": n_lines,
                        "mtime": time.strftime(
                            "%Y-%m-%d %H:%M:%S",
                            time.localtime(f.stat().st_mtime))})
        return out


# ---------------------------------------------------------------------------
# Context builders - baize's own edge: the agent wakes up environment-aware
# ---------------------------------------------------------------------------


def build_system_prompt(role: str = "executor",
                        cfg: dict | None = None,
                        registry: ToolRegistry | None = None,
                        extra: str = "") -> str:
    cfg = cfg or load_config()
    registry = registry or default_registry()

    skill_hint = ""
    try:
        idx_file = Path(cfg["BAIZE_INDEX_FILE"])
        if idx_file.exists():
            idx = json.loads(idx_file.read_text(encoding="utf-8"))
            skill_hint = (f"A skill index with {idx.get('count', 0)} skills is "
                          "available - use search_skills/load_skill on demand "
                          "(progressive disclosure; do NOT guess workflows "
                          "that a skill already defines).")
    except (OSError, json.JSONDecodeError):
        pass

    role_prompts = {
        "director": (
            "You are the DIRECTOR agent. Break the user goal into a short, "
            "ordered plan of concrete subtasks. Do not execute anything "
            "yourself. Respond ONLY with JSON: "
            '{"plan": [{"id": 1, "task": "...", "verify": "...", '
            '"checks": [{"type": "file_exists", "path": "..."}]}]} '
            "with 1-6 subtasks. 'verify' states how success is checked. "
            "'checks' (optional) declares machine-verifiable gates: "
            'file_exists{path}, file_contains{path,text}, cmd_ok{cmd}.'),
        "executor": (
            "You are the EXECUTOR agent. Solve the task using the provided "
            "tools. Work step by step: inspect before you modify, verify "
            "after you change. When done, reply with a plain-text summary "
            "of what was done (no tool call)."),
        "verifier": (
            "You are the VERIFIER agent. Independently check whether the "
            "task was truly completed (read files / run commands as needed; "
            "never trust the executor's claim - NO FAKE DONE). Respond ONLY "
            'with JSON: {"verdict": "pass"|"fail", "evidence": "...", '
            '"issues": ["..."]}.'),
    }
    base = role_prompts.get(role, role_prompts["executor"])
    parts = [
        "You are Baize, an autonomous engineering agent (V20 runtime). "
        "You may receive REFLECTION CHECKPOINT prompts - use them to "
        "self-assess and correct course instead of repeating failing actions.",
        base,
        f"Available tools: {', '.join(registry.names())}.",
        skill_hint,
        "Persist important learnings with memory_log; reusable workflows "
        "with save_skill.",
    ]
    if extra:
        parts.append(extra)
    return "\n\n".join(p for p in parts if p)


def recall_context(goal: str, cfg: dict | None = None, limit: int = 5) -> str:
    """Inject relevant persistent memory into the first user turn.

    V20: RAG (TF-IDF over skills + memory) ranks context semantically first.
    Falls back to the V19 keyword scan when RAG yields nothing or errors -
    defensive: memory recall must never crash an agent run.
    """
    try:
        from . import rag
        block = rag.augment(goal, cfg=cfg, top_k=limit)
        if block:
            return f"Relevant persistent memory:\n{block}"
    except Exception:
        obs.record_error("rag_recall_failed")
    words = [w for w in goal.split() if len(w) >= 3][:4]
    hits: list[dict] = []
    for w in words:
        for h in memory_mod.recall(w, cfg=cfg, limit=limit):
            if h not in hits:
                hits.append(h)
    if not hits:
        return ""
    lines = "\n".join(f"- [{h['source']}] {h['text']}" for h in hits[:limit])
    return f"Relevant persistent memory:\n{lines}"


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    session_id: str
    final_text: str
    steps: int
    tool_calls: int
    stopped_reason: str  # "final" | "max_steps" | "error" | "loop_detected"
    transcript: list[dict] = field(default_factory=list)


def _total_chars(messages: list[dict]) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)


def compress_context(messages: list[dict],
                     keep_recent: int = KEEP_RECENT_MESSAGES) -> int:
    """Long-horizon context compression (V20).

    Shrinks OLD tool observations in-place (in memory only - the JSONL file
    stays append-only and untouched). The system prompt, all user turns and
    the most recent ``keep_recent`` messages are never modified.
    Returns the number of messages compressed."""
    compressed = 0
    cutoff = max(0, len(messages) - keep_recent)
    for m in messages[:cutoff]:
        content = str(m.get("content") or "")
        if (m.get("role") == "tool"
                and len(content) > COMPRESSED_OBSERVATION_CHARS):
            m["content"] = (content[:COMPRESSED_OBSERVATION_CHARS]
                            + " ...[compressed: old observation truncated]")
            compressed += 1
    return compressed


class Agent:
    def __init__(self, role: str = "executor", cfg: dict | None = None,
                 client: LLMClient | None = None,
                 registry: ToolRegistry | None = None,
                 session: Session | None = None,
                 on_event=None):
        self.cfg = cfg or load_config()
        self.role = role
        self.client = client or LLMClient(self.cfg)
        self.registry = registry or default_registry()
        self.session = session or Session(cfg=self.cfg)
        self.max_steps = int(self.cfg.get("BAIZE_AGENT_MAX_STEPS", "24"))
        self.reflect_every = int(self.cfg.get("BAIZE_REFLECT_EVERY", "6"))
        self.loop_window = max(2, int(self.cfg.get("BAIZE_LOOP_DETECT_WINDOW", "3")))
        self.compress_chars = int(self.cfg.get("BAIZE_CONTEXT_COMPRESS_CHARS", "60000"))
        self.on_event = on_event or (lambda *_: None)

    def run(self, goal: str, extra_system: str = "") -> AgentResult:
        sys_prompt = build_system_prompt(self.role, self.cfg,
                                         self.registry, extra_system)
        if not self.session.messages:
            self.session.append({"role": "system", "content": sys_prompt})
            mem = recall_context(goal, self.cfg)
            user_content = f"{mem}\n\nTASK: {goal}" if mem else goal
            self.session.append({"role": "user", "content": user_content})
        else:  # resumed session - just add the new user turn
            self.session.append({"role": "user", "content": goal})

        tool_schemas = self.registry.schemas()
        n_tool_calls = 0
        last_sig = ""            # loop detection: consecutive identical calls
        repeat_count = 0
        warned_loop = False

        plugin_registry.fire("on_agent_start", goal)
        obs.inc("agent_runs")

        for step in range(1, self.max_steps + 1):
            # V20: long-horizon context compression (in-memory only)
            if _total_chars(self.session.messages) > self.compress_chars:
                n = compress_context(self.session.messages)
                if n:
                    obs.inc("context_compressions")
                    self.on_event("compress", f"compressed {n} old observations")
                    self.session.append({"compressed": n}, kind="compress")

            try:
                msg = self.client.chat(self.session.messages, tools=tool_schemas)
            except LLMError as exc:
                plugin_registry.fire("on_error", exc)
                obs.record_error("agent_errors")
                self.session.append({"role": "assistant",
                                     "content": f"[error] {exc}"})
                return AgentResult(self.session.id, str(exc), step,
                                   n_tool_calls, "error",
                                   self.session.messages)
            self.session.append(msg)
            obs.inc("agent_steps")

            calls = msg.get("tool_calls") or []
            if not calls:  # plain answer -> done
                self.on_event("final", msg.get("content") or "")
                return AgentResult(self.session.id, msg.get("content") or "",
                                   step, n_tool_calls, "final",
                                   self.session.messages)

            for call in calls:
                n_tool_calls += 1
                fn = call.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}

                # V20: dead-loop detection on identical consecutive calls
                sig = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
                repeat_count = repeat_count + 1 if sig == last_sig else 1
                last_sig = sig
                if repeat_count >= self.loop_window * 2:
                    obs.inc("agent_loops_aborted")
                    self.on_event("loop", f"aborting: {name} repeated {repeat_count}x")
                    self.session.append({"role": "assistant", "content":
                                         f"[loop_detected] {name} repeated "
                                         f"{repeat_count} times - aborting"})
                    return AgentResult(self.session.id,
                                       f"stopped: identical tool call repeated "
                                       f"{repeat_count} times ({name})",
                                       step, n_tool_calls, "loop_detected",
                                       self.session.messages)

                self.on_event("tool", f"{name}({json.dumps(args, ensure_ascii=False)[:200]})")
                plugin_registry.fire("on_tool_call", name, args)
                obs.inc("tool_calls")
                observation = self.registry.execute(name, args)
                if repeat_count == self.loop_window and not warned_loop:
                    warned_loop = True
                    observation = (str(observation)
                                   + f"\n\n[WARNING] You have called {name} with "
                                     "identical arguments "
                                     f"{repeat_count} times in a row. Change "
                                     "strategy - repeating it again will abort the run.")
                self.session.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": str(observation)[:MAX_OBSERVATION_CHARS],
                })

            # V20: periodic self-reflection checkpoint
            if (self.reflect_every > 0 and step % self.reflect_every == 0
                    and step < self.max_steps):
                obs.inc("agent_reflections")
                self.on_event("reflect", f"checkpoint at step {step}")
                self.session.append({"role": "user",
                                     "content": REFLECTION_PROMPT})

        return AgentResult(self.session.id,
                           "stopped: reached max steps", self.max_steps,
                           n_tool_calls, "max_steps", self.session.messages)
