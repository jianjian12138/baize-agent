"""Unified Repo Map, Hierarchical Architecture Navigation & AST Context Slicer.

Pure Python standard library — zero third-party dependencies.
Consolidates three complementary context-compression views over ``SymbolGraph``:

1. **Flat PageRank Repo Map** (``RepoMapGenerator``, ``generate_workspace_repo_map``):
   Ranks symbols via integer-indexed PageRank to distill compact architecture skeletons.
2. **Hierarchical L1/L2 Repo Map** (``HierarchicalRepoMap``, ``get_hierarchical_repo_map``):
   Produces token-budgeted package topology + top-ranked interface skeletons for large repos.
3. **AST Context Slicer** (``slice_code_context``):
   Prunes unrelated Python function bodies into docstring + ellipsis stubs around a focus symbol.
"""
from __future__ import annotations

import ast
import collections
from pathlib import Path
from typing import Any

from .arch_cache import get_cached_symbol_graph
from .symbol_graph import SymbolGraph, SymbolNode

__all__ = [
    "RepoMapGenerator",
    "generate_workspace_repo_map",
    "HierarchicalRepoMap",
    "get_hierarchical_repo_map",
    "slice_code_context",
]


def _group_symbols_by_file(
    graph: SymbolGraph,
    pagerank_scores: dict[str, float],
) -> list[tuple[str, list[tuple[float, SymbolNode]]]]:
    """Group symbols by file and sort files descending by aggregate PageRank weight."""
    file_to_nodes: dict[str, list[tuple[float, SymbolNode]]] = collections.defaultdict(list)
    file_sums: dict[str, float] = collections.defaultdict(float)
    for name, nodes in graph.symbols.items():
        score = pagerank_scores.get(name, 0.0)
        for node in nodes:
            file_to_nodes[node.file_path].append((score, node))
            file_sums[node.file_path] += score
    return sorted(
        file_to_nodes.items(),
        key=lambda item: file_sums[item[0]],
        reverse=True,
    )


class RepoMapGenerator:
    """Computes PageRank weights over code symbols and formats compact repo map."""

    def __init__(self, graph: SymbolGraph):
        self.graph = graph
        self.pagerank_scores: dict[str, float] = {}
        self._pr_sig: tuple[int, int, int] | None = None

    def compute_pagerank(self, iterations: int = 20, damping: float = 0.85) -> dict[str, float]:
        """Compute PageRank scores across all unique symbol names using integer-indexed push iteration."""
        sig = (len(self.graph.symbols), self.graph.total_files_indexed, iterations)
        if self._pr_sig == sig and self.pagerank_scores:
            return self.pagerank_scores

        if hasattr(self.graph, "iter_unique_nodes"):
            all_nodes = self.graph.iter_unique_nodes()
        else:
            seen_ids: set[int] = set()
            all_nodes = []
            for nodes in self.graph.symbols.values():
                for n in nodes:
                    if id(n) not in seen_ids:
                        seen_ids.add(id(n))
                        all_nodes.append(n)
        if not all_nodes:
            return {}

        # Deduplicate distinct symbol names and build dense integer adjacency
        name_to_idx: dict[str, int] = {}
        idx_names: list[str] = []
        raw_calls: list[set[int]] = []

        for n in all_nodes:
            if n.name not in name_to_idx:
                name_to_idx[n.name] = len(idx_names)
                idx_names.append(n.name)
                raw_calls.append(set())
        for n in all_nodes:
            for call in n.calls:
                if call not in name_to_idx:
                    name_to_idx[call] = len(idx_names)
                    idx_names.append(call)
                    raw_calls.append(set())
            src = name_to_idx[n.name]
            adj_set = raw_calls[src]
            for call in n.calls:
                adj_set.add(name_to_idx[call])

        total_nodes = len(idx_names)
        adj: list[list[int]] = [list(s) for s in raw_calls]
        inv_out_deg: list[float] = [damping / len(a) if a else 0.0 for a in adj]

        base = (1.0 - damping) / total_nodes
        scores = [1.0 / total_nodes] * total_nodes

        for _ in range(iterations):
            new_scores = [base] * total_nodes
            for u in range(total_nodes):
                inv = inv_out_deg[u]
                if inv == 0.0:
                    continue
                contrib = scores[u] * inv
                for v in adj[u]:
                    new_scores[v] += contrib
            s_sum = sum(new_scores) or 1.0
            inv_sum = 1.0 / s_sum
            scores = [v * inv_sum for v in new_scores]

        result = {idx_names[i]: scores[i] for i in range(total_nodes)}
        self.pagerank_scores = result
        self._pr_sig = sig
        return result

    def generate_repo_map(self, max_symbols: int = 40) -> str:
        """Generate high-density structural code skeleton map."""
        if not self.pagerank_scores:
            self.compute_pagerank()

        sorted_files = _group_symbols_by_file(self.graph, self.pagerank_scores)

        lines = [
            "=== 🌲 [BAIZE PAGERANK REPO MAP · 全局核心架构骨架图] ===",
            "// 自动按拓扑引用重要度精炼，包含核心类、接口与顶层方法签名：",
        ]

        emitted_symbols = 0
        for file_path, scored_nodes in sorted_files:
            if emitted_symbols >= max_symbols:
                break
            seen: set[str] = set()
            unique_nodes = []
            for sc, n in sorted(scored_nodes, key=lambda x: x[0], reverse=True):
                if n.name not in seen:
                    seen.add(n.name)
                    unique_nodes.append((sc, n))

            lines.append(f"\n📁 {file_path}:")
            for _sc, node in unique_nodes:
                sig = node.signature or f"{node.kind} {node.name}"
                lines.append(f"  │ {sig}  [L{node.line_number}]")
                emitted_symbols += 1
                if emitted_symbols >= max_symbols:
                    break

        lines.append("\n=======================================================")
        return "\n".join(lines)


def generate_workspace_repo_map(root_dir: str = ".", max_symbols: int = 40) -> str:
    """Helper to generate workspace repo map (prefers incremental cache)."""
    graph = get_cached_symbol_graph(root_dir=root_dir)
    gen = RepoMapGenerator(graph)
    return gen.generate_repo_map(max_symbols=max_symbols)



class HierarchicalRepoMap:
    """Generates a bounded, multi-tier architecture skeleton map for large repositories."""

    def __init__(self, graph: SymbolGraph, root_dir: str | Path | None = None):
        self.graph = graph
        self.root_dir = Path(root_dir or graph.root_dir).resolve()
        self.repo_map_gen = RepoMapGenerator(graph)

    def extract_package_topology(self) -> dict[str, dict[str, Any]]:
        """Extract high-level directories, module counts, and docstring summaries (Level 1)."""
        packages: dict[str, dict[str, Any]] = collections.defaultdict(
            lambda: {"files": [], "docstring": "", "symbol_count": 0}
        )

        for rel_path, nodes in self.graph.file_symbols.items():
            parts = rel_path.split("/")
            pkg_name = parts[0] if len(parts) > 1 else "(root)"
            packages[pkg_name]["files"].append(rel_path)
            packages[pkg_name]["symbol_count"] += len(nodes)

            # Check for __init__.py / mod.rs / index.ts description
            if parts[-1] in ("__init__.py", "mod.rs", "index.ts", "package.json"):
                full_path = self.root_dir / rel_path
                try:
                    head = full_path.read_text(encoding="utf-8", errors="replace")[:1000]
                    # Extract module docstring or comment
                    doc = ""
                    if '"""' in head:
                        doc = head.split('"""')[1].strip().split("\n")[0]
                    elif "'''" in head:
                        doc = head.split("'''")[1].strip().split("\n")[0]
                    elif "//" in head:
                        for line in head.splitlines():
                            if line.strip().startswith("//"):
                                doc = line.strip().lstrip("/").strip()
                                break
                    if doc and not packages[pkg_name]["docstring"]:
                        packages[pkg_name]["docstring"] = doc[:80]
                except Exception:
                    pass

        return dict(packages)

    def render(self, token_budget: int = 3000) -> str:
        """Render compact multi-tier skeleton map respecting token budget (~4 chars per token)."""
        char_budget = token_budget * 4
        pkg_topo = self.extract_package_topology()
        pagerank = self.repo_map_gen.compute_pagerank()

        lines: list[str] = [
            "=== 🌲 [BAIZE HIERARCHICAL REPO MAP · 全局分级架构导航图] ===",
            "// 专为超大工程认知设计：L1 模块边界拓扑 + L2 核心接口骨架（函数体已精简为 ...）",
        ]

        # 1. Level 1: Package Topology Summary
        lines.append("\n[L1 系统模块拓扑与领域划分]:")
        sorted_pkgs = sorted(pkg_topo.items(), key=lambda x: len(x[1]["files"]), reverse=True)
        for pkg_name, data in sorted_pkgs:
            doc = f" - {data['docstring']}" if data["docstring"] else ""
            lines.append(f"  📦 {pkg_name}/ ({len(data['files'])} 文件, {data['symbol_count']} 符号){doc}")

        # 2. Level 2: High-Ranked Interface Skeletons
        lines.append("\n[L2 核心架构接口与类骨架 (Top-Ranked)]: ")

        sorted_files = _group_symbols_by_file(self.graph, pagerank)

        current_chars = sum(len(l) + 1 for l in lines)
        for file_path, scored_nodes in sorted_files:
            if current_chars >= char_budget - 300:
                lines.append(f"  ... [已按 Token 上限精炼其余 {len(sorted_files)} 个低阶文件，按需通过 read_file 查看]")
                break

            file_header = f"\n📄 {file_path}:"
            if current_chars + len(file_header) >= char_budget - 200:
                break
            lines.append(file_header)
            current_chars += len(file_header) + 1

            # Sort symbols in file by line number
            unique_nodes = []
            seen = set()
            for _, node in sorted(scored_nodes, key=lambda x: x[1].line_number):
                key = (node.name, node.kind, node.line_number)
                if key not in seen:
                    seen.add(key)
                    unique_nodes.append(node)

            for node in unique_nodes:
                if node.kind in ("class", "interface", "struct", "trait"):
                    line_str = f"  class {node.name}:"
                    doc = f'    """{node.docstring.splitlines()[0]}"""' if node.docstring else ""
                elif node.kind in ("function", "method"):
                    sig = node.signature or f"def {node.name}(...)"
                    doc_snip = f" # {node.docstring.splitlines()[0]}" if node.docstring else ""
                    line_str = f"    {sig}: ...{doc_snip}"
                else:
                    line_str = f"    {node.kind} {node.name}"

                if current_chars + len(line_str) + 1 >= char_budget - 100:
                    lines.append("    ...")
                    current_chars += 8
                    break

                lines.append(line_str)
                current_chars += len(line_str) + 1

        return "\n".join(lines)


def get_hierarchical_repo_map(
    root_dir: str | Path | None = None,
    token_budget: int = 3000,
    cfg: dict | None = None,
) -> str:
    """Convenience entry point to get a cached hierarchical repo map string."""
    graph = get_cached_symbol_graph(root_dir=root_dir, cfg=cfg)
    h_map = HierarchicalRepoMap(graph, root_dir=root_dir)
    return h_map.render(token_budget=token_budget)



class _ContextSlicingTransformer(ast.NodeTransformer):
    """Prunes function bodies not related to the focus symbol into docstring/ellipsis stubs."""
    def __init__(self, focus_symbol: str):
        self.focus_symbol = focus_symbol.lower().strip()
        self.pruned_functions_count = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._transform_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._transform_func(node)

    def _transform_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
        # If this is the focus symbol or contains it, keep full body
        if self.focus_symbol in node.name.lower():
            return self.generic_visit(node)

        # Otherwise prune body: keep docstring if present, and replace rest with `...` (Pass / Ellipsis)
        self.pruned_functions_count += 1
        doc = ast.get_docstring(node)
        new_body: list[ast.stmt] = []
        if doc:
            new_body.append(ast.Expr(value=ast.Constant(value=doc)))
        new_body.append(ast.Expr(value=ast.Constant(value=...)))
        
        node.body = new_body
        return node


def slice_code_context(code: str, focus_symbol: str = "") -> dict[str, Any]:
    """Perform AST syntax-aware context slicing on python source code."""
    if not code or not code.strip():
        return {
            "original_code": code,
            "sliced_code": code,
            "original_chars": 0,
            "sliced_chars": 0,
            "compression_ratio": "0%",
            "pruned_count": 0,
        }

    try:
        tree = ast.parse(code)
    except Exception:
        # Fallback if code is not valid Python
        return {
            "original_code": code,
            "sliced_code": code,
            "original_chars": len(code),
            "sliced_chars": len(code),
            "compression_ratio": "0%",
            "pruned_count": 0,
        }

    transformer = _ContextSlicingTransformer(focus_symbol=focus_symbol)
    new_tree = transformer.visit(tree)
    ast.fix_missing_locations(new_tree)

    try:
        sliced_code = ast.unparse(new_tree)
    except Exception:
        sliced_code = code

    orig_len = len(code)
    sliced_len = len(sliced_code)
    saved_ratio = round((1.0 - (sliced_len / max(1, orig_len))) * 100, 1)

    return {
        "focus_symbol": focus_symbol,
        "original_chars": orig_len,
        "sliced_chars": sliced_len,
        "compression_ratio": f"{max(0.0, saved_ratio)}%",
        "pruned_functions_count": transformer.pruned_functions_count,
        "sliced_code": sliced_code,
        "message": f"AST 上下文剪枝完成：修剪了 {transformer.pruned_functions_count} 个非目标函数体，Token 消耗压缩 {max(0.0, saved_ratio)}%！"
    }

