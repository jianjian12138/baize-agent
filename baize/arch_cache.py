"""Architecture & Symbol Graph Incremental Persistent Cache (V39.0.0 Aegis).

Pure Python standard library — zero third-party dependencies.
Maintains an incremental AST symbol and dependency cache across large-scale
codebases (100k+ lines), avoiding repeated expensive full-repo AST walks.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .config import ROOT, load_config
from .symbol_graph import SymbolGraph, SymbolNode

__all__ = [
    "ArchCacheManager",
    "get_cached_symbol_graph",
]


class ArchCacheManager:
    """Manages incremental filesystem scanning and serialization for SymbolGraph."""

    def __init__(self, cache_file: str | Path | None = None, cfg: dict | None = None):
        self.cfg = cfg or load_config()
        if cache_file:
            self.cache_file = Path(cache_file)
        else:
            persist_dir = Path(self.cfg.get("BAIZE_PERSISTENCE_DIR", str(ROOT / "persistence")))
            self.cache_file = persist_dir / "arch_cache.json"

        self.cache_data: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def load(self) -> dict[str, dict[str, Any]]:
        """Load cached AST symbols and file stats from JSON."""
        if self._loaded:
            return self.cache_data
        if self.cache_file.exists():
            try:
                content = self.cache_file.read_text(encoding="utf-8", errors="replace")
                data = json.loads(content)
                if isinstance(data, dict):
                    self.cache_data = data.get("files", {})
            except Exception:
                self.cache_data = {}
        self._loaded = True
        return self.cache_data

    def save(self) -> None:
        """Atomically persist cache data to disk."""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": "1.0",
                "updated_at": time.time(),
                "file_count": len(self.cache_data),
                "files": self.cache_data,
            }
            tmp = self.cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.cache_file)
        except Exception:
            pass

    def sync_workspace(
        self,
        root_dir: str | Path | None = None,
        max_files: int = 3000,
    ) -> SymbolGraph:
        """Incrementally sync the workspace symbol graph using mtime & file size."""
        self.load()
        root = Path(root_dir or self.cfg.get("BAIZE_WORKSPACE_DIR", str(ROOT))).resolve()
        graph = SymbolGraph(str(root))

        supported_exts = {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
        }

        current_files: set[str] = set()
        dirty = False
        files_scanned = 0

        for r, dirs, files in os.walk(root):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d not in ("__pycache__", "node_modules", "persistence", "dist", "build", "target", ".git", "venv", ".venv")
            ]
            for file in files:
                ext = Path(file).suffix.lower()
                if ext in supported_exts:
                    full_path = Path(r) / file
                    try:
                        stat = full_path.stat()
                        mtime = stat.st_mtime
                        size = stat.st_size
                    except OSError:
                        continue

                    rel_path = str(full_path.relative_to(root)).replace("\\", "/")
                    current_files.add(rel_path)
                    lang = supported_exts[ext]
                    graph.languages_detected.add(lang)

                    cached = self.cache_data.get(rel_path)
                    if cached and cached.get("mtime") == mtime and cached.get("size") == size:
                        # Reconstitute symbol nodes from cache
                        nodes: list[SymbolNode] = []
                        for s_dict in cached.get("symbols", []):
                            node = SymbolNode(
                                name=s_dict["name"],
                                kind=s_dict["kind"],
                                file_path=s_dict["file_path"],
                                line_number=s_dict["line_number"],
                                end_line_number=s_dict.get("end_line_number", s_dict["line_number"]),
                                docstring=s_dict.get("docstring", ""),
                                signature=s_dict.get("signature", ""),
                                language=s_dict.get("language", lang),
                            )
                            node.calls = s_dict.get("calls", [])
                            nodes.append(node)
                            graph.symbols.setdefault(node.name, []).append(node)

                        graph.file_symbols[rel_path] = nodes
                        graph.file_imports[rel_path] = cached.get("imports", [])
                    else:
                        # File modified or new -> parse via graph
                        if ext == ".py":
                            graph._parse_python_file(full_path, rel_path)
                        else:
                            graph._parse_polyglot_file(full_path, rel_path, lang)

                        parsed_nodes = graph.file_symbols.get(rel_path, [])
                        parsed_imports = graph.file_imports.get(rel_path, [])
                        self.cache_data[rel_path] = {
                            "mtime": mtime,
                            "size": size,
                            "language": lang,
                            "symbols": [n.to_dict() for n in parsed_nodes],
                            "imports": parsed_imports,
                        }
                        dirty = True

                    files_scanned += 1
                    if files_scanned >= max_files:
                        break
            if files_scanned >= max_files:
                break

        # Evict deleted files from cache
        deleted = set(self.cache_data.keys()) - current_files
        if deleted:
            for d in deleted:
                self.cache_data.pop(d, None)
            dirty = True

        graph.total_files_indexed = files_scanned
        if dirty:
            self.save()

        return graph


def get_cached_symbol_graph(root_dir: str | Path | None = None, cfg: dict | None = None) -> SymbolGraph:
    """Convenience helper to obtain an incrementally-cached SymbolGraph."""
    manager = ArchCacheManager(cfg=cfg)
    return manager.sync_workspace(root_dir=root_dir)
