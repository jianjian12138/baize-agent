"""baize.codebase — 6 orthogonal static code intelligence modules."""
from __future__ import annotations

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    "SUPPORTED_EXTS": (".symbol_graph", "SUPPORTED_EXTS"),
    "SKIP_DIRS": (".symbol_graph", "SKIP_DIRS"),
    "SymbolGraph": (".symbol_graph", "SymbolGraph"),
    "SymbolNode": (".symbol_graph", "SymbolNode"),
    "ArchCacheManager": (".arch_cache", "ArchCacheManager"),
    "get_cached_symbol_graph": (".arch_cache", "get_cached_symbol_graph"),
    "invalidate_arch_cache": (".arch_cache", "invalidate_arch_cache"),
    "get_arch_cache_stats": (".arch_cache", "get_arch_cache_stats"),
    "RepoMapGenerator": (".repo_map", "RepoMapGenerator"),
    "generate_workspace_repo_map": (".repo_map", "generate_workspace_repo_map"),
    "HierarchicalRepoMap": (".repo_map", "HierarchicalRepoMap"),
    "get_hierarchical_repo_map": (".repo_map", "get_hierarchical_repo_map"),
    "slice_code_context": (".repo_map", "slice_code_context"),
    "RiskLevel": (".impact", "RiskLevel"),
    "CallerReference": (".impact", "CallerReference"),
    "BlastRadiusReport": (".impact", "BlastRadiusReport"),
    "BlastRadiusAnalyzer": (".impact", "BlastRadiusAnalyzer"),
    "analyze_blast_radius": (".impact", "analyze_blast_radius"),
    "TestImpactResult": (".impact", "TestImpactResult"),
    "TestImpactMatrix": (".impact", "TestImpactMatrix"),
    "analyze_test_impact": (".impact", "analyze_test_impact"),
    "ChangeImpactReport": (".impact", "ChangeImpactReport"),
    "analyze_change_impact": (".impact", "analyze_change_impact"),
    "grep_workspace": (".workspace_search", "grep_workspace"),
    "find_workspace_files": (".workspace_search", "find_workspace_files"),
    "extract_keywords": (".recon", "extract_keywords"),
    "run_recon": (".recon", "recon"),
    "recon_library": (".recon", "recon_library"),
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
