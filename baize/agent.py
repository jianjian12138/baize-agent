"""Autonomous agent loop - the heart of baize (V33).

V33 additions:
- Structured CoT <thinking> injection for complex reasoning (B1)
- Trace IDs (run_id / span_id) per step written to JSONL (E1)
- Tool argument JSON parse failure retry up to BAIZE_TOOL_RETRY_MAX (B3)

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

from .config import ROOT, load_config
from .hooks import HookRegistry
from .autonomy import AutonomyPolicy, READONLY_TOOLS, build_policy
from .modes import resolve_mode
from .llm import LLMClient, LLMError
from .logging_setup import redact
from .observability import obs
from .plugin import registry as plugin_registry
from .tools import ToolRegistry, default_registry
from . import memory as memory_mod
from . import agent_rules

MAX_OBSERVATION_CHARS = 8000
COMPRESSED_OBSERVATION_CHARS = 400   # size of an observation after compression
KEEP_RECENT_MESSAGES = 8             # never compress the most recent N messages

REFLECTION_PROMPT = (
    "REFLECTION CHECKPOINT - pause and self-assess before continuing:\n"
    "1) Am I measurably closer to the goal than N steps ago?\n"
    "2) Have any actions failed repeatedly? If so, change strategy - do NOT retry the same thing.\n"
    "3) What is the single most valuable next action?\n"
    "Answer in 2-3 short lines, then continue working (or give the final answer if done).")

# V33-B1: Structured Chain-of-Thought instruction injected into every system prompt.
# Encourages the model to reason before acting on complex tasks while skipping
# the overhead for trivial single-step responses.
COT_SYSTEM_INSTRUCTION = (
    "When facing complex tasks, multi-step decisions, or ambiguous situations, "
    "ALWAYS begin your response with a <thinking>...</thinking> block that outlines "
    "your reasoning step-by-step before proceeding with tool calls or a final answer. "
    "For trivial single-step responses you may skip the thinking block.")


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
        # P0-4: secrets must never land in the session JSONL in cleartext.
        stored = message
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            clean_content = message["content"].replace("\r\n", "\n")
            stored = {**message, "content": redact(clean_content)}
            if kind == "message":
                message["content"] = clean_content
        if kind == "message":
            self.messages.append(message)
        rec = {"kind": kind, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "message": stored}
        with self.file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def append_record(self, rec: dict) -> None:
        """Write a raw record line (used by session fork lineage markers).

        Unlike :meth:`append`, this does NOT redact or mutate ``rec`` - the
        caller is responsible for its contents - and never touches
        ``self.messages``.
        """
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
    registry = registry or _resolve_tool_registry()

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
        "clarifier": (
            "You are the CLARIFIER agent. Before any plan is made, pin down "
            "what the goal actually requires. Ask the few highest-leverage "
            "clarifying questions (scope, constraints, success criteria, "
            "non-goals), then state the assumptions you are making. Respond "
            'ONLY with JSON: {"questions": ["..."], "answers": ["..."], '
            '"assumptions": ["..."], "prd": "one-paragraph product spec"}.'),
    }
    base = role_prompts.get(role, role_prompts["executor"])
    parts = [
        "You are Baize, an autonomous engineering agent (V33 runtime). "
        "You may receive REFLECTION CHECKPOINT prompts - use them to "
        "self-assess and correct course instead of repeating failing actions.",
        base,
        # V33-B1: structured CoT instruction
        COT_SYSTEM_INSTRUCTION,
        f"Available tools: {', '.join(registry.names())}.",
        skill_hint,
        "Persist important learnings with memory_log; reusable workflows "
        "with save_skill.",
    ]
    if extra:
        parts.append(extra)
    # P0-2: inject external AGENTS.md/CLAUDE.md as untrusted reference only.
    external_rules = agent_rules.load_external_rules(
        cfg.get("BAIZE_WORKSPACE_DIR", str(ROOT)))
    if external_rules:
        parts.append(external_rules)
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


def _evidence_note(content: str) -> str:
    """Build a structured, bi-directional evidence-preserving stub for an old observation.

    P3-2 & V33 fix: preserves:
    - Verifier verdict (pass/fail)
    - Error indicators & exit codes
    - Head 120 chars (command/request context)
    - Tail 150 chars (stack trace, error message, or exit summary)
    """
    low = content.lower()
    verdict = None
    if "verdict" in low:
        for tok in ("pass", "fail"):
            if tok in low:
                verdict = tok
                break
    has_error = ("error" in low) or ("traceback" in low) or ("exception" in low) or ("exit=" in low and "exit=0" not in low)
    if len(content) <= 300:
        snippet = content.replace("\n", " ")
    else:
        head = content[:120].replace("\n", " ")
        tail = content[-150:].replace("\n", " ")
        snippet = f"{head} [...truncated {len(content)-270} chars...] {tail}"
    return (f"[compressed old observation | verdict={verdict or 'n/a'} "
            f"errors={'yes' if has_error else 'no'}] {snippet}")


def compress_context(messages: list[dict],
                     keep_recent: int = KEEP_RECENT_MESSAGES) -> int:
    """Long-horizon context compression (V20, hardened in P3-2).

    Shrinks OLD tool observations in-place (in memory only - the JSONL file
    stays append-only and untouched). The system prompt, all user turns and
    the most recent ``keep_recent`` messages are never modified. Critically,
    the compressed stub PRESERVES Verifier evidence (verdict / error signal)
    rather than discarding it (risk #3 from the P1-P3 plan).
    Returns the number of messages compressed."""
    compressed = 0
    cutoff = max(0, len(messages) - keep_recent)
    for m in messages[:cutoff]:
        content = str(m.get("content") or "")
        if (m.get("role") == "tool"
                and len(content) > COMPRESSED_OBSERVATION_CHARS):
            m["content"] = _evidence_note(content)
            compressed += 1
    return compressed


class Agent:
    def __init__(self, role: str = "executor", cfg: dict | None = None,
                 client: LLMClient | None = None,
                 registry: ToolRegistry | None = None,
                 session: Session | None = None,
                 on_event=None,
                 hooks: HookRegistry | None = None,
                 plan_mode: bool | None = None,
                 autonomy=None,
                 loop_strategy=None):
        self.cfg = cfg or load_config()
        self.role = role
        self.client = client or LLMClient(self.cfg)
        self.registry = registry or _resolve_tool_registry()
        self.session = session or Session(cfg=self.cfg)
        self.max_steps = int(self.cfg.get("BAIZE_AGENT_MAX_STEPS", "24"))
        self.reflect_every = int(self.cfg.get("BAIZE_REFLECT_EVERY", "6"))
        self.loop_window = max(2, int(self.cfg.get("BAIZE_LOOP_DETECT_WINDOW", "3")))
        self.compress_chars = int(self.cfg.get("BAIZE_CONTEXT_COMPRESS_CHARS", "60000"))
        self.on_event = on_event or (lambda *_: None)
        # V21 P1-1: lifecycle hook bus. Default off (empty) unless a hooks file
        # is declared via BAIZE_HOOKS_FILE - never silently on.
        self.hooks = hooks or HookRegistry.from_config(self.cfg)
        # V22 #97: named modes carry authority over the scalar sliders when set.
        bundle = resolve_mode(self.cfg)
        # V21 P2-1: Plan Mode + autonomy slider (fail-closed). Constructor
        # params always win; otherwise the mode bundle (if BAIZE_MODE set)
        # overrides the scalar sliders, which are the final fallback.
        if plan_mode is None:
            mode_set = bool((self.cfg.get("BAIZE_MODE") or "").strip())
            self.plan_mode = bool(bundle["plan_mode"]) if mode_set \
                else bool(self.cfg.get("BAIZE_PLAN_MODE", "0") == "1")
        else:
            self.plan_mode = bool(plan_mode)
        if autonomy is None:
            self.autonomy = build_policy(self.cfg, level=bundle["autonomy"])
        elif isinstance(autonomy, str):
            self.autonomy = AutonomyPolicy(level=autonomy)
        else:
            self.autonomy = autonomy
        # V22 #96: loop strategy - explicit constructor param wins; otherwise
        # the mode bundle decides (eval -> ProgrammaticLoop), else DefaultLoop.
        if loop_strategy is not None:
            self.loop = loop_strategy
        elif bundle["loop"] == "programmatic":
            self.loop = ProgrammaticLoop()
        else:
            self.loop = DefaultLoop()

    def _emit(self, event: str, detail: str = "", **payload) -> list:
        """Emit a legacy phase event to on_event AND the hook bus."""
        self.on_event(event, detail)
        return self.hooks.dispatch(event, {"detail": detail, **payload})

    def _tool_permitted(self, name: str, args: dict) -> tuple[bool, str]:
        """Plan Mode + autonomy gate (fail-closed). Returns (allow, reason)."""
        if self.plan_mode and name not in READONLY_TOOLS:
            return False, "plan mode allows read-only tools only"
        return self.autonomy.allow(name, args)

    def run(self, goal: str, extra_system: str = "") -> AgentResult:
        """Run the agent to completion via the active loop strategy.

        V22 #96 (review downgrade): the loop is a swappable strategy rather
        than a ``kind=loop`` component. Default strategy is ``DefaultLoop``;
        a custom strategy may be injected via ``loop_strategy=`` (e.g.
        ``ProgrammaticLoop`` for the opt-in / eval path).
        """
        return self.loop.run(self, goal, extra_system)

    def _run_loop(self, goal: str, extra_system: str = "") -> AgentResult:
        extra = extra_system
        ws_scope = getattr(self, "_workspace_scope", "")
        if ws_scope:
            scope_note = f"Workspace scope constraint: you are confined to path prefix '{ws_scope}'."
            extra = f"{extra}\n\n{scope_note}".strip() if extra else scope_note

        sys_prompt = build_system_prompt(self.role, self.cfg,
                                         self.registry, extra)
        if not self.session.messages:
            self.session.append({"role": "system", "content": sys_prompt})
            mem = "" if getattr(self, "_no_memory", False) else recall_context(goal, self.cfg)
            user_content = f"{mem}\n\nTASK: {goal}" if mem else goal
            self.session.append({"role": "user", "content": user_content})
            self.hooks.user_prompt_submit(user_content)
        else:  # resumed session - just add the new user turn
            self.session.append({"role": "user", "content": goal})
            self.hooks.user_prompt_submit(goal)

        tool_schemas = self.registry.schemas()
        n_tool_calls = 0
        last_sig = ""            # loop detection: consecutive identical calls
        repeat_count = 0
        warned_loop = False

        plugin_registry.fire("on_agent_start", goal)
        obs.inc("agent_runs")
        # V21 P1-1: lifecycle hooks fire for real (no tool gate here).
        self.hooks.session_start(goal)

        # V33-E1: generate a unique run_id for this execution for trace correlation
        run_id = uuid.uuid4().hex[:8]
        tool_retry_max = int(self.cfg.get("BAIZE_TOOL_RETRY_MAX", "2"))

        for step in range(1, self.max_steps + 1):
            # V20: long-horizon context compression (in-memory only)
            if _total_chars(self.session.messages) > self.compress_chars:
                n = compress_context(self.session.messages)
                if n:
                    obs.inc("context_compressions")
                    self.hooks.pre_compact(n)
                    self._emit("compress", f"compressed {n} old observations")
                    self.session.append({"compressed": n}, kind="compress")

            try:
                # P3-4: pin the cacheable prefix (system prompt first) so the
                # stable block is unambiguous - required for prompt caching.
                msgs = self.client.build_messages(
                    sys_prompt, tool_schemas, self.session.messages)
                msg = self.client.chat(msgs, tools=tool_schemas)
            except LLMError as exc:
                plugin_registry.fire("on_error", exc)
                obs.record_error("agent_errors")
                self.session.append({"role": "assistant",
                                     "content": f"[error] {exc}"})
                res = AgentResult(self.session.id, str(exc), step,
                                  n_tool_calls, "error",
                                  self.session.messages)
                self.hooks.session_end(res)
                return res
            self.session.append(msg)
            obs.inc("agent_steps")

            calls = msg.get("tool_calls") or []
            if not calls:  # plain answer -> done
                res = AgentResult(self.session.id, msg.get("content") or "",
                                  step, n_tool_calls, "final",
                                  self.session.messages)
                if str(self.cfg.get("BAIZE_AUTO_HARVEST_SKILLS", "1")).lower() in ("1", "true"):
                    try:
                        from .skill_harvester import SkillHarvester
                        harvester = SkillHarvester(self.cfg)
                        if harvester.should_harvest(res):
                            h_path = harvester.harvest(res, goal=goal)
                            if h_path:
                                self._emit("skill_harvested", f"distilled skill to {h_path.name}")
                    except Exception:
                        pass
                self.hooks.session_end(res)
                return res

            for call in calls:
                n_tool_calls += 1
                fn = call.get("function", {})
                name = fn.get("name", "")
                # V33-B3: retry JSON parse failure up to tool_retry_max times
                raw_args = fn.get("arguments") or "{}"
                args = {}
                parse_ok = False
                for _attempt in range(tool_retry_max + 1):
                    try:
                        args = json.loads(raw_args)
                        parse_ok = True
                        break
                    except json.JSONDecodeError:
                        if _attempt < tool_retry_max:
                            obs.inc("tool_arg_parse_retries")
                            # Inject a correction nudge into the session so model
                            # knows to fix its tool call format
                            self.session.append({
                                "role": "user",
                                "content": (
                                    f"[system] Tool call '{name}' had malformed JSON "
                                    f"arguments. Please retry with valid JSON."
                                ),
                            })
                            try:
                                msgs2 = self.client.build_messages(
                                    sys_prompt, tool_schemas, self.session.messages)
                                retry_msg = self.client.chat(msgs2, tools=tool_schemas)
                                retry_calls = retry_msg.get("tool_calls") or []
                                if retry_calls:
                                    fn = retry_calls[0].get("function", {})
                                    name = fn.get("name", name)
                                    raw_args = fn.get("arguments") or "{}"
                            except LLMError:
                                break
                        else:
                            break
                if not parse_ok:
                    self.session.append({
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": f"ERROR: could not parse JSON arguments for '{name}' after {tool_retry_max} retries",
                    })
                    continue

                # V20: dead-loop detection on identical consecutive calls
                sig = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
                repeat_count = repeat_count + 1 if sig == last_sig else 1
                last_sig = sig
                if repeat_count >= self.loop_window * 2:
                    obs.inc("agent_loops_aborted")
                    self._emit("loop", f"aborting: {name} repeated {repeat_count}x")
                    self.session.append({"role": "assistant", "content":
                                         f"[loop_detected] {name} repeated "
                                         f"{repeat_count} times - aborting"})
                    res = AgentResult(self.session.id,
                                      f"stopped: identical tool call repeated "
                                      f"{repeat_count} times ({name})",
                                      step, n_tool_calls, "loop_detected",
                                      self.session.messages)
                    self.hooks.session_end(res)
                    return res

                # V21 P1-1: pre_tool_use hook gate (fail-closed). A deny blocks
                # the tool entirely - the agent receives an observation with the
                # reason instead of a fake "ran" result.
                decision = self.hooks.pre_tool_use(name, args)
                if not decision.allow:
                    obs.inc("hook_pre_tool_blocked")
                    self._emit("pre_tool_use_denied",
                               f"{name}: {decision.reason}")
                    self.session.append({
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": f"ERROR: blocked by pre_tool_use hook: "
                                   f"{decision.reason}",
                    })
                    continue

                # V21 P2-1: Plan Mode + autonomy slider (fail-closed). A deny
                # reports an ERROR observation and the loop continues - the
                # action never silently succeeds.
                permit, reason = self._tool_permitted(name, args)
                if not permit:
                    obs.inc("tool_blocked_policy")
                    self._emit("tool_blocked", f"{name}: {reason}")
                    self.session.append({
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": f"ERROR: blocked by policy: {reason}",
                    })
                    continue

                self.on_event("tool", f"{name}({json.dumps(args, ensure_ascii=False)[:200]})")
                plugin_registry.fire("on_tool_call", name, args)
                obs.inc("tool_calls")
                # V33-E1: record span timing for this tool call
                span_start = time.time()
                span_id = uuid.uuid4().hex[:6]
                observation = self.registry.execute(name, args)
                span_elapsed_ms = int((time.time() - span_start) * 1000)
                # Write span to session JSONL for trace inspection
                self.session.append_record({
                    "kind": "span",
                    "run_id": run_id,
                    "span_id": span_id,
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "tool": name,
                    "elapsed_ms": span_elapsed_ms,
                    "ok": not str(observation).startswith("ERROR"),
                })
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
                # V21 P2-1: account estimated token spend; a breach forces an
                # autonomy downgrade (token-runaway guard).
                try:
                    self.autonomy.record_cost(len(str(observation)) // 4)
                except Exception:
                    pass
                # V21 P1-1: fire post_tool_use (and failure variant) hooks.
                self.hooks.post_tool_use(name, args, observation)
                if str(observation).startswith("ERROR"):
                    self.hooks.post_tool_use_failure(name, args, observation)

            # V20: periodic self-reflection checkpoint
            if (self.reflect_every > 0 and step % self.reflect_every == 0
                    and step < self.max_steps):
                obs.inc("agent_reflections")
                self._emit("reflect", f"checkpoint at step {step}")
                self.session.append({"role": "user",
                                     "content": REFLECTION_PROMPT})

        res = AgentResult(self.session.id,
                          "stopped: reached max steps", self.max_steps,
                          n_tool_calls, "max_steps", self.session.messages)
        self.hooks.session_end(res)
        return res


# ---------------------------------------------------------------------------
# V22 #96 (review downgrade): loop strategies. The loop is NOT a kind=loop
# component - it is tightly coupled to Agent internals (session/hooks/autonomy/
# plugin/reflection), so it is isolated as a swappable strategy class instead.
# ---------------------------------------------------------------------------


class DefaultLoop:
    """The standard reason -> tool -> observe loop, as a strategy object.

    Delegates to ``Agent._run_loop`` so the existing, regression-locked loop
    body is preserved byte-for-byte. Swapping this strategy never changes the
    model interaction - only ``Agent.run``'s top-level dispatch does.
    """

    def run(self, agent: "Agent", goal: str, extra_system: str = "") -> "AgentResult":
        return agent._run_loop(goal, extra_system)


class ProgrammaticLoop:
    """Opt-in, LLM-free loop strategy (V22 #96 / #97 ``eval`` mode).

    Executes a fixed sequence of tool calls with no model call at all, collects
    their observations, and returns an ``AgentResult``. This is real end-to-end
    behaviour (tools actually run) with zero network - the minimal harness
    "Minimal" analogue, used to benchmark the tool layer deterministically.
    """

    def __init__(self, steps: list[dict] | None = None):
        self.steps = steps or []

    def run(self, agent: "Agent", goal: str, extra_system: str = "") -> "AgentResult":
        if not agent.session.messages:
            agent.session.append({"role": "system",
                                  "content": "programmatic loop (no LLM)"})
            agent.session.append({"role": "user", "content": goal})
            agent.hooks.user_prompt_submit(goal)
        agent.hooks.session_start(goal)
        n_tool_calls = 0
        outcomes: list[str] = []
        for call in self.steps:
            name = call.get("name", "")
            args = call.get("arguments", {}) or {}
            permit, reason = agent._tool_permitted(name, args)
            if not permit:
                outcomes.append(f"{name}: BLOCKED ({reason})")
                continue
            n_tool_calls += 1
            observation = agent.registry.execute(name, args)
            outcomes.append(f"{name}: {str(observation)[:MAX_OBSERVATION_CHARS]}")
            agent.hooks.post_tool_use(name, args, observation)
        summary = "\n".join(outcomes)
        res = AgentResult(agent.session.id, summary, len(self.steps),
                          n_tool_calls, "final", agent.session.messages)
        agent.hooks.session_end(res)
        return res


# ---------------------------------------------------------------------------
# V22 #96 / #97: loop-strategy registry. Modes resolve a loop by *name*
# ("default" / "programmatic"); this maps the name to the concrete strategy
# class so the gate can instantiate and type-check it for real (fail-closed),
# instead of only checking the string is present (F3).
# ---------------------------------------------------------------------------

LOOP_STRATEGIES: dict[str, type] = {
    "default": DefaultLoop,
    "programmatic": ProgrammaticLoop,
}


def get_loop_strategy(name: str) -> "DefaultLoop | ProgrammaticLoop":
    """Instantiate a loop strategy by name. Raises ValueError for an unknown
    name (fail-closed) so callers cannot silently accept a bogus mode."""
    cls = LOOP_STRATEGIES.get(name)
    if cls is None:
        raise ValueError(f"unknown loop strategy: {name!r}")
    return cls()


def _resolve_tool_registry() -> "ToolRegistry":
    """Resolve the active tool provider through the composition kernel so an
    explicit ``BAIZE_COMPONENTS`` override of Kind.TOOL is honored (F4). Falls
    back to the global default registry if the kernel cannot be assembled, so
    Agent construction never breaks - the honest gate separately catches a
    broken kernel.

    In the default configuration the kernel's Kind.TOOL resolves to the very
    same ``default_registry()`` singleton, so behaviour is unchanged; only an
    explicit override diverges.
    """
    try:
        from .component import get_runtime, Kind
        inst = get_runtime().get(Kind.TOOL)
        if inst is not None:
            return inst
    except Exception:
        pass
    return default_registry()
