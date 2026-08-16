"""Baize Engine - autonomous agent runtime (V22).

Stdlib-only runtime that provides:
- doctor        : environment gate (real checks, real exit codes)
- skill_index   : scans skill libraries and builds a searchable index
- manifest      : project pipeline manifest validator
- memory        : persistence read/write for cross-session memory
- llm           : model-agnostic OpenAI-compatible client (hermes trait)
- tools         : sandboxed tool registry - primitives, not features (pi trait)
- sandbox       : optional OS-level sandbox adapter (Landlock/Seatbelt/Windows degrade)
- agent         : autonomous loop with JSONL session persistence
- orchestrator  : Director -> Executor -> Verifier multi-agent pipeline
- component     : V22 unified component contract + CompositionKernel (Cordis-inspired, hardened)
- modes         : V22 named modes = component-set bundles (coding/eval/autonomous/safe-review)
- gate          : NO FAKE DONE honest gate (manifest + real coverage + composition check)

Usage:
    python -m baize doctor
    python -m baize index build | search <kw>
    python -m baize manifest validate <path>
    python -m baize memory log|remember|recall|stats
    python -m baize run "<goal>" [--resume <session-id>]
    python -m baize team "<goal>"
    python -m baize sessions [<session-id>]
    python -m baize gate
"""

__version__ = "22.0.0"
