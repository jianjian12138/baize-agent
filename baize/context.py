"""Context / long-term memory management (P3-2). Zero dependencies.

Fixes the V20 blind-truncation risk (cutting an observation to N chars could
silently destroy Verifier evidence - the proof a task actually completed):

* ``extract_evidence`` - pull the structured signals (verdicts, errors, goals,
  tool calls) out of a transcript so compression never loses the proof.
* ``TieredMemory`` - hot / warm / cold layering:
    hot  : recent raw messages (verbatim, capped)
    warm : compressed mid-term textual summaries
    cold : structured evidence distilled to disk for true long-horizon recall
"""
from __future__ import annotations

import json
from pathlib import Path

__all__ = ["extract_evidence", "TieredMemory"]


def extract_evidence(messages: list[dict]) -> dict:
    """Return the structured evidence carried by a transcript.

    Verifier verdicts, tool errors, user goals and tool calls are extracted
    individually so a later compression can keep them while dropping the bulk
    of the prose.
    """
    verdicts: list[str] = []
    errors = 0
    goals: list[str] = []
    tool_calls: list[str] = []
    for m in messages:
        role = str(m.get("role", "unknown"))
        content = m.get("content")
        if role == "user" and isinstance(content, str) and len(goals) < 3:
            goals.append(content[:160])
        if isinstance(content, list):                  # Anthropic-style blocks
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool_use":
                    tool_calls.append(str(part.get("name", "?")))
                elif part.get("type") == "tool_result":
                    if "error" in str(part.get("content", "")).lower():
                        errors += 1
        elif isinstance(content, str):
            low = content.lower()
            if "verdict" in low and ("pass" in low or "fail" in low):
                verdicts.append(content[:200])
            if "traceback" in low or low.startswith("error:"):
                errors += 1
    return {"goals": goals, "tool_calls": tool_calls,
            "verdicts": verdicts, "errors": errors}


class TieredMemory:
    """Hot/warm/cold long-term memory.

    ``hot`` holds the most recent messages verbatim (capped at ``hot_limit``).
    When it overflows, the oldest message is demoted: its structured evidence
    is merged into ``cold`` and a short textual summary is pushed to ``warm``.
    ``snapshot()`` reconstructs the context to feed a model: hot verbatim, plus
    a warm summary message and a cold evidence message.
    """

    def __init__(self, hot_limit: int = 8, path: str | None = None):
        self.hot_limit = hot_limit
        self.hot: list[dict] = []
        self.warm: list[str] = []
        self.cold: dict = {"verdicts": [], "errors": 0,
                           "tool_calls": [], "goals": []}
        self.path = Path(path) if path else None
        if self.path and self.path.exists():
            self.load()

    def push(self, message: dict) -> None:
        self.hot.append(message)
        while len(self.hot) > self.hot_limit:
            self._demote(self.hot.pop(0))

    def _demote(self, message: dict) -> None:
        ev = extract_evidence([message])
        for v in ev["verdicts"]:
            if v not in self.cold["verdicts"]:
                self.cold["verdicts"].append(v)
        self.cold["errors"] += ev["errors"]
        for t in ev["tool_calls"]:
            if t not in self.cold["tool_calls"]:
                self.cold["tool_calls"].append(t)
        for g in ev["goals"]:
            if g not in self.cold["goals"]:
                self.cold["goals"].append(g)
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            self.warm.append(f"[{message.get('role')}] {content[:120]}")

    def snapshot(self) -> list[dict]:
        """Context to hand to the model: hot verbatim + warm + cold."""
        ctx = list(self.hot)
        if self.warm:
            ctx.append({"role": "system",
                        "content": "[warm context summary]\n"
                                   + "\n".join(self.warm)})
        ev = self.cold
        if ev["verdicts"] or ev["errors"] or ev["tool_calls"] or ev["goals"]:
            ctx.append({"role": "system",
                        "content": "[long-term evidence]\n"
                                   + json.dumps(ev, ensure_ascii=False)})
        return ctx

    def persist(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cold, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    def load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if isinstance(data, dict):
            self.cold = data
