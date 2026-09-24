"""Hierarchical Codebase Architecture & Interface Skeleton Map (V39.0.0 Aegis).

Pure Python standard library — zero third-party dependencies.
Provides multi-tier progressive codebase architecture projection for 100k+ line codebases:
1. Level 1: Package & Module Boundary Topology (Domain responsibilities)
2. Level 2: PageRank-Weighted Interface Skeletons (Signatures + Docstrings, bodies stubbed out)
3. Level 3: Strict Adaptive Token Budgeting (Stays under ~3,000 tokens / 12,000 chars)
"""
from __future__ import annotations

import collections
import os
from pathlib import Path
from typing import Any

from .config import ROOT, load_config
from .symbol_graph import SymbolGraph, SymbolNode
from .arch_cache import get_cached_symbol_graph
from .repo_map import RepoMapGenerator

__all__ = [
    "HierarchicalRepoMap",
    "get_hierarchical_repo_map",
]


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

        # Group symbols by file, scored by PageRank
        file_to_nodes: dict[str, list[tuple[float, SymbolNode]]] = collections.defaultdict(list)
        for name, nodes in self.graph.symbols.items():
            score = pagerank.get(name, 0.0)
            for node in nodes:
                file_to_nodes[node.file_path].append((score, node))

        # Sort files by sum of their symbol scores descending
        sorted_files = sorted(
            file_to_nodes.items(),
            key=lambda item: sum(score for score, _ in item[1]),
            reverse=True
        )

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
