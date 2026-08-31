"""Interactive CLI Prompt Sniffer & Anti-Hang Safe Auto-Responder (V36.0.0 Titan).

Pure Python standard library — zero third-party dependencies.
Intercepts command-line interactive questions (npm init, y/n confirmation, password prompts, press enter)
to prevent 60-second subprocess deadlock timeouts and enable graceful automated recovery.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = [
    "detect_interactive_prompt",
    "get_safe_auto_answer",
]

# Patterns for common blocking CLI prompts
_INTERACTIVE_PATTERNS = [
    (r'(?i)\[y/n\]|\(y/n\)|\(yes/no\)|\[yes/no\]', "confirmation", "y\n"),
    (r'(?i)password\b.*:\s*$', "password_prompt", "\n"),
    (r'(?i)passphrase\b.*:\s*$', "password_prompt", "\n"),
    (r'(?i)press\s+(?:any\s+key|enter)\s+to\s+continue', "press_enter", "\n"),
    (r'(?i)package\s+name\s*:\s*(?:\([^)]*\))?\s*$', "npm_init_field", "\n"),
    (r'(?i)version\s*:\s*(?:\([^)]*\))?\s*$', "npm_init_field", "\n"),
    (r'(?i)author\s*:\s*(?:\([^)]*\))?\s*$', "npm_init_field", "\n"),
    (r'(?i)license\s*:\s*(?:\([^)]*\))?\s*$', "npm_init_field", "\n"),
    (r'(?i)is\s+this\s+ok\?\s*\(yes\)\s*$', "npm_confirm", "yes\n"),
    (r'(?i)are\s+you\s+sure\s+you\s+want\s+to\s+continue\s+connecting', "ssh_fingerprint", "yes\n"),
]


def detect_interactive_prompt(text: str) -> dict[str, Any]:
    """Scan stdout/stderr text chunk to detect if subprocess is waiting for interactive user input."""
    if not text:
        return {"is_interactive": False, "prompt_type": None, "suggested_answer": None}

    cleaned = text.strip()
    # Check last line or last 200 chars
    tail = cleaned[-200:] if len(cleaned) > 200 else cleaned

    for pattern, ptype, answer in _INTERACTIVE_PATTERNS:
        if re.search(pattern, tail):
            return {
                "is_interactive": True,
                "prompt_type": ptype,
                "suggested_answer": answer,
                "matched_snippet": tail[-80:],
                "message": f"嗅探到交互式 CLI 提示 [{ptype}]，已自动注入安全默认应答避免 60s 超时死锁！"
            }

    return {"is_interactive": False, "prompt_type": None, "suggested_answer": None}


def get_safe_auto_answer(prompt_type: str) -> str:
    """Return default safe newline response."""
    for _, ptype, answer in _INTERACTIVE_PATTERNS:
        if ptype == prompt_type:
            return answer
    return "\n"
