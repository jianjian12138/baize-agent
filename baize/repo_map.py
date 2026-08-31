"""PageRank-Weighted Codebase Structural Repo Map Generator (V37.0.0 Prometheus).

Pure Python standard library — zero third-party dependencies.
Inspired by Aider's revolutionary Repo Map architecture:
1. Builds a graph of symbols and cross-file references across Python/TS/Rust/Go/Java.
2. Applies standard PageRank algorithm (damping=0.85) to calculate topological importance.
3. Formats a high-density, tree-sitter style architectural skeleton map for LLM prompts.
"""
from __future__ import annotations

import collections
from typing import Any
from pathlib import Path

from baize.symbol_graph import SymbolGraph, build_workspace_symbol_graph

__all__ = [
    "RepoMapGenerator",
    "generate_workspace_repo_map",
]


class RepoMapGenerator:
    """Computes PageRank weights over code symbols and formats compact repo map."""
    def __init__(self, graph: SymbolGraph):
        self.graph = graph
        self.pagerank_scores: dict[str, float] = {}

    def compute_pagerank(self, iterations: int = 20, damping: float = 0.85) -> dict[str, float]:
        """Compute PageRank scores across all indexed symbol nodes."""
        all_nodes = [node for nodes in self.graph.symbols.values() for node in nodes]
        if not all_nodes:
            return {}

        total_nodes = len(all_nodes)
        node_names = [n.name for n in all_nodes]
        
        # Build adjacency graph based on function/method calls
        out_links: dict[str, list[str]] = collections.defaultdict(list)
        in_links: dict[str, list[str]] = collections.defaultdict(list)

        for n in all_nodes:
            for call in n.calls:
                out_links[n.name].append(call)
                in_links[call].append(n.name)

        # Initialize uniform scores
        scores = {name: 1.0 / total_nodes for name in node_names}

        # PageRank power iterations
        for _ in range(iterations):
            new_scores = {}
            for name in node_names:
                incoming_sum = 0.0
                for caller in in_links.get(name, []):
                    c_out_count = len(out_links.get(caller, []))
                    if c_out_count > 0:
                        incoming_sum += scores.get(caller, 0.0) / c_out_count

                new_scores[name] = ((1.0 - damping) / total_nodes) + (damping * incoming_sum)

            # Normalize scores
            s_sum = sum(new_scores.values()) or 1.0
            scores = {k: v / s_sum for k, v in new_scores.items()}

        self.pagerank_scores = scores
        return scores

    def generate_repo_map(self, max_symbols: int = 40) -> str:
        """Generate high-density structural code skeleton map."""
        if not self.pagerank_scores:
            self.compute_pagerank()

        # Group symbols by file path
        file_to_nodes: dict[str, list[tuple[float, Any]]] = collections.defaultdict(list)
        for name, nodes in self.graph.symbols.items():
            score = self.pagerank_scores.get(name, 0.0)
            for node in nodes:
                file_to_nodes[node.file_path].append((score, node))

        # Sort files by sum of their symbol scores descending
        sorted_files = sorted(
            file_to_nodes.items(),
            key=lambda item: sum(score for score, _ in item[1]),
            reverse=True
        )

        lines = [
            "=== 🌲 [BAIZE PAGERANK REPO MAP · 全局核心架构骨架图] ===",
            "// 自动按拓扑引用重要度精炼，包含核心类、接口与顶层方法签名：",
        ]

        emitted_symbols = 0
        for file_path, scored_nodes in sorted_files:
            if emitted_symbols >= max_symbols:
                break

            # Deduplicate and sort symbols within file
            seen = set()
            unique_nodes = []
            for sc, n in sorted(scored_nodes, key=lambda x: x[0], reverse=True):
                if n.name not in seen:
                    seen.add(n.name)
                    unique_nodes.append((sc, n))

            lines.append(f"\n📁 {file_path}:")
            for sc, node in unique_nodes:
                sig = node.signature or f"{node.kind} {node.name}"
                lines.append(f"  │ {sig}  [L{node.line_number}]")
                emitted_symbols += 1
                if emitted_symbols >= max_symbols:
                    break

        lines.append("\n=======================================================")
        return "\n".join(lines)


def generate_workspace_repo_map(root_dir: str = ".", max_symbols: int = 40) -> str:
    """Helper to generate workspace repo map."""
    graph = build_workspace_symbol_graph(root_dir)
    gen = RepoMapGenerator(graph)
    return gen.generate_repo_map(max_symbols=max_symbols)
