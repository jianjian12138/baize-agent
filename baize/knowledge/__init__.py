"""baize.knowledge — Layered memory storage, semantic RAG, vectors, and skill catalog/indexing."""
from __future__ import annotations

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    "log_event": (".memory", "log_event"),
    "remember": (".memory", "remember"),
    "recall": (".memory", "recall"),
    "compress": (".memory", "compress"),
    "stats": (".memory", "stats"),
    "VALID_CATEGORIES": (".memory", "VALID_CATEGORIES"),
    "augment": (".rag", "augment"),
    "get_backend": (".rag", "get_backend"),
    "TfidfIndex": (".rag", "TfidfIndex"),
    "EmbeddingBackend": (".rag", "EmbeddingBackend"),
    "tokenize": (".rag", "tokenize"),
    "graph_add": (".graph", "add"),
    "graph_query": (".graph", "query"),
    "TeamMemory": (".memory", "TeamMemory"),
    "build_index": (".skills", "build_index"),
    "SkillHarvester": (".skills", "SkillHarvester"),
    "SkillRunner": (".skill_runner", "SkillRunner"),
    "verify_skill_draft": (".skill_runner", "verify_skill_draft"),
    "BoundedMemoryStore": (".memory", "BoundedMemoryStore"),
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
