"""baize.labs — Experimental and research engines (causal slicing, speculative forking, swarm, radar)."""
from __future__ import annotations

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    "ASTCausalTracker": (".causal", "ASTCausalTracker"),
    "MutationFuzzer": (".causal", "MutationFuzzer"),
    "CausalProof": (".causal", "CausalProof"),
    "CausalSlice": (".causal", "CausalSlice"),
    "MutationCase": (".causal", "MutationCase"),
    "TimeTravelReplayer": (".replay", "TimeTravelReplayer"),
    "SpeculativeEngine": (".forking", "SpeculativeEngine"),
    "SpeculativeTimeline": (".forking", "SpeculativeTimeline"),
    "AdversarialHegemony": (".adversarial", "AdversarialHegemony"),
    "ExecutionSnapshot": (".snapshot", "ExecutionSnapshot"),
    "SnapshotStore": (".snapshot", "SnapshotStore"),
    "MetaToolSynthesizer": (".synthesizer", "MetaToolSynthesizer"),
}

__all__ = list(_EXPORTS)

def __getattr__(name: str):
    if name in _EXPORTS:
        mod_path, attr = _EXPORTS[name]
        mod = importlib.import_module(mod_path, __name__)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
