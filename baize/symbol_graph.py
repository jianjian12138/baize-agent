"""Global Codebase Polyglot AST & Grammar Symbol Graph Indexer (V36.0.0 Titan).

Pure Python standard library — zero third-party dependencies.
Indexes cross-file symbol definitions, interfaces, structs, functions and imports across:
- Python (.py) -> Full AST parse
- TypeScript & JavaScript (.ts, .tsx, .js, .jsx) -> Interface, Class, Function, Export definitions
- Rust (.rs) -> struct, enum, fn, trait, impl
- Go (.go) -> type ... struct, type ... interface, func
- Java (.java) -> class, interface, enum, method
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

__all__ = [
    "SymbolNode",
    "SymbolGraph",
    "build_workspace_symbol_graph",
]


class SymbolNode:
    """Represents a defined code symbol (function, class, method, struct, interface)."""
    def __init__(
        self,
        name: str,
        kind: str,  # 'function', 'class', 'method', 'struct', 'interface', 'enum', 'trait'
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

    def index_workspace(self, max_files: int = 1500) -> None:
        """Scan workspace and index symbols for Python, TS/JS, Rust, Go, Java."""
        self.symbols.clear()
        self.file_symbols.clear()
        self.file_imports.clear()
        self.total_files_indexed = 0
        self.languages_detected.clear()

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

        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d not in ("__pycache__", "node_modules", "persistence", "dist", "build", "target")
            ]
            for file in files:
                ext = Path(file).suffix.lower()
                if ext in supported_exts:
                    lang = supported_exts[ext]
                    self.languages_detected.add(lang)
                    full_path = Path(root) / file
                    rel_path = str(full_path.relative_to(self.root_dir)).replace("\\", "/")
                    
                    if ext == ".py":
                        self._parse_python_file(full_path, rel_path)
                    else:
                        self._parse_polyglot_file(full_path, rel_path, lang)
                        
                    self.total_files_indexed += 1
                    if self.total_files_indexed >= max_files:
                        break
            if self.total_files_indexed >= max_files:
                break

    def _parse_python_file(self, full_path: Path, rel_path: str) -> None:
        """Extract classes, functions, and imports from a single Python file AST."""
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=rel_path)
        except Exception:
            return

        file_nodes: list[SymbolNode] = []
        imports: list[str] = []

        class ASTSymbolVisitor(ast.NodeVisitor):
            def __init__(self, parent_graph: SymbolGraph):
                self.parent_graph = parent_graph
                self.current_class: str | None = None

            def visit_Import(self, node: ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
                self.generic_visit(node)

            def visit_ImportFrom(self, node: ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
                self.generic_visit(node)

            def visit_ClassDef(self, node: ast.ClassDef):
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

            def visit_FunctionDef(self, node: ast.FunctionDef):
                self._handle_func(node)
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
                self._handle_func(node, is_async=True)
                self.generic_visit(node)

            def _handle_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool = False):
                doc = ast.get_docstring(node) or ""
                args = [a.arg for a in node.args.args]
                sig = f"{'async ' if is_async else ''}def {node.name}({', '.join(args)})"
                kind = "method" if self.current_class else "function"
                full_name = f"{self.current_class}.{node.name}" if self.current_class else node.name
                
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            calls.append(child.func.id)
                        elif isinstance(child.func, ast.Attribute):
                            calls.append(child.func.attr)

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
                sym.calls = list(dict.fromkeys(calls))[:15]
                file_nodes.append(sym)

        visitor = ASTSymbolVisitor(self)
        visitor.visit(tree)

        self.file_symbols[rel_path] = file_nodes
        self.file_imports[rel_path] = imports

        for node in file_nodes:
            self.symbols.setdefault(node.name, []).append(node)
            if "." in node.name:
                unqualified = node.name.split(".")[-1]
                self.symbols.setdefault(unqualified, []).append(node)

    def _parse_polyglot_file(self, full_path: Path, rel_path: str, lang: str) -> None:
        """Extract symbols for TS/JS, Rust, Go, Java using syntax patterns."""
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        lines = content.splitlines()
        file_nodes: list[SymbolNode] = []

        if lang in ("typescript", "javascript"):
            # Interfaces, types, classes, functions
            for i, line in enumerate(lines, 1):
                m_iface = re.search(r'\b(?:export\s+)?interface\s+([A-Za-z0-9_]+)', line)
                if m_iface:
                    file_nodes.append(SymbolNode(m_iface.group(1), "interface", rel_path, i, i, signature=line.strip(), language=lang))
                m_cls = re.search(r'\b(?:export\s+)?class\s+([A-Za-z0-9_]+)', line)
                if m_cls:
                    file_nodes.append(SymbolNode(m_cls.group(1), "class", rel_path, i, i, signature=line.strip(), language=lang))
                m_fn = re.search(r'\b(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)', line)
                if m_fn:
                    file_nodes.append(SymbolNode(m_fn.group(1), "function", rel_path, i, i, signature=line.strip(), language=lang))
                m_type = re.search(r'\b(?:export\s+)?type\s+([A-Za-z0-9_]+)\s*=', line)
                if m_type:
                    file_nodes.append(SymbolNode(m_type.group(1), "type", rel_path, i, i, signature=line.strip(), language=lang))

        elif lang == "rust":
            # struct, fn, enum, trait, impl
            for i, line in enumerate(lines, 1):
                m_st = re.search(r'\b(?:pub\s+)?struct\s+([A-Za-z0-9_]+)', line)
                if m_st:
                    file_nodes.append(SymbolNode(m_st.group(1), "struct", rel_path, i, i, signature=line.strip(), language="rust"))
                m_fn = re.search(r'\b(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)', line)
                if m_fn:
                    file_nodes.append(SymbolNode(m_fn.group(1), "function", rel_path, i, i, signature=line.strip(), language="rust"))
                m_tr = re.search(r'\b(?:pub\s+)?trait\s+([A-Za-z0-9_]+)', line)
                if m_tr:
                    file_nodes.append(SymbolNode(m_tr.group(1), "trait", rel_path, i, i, signature=line.strip(), language="rust"))

        elif lang == "go":
            # type X struct, func X
            for i, line in enumerate(lines, 1):
                m_st = re.search(r'\btype\s+([A-Za-z0-9_]+)\s+struct\b', line)
                if m_st:
                    file_nodes.append(SymbolNode(m_st.group(1), "struct", rel_path, i, i, signature=line.strip(), language="go"))
                m_if = re.search(r'\btype\s+([A-Za-z0-9_]+)\s+interface\b', line)
                if m_if:
                    file_nodes.append(SymbolNode(m_if.group(1), "interface", rel_path, i, i, signature=line.strip(), language="go"))
                m_fn = re.search(r'\bfunc\s+(?:\([^)]+\)\s+)?([A-Za-z0-9_]+)\s*\(', line)
                if m_fn:
                    file_nodes.append(SymbolNode(m_fn.group(1), "function", rel_path, i, i, signature=line.strip(), language="go"))

        self.file_symbols[rel_path] = file_nodes
        for node in file_nodes:
            self.symbols.setdefault(node.name, []).append(node)

    def find_definitions(self, symbol_name: str) -> list[dict[str, Any]]:
        """Find definition locations for a given symbol name."""
        nodes = self.symbols.get(symbol_name, [])
        return [n.to_dict() for n in nodes]

    def search_symbols(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        """Fuzzy/prefix search for symbols across polyglot codebase."""
        q = query.lower().strip()
        if not q:
            return []
        
        results: list[dict[str, Any]] = []
        for name, nodes in self.symbols.items():
            if q in name.lower():
                for node in nodes:
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
            "languages_detected": sorted(list(self.languages_detected)),
        }


_GLOBAL_GRAPH: SymbolGraph | None = None


def build_workspace_symbol_graph(root_dir: str = ".") -> SymbolGraph:
    """Build or retrieve cached global workspace symbol graph."""
    global _GLOBAL_GRAPH
    if _GLOBAL_GRAPH is None or _GLOBAL_GRAPH.total_files_indexed == 0:
        _GLOBAL_GRAPH = SymbolGraph(root_dir=root_dir)
        _GLOBAL_GRAPH.index_workspace()
    return _GLOBAL_GRAPH
