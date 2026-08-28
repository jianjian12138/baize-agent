"""baize.knowledge — Layered memory storage, semantic RAG, and vector retrieval."""
from ..memory import log_event, remember, recall, compress, stats, VALID_CATEGORIES
from ..rag import augment
from ..vector import get_backend, TfidfIndex, EmbeddingBackend, tokenize
from .causal import ASTCausalTracker, MutationFuzzer, CausalProof, CausalSlice, MutationCase
from .replay import TimeTravelReplayer

__all__ = [
    "log_event", "remember", "recall", "compress", "stats", "VALID_CATEGORIES",
    "augment", "get_backend", "TfidfIndex", "EmbeddingBackend", "tokenize",
    "ASTCausalTracker", "MutationFuzzer", "CausalProof", "CausalSlice", "MutationCase",
    "TimeTravelReplayer",
]
