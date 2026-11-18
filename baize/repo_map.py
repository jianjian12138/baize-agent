"""RepoMap Code Skeleton & PageRank Reference Weighting Engine (V35.0.0 Prometheus).

Pure Python standard library — zero third-party dependencies.
Applies PageRank-style graph ranking over AST symbol calls to distill high-density
structural code skeletons without inflating the agent's context window.
"""
from __future__ import annotations

import collections
from typing import Any

from .symbol_graph import SymbolGraph

__all__ = [
    "RepoMapGenerator",
    "generate_workspace_repo_map",
]


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

        file_to_nodes: dict[str, list[tuple[float, Any]]] = collections.defaultdict(list)
        file_sums: dict[str, float] = collections.defaultdict(float)
        scores_map = self.pagerank_scores

        for name, nodes in self.graph.symbols.items():
            score = scores_map.get(name, 0.0)
            for node in nodes:
                file_to_nodes[node.file_path].append((score, node))
                file_sums[node.file_path] += score

        sorted_files = sorted(
            file_to_nodes.items(),
            key=lambda item: file_sums[item[0]],
            reverse=True,
        )

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
    from .arch_cache import get_cached_symbol_graph
    graph = get_cached_symbol_graph(root_dir=root_dir)
    gen = RepoMapGenerator(graph)
    return gen.generate_repo_map(max_symbols=max_symbols)
