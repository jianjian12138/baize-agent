"""Baize Engine - autonomous agent runtime (V19).

Stdlib-only runtime that provides:
- doctor        : environment gate (real checks, real exit codes)
- skill_index   : scans skill libraries and builds a searchable index
- manifest      : project pipeline manifest validator
- memory        : persistence read/write for cross-session memory
- llm           : model-agnostic OpenAI-compatible client (hermes trait)
- tools         : sandboxed tool registry - primitives, not features (pi trait)
- agent         : autonomous loop with JSONL session persistence
- orchestrator  : Director -> Executor -> Verifier multi-agent pipeline

Usage:
    python -m baize doctor
    python -m baize index build | search <kw>
    python -m baize manifest validate <path>
    python -m baize memory log|remember|recall|stats
    python -m baize run "<goal>" [--resume <session-id>]
    python -m baize team "<goal>"
    python -m baize sessions [<session-id>]
"""

__version__ = "19.0.0"
