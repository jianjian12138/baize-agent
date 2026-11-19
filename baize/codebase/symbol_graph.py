"""Global Codebase Polyglot AST & Grammar Symbol Graph Indexer (V36.0.0 Titan).

Pure Python standard library — zero third-party dependencies.
Indexes cross-file symbol definitions, interfaces, structs, functions and imports across:
- Python (.py) -> Full AST parse (single-pass non-quadratic call collector)
- TypeScript & JavaScript (.ts, .tsx, .js, .jsx) -> Precompiled grammar patterns
- Rust (.rs) -> struct, enum, fn, trait, impl
- Go (.go) -> type ... struct, type ... interface, func
- Java (.java) -> class, interface, enum, method
"""
from __future__ import annotations

import ast
import os
import re
import threading
from pathlib import Path
from typing import Any

__all__ = [
    "SUPPORTED_EXTS",
    "SKIP_DIRS",
    "SymbolNode",
    "SymbolGraph",
    "build_workspace_symbol_graph",
    "clear_symbol_graph_cache",
]

SUPPORTED_EXTS: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
}

SKIP_DIRS = frozenset({
    "__pycache__", "node_modules", "persistence", "dist", "build", "target", "venv", ".venv",
})

# Backward-compatible internal aliases
_SUPPORTED_EXTS = SUPPORTED_EXTS
_SKIP_DIRS = SKIP_DIRS

# Precompiled polyglot extraction patterns
_RE_TS_IFACE = re.compile(r"\b(?:export\s+)?interface\s+([A-Za-z0-9_]+)")
_RE_TS_CLASS = re.compile(r"\b(?:export\s+)?class\s+([A-Za-z0-9_]+)")
_RE_TS_FUNC = re.compile(r"\b(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)")
_RE_TS_TYPE = re.compile(r"\b(?:export\s+)?type\s+([A-Za-z0-9_]+)\s*=")

_RE_RS_STRUCT = re.compile(r"\b(?:pub\s+)?struct\s+([A-Za-z0-9_]+)")
_RE_RS_FN = re.compile(r"\b(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)")
_RE_RS_TRAIT = re.compile(r"\b(?:pub\s+)?trait\s+([A-Za-z0-9_]+)")

_RE_GO_STRUCT = re.compile(r"\btype\s+([A-Za-z0-9_]+)\s+struct\b")
_RE_GO_IFACE = re.compile(r"\btype\s+([A-Za-z0-9_]+)\s+interface\b")
_RE_GO_FUNC = re.compile(r"\bfunc\s+(?:\([^)]+\)\s+)?([A-Za-z0-9_]+)\s*\(")

_RE_JAVA_DECL = re.compile(r"\b(?:public|private|protected)?\s*(?:abstract\s+|final\s+)?(class|interface|enum)\s+([A-Za-z0-9_]+)")


class _DirectCallCollector(ast.NodeVisitor):
    """Collect direct function/attribute call names inside a single scope without recursing into nested defs."""

    __slots__ = ("calls", "_seen")

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._seen: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        if len(self.calls) < 15:
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if name and name not in self._seen:
                self._seen.add(name)
                self.calls.append(name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return  # handled by outer ASTSymbolVisitor

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


class SymbolNode:
    """Represents a defined code symbol (function, class, method, struct, interface)."""

    __slots__ = (
        "name", "kind", "file_path", "line_number", "end_line_number",
        "docstring", "signature", "language", "references", "calls",
    )

    def __init__(
        self,
        name: str,
        kind: str,
        file_path: str,
        line_number: int,
        end_line_number: int,
        docstring: str = "",
        signature: str = "",
        language: str = "python",
    ):
        self.name = name
        self.kind = kind
        self.file_path = file_path.replace("\\", "/")
        self.line_number = line_number
        self.end_line_number = end_line_number
        self.docstring = docstring.strip() if docstring else ""
        self.signature = signature
        self.language = language
        self.references: list[dict[str, Any]] = []
        self.calls: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "language": self.language,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "end_line_number": self.end_line_number,
            "docstring": self.docstring,
            "signature": self.signature,
            "references_count": len(self.references),
            "calls": self.calls[:10],
        }


class SymbolGraph:
    """In-memory polyglot symbol graph indexing definitions, references, and dependencies."""

    def __init__(self, root_dir: str = "."):
        self.root_dir = Path(root_dir).resolve()
        self.symbols: dict[str, list[SymbolNode]] = {}
        self.file_symbols: dict[str, list[SymbolNode]] = {}
        self.file_imports: dict[str, list[str]] = {}
        self.total_files_indexed = 0
        self.languages_detected: set[str] = set()

    def build(self, max_files: int = 1500) -> None:
        """Alias for index_workspace."""
        self.index_workspace(max_files=max_files)

    def iter_unique_nodes(self) -> list[SymbolNode]:
        """Return deduplicated list of defined SymbolNode objects (preserving insertion order)."""
        nodes: list[SymbolNode] = []
        for f_nodes in self.file_symbols.values():
            nodes.extend(f_nodes)
        return nodes

    def index_workspace(self, max_files: int = 1500) -> None:
        """Scan workspace using fast os.scandir and index symbols."""
        self.symbols.clear()
        self.file_symbols.clear()
        self.file_imports.clear()
        self.total_files_indexed = 0
        self.languages_detected.clear()

        root_str = str(self.root_dir)
        stack = [root_str]
        while stack and self.total_files_indexed < max_files:
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
                self.languages_detected.add(lang)
                rel_path = os.path.relpath(entry.path, root_str).replace("\\", "/")
                full_path = Path(entry.path)
                if ext == ".py":
                    self._parse_python_file(full_path, rel_path)
                else:
                    self._parse_polyglot_file(full_path, rel_path, lang)
                self.total_files_indexed += 1
                if self.total_files_indexed >= max_files:
                    break

    def _parse_python_file(self, full_path: Path, rel_path: str) -> None:
        """Parse Python AST for imports, classes, functions, methods, docstrings, and direct calls."""
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=rel_path)
        except Exception:
            return

        file_nodes: list[SymbolNode] = []
        imports: list[str] = []
        symbols_dict = self.symbols

        class ASTSymbolVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.current_class: str | None = None

            def visit_Import(self, node: ast.Import) -> None:
                for alias in node.names:
                    imports.append(alias.name)

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                if node.module:
                    imports.append(node.module)

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                doc = ast.get_docstring(node) or ""
                sym = SymbolNode(
                    name=node.name,
                    kind="class",
                    file_path=rel_path,
                    line_number=node.lineno,
                    end_line_number=getattr(node, "end_lineno", node.lineno),
                    docstring=doc,
                    signature=f"class {node.name}",
                    language="python",
                )
                file_nodes.append(sym)
                old_class = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = old_class

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._handle_func(node, is_async=False)
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._handle_func(node, is_async=True)
                self.generic_visit(node)

            def _handle_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool = False) -> None:
                doc = ast.get_docstring(node) or ""
                args = [a.arg for a in node.args.args]
                sig = f"{'async ' if is_async else ''}def {node.name}({', '.join(args)})"
                kind = "method" if self.current_class else "function"
                full_name = f"{self.current_class}.{node.name}" if self.current_class else node.name

                collector = _DirectCallCollector()
                for stmt in node.body:
                    collector.visit(stmt)

                sym = SymbolNode(
                    name=full_name,
                    kind=kind,
                    file_path=rel_path,
                    line_number=node.lineno,
                    end_line_number=getattr(node, "end_lineno", node.lineno),
                    docstring=doc,
                    signature=sig,
                    language="python",
                )
                sym.calls = collector.calls
                file_nodes.append(sym)

        ASTSymbolVisitor().visit(tree)
        self.file_symbols[rel_path] = file_nodes
        self.file_imports[rel_path] = imports
        for node in file_nodes:
            symbols_dict.setdefault(node.name, []).append(node)
            if "." in node.name:
                unqualified = node.name.rsplit(".", 1)[-1]
                symbols_dict.setdefault(unqualified, []).append(node)

    def _parse_polyglot_file(self, full_path: Path, rel_path: str, lang: str) -> None:
        """Extract symbols for TS/JS, Rust, Go, Java using precompiled patterns + keyword prefilter."""
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        file_nodes: list[SymbolNode] = []
        lines = content.splitlines()
        if lang in ("typescript", "javascript"):
            for i, line in enumerate(lines, 1):
                if ("interface " not in line and "class " not in line
                        and "function " not in line and "type " not in line):
                    continue
                if "interface " in line:
                    m = _RE_TS_IFACE.search(line)
                    if m:
                        file_nodes.append(SymbolNode(m.group(1), "interface", rel_path, i, i, signature=line.strip(), language=lang))
                if "class " in line:
                    m = _RE_TS_CLASS.search(line)
                    if m:
                        file_nodes.append(SymbolNode(m.group(1), "class", rel_path, i, i, signature=line.strip(), language=lang))
                if "function " in line:
                    m = _RE_TS_FUNC.search(line)
                    if m:
                        file_nodes.append(SymbolNode(m.group(1), "function", rel_path, i, i, signature=line.strip(), language=lang))
                if "type " in line:
                    m = _RE_TS_TYPE.search(line)
                    if m:
                        file_nodes.append(SymbolNode(m.group(1), "type", rel_path, i, i, signature=line.strip(), language=lang))
        elif lang == "rust":
            for i, line in enumerate(lines, 1):
                if "struct " not in line and "fn " not in line and "trait " not in line:
                    continue
                if "struct " in line:
                    m = _RE_RS_STRUCT.search(line)
                    if m:
                        file_nodes.append(SymbolNode(m.group(1), "struct", rel_path, i, i, signature=line.strip(), language="rust"))
                if "fn " in line:
                    m = _RE_RS_FN.search(line)
                    if m:
                        file_nodes.append(SymbolNode(m.group(1), "function", rel_path, i, i, signature=line.strip(), language="rust"))
                if "trait " in line:
                    m = _RE_RS_TRAIT.search(line)
                    if m:
                        file_nodes.append(SymbolNode(m.group(1), "trait", rel_path, i, i, signature=line.strip(), language="rust"))
        elif lang == "go":
            for i, line in enumerate(lines, 1):
                if "type " not in line and "func " not in line:
                    continue
                if "type " in line:
                    m = _RE_GO_STRUCT.search(line)
                    if m:
                        file_nodes.append(SymbolNode(m.group(1), "struct", rel_path, i, i, signature=line.strip(), language="go"))
                    m_if = _RE_GO_IFACE.search(line)
                    if m_if:
                        file_nodes.append(SymbolNode(m_if.group(1), "interface", rel_path, i, i, signature=line.strip(), language="go"))
                if "func " in line:
                    m = _RE_GO_FUNC.search(line)
                    if m:
                        file_nodes.append(SymbolNode(m.group(1), "function", rel_path, i, i, signature=line.strip(), language="go"))
        elif lang == "java":
            for i, line in enumerate(lines, 1):
                if "class " not in line and "interface " not in line and "enum " not in line:
                    continue
                m = _RE_JAVA_DECL.search(line)
                if m:
                    file_nodes.append(SymbolNode(m.group(2), m.group(1), rel_path, i, i, signature=line.strip(), language="java"))

        self.file_symbols[rel_path] = file_nodes
        for node in file_nodes:
            self.symbols.setdefault(node.name, []).append(node)

    def find_definitions(self, symbol_name: str) -> list[dict[str, Any]]:
        """Find definition locations for a given symbol name."""
        return [n.to_dict() for n in self.symbols.get(symbol_name, [])]

    def search_symbols(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        """Fuzzy/prefix search for symbols across polyglot codebase."""
        q = query.lower().strip()
        if not q:
            return []
        results: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for name, nodes in self.symbols.items():
            if q in name.lower():
                for node in nodes:
                    nid = id(node)
                    if nid in seen_ids:
                        continue
                    seen_ids.add(nid)
                    results.append(node.to_dict())
                    if len(results) >= limit:
                        return results
        return results

    def get_summary(self) -> dict[str, Any]:
        """Return high-level summary of the code graph."""
        total_symbols = sum(len(nodes) for nodes in self.file_symbols.values())
        return {
            "total_files_indexed": self.total_files_indexed,
            "total_symbols": total_symbols,
            "unique_symbol_names": len(self.symbols),
            "files_count": len(self.file_symbols),
            "languages_detected": sorted(self.languages_detected),
        }


_GRAPH_LOCK = threading.RLock()
_GLOBAL_GRAPHS: dict[str, SymbolGraph] = {}


def clear_symbol_graph_cache() -> None:
    """Clear the module-level workspace symbol graph cache."""
    with _GRAPH_LOCK:
        _GLOBAL_GRAPHS.clear()


def build_workspace_symbol_graph(root_dir: str = ".") -> SymbolGraph:
    """Build or retrieve cached workspace symbol graph (keyed by resolved root_dir)."""
    key = str(Path(root_dir).resolve())
    with _GRAPH_LOCK:
        graph = _GLOBAL_GRAPHS.get(key)
        if graph is None or graph.total_files_indexed == 0:
            graph = SymbolGraph(root_dir=key)
            graph.index_workspace()
            _GLOBAL_GRAPHS[key] = graph
        return graph
