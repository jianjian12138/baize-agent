"""V41 Context Governance Engine: Artifact Spillover, Auto-Compaction & Tiered Tool Profiles.

Pure Python standard library implementation designed to:
  1. Spill oversized tool outputs (>8KB default) to session-scoped artifact files
     and return head/tail previews + line-range pointers instead of truncating blindly.
  2. Automatically compact older conversation turns into a structured state digest
     when estimated token usage crosses the configured budget ratio (default 75%),
     while keeping the system prefix and recent turns verbatim for Prompt Cache hits.
  3. Expose tiered tool profiles (`minimal` = 4 core tools, `tiered` = 6 core tools +
     on-demand `tool_search` activation, `full` = all tools) in append-only order so
     Prefix Cache stability is preserved while cutting schema token overhead.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .llm import estimate_tokens

# ---------------------------------------------------------------------------
# 1. Tiered Tool Profiles
# ---------------------------------------------------------------------------

MINIMAL_CORE_TOOLS: tuple[str, ...] = (
    "read_file",
    "write_file",
    "patch_file",
    "bash",
)

TIERED_CORE_TOOLS: tuple[str, ...] = (
    "read_file",
    "write_file",
    "patch_file",
    "grep_search",
    "find_files",
    "bash",
)

VALID_TOOL_PROFILES = frozenset({"minimal", "tiered", "full"})


class ToolProfileManager:
    """Manages which tool schemas are exposed to the LLM per turn.

    In ``tiered`` mode, only the 6 core tools + ``tool_search`` are sent initially.
    When the model invokes ``tool_search`` to discover/activate deferred tools,
    activated names are appended in stable insertion order so prompt-cache prefixes
    remain valid across subsequent turns.
    """

    def __init__(self, all_schemas: list[dict[str, Any]], profile: str = "tiered",
                 custom_registry: bool = False) -> None:
        prof = (profile or "tiered").strip().lower()
        if prof not in VALID_TOOL_PROFILES:
            prof = "tiered"
        self.profile = "full" if custom_registry else prof
        self._schema_by_name: dict[str, dict[str, Any]] = {}
        self._all_order: list[str] = []
        for s in all_schemas:
            fn = (s.get("function") or {})
            name = str(fn.get("name") or "")
            if name and name not in self._schema_by_name:
                self._schema_by_name[name] = s
                self._all_order.append(name)

        self._active: list[str] = []
        if self.profile == "full":
            self._active = list(self._all_order)
        elif self.profile == "minimal":
            self._active = [n for n in MINIMAL_CORE_TOOLS if n in self._schema_by_name]
        else:
            self._active = [n for n in TIERED_CORE_TOOLS if n in self._schema_by_name]
            if "tool_search" in self._schema_by_name and "tool_search" not in self._active:
                self._active.append("tool_search")

    @property
    def active_names(self) -> list[str]:
        return list(self._active)

    @property
    def deferred_names(self) -> list[str]:
        active_set = set(self._active)
        return [n for n in self._all_order if n not in active_set]

    def active_schemas(self) -> list[dict[str, Any]]:
        return [self._schema_by_name[n] for n in self._active if n in self._schema_by_name]

    def activate(self, names: list[str]) -> list[str]:
        """Append-only activation of deferred tools; returns newly activated names."""
        added: list[str] = []
        active_set = set(self._active)
        for raw in names:
            name = str(raw).strip()
            if name in self._schema_by_name and name not in active_set:
                self._active.append(name)
                active_set.add(name)
                added.append(name)
        return added

    def search_and_activate(self, query: str, *, auto_activate: bool = True, limit: int = 5) -> dict[str, Any]:
        """Search deferred (and all) tools by keyword and optionally activate matches."""
        q_tokens = [t for t in re.split(r"[\s,;_/-]+", (query or "").lower()) if t]
        scored: list[tuple[int, str, str]] = []
        for name in self._all_order:
            fn = self._schema_by_name[name].get("function") or {}
            desc = str(fn.get("description") or "")
            hay = f"{name} {desc}".lower()
            if not q_tokens:
                score = 1
            else:
                score = sum(3 if t in name.lower() else (1 if t in hay else 0) for t in q_tokens)
            if score > 0:
                scored.append((score, name, desc))
        scored.sort(key=lambda x: (-x[0], x[1]))
        top = scored[:max(1, limit)]
        matched_names = [name for _, name, _ in top]
        newly_activated = self.activate(matched_names) if auto_activate else []
        return {
            "profile": self.profile,
            "query": query,
            "matches": [{"name": n, "description": d} for _, n, d in top],
            "newly_activated": newly_activated,
            "active_count": len(self._active),
            "total_available": len(self._all_order),
        }

    def schema_token_estimate(self) -> int:
        return estimate_tokens(json.dumps(self.active_schemas(), ensure_ascii=False))


# ---------------------------------------------------------------------------
# 2. Tool Output Artifact Spillover
# ---------------------------------------------------------------------------

@dataclass
class SpilloverResult:
    spilled: bool
    text: str
    artifact_path: str = ""
    total_bytes: int = 0
    total_lines: int = 0


def spill_tool_output(
    output: str,
    *,
    tool_name: str,
    session_id: str,
    step: int,
    max_bytes: int = 8192,
    artifacts_root: str | Path | None = None,
    head_lines: int = 35,
    tail_lines: int = 35,
) -> SpilloverResult:
    """Spill large tool output to disk and return head/tail preview + pointer."""
    raw = output or ""
    raw_bytes = raw.encode("utf-8", errors="replace")
    total_bytes = len(raw_bytes)
    lines = raw.splitlines()
    total_lines = len(lines)

    if max_bytes <= 0 or total_bytes <= max_bytes:
        return SpilloverResult(
            spilled=False,
            text=raw,
            total_bytes=total_bytes,
            total_lines=total_lines,
        )

    base = Path(artifacts_root) if artifacts_root else (Path("persistence") / "artifacts")
    safe_sess = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id or "default")
    safe_tool = re.sub(r"[^A-Za-z0-9_.-]+", "_", tool_name or "tool")
    out_dir = base / safe_sess
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = out_dir / f"step_{step:03d}_{safe_tool}_{int(time.time() * 1000) % 100000}.txt"
    artifact.write_text(raw, encoding="utf-8", errors="replace")

    if total_lines <= head_lines + tail_lines:
        half = max(512, max_bytes // 3)
        head_preview = raw[:half]
        tail_preview = raw[-half:]
        omitted_info = f"{total_bytes - len(head_preview.encode('utf-8')) - len(tail_preview.encode('utf-8'))} bytes omitted"
    else:
        head_preview = "\n".join(lines[:head_lines])
        tail_preview = "\n".join(lines[-tail_lines:])
        omitted = total_lines - head_lines - tail_lines
        omitted_info = f"{omitted} lines omitted (lines {head_lines + 1}..{total_lines - tail_lines})"

    summary = (
        f"[ARTIFACT SPILLOVER: {tool_name} output was {total_bytes} bytes / {total_lines} lines; "
        f"full output saved to {artifact}]\n"
        f"--- HEAD ---\n{head_preview}\n"
        f"... [{omitted_info}; inspect with read_file or bash/python if needed] ...\n"
        f"--- TAIL ---\n{tail_preview}"
    )
    return SpilloverResult(
        spilled=True,
        text=summary,
        artifact_path=str(artifact),
        total_bytes=total_bytes,
        total_lines=total_lines,
    )


# ---------------------------------------------------------------------------
# 3. Budget-Driven Structured Auto-Compaction
# ---------------------------------------------------------------------------

_FILE_PATH_RE = re.compile(r"\b[\w./-]+\.(?:py|ts|tsx|js|jsx|go|rs|json|md|yaml|yml|toml|sh)\b")


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif content is not None:
            total += estimate_tokens(json.dumps(content, ensure_ascii=False))
        if m.get("tool_calls"):
            total += estimate_tokens(json.dumps(m["tool_calls"], ensure_ascii=False))
    return total


def estimate_context_ratio(messages: list[dict[str, Any]], budget_tokens: int = 64000) -> tuple[int, float]:
    used = estimate_messages_tokens(messages)
    budget = max(1000, int(budget_tokens))
    return used, round(min(1.0, used / budget), 4)


@dataclass
class CompactionReport:
    compacted: bool
    tokens_before: int
    tokens_after: int
    messages_removed: int
    touched_files: list[str] = field(default_factory=list)
    errors_preserved: int = 0


def compact_messages_structured(
    messages: list[dict[str, Any]],
    *,
    budget_tokens: int = 64000,
    threshold_ratio: float = 0.75,
    keep_recent: int = 8,
    force: bool = False,
) -> CompactionReport:
    """Compact middle conversation turns in-place into a structured digest.

    Preserves:
      - Leading system message(s) verbatim (protects Prefix Cache)
      - Initial user goal message verbatim
      - Most recent ``keep_recent`` messages verbatim (aligned to a safe message boundary)
    Summarizes removed turns into a single structured digest listing modified files,
    executed tool counts, and preserved error snippets.
    """
    tokens_before = estimate_messages_tokens(messages)
    budget = max(1000, int(budget_tokens))
    if not force and (tokens_before / budget) < threshold_ratio:
        return CompactionReport(False, tokens_before, tokens_before, 0)

    # Find end of leading system + initial user goal prefix
    prefix_end = 0
    while prefix_end < len(messages) and messages[prefix_end].get("role") == "system":
        prefix_end += 1
    if prefix_end < len(messages) and messages[prefix_end].get("role") == "user":
        prefix_end += 1

    tail_start = max(prefix_end, len(messages) - max(4, keep_recent))
    # Avoid splitting an assistant tool_calls turn from its following tool results
    while tail_start > prefix_end and messages[tail_start].get("role") == "tool":
        tail_start -= 1

    middle = messages[prefix_end:tail_start]
    if len(middle) < 3:
        return CompactionReport(False, tokens_before, tokens_before, 0)

    touched_files: list[str] = []
    seen_files: set[str] = set()
    tool_counts: dict[str, int] = {}
    error_snippets: list[str] = []
    decisions: list[str] = []

    for m in middle:
        role = m.get("role", "")
        content = str(m.get("content") or "")
        for tc in m.get("tool_calls") or []:
            fn = (tc.get("function") or {})
            tname = str(fn.get("name") or "tool")
            tool_counts[tname] = tool_counts.get(tname, 0) + 1
            raw_args = str(fn.get("arguments") or "")
            for match in _FILE_PATH_RE.findall(raw_args):
                if match not in seen_files and len(touched_files) < 25:
                    seen_files.add(match)
                    touched_files.append(match)
        if role == "tool":
            lower = content.lower()
            if any(k in lower for k in ("error", "traceback", "failed", "exception", "denied")):
                first_err = content.strip().splitlines()[:3]
                snippet = " | ".join(line.strip() for line in first_err if line.strip())[:240]
                if snippet and len(error_snippets) < 6:
                    error_snippets.append(snippet)
        elif role == "assistant" and content.strip():
            first_line = content.strip().splitlines()[0][:180]
            if first_line and len(decisions) < 5:
                decisions.append(first_line)
        elif role == "user" and content.strip():
            first_line = content.strip().splitlines()[0][:180]
            if first_line and len(decisions) < 6:
                decisions.append(f"[User] {first_line}")

    tool_summary = ", ".join(f"{k}×{v}" for k, v in sorted(tool_counts.items())) or "none"
    files_summary = ", ".join(touched_files) or "none recorded"
    digest_lines = [
        f"[AUTO-COMPACTED CONTEXT DIGEST — {len(middle)} earlier messages summarized]",
        f"- Tools invoked: {tool_summary}",
        f"- Files touched/inspected: {files_summary}",
    ]
    if decisions:
        digest_lines.append("- Key progress notes:")
        for d in decisions:
            digest_lines.append(f"  * {d}")
    if error_snippets:
        digest_lines.append("- Preserved errors / gate feedback:")
        for e in error_snippets:
            digest_lines.append(f"  * {e}")

    digest_msg = {"role": "user", "content": "\n".join(digest_lines)}
    messages[prefix_end:tail_start] = [digest_msg]
    tokens_after = estimate_messages_tokens(messages)
    return CompactionReport(
        compacted=True,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        messages_removed=len(middle),
        touched_files=touched_files,
        errors_preserved=len(error_snippets),
    )
