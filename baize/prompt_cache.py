"""Prompt-cache-friendly message shaping + token accounting (P3-4).

Zero dependencies. Two honest primitives:

* ``estimate_tokens`` - an explicitly APPROXIMATE token count (~4 chars/token).
  It is never presented as exact (NO FAKE DONE): real tokenizers vary by model
  and language, so the ``approx`` flag stays True and callers must treat the
  number as a budget hint, not ground truth.
* cacheable prefix shaping - the system prompt and tool definitions are the
  stable "prefix" that never changes turn-to-turn, so providers with prompt
  caching (Anthropic ``cache_control``, OpenAI automatic prefix caching) can
  reuse it. ``build_cacheable_messages`` pins the system prompt first and keeps
  the conversation after it; ``mark_cacheable`` attaches the provider-native
  cache marker only when explicitly enabled.
"""
from __future__ import annotations

__all__ = ["estimate_tokens", "cacheable_prefix",
           "build_cacheable_messages", "mark_cacheable"]


def estimate_tokens(text: str, approx: bool = True) -> int:
    """APPROXIMATE token count.

    Heuristic of ~4 characters per token (English baseline). This is
    intentionally coarse: real tokenizers differ by model and by language.
    The ``approx`` flag is True by default and the result must never be
    reported as an exact token count.
    """
    if not isinstance(text, str):
        text = str(text)
    return max(1, len(text) // 4)


def cacheable_prefix(system_prompt: str,
                     tool_schemas: list[dict] | None = None) -> list[dict]:
    """The stable leading block that should be cached across turns.

    Returns ``[{"role": "system", "content": system_prompt}]`` - the system
    prompt is the primary cache anchor. Tool definitions, when supplied to the
    model via the ``tools=`` parameter, form a second stable block and are
    treated as part of the same cached prefix. The output is deterministic:
    identical inputs always yield an identical, ordered structure.
    """
    block: list[dict] = [{"role": "system", "content": system_prompt}]
    return block


def build_cacheable_messages(system_prompt: str,
                             tool_schemas: list[dict] | None,
                             conversation: list[dict]) -> list[dict]:
    """Pin the cacheable prefix first, then append the conversation.

    Any pre-existing ``system`` message in ``conversation`` is collapsed into
    the single canonical system prompt so the prefix is unambiguous and stable
    (a requirement for reliable prompt caching).
    """
    convo = [m for m in conversation if m.get("role") != "system"]
    return cacheable_prefix(system_prompt, tool_schemas) + convo


def mark_cacheable(messages: list[dict], provider: str) -> list[dict]:
    """Attach the provider-native cache marker to the prefix.

    - Anthropic: adds ``cache_control: {"type": "ephemeral"}`` to the last
      system block (the cache breakpoint sits at the end of the stable prefix).
    - OpenAI / Ollama: returned unchanged - they cache identical prefixes
      automatically, no marker required.

    Returns a NEW list; the input is never mutated.
    """
    if provider != "anthropic":
        return list(messages)
    out = []
    last_sys_idx = -1
    for i, m in enumerate(messages):
        if m.get("role") == "system":
            last_sys_idx = i
        out.append(dict(m))
    if last_sys_idx >= 0:
        out[last_sys_idx] = {
            **out[last_sys_idx],
            "cache_control": {"type": "ephemeral"},
        }
    return out
