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

from concurrent.futures import ThreadPoolExecutor
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__
from .config import ROOT, load_config
from ..orchestration.hooks import HookRegistry
from .autonomy import AutonomyPolicy, READONLY_TOOLS, build_policy
from .autonomy import resolve_mode
from .llm import LLMClient, LLMError
from .config import redact
from ..governance.observability import obs
from .plugin import registry as plugin_registry
from ..execution.tools import ToolRegistry, default_registry
from ..knowledge import memory as memory_mod
from ..execution import tools as agent_rules

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
        self._lock = threading.RLock()
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
        with self._lock:
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
        with self._lock:
            with self.file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    @classmethod
    def list_sessions(cls, cfg: dict | None = None) -> list[dict]:
        cfg = cfg or load_config()
        d = Path(cfg["BAIZE_SESSIONS_DIR"])
        if not d.is_dir():
            return []
        entries = sorted(
            d.glob("*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        out = []
        for f in entries:
            try:
                st = f.stat()
                with f.open(encoding="utf-8", errors="replace") as fh:
                    n_lines = sum(1 for _ in fh)
                out.append({"id": f.stem, "events": n_lines,
                            "mtime": time.strftime(
                                "%Y-%m-%d %H:%M:%S",
                                time.localtime(st.st_mtime))})
            except OSError:
                continue
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
        # Read the release from the single source of truth instead of a literal.
        # This line used to be hardcoded "(V33 runtime)" and was still saying V33
        # four releases later, so every model call was told the wrong version.
        f"You are Baize, an autonomous engineering agent (V{__version__} runtime). "
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

    # V39.0.0 Aegis: Hierarchical Repo Map for large-scale codebase awareness
    if cfg.get("BAIZE_REPO_MAP_ENABLED", "1") != "0":
        try:
            from ..codebase.repo_map import get_hierarchical_repo_map
            ws_dir = cfg.get("BAIZE_WORKSPACE_DIR", str(ROOT))
            repo_tokens = int(cfg.get("BAIZE_REPO_MAP_TOKENS", "2500"))
            repo_map = get_hierarchical_repo_map(ws_dir, token_budget=repo_tokens, cfg=cfg)
            if repo_map and len(repo_map.splitlines()) > 3:
                parts.append(repo_map)
        except Exception:
            pass

    return "\n\n".join(p for p in parts if p)


def recall_context(goal: str, cfg: dict | None = None, limit: int = 5) -> str:
    """Inject relevant persistent memory into the first user turn.

    V20: RAG (TF-IDF over skills + memory) ranks context semantically first.
    Falls back to the V19 keyword scan when RAG yields nothing or errors -
    defensive: memory recall must never crash an agent run.
    """
    try:
        from ..knowledge import rag
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
    checkpoint_id: str = ""
    rolled_back: bool = False


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



#: Tools verified to have no workspace side effects, eligible for bounded
#: parallel execution when the model emits multiple calls in a single turn.
READ_ONLY_TOOLS = frozenset({
    "read_file",
    "list_dir",
    "find_files",
    "grep_search",
    "blast_radius",
    "diagnostics",
    "search_skills",
    "load_skill",
    "memory_recall",
    "tool_search",
    "bash_bg_output",
    "lsp_definition",
    "lsp_references",
    "lsp_hover",
    "verify_ui",
})

#: Tools that mutate workspace files and trigger automatic post-edit diagnostics.
EDIT_TOOLS = frozenset({"write_file", "patch_file"})

class Agent:
    def __init__(self, role: str = "executor", cfg: dict | None = None,
                 client: LLMClient | None = None,
                 registry: ToolRegistry | None = None,
                 session: Session | None = None,
                 on_event=None,
                 hooks: HookRegistry | None = None,
                 plan_mode: bool | None = None,
                 autonomy=None,
                 loop_strategy=None,
                 on_token=None,
                 auto_rollback: bool | None = None,
                 enable_checkpoint: bool | None = None,
                 approval_callback=None,
                 tool_profile: str | None = None,
                 spillover_bytes: int | None = None,
                 context_budget_tokens: int | None = None,
                 compact_ratio: float | None = None):
        self.cfg = cfg or load_config()
        self.role = role
        self.client = client or LLMClient(self.cfg)
        self._custom_registry = registry is not None
        self.registry = registry or _resolve_tool_registry()
        self.approval_callback = approval_callback
        self.tool_profile_name = (
            tool_profile
            if tool_profile is not None
            else str(self.cfg.get("BAIZE_TOOL_PROFILE", "tiered"))
        )
        self.spillover_bytes = (
            int(spillover_bytes)
            if spillover_bytes is not None
            else int(self.cfg.get("BAIZE_SPILLOVER_BYTES", "8192") or "8192")
        )
        self.context_budget_tokens = (
            int(context_budget_tokens)
            if context_budget_tokens is not None
            else int(self.cfg.get("BAIZE_CONTEXT_BUDGET_TOKENS", "64000") or "64000")
        )
        self.compact_ratio = (
            float(compact_ratio)
            if compact_ratio is not None
            else float(self.cfg.get("BAIZE_COMPACT_RATIO", "0.75") or "0.75")
        )
        self._steer_lock = threading.Lock()
        self._steer_queue: list[str] = []
        self._interrupt_event = threading.Event()
        self.last_tree_node_id: str = ""
        self._active_profile_mgr = None
        self.session = session or Session(cfg=self.cfg)
        self.max_steps = int(self.cfg.get("BAIZE_AGENT_MAX_STEPS", "24"))
        self.reflect_every = int(self.cfg.get("BAIZE_REFLECT_EVERY", "6"))
        self.loop_window = max(2, int(self.cfg.get("BAIZE_LOOP_DETECT_WINDOW", "3")))
        self.compress_chars = int(self.cfg.get("BAIZE_CONTEXT_COMPRESS_CHARS", "60000"))
        self.on_event = on_event or (lambda *_: None)
        self.on_token = on_token
        self.auto_rollback = (
            bool(auto_rollback)
            if auto_rollback is not None
            else str(self.cfg.get("BAIZE_AUTO_ROLLBACK", "0")).strip().lower() in ("1", "true", "yes")
        )
        self.enable_checkpoint = (
            bool(enable_checkpoint)
            if enable_checkpoint is not None
            else (
                self.auto_rollback
                or str(self.cfg.get("BAIZE_CHECKPOINT", "0")).strip().lower() in ("1", "true", "yes")
            )
        )
        self.auto_diagnostics = (
            str(self.cfg.get("BAIZE_AUTO_DIAGNOSTICS", "1")).strip().lower() not in ("0", "false", "no")
        )
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

    def run(
        self,
        goal: str,
        extra_system: str = "",
        images: list[str] | None = None,
    ) -> AgentResult:
        """Run the agent to completion via the active loop strategy.

        V22 #96 (review downgrade): the loop is a swappable strategy rather
        than a ``kind=loop`` component. Default strategy is ``DefaultLoop``;
        a custom strategy may be injected via ``loop_strategy=`` (e.g.
        ``ProgrammaticLoop`` for the opt-in / eval path).
        V42: Optional ``images`` paths are encoded as multimodal user parts.
        """
        self._pending_images = list(images or [])
        return self.loop.run(self, goal, extra_system)


    def _start_checkpoint(self, goal: str, run_id: str) -> tuple[Any, str]:
        if not self.enable_checkpoint:
            return None, ""
        try:
            from ..execution.checkpoint import GitCheckpointManager
            ws = self.cfg.get("BAIZE_WORKSPACE_DIR") or "."
            mgr = GitCheckpointManager(ws)
            if not mgr.is_git_repo():
                return None, ""
            cp = mgr.create(label=goal[:120], run_id=run_id)
            self._emit("checkpoint_created", cp.checkpoint_id)
            return mgr, cp.checkpoint_id
        except Exception:
            return None, ""

    def _finish_checkpoint(self, mgr: Any, checkpoint_id: str, res: AgentResult) -> AgentResult:
        if not mgr or not checkpoint_id:
            return res
        res.checkpoint_id = checkpoint_id
        if res.stopped_reason == "final":
            try:
                mgr.commit(checkpoint_id)
            except Exception:
                pass
            return res
        if self.auto_rollback:
            try:
                rb = mgr.rollback(checkpoint_id)
                if rb.get("ok"):
                    res.rolled_back = True
                    self._emit("checkpoint_rolled_back", checkpoint_id)
            except Exception:
                pass
        return res

    def _post_edit_diagnostics(self, name: str, args: dict, observation: str) -> str:
        if (not self.auto_diagnostics or name not in EDIT_TOOLS
                or str(observation).startswith("ERROR")):
            return observation
        target_path = args.get("path") or args.get("file_path") or ""
        if not target_path:
            return observation
        try:
            from ..codebase.diagnostics import diagnose_file
            ws = self.cfg.get("BAIZE_WORKSPACE_DIR") or "."
            rep = diagnose_file(target_path, workspace=ws)
            if not rep.ok:
                diag_txt = rep.format_for_agent()
                self._emit("diagnostic_report", diag_txt[:200])
                return f"{observation}\n\n{diag_txt}"
        except Exception:
            pass
        return observation

    def steer(self, message: str) -> None:
        """Queue a mid-turn user course-correction injected before the next reasoning step."""
        msg = (message or "").strip()
        if msg:
            with self._steer_lock:
                self._steer_queue.append(msg)

    def request_interrupt(self) -> None:
        """Request a soft interrupt of the current agent loop."""
        self._interrupt_event.set()

    def _drain_steering(self) -> list[str]:
        with self._steer_lock:
            items = list(self._steer_queue)
            self._steer_queue.clear()
        return items

    def context_status(self) -> dict[str, Any]:
        from .context_engine import estimate_context_ratio
        used, ratio = estimate_context_ratio(self.session.messages, self.context_budget_tokens)
        active_tools = len(self._active_profile_mgr.active_names) if self._active_profile_mgr else len(self.registry.names())
        return {
            "tokens_est": used,
            "budget_tokens": self.context_budget_tokens,
            "context_ratio": ratio,
            "tool_profile": self.tool_profile_name,
            "active_tools": active_tools,
        }

    def _run_loop(self, goal: str, extra_system: str = "") -> AgentResult:
        from .runtime_ctx import execution_context
        ws_dir = str(self.cfg.get("BAIZE_WORKSPACE_DIR", ".") or ".")

        def _on_tool_out(tool_name: str, stream: str, chunk: str) -> None:
            self._emit("tool_output_chunk", f"{tool_name}[{stream}]: {chunk[:400]}")

        with execution_context(workspace=ws_dir, session_id=self.session.id, on_tool_output=_on_tool_out):
            return self._run_loop_impl(goal, extra_system)

    def _run_loop_impl(self, goal: str, extra_system: str = "") -> AgentResult:
        extra = extra_system
        ws_scope = getattr(self, "_workspace_scope", "")
        if ws_scope:
            scope_note = f"Workspace scope constraint: you are confined to path prefix '{ws_scope}'."
            extra = f"{extra}\n\n{scope_note}".strip() if extra else scope_note

        if not getattr(self, "_no_memory", False):
            try:
                from ..knowledge.memory import BoundedMemoryStore
                mem_snap = BoundedMemoryStore(self.cfg).render_prefix_snapshot()
                if mem_snap:
                    extra = f"{extra}\n\n{mem_snap}".strip() if extra else mem_snap
            except Exception:
                pass

        # V45: Auto-inject polyglot project fingerprint (languages, PM, test/build commands)
        try:
            from ..codebase.project_profile import detect_project_profile
            ws_dir = str(self.cfg.get("BAIZE_WORKSPACE_DIR") or ".")
            prof_ctx = detect_project_profile(ws_dir).format_for_context()
            if prof_ctx:
                extra = f"{extra}\n\n{prof_ctx}".strip() if extra else prof_ctx
        except Exception:
            pass

        # V46: Auto-enable Spec Mode when BAIZE_SPEC_MODE=1 on a fresh session
        try:
            if str(self.cfg.get("BAIZE_SPEC_MODE", "0")).strip().lower() in ("1", "true", "yes"):
                from ..orchestration.spec_workflow import get_spec_manager
                sm = get_spec_manager(self.cfg)
                st = sm.get(self.session.id)
                if not st.enabled and st.phase == "off":
                    sm.enable(self.session.id, note="auto-enabled via BAIZE_SPEC_MODE=1")
        except Exception:
            pass

        sys_prompt = build_system_prompt(self.role, self.cfg,
                                         self.registry, extra)
        pending_imgs = getattr(self, "_pending_images", None) or []
        self._pending_images = []
        if not self.session.messages:
            self.session.append({"role": "system", "content": sys_prompt})
            mem = "" if getattr(self, "_no_memory", False) else recall_context(goal, self.cfg)
            user_text = f"{mem}\n\nTASK: {goal}" if mem else goal
        else:  # resumed session - just add the new user turn
            user_text = goal
        if pending_imgs:
            from .llm import encode_image_part
            max_img_bytes = int(self.cfg.get("BAIZE_MULTIMODAL_MAX_BYTES", "4194304") or "4194304")
            models_list = getattr(self.client, "models", [])
            prov = models_list[0].provider if models_list else "openai"
            content_parts: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
            for img_p in pending_imgs:
                try:
                    content_parts.append(encode_image_part(img_p, provider=prov, max_bytes=max_img_bytes))
                except Exception as img_exc:
                    self._emit("warning", f"skipped image {img_p}: {img_exc}")
            self.session.append({"role": "user", "content": content_parts})
            self.hooks.user_prompt_submit(user_text)
        else:
            self.session.append({"role": "user", "content": user_text})
            self.hooks.user_prompt_submit(user_text)

        from .context_engine import ToolProfileManager, compact_messages_structured, spill_tool_output
        profile_mgr = ToolProfileManager(
            self.registry.schemas(),
            profile=self.tool_profile_name,
            custom_registry=self._custom_registry,
        )
        self._active_profile_mgr = profile_mgr
        tool_schemas = profile_mgr.active_schemas()
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
        cp_mgr, cp_id = self._start_checkpoint(goal, run_id)
        try:
            from .sessions import record_checkpoint_node
            node = record_checkpoint_node(
                self.session.id,
                turn_index=len(self.session.messages),
                checkpoint_id=cp_id or "",
                summary=goal[:80],
                parent_node_id=self.last_tree_node_id,
                cfg=self.cfg,
            )
            self.last_tree_node_id = node["node_id"]
        except Exception:
            pass
        tool_retry_max = int(self.cfg.get("BAIZE_TOOL_RETRY_MAX", "2"))
        self._interrupt_event.clear()

        for step in range(1, self.max_steps + 1):
            # V41: drain mid-turn steering queue & handle soft interrupt
            steered_msgs = self._drain_steering()
            for sm in steered_msgs:
                self._emit("steered", sm)
                self.session.append({"role": "user", "content": f"[MID-TURN STEERING] {sm}"})
            if self._interrupt_event.is_set():
                self._interrupt_event.clear()
                if not steered_msgs:
                    res = AgentResult(self.session.id, "stopped: interrupted by user",
                                      step, n_tool_calls, "interrupted",
                                      self.session.messages)
                    res = self._finish_checkpoint(cp_mgr, cp_id, res)
                    self.hooks.session_end(res)
                    return res

            # V41: refresh active tiered tool schemas (append-only for Prefix Cache stability)
            tool_schemas = profile_mgr.active_schemas()

            # V41: budget-driven structured auto-compaction (default 75% budget)
            comp = compact_messages_structured(
                self.session.messages,
                budget_tokens=self.context_budget_tokens,
                threshold_ratio=self.compact_ratio,
            )
            if comp.compacted:
                obs.inc("context_compressions")
                self.hooks.pre_compact(comp.messages_removed)
                self._emit(
                    "compacted",
                    f"compacted {comp.messages_removed} msgs ({comp.tokens_before}->{comp.tokens_after} tok)",
                )
                self.session.append({
                    "compressed": comp.messages_removed,
                    "tokens_before": comp.tokens_before,
                    "tokens_after": comp.tokens_after,
                }, kind="compress")
            elif _total_chars(self.session.messages) > self.compress_chars:
                # Legacy char-cap fallback
                n = compress_context(self.session.messages)
                if n:
                    obs.inc("context_compressions")
                    self.hooks.pre_compact(n)
                    self._emit("compress", f"compressed {n} old observations")
                    self.session.append({"compressed": n}, kind="compress")

            # V42: session cost/token budget guard (80% soft warning, 100% hard circuit breaker)
            from .cost_ledger import get_cost_ledger
            _ledger = get_cost_ledger(self.cfg)
            _bstat = _ledger.check_budget(self.session.id)
            if _bstat.exceeded:
                self._emit("budget_exceeded", _bstat.reason)
                self.session.append({"role": "assistant", "content": f"[budget_exceeded] {_bstat.reason}"})
                res = AgentResult(
                    self.session.id,
                    f"Session halted by hard budget circuit breaker: {_bstat.reason}",
                    step,
                    n_tool_calls,
                    "budget_exceeded",
                    self.session.messages,
                )
                res = self._finish_checkpoint(cp_mgr, cp_id, res)
                self.hooks.session_end(res)
                return res
            if _bstat.warning and not getattr(self, "_budget_warned", False):
                self._budget_warned = True
                self._emit("budget_warning", _bstat.reason)

            try:
                # P3-4: pin the cacheable prefix (system prompt first) so the
                # stable block is unambiguous - required for prompt caching.
                msgs = self.client.build_messages(
                    sys_prompt, tool_schemas, self.session.messages)
                if self.on_token is not None and hasattr(self.client, "chat_with_stream"):
                    msg = self.client.chat_with_stream(
                        msgs, tools=tool_schemas, on_token=self.on_token
                    )
                else:
                    msg = self.client.chat(msgs, tools=tool_schemas)
                _usage = getattr(self.client, "last_usage", None) or (
                    msg.get("_usage") if isinstance(msg, dict) else None
                )
                if isinstance(_usage, dict) and (
                    int(_usage.get("prompt_tokens") or 0) > 0 or int(_usage.get("completion_tokens") or 0) > 0
                ):
                    _ledger.record(
                        session_id=self.session.id,
                        provider=str(_usage.get("provider") or "openai"),
                        model=str(_usage.get("model") or self.cfg.get("BAIZE_MODEL_NAME") or "unknown"),
                        prompt_tokens=int(_usage.get("prompt_tokens") or 0),
                        cached_tokens=int(_usage.get("cached_tokens") or 0),
                        completion_tokens=int(_usage.get("completion_tokens") or 0),
                    )
            except LLMError as exc:
                plugin_registry.fire("on_error", exc)
                obs.record_error("agent_errors")
                self.session.append({"role": "assistant",
                                     "content": f"[error] {exc}"})
                res = AgentResult(self.session.id, str(exc), step,
                                  n_tool_calls, "error",
                                  self.session.messages)
                res = self._finish_checkpoint(cp_mgr, cp_id, res)
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
                        from ..knowledge.skills import SkillHarvester
                        harvester = SkillHarvester(self.cfg)
                        if harvester.should_harvest(res):
                            h_path = harvester.harvest(res, goal=goal)
                            if h_path:
                                self._emit("skill_harvested", f"distilled skill to {h_path.name}")
                    except Exception:
                        pass
                res = self._finish_checkpoint(cp_mgr, cp_id, res)
                self.hooks.session_end(res)
                return res

            # Pre-parse arguments for all calls in this turn so contiguous read-only
            # calls can be batched concurrently while preserving deterministic order.
            prepared_calls: list[dict[str, Any]] = []
            for call in calls:
                n_tool_calls += 1
                fn = call.get("function", {})
                name = fn.get("name", "")
                # V33-B3: retry JSON parse failure without corrupting tool_call_id protocol
                raw_args = fn.get("arguments") or "{}"
                args = {}
                parse_ok = False
                scratch_msgs = list(self.session.messages)
                other_pending_ids = [
                    c.get("id", "") for c in calls if c is not call and c.get("id")
                ]
                for _attempt in range(tool_retry_max + 1):
                    candidate = raw_args.strip() if isinstance(raw_args, str) else raw_args
                    if isinstance(candidate, dict):
                        args = candidate
                        parse_ok = True
                        break
                    # Strip accidental markdown code fences around JSON arguments
                    if candidate.startswith("```"):
                        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.DOTALL).strip()
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            args = parsed
                            parse_ok = True
                            break
                    except json.JSONDecodeError:
                        pass
                    if _attempt < tool_retry_max:
                        obs.inc("tool_arg_parse_retries")
                        # Answer the dangling tool_call_id in scratch_msgs so the
                        # provider never sees an unanswered assistant tool_call.
                        for oid in other_pending_ids:
                            scratch_msgs.append({
                                "role": "tool",
                                "tool_call_id": oid,
                                "content": "DEFERRED: awaiting retry of sibling tool call",
                            })
                        scratch_msgs.append({
                            "role": "tool",
                            "tool_call_id": call.get("id", ""),
                            "content": (
                                f"ERROR: Tool call '{name}' had malformed JSON "
                                f"arguments ({raw_args[:120]}). Retry with valid JSON object."
                            ),
                        })
                        try:
                            msgs2 = self.client.build_messages(
                                sys_prompt, tool_schemas, scratch_msgs)
                            retry_msg = self.client.chat(msgs2, tools=tool_schemas)
                            scratch_msgs.append(retry_msg)
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
                    res = self._finish_checkpoint(cp_mgr, cp_id, res)
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

                # V46: Spec-Driven Workflow Hard-Gate (locks mutating tools until user approves spec)
                try:
                    from ..orchestration.spec_workflow import get_spec_manager
                    _spec_mgr = get_spec_manager(self.cfg)
                    _spec_ok, _spec_reason = _spec_mgr.check_tool_allowed(
                        self.session.id, name, READ_ONLY_TOOLS
                    )
                except Exception:
                    _spec_mgr = None
                    _spec_ok, _spec_reason = True, ""
                if not _spec_ok:
                    obs.inc("tool_blocked_spec_gate")
                    self._emit("spec_locked", f"{name}: {_spec_reason}")
                    self.session.append({
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": f"ERROR: SPEC_GATE_LOCKED: {_spec_reason}",
                    })
                    continue

                # V49: fine-grained three-state permission rules engine (.baize/permissions.json: deny > ask > allow)
                _perm_action = "default"
                _perm_reason = ""
                try:
                    from ..governance.permissions import evaluate_tool_permission
                    from .runtime_ctx import current_workspace
                    _p_ws = str(current_workspace(self.cfg))
                    _p_dec = evaluate_tool_permission(name, args, workspace=_p_ws, cfg=self.cfg)
                    _perm_action = _p_dec.action
                    _perm_reason = _p_dec.reason
                except Exception:
                    _p_ws = str(self.cfg.get("BAIZE_WORKSPACE_DIR", "."))
                if _perm_action == "deny":
                    obs.inc("tool_blocked_permission")
                    self._emit("permission_denied", f"{name}: {_perm_reason}")
                    self.session.append({
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": f"ERROR: PERMISSION_DENIED: {_perm_reason}",
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

                # V41/V43/V49: tiered approval callback OR persistent SQLite ApprovalQueue bridge
                _active_apr_cb = self.approval_callback
                if _active_apr_cb is None and str(self.cfg.get("BAIZE_APPROVAL_BRIDGE", "")).strip().lower() == "queue":
                    from ..interfaces.approval import get_approval_queue as _get_apr_q
                    _apr_timeout = float(self.cfg.get("BAIZE_APPROVAL_TIMEOUT", "300") or "300")
                    _active_apr_cb = lambda req, _q=_get_apr_q(), _t=_apr_timeout: _q.submit(req, timeout=_t)
                _yolo = str(self.cfg.get("BAIZE_YOLO", "0")).strip().lower() in ("1", "true", "yes")
                if _perm_action == "ask" and _active_apr_cb is None and not _yolo:
                    obs.inc("tool_approval_denied")
                    self._emit("approval_denied", f"{name}: {_perm_reason} (no interactive approver attached)")
                    self.session.append({
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": f"ERROR: APPROVAL_REQUIRED: {_perm_reason} (fail-closed: no approver attached).",
                    })
                    continue
                _needs_approval = (
                    _active_apr_cb is not None
                    and _perm_action != "allow"
                    and (name not in READ_ONLY_TOOLS or _perm_action == "ask")
                )
                if _needs_approval:
                    from ..interfaces.approval import ApprovalRequest, build_tool_preview
                    ws_dir = str(self.cfg.get("BAIZE_WORKSPACE_DIR", "."))
                    preview = build_tool_preview(name, args, workspace=ws_dir, color=False)
                    self._emit("diff_preview", f"{name}: {preview[:300]}")
                    apr_dec = _active_apr_cb(ApprovalRequest(
                        tool_name=name,
                        arguments=args,
                        preview=preview,
                        risk="high" if name in ("bash", "bash_bg_start", "git") else "medium",
                    ))
                    if not getattr(apr_dec, "approved", False):
                        deny_reason = getattr(apr_dec, "reason", "") or "denied by user"
                        obs.inc("tool_approval_denied")
                        self._emit("approval_denied", f"{name}: {deny_reason}")
                        self.session.append({
                            "role": "tool",
                            "tool_call_id": call.get("id", ""),
                            "content": f"ERROR: user denied '{name}': {deny_reason}. Adjust your approach accordingly.",
                        })
                        continue

                warn_now = (repeat_count == self.loop_window and not warned_loop)
                if warn_now:
                    warned_loop = True
                if _spec_mgr is not None and name not in READ_ONLY_TOOLS:
                    try:
                        _st_now = _spec_mgr.get(self.session.id)
                        if _st_now.enabled and _st_now.phase == "approved":
                            _spec_mgr.mark_executing(self.session.id)
                    except Exception:
                        pass
                prepared_calls.append({
                    "call_id": call.get("id", ""),
                    "name": name,
                    "args": args,
                    "repeat_count": repeat_count,
                    "warn_now": warn_now,
                    "read_only": name in READ_ONLY_TOOLS,
                })

            # Group prepared_calls into contiguous read-only parallel batches vs
            # strictly serial mutating tool invocations.
            groups: list[tuple[bool, list[dict[str, Any]]]] = []
            for item in prepared_calls:
                if item["read_only"] and groups and groups[-1][0]:
                    groups[-1][1].append(item)
                else:
                    groups.append((item["read_only"], [item]))

            def _exec_one(item: dict[str, Any]) -> tuple[str, int]:
                from ..governance.telemetry import get_tracer
                t0 = time.time()
                with get_tracer(self.cfg).start_span(f"tool.{item['name']}", attributes={"tool.name": item["name"]}):
                    if item["name"] == "tool_search":
                        q = str(item["args"].get("query") or "")
                        auto_act = bool(item["args"].get("activate", True))
                        res_obj = profile_mgr.search_and_activate(q, auto_activate=auto_act)
                        out = json.dumps(res_obj, ensure_ascii=False)
                    else:
                        out = self.registry.execute(item["name"], item["args"])
                elapsed_ms = int((time.time() - t0) * 1000)
                return str(out), elapsed_ms

            for is_ro, batch in groups:
                for item in batch:
                    self.on_event("tool", f"{item['name']}({json.dumps(item['args'], ensure_ascii=False)[:200]})")
                    plugin_registry.fire("on_tool_call", item["name"], item["args"])
                    obs.inc("tool_calls")

                if is_ro and len(batch) > 1:
                    obs.inc("parallel_tool_batches")
                    self._emit("tool_batch_start", f"parallel x{len(batch)}: {', '.join(i['name'] for i in batch)}")
                    import contextvars as _cv
                    with ThreadPoolExecutor(max_workers=min(4, len(batch))) as pool:
                        futs = [pool.submit(_cv.copy_context().run, _exec_one, it) for it in batch]
                        results_batch = [f.result() for f in futs]
                else:
                    results_batch = [_exec_one(item) for item in batch]

                for item, (observation, span_elapsed_ms) in zip(batch, results_batch):
                    name = item["name"]
                    args = item["args"]
                    observation = self._post_edit_diagnostics(name, args, observation)
                    try:
                        from ..governance.dlp import get_audit_ledger, guard_untrusted_output
                        observation, _inj_hits, _sec_hits = guard_untrusted_output(str(observation), source=name, cfg=self.cfg)
                        get_audit_ledger(self.cfg).append(
                            "tool_call",
                            actor=self.role,
                            target=name,
                            outcome="error" if str(observation).startswith("ERROR") else "ok",
                            details={
                                "session_id": self.session.id,
                                "elapsed_ms": span_elapsed_ms,
                                "injection_hits": len(_inj_hits),
                                "secret_redactions": len(_sec_hits),
                            },
                        )
                    except Exception:
                        pass
                    span_id = uuid.uuid4().hex[:6]
                    self.session.append_record({
                        "kind": "span",
                        "run_id": run_id,
                        "span_id": span_id,
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "tool": name,
                        "elapsed_ms": span_elapsed_ms,
                        "ok": not str(observation).startswith("ERROR"),
                    })
                    if item["warn_now"]:
                        observation = (
                            str(observation)
                            + f"\n\n[WARNING] You have called {name} with "
                              "identical arguments "
                              f"{item['repeat_count']} times in a row. Change "
                              "strategy - repeating it again will abort the run."
                        )
                    spill = spill_tool_output(
                        str(observation),
                        tool_name=name,
                        session_id=self.session.id,
                        step=step,
                        max_bytes=self.spillover_bytes,
                        artifacts_root=Path(self.cfg.get("BAIZE_PERSISTENCE_DIR", "persistence")) / "artifacts",
                    )
                    if spill.spilled:
                        self._emit("artifact_spilled", f"{name}: {spill.total_bytes}B -> {spill.artifact_path}")
                    final_obs = spill.text[:MAX_OBSERVATION_CHARS]
                    self.session.append({
                        "role": "tool",
                        "tool_call_id": item["call_id"],
                        "content": final_obs,
                    })
                    try:
                        self.autonomy.record_cost(len(str(observation)) // 4)
                    except Exception:
                        pass
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
        res = self._finish_checkpoint(cp_mgr, cp_id, res)
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
