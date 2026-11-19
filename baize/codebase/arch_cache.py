"""Architecture & Symbol Graph Incremental Persistent Cache (V39.0.0 Aegis).

Pure Python standard library — zero third-party dependencies.
Maintains both a disk-backed incremental AST cache and a fast thread-safe
in-process warm cache (validated via TTL and fast os.scandir), avoiding repeated
full-repo AST walks or JSON deserialization on hot paths.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from ..core.config import ROOT, load_config
from .symbol_graph import SKIP_DIRS as _SKIP_DIRS
from .symbol_graph import SUPPORTED_EXTS as _SUPPORTED_EXTS
from .symbol_graph import SymbolGraph, SymbolNode

__all__ = [
    "ArchCacheManager",
    "get_cached_symbol_graph",
    "invalidate_arch_cache",
    "get_arch_cache_stats",
]


_INPROC_LOCK = threading.RLock()
_INPROC_CACHE: dict[tuple[str, str], tuple[float, SymbolGraph, dict[str, dict[str, Any]]]] = {}
_CACHE_STATS: dict[str, int] = {"inproc_hits": 0, "disk_hits": 0, "rebuilds": 0}


def invalidate_arch_cache() -> None:
    """Clear the process-local warm SymbolGraph cache."""
    with _INPROC_LOCK:
        _INPROC_CACHE.clear()


def get_arch_cache_stats() -> dict[str, int]:
    """Return real in-process and disk cache hit/miss counters."""
    with _INPROC_LOCK:
        return dict(_CACHE_STATS)


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
        self._lock = threading.RLock()

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
        """Atomically persist cache data to disk (thread-safe unique temp file)."""
        with self._lock:
            try:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "version": "1.0",
                    "updated_at": time.time(),
                    "file_count": len(self.cache_data),
                    "files": self.cache_data,
                }
                fd, tmp_name = tempfile.mkstemp(
                    dir=str(self.cache_file.parent),
                    prefix=self.cache_file.stem + ".",
                    suffix=".tmp",
                )
                tmp_path = Path(tmp_name)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        json.dump(payload, fh, ensure_ascii=False)
                    tmp_path.replace(self.cache_file)
                except Exception:
                    tmp_path.unlink(missing_ok=True)
                    raise
            except Exception:
                pass

    def sync_workspace(
        self,
        root_dir: str | Path | None = None,
        max_files: int = 3000,
    ) -> SymbolGraph:
        """Incrementally sync the workspace symbol graph using fast os.scandir mtime & size checks."""
        self.load()
        root = Path(root_dir or self.cfg.get("BAIZE_WORKSPACE_DIR", str(ROOT))).resolve()
        root_str = str(root)
        graph = SymbolGraph(root_str)

        current_files: set[str] = set()
        dirty = False
        files_scanned = 0

        stack = [root_str]
        while stack and files_scanned < max_files:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    entries = list(it)
            except OSError:
                continue

            for entry in entries:
                name = entry.name
                if entry.is_dir(follow_symlinks=False):
                    if not name.startswith(".") and name not in _SKIP_DIRS:
                        stack.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                _, ext = os.path.splitext(name)
                ext = ext.lower()
                lang = _SUPPORTED_EXTS.get(ext)
                if not lang:
                    continue

                try:
                    stat = entry.stat(follow_symlinks=False)
                    mtime = stat.st_mtime
                    size = stat.st_size
                except OSError:
                    continue

                rel_path = os.path.relpath(entry.path, root_str).replace("\\", "/")
                current_files.add(rel_path)
                graph.languages_detected.add(lang)

                cached = self.cache_data.get(rel_path)
                if cached and cached.get("mtime") == mtime and cached.get("size") == size:
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
                        if "." in node.name:
                            unqualified = node.name.rsplit(".", 1)[-1]
                            graph.symbols.setdefault(unqualified, []).append(node)
                    graph.file_symbols[rel_path] = nodes
                    graph.file_imports[rel_path] = cached.get("imports", [])
                else:
                    full_path = Path(entry.path)
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

        deleted = set(self.cache_data.keys()) - current_files
        if deleted:
            for d in deleted:
                self.cache_data.pop(d, None)
            dirty = True

        graph.total_files_indexed = files_scanned
        if dirty:
            self.save()
            with _INPROC_LOCK:
                _CACHE_STATS["rebuilds"] += 1
        else:
            with _INPROC_LOCK:
                _CACHE_STATS["disk_hits"] += 1
        return graph


def get_cached_symbol_graph(
    root_dir: str | Path | None = None,
    cfg: dict | None = None,
    *,
    force_refresh: bool = False,
) -> SymbolGraph:
    """Obtain an incrementally-cached SymbolGraph (uses fast in-process warm TTL cache)."""
    cfg = cfg or load_config()
    root_resolved = str(Path(root_dir or cfg.get("BAIZE_WORKSPACE_DIR", str(ROOT))).resolve())
    cache_file = str(Path(cfg.get("BAIZE_PERSISTENCE_DIR", str(ROOT / "persistence"))) / "arch_cache.json")
    try:
        ttl = float(cfg.get("BAIZE_ARCH_CACHE_TTL", "2.0"))
    except (ValueError, TypeError):
        ttl = 2.0

    key = (root_resolved, cache_file)
    now = time.monotonic()
    if not force_refresh and ttl > 0:
        with _INPROC_LOCK:
            cached = _INPROC_CACHE.get(key)
            if cached and (now - cached[0]) <= ttl:
                _CACHE_STATS["inproc_hits"] += 1
                return cached[1]

    manager = ArchCacheManager(cache_file=cache_file, cfg=cfg)
    graph = manager.sync_workspace(root_dir=root_resolved)
    with _INPROC_LOCK:
        _INPROC_CACHE[key] = (time.monotonic(), graph, manager.cache_data)
    return graph
