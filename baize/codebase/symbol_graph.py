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
    "strip_comments_and_strings",
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
    ".dart": "dart",
    ".kt": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
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
_RE_JAVA_METHOD = re.compile(r"\b(?:public|private|protected)\s+(?:static\s+)?(?:[A-Za-z0-9_<>\[\]]+\s+)+([A-Za-z_][A-Za-z0-9_]*)\s*\(")

_RE_DART_DECL = re.compile(r"\b(?:abstract\s+)?(class|mixin|enum|extension)\s+([A-Za-z0-9_]+)")
_RE_DART_FUNC = re.compile(r"^\s*(?:Future<[^>]+>|Stream<[^>]+>|void|int|double|bool|String|dynamic|[A-Z][A-Za-z0-9_<>?]*)\s+([a-z_][A-Za-z0-9_]*)\s*\(")

_RE_KT_DECL = re.compile(r"\b(?:data\s+|sealed\s+|abstract\s+)?(class|interface|object)\s+([A-Za-z0-9_]+)")
_RE_KT_FUNC = re.compile(r"\bfun\s+(?:<[^>]+>\s+)?([A-Za-z0-9_]+)\s*\(")

_RE_SWIFT_DECL = re.compile(r"\b(class|struct|protocol|enum)\s+([A-Za-z0-9_]+)")
_RE_SWIFT_FUNC = re.compile(r"\bfunc\s+([A-Za-z0-9_]+)\s*\(")

_RE_CPP_DECL = re.compile(r"\b(class|struct|enum)\s+([A-Za-z_][A-Za-z0-9_]*)\s*[:{]")
_RE_CPP_FUNC = re.compile(r"^\s*(?:static\s+|inline\s+|virtual\s+)?[A-Za-z_][A-Za-z0-9_:*&<>\s]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*\)\s*(?:const\s*)?\{?")

_RE_CS_DECL = re.compile(r"\b(?:public|private|internal|protected)?\s*(?:sealed\s+|abstract\s+|static\s+|partial\s+)?(class|interface|record|struct|enum)\s+([A-Za-z0-9_]+)")

_RE_CALL_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_CALL_KEYWORDS = frozenset({
    "if", "for", "while", "switch", "catch", "return", "sizeof", "typeof",
    "new", "delete", "throw", "function", "func", "fn", "def", "class",
    "struct", "interface", "match", "else", "elif", "await", "async",
    "print", "println", "fmt", "len", "cap", "make", "append", "super", "this",
})


# Additional V47.0.0 Horizon lexical scope & import regexes (pure stdlib)
_RE_TS_METHOD = re.compile(
    r"^\s*(?:public\s+|private\s+|protected\s+|static\s+|readonly\s+|override\s+|abstract\s+)*"
    r"(?:async\s+)?(?:get\s+|set\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*(?:<[^>{}()]+>)?\s*\([^)]*\)\s*(?::[^{=]+)?\{"
)
_RE_TS_ARROW_FN = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?::[^=]+)?=\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*(?::[^=]+)?=>"
)
_RE_RS_IMPL = re.compile(
    r"\bimpl(?:\s*<[^>]+>)?\s+(?:[A-Za-z0-9_:]+\s+for\s+)?([A-Za-z_][A-Za-z0-9_]*)"
)
_RE_RS_ENUM = re.compile(r"\b(?:pub(?:\([^)]*\))?\s+)?enum\s+([A-Za-z0-9_]+)")
_RE_GO_METHOD = re.compile(
    r"\bfunc\s+\(\s*[A-Za-z_][A-Za-z0-9_]*\s+\*?([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]+\])?\s*\)\s*([A-Za-z_][A-Za-z0-9_]*)\s*\("
)
_RE_SWIFT_EXT = re.compile(r"\bextension\s+([A-Za-z_][A-Za-z0-9_]*)")
_RE_CS_METHOD = re.compile(
    r"\b(?:public|private|internal|protected)\s+(?:static\s+|async\s+|virtual\s+|override\s+|sealed\s+)*"
    r"(?:[A-Za-z0-9_<>\[\]?]+\s+)+([A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^>]+>)?\s*\("
)

# Polyglot import patterns
_RE_IMP_TS_FROM = re.compile(r"""(?:import|export)\s+(?:[^'"]+?\s+from\s+)?['"]([^'"]+)['"]""")
_RE_IMP_TS_REQ = re.compile(r"""\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)""")
_RE_IMP_GO_SINGLE = re.compile(r'^\s*import\s+(?:[A-Za-z_.]+\s+)?"([^"]+)"')
_RE_IMP_GO_ITEM = re.compile(r'^\s*(?:[A-Za-z_.]+\s+)?"([^"]+)"')
_RE_IMP_RS_USE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?use\s+([^;]+);")
_RE_IMP_RS_MOD = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+([A-Za-z_][A-Za-z0-9_]*)\s*;")
_RE_IMP_JAVA_KT_SWIFT = re.compile(r"^\s*import\s+(?:static\s+)?([A-Za-z0-9_.*]+)")
_RE_IMP_DART = re.compile(r"""^\s*(?:import|export|part)\s+['"]([^'"]+)['"]""")
_RE_IMP_CPP = re.compile(r"""^\s*#\s*include\s*[<"]([^>"]+)[>"]""")
_RE_IMP_CS = re.compile(r"^\s*using\s+(?:static\s+)?([A-Za-z0-9_.]+)\s*;")

_TS_METHOD_IGNORE = _CALL_KEYWORDS | frozenset({"constructor", "export", "import", "from", "default", "case", "try", "finally", "do"})


def strip_comments_and_strings(content: str, lang: str = "") -> str:
    """Pure-stdlib lexical scanner stripping comments and string literals while preserving exact line numbers.

    Every newline ``\n`` inside block comments or multi-line strings is preserved verbatim so
    ``strip_comments_and_strings(src).splitlines()`` has 1-to-1 line alignment with ``src.splitlines()``.
    """
    n = len(content)
    out: list[str] = []
    i = 0
    allow_backtick = lang in ("typescript", "javascript", "go", "")
    is_rust = lang == "rust"

    while i < n:
        ch = content[i]
        nxt = content[i + 1] if i + 1 < n else ""

        # Line comment // ...
        if ch == "/" and nxt == "/":
            i += 2
            out.append("  ")
            while i < n and content[i] != "\n":
                out.append(" ")
                i += 1
            continue

        # Block comment /* ... */ (supports nesting in Rust/Swift/Kotlin)
        if ch == "/" and nxt == "*":
            nested_supported = lang in ("rust", "swift", "kotlin")
            depth = 1
            i += 2
            out.append("  ")
            while i < n and depth > 0:
                c = content[i]
                c2 = content[i + 1] if i + 1 < n else ""
                if nested_supported and c == "/" and c2 == "*":
                    depth += 1
                    out.append("  ")
                    i += 2
                elif c == "*" and c2 == "/":
                    depth -= 1
                    out.append("  ")
                    i += 2
                elif c == "\n":
                    out.append("\n")
                    i += 1
                else:
                    out.append(" ")
                    i += 1
            continue

        # Rust raw string r#"..."# or r"..."
        if is_rust and ch == "r" and (nxt == "#" or nxt == '"'):
            j = i + 1
            hashes = 0
            while j < n and content[j] == "#":
                hashes += 1
                j += 1
            if j < n and content[j] == '"':
                out.append(" " * (j - i + 1))
                i = j + 1
                closing = '"' + ("#" * hashes)
                clen = len(closing)
                while i < n:
                    if content[i:i + clen] == closing:
                        out.append(" " * clen)
                        i += clen
                        break
                    out.append("\n" if content[i] == "\n" else " ")
                    i += 1
                continue

        # Double or single quoted string literals (skip Rust lifetime ticks like `'a`)
        if ch == '"' or (ch == "'" and not (is_rust and nxt.isalpha())):
            quote = ch
            # Check triple-quoted strings (Kotlin/Dart/Swift)
            if i + 2 < n and content[i + 1] == quote and content[i + 2] == quote:
                out.append("   ")
                i += 3
                while i < n:
                    if i + 2 < n and content[i] == quote and content[i + 1] == quote and content[i + 2] == quote:
                        out.append("   ")
                        i += 3
                        break
                    if content[i] == "\\" and i + 1 < n:
                        out.append(" ")
                        out.append("\n" if content[i + 1] == "\n" else " ")
                        i += 2
                        continue
                    out.append("\n" if content[i] == "\n" else " ")
                    i += 1
                continue

            out.append(" ")
            i += 1
            while i < n:
                c = content[i]
                if c == "\\" and i + 1 < n:
                    out.append(" ")
                    out.append("\n" if content[i + 1] == "\n" else " ")
                    i += 2
                    continue
                if c == quote:
                    out.append(" ")
                    i += 1
                    break
                if c == "\n":
                    out.append("\n")
                    i += 1
                    break
                out.append(" ")
                i += 1
            continue

        # Backtick template/raw strings (JS/TS/Go)
        if allow_backtick and ch == "`":
            out.append(" ")
            i += 1
            while i < n:
                c = content[i]
                if c == "\\" and lang != "go" and i + 1 < n:
                    out.append(" ")
                    out.append("\n" if content[i + 1] == "\n" else " ")
                    i += 2
                    continue
                if c == "`":
                    out.append(" ")
                    i += 1
                    break
                out.append("\n" if c == "\n" else " ")
                i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


_strip_comments_and_strings = strip_comments_and_strings


def _extract_polyglot_imports(raw_lines: list[str], clean_lines: list[str], lang: str) -> list[str]:
    """Extract module/package imports from non-comment lines across polyglot languages."""
    imports: list[str] = []
    seen: set[str] = set()

    def _add(mod: str) -> None:
        m = mod.strip()
        if m and m not in seen:
            seen.add(m)
            imports.append(m)

    in_go_import_block = False
    for raw, clean in zip(raw_lines, clean_lines):
        cs = clean.strip()
        if lang == "go" and in_go_import_block:
            if cs.startswith(")"):
                in_go_import_block = False
                continue
            rs = raw.strip()
            if rs and not rs.startswith("//") and not rs.startswith("/*"):
                m = _RE_IMP_GO_ITEM.match(raw)
                if m:
                    _add(m.group(1))
            continue
        if not cs:
            continue
        if lang in ("typescript", "javascript"):
            if "import" in cs or "export" in cs:
                for m in _RE_IMP_TS_FROM.finditer(raw):
                    _add(m.group(1))
            if "require" in cs:
                for m in _RE_IMP_TS_REQ.finditer(raw):
                    _add(m.group(1))
        elif lang == "go":
            if in_go_import_block:
                if cs.startswith(")"):
                    in_go_import_block = False
                    continue
                m = _RE_IMP_GO_ITEM.match(raw)
                if m:
                    _add(m.group(1))
                continue
            if cs.startswith("import") and "(" in cs and ")" not in cs:
                in_go_import_block = True
                continue
            if cs.startswith("import"):
                m = _RE_IMP_GO_SINGLE.match(raw)
                if m:
                    _add(m.group(1))
        elif lang == "rust":
            m = _RE_IMP_RS_USE.match(clean)
            if m:
                _add(m.group(1))
            mm = _RE_IMP_RS_MOD.match(clean)
            if mm:
                _add(mm.group(1))
        elif lang in ("java", "kotlin", "swift"):
            m = _RE_IMP_JAVA_KT_SWIFT.match(clean)
            if m:
                _add(m.group(1))
        elif lang == "dart":
            m = _RE_IMP_DART.match(raw)
            if m:
                _add(m.group(1))
        elif lang in ("c", "cpp"):
            m = _RE_IMP_CPP.match(raw)
            if m:
                _add(m.group(1))
        elif lang == "csharp":
            m = _RE_IMP_CS.match(clean)
            if m:
                _add(m.group(1))
    return imports


def _find_block_end(clean_lines: list[str], start_line_1idx: int) -> int:
    """Find the 1-indexed closing brace line for a block starting at/shortly after ``start_line_1idx``."""
    n = len(clean_lines)
    depth = 0
    opened = False
    search_limit = min(n, start_line_1idx + 4)
    for idx in range(start_line_1idx - 1, n):
        line = clean_lines[idx]
        if not opened and idx >= search_limit:
            return start_line_1idx
        for ch in line:
            if ch == "{":
                depth += 1
                opened = True
            elif ch == "}":
                if opened:
                    depth -= 1
                    if depth <= 0:
                        return idx + 1
        if not opened and ";" in line:
            return idx + 1
    return n if opened else start_line_1idx


def _extract_polyglot_calls(clean_lines: list[str], start_line_1idx: int, end_line_1idx: int, own_name: str) -> list[str]:
    """Extract direct identifier call names inside a comment/string-stripped polyglot function/method span."""
    seen: set[str] = set()
    calls: list[str] = []
    short_own = own_name.rsplit(".", 1)[-1]
    body_start = start_line_1idx if end_line_1idx > start_line_1idx else max(0, start_line_1idx - 1)
    snippet = "\n".join(clean_lines[body_start:end_line_1idx])
    for m in _RE_CALL_IDENT.finditer(snippet):
        name = m.group(1)
        if name == own_name or name == short_own or name in _CALL_KEYWORDS or name in seen:
            continue
        seen.add(name)
        calls.append(name)
        if len(calls) >= 15:
            break
    return calls


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
        """Lexical scope & call-chain extractor for TS/JS, Rust, Go, Java, Dart, Kotlin, Swift, C/C++, C#.

        Pure stdlib: strips comments and string literals before scanning, tracks brace-delimited
        container scopes (``class``/``struct``/``trait``/``impl``/``interface``/``extension``),
        qualifies nested methods as ``Container.method``, computes accurate ``(line_number, end_line_number)``
        block spans, extracts phantom-free calls strictly inside each symbol body, and populates
        ``self.file_imports[rel_path]``.
        """
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        raw_lines = content.splitlines()
        clean_content = strip_comments_and_strings(content, lang)
        clean_lines = clean_content.splitlines()
        if len(clean_lines) < len(raw_lines):
            clean_lines.extend([""] * (len(raw_lines) - len(clean_lines)))

        self.file_imports[rel_path] = _extract_polyglot_imports(raw_lines, clean_lines, lang)

        file_nodes: list[SymbolNode] = []
        container_stack: list[tuple[str, int]] = []

        def _active_container(cur_line: int) -> str | None:
            while container_stack and cur_line > container_stack[-1][1]:
                container_stack.pop()
            return container_stack[-1][0] if container_stack else None

        def _push_container(name: str, kind: str, line_no: int, sig: str, *, record_node: bool = True) -> None:
            end_no = _find_block_end(clean_lines, line_no)
            if record_node:
                file_nodes.append(
                    SymbolNode(name, kind, rel_path, line_no, end_no, signature=sig, language=lang)
                )
            if end_no > line_no:
                container_stack.append((name, end_no))

        def _add_callable(raw_name: str, kind: str, line_no: int, sig: str, *, explicit_owner: str | None = None) -> None:
            owner = explicit_owner or _active_container(line_no)
            qname = f"{owner}.{raw_name}" if (owner and "." not in raw_name) else raw_name
            eff_kind = "method" if (owner and kind == "function") else kind
            end_no = _find_block_end(clean_lines, line_no)
            file_nodes.append(
                SymbolNode(qname, eff_kind, rel_path, line_no, end_no, signature=sig, language=lang)
            )

        for i, clean in enumerate(clean_lines, 1):
            stripped = clean.strip()
            if not stripped:
                continue
            raw_sig = raw_lines[i - 1].strip() if i - 1 < len(raw_lines) else stripped
            owner = _active_container(i)

            if lang in ("typescript", "javascript"):
                if "interface " in stripped:
                    m = _RE_TS_IFACE.search(clean)
                    if m:
                        _push_container(m.group(1), "interface", i, raw_sig)
                        continue
                if "class " in stripped:
                    m = _RE_TS_CLASS.search(clean)
                    if m:
                        _push_container(m.group(1), "class", i, raw_sig)
                        continue
                if "function " in stripped:
                    m = _RE_TS_FUNC.search(clean)
                    if m:
                        _add_callable(m.group(1), "function", i, raw_sig)
                        continue
                if "type " in stripped:
                    m = _RE_TS_TYPE.search(clean)
                    if m:
                        end_no = _find_block_end(clean_lines, i)
                        file_nodes.append(SymbolNode(m.group(1), "type", rel_path, i, end_no, signature=raw_sig, language=lang))
                        continue
                if owner and "(" in stripped and "{" in stripped:
                    mm = _RE_TS_METHOD.match(clean)
                    if mm and mm.group(1) not in _TS_METHOD_IGNORE:
                        _add_callable(mm.group(1), "method", i, raw_sig)
                        continue
                if "=>" in stripped:
                    ma = _RE_TS_ARROW_FN.match(clean)
                    if ma and ma.group(1) not in _CALL_KEYWORDS:
                        _add_callable(ma.group(1), "function", i, raw_sig)
                        continue

            elif lang == "rust":
                if "struct " in stripped:
                    m = _RE_RS_STRUCT.search(clean)
                    if m:
                        _push_container(m.group(1), "struct", i, raw_sig)
                        continue
                if "enum " in stripped:
                    m = _RE_RS_ENUM.search(clean)
                    if m:
                        _push_container(m.group(1), "enum", i, raw_sig)
                        continue
                if "trait " in stripped:
                    m = _RE_RS_TRAIT.search(clean)
                    if m:
                        _push_container(m.group(1), "trait", i, raw_sig)
                        continue
                if stripped.startswith("impl ") or " impl " in clean or stripped.startswith("impl<"):
                    mi = _RE_RS_IMPL.search(clean)
                    if mi:
                        _push_container(mi.group(1), "impl", i, raw_sig, record_node=False)
                        continue
                if "fn " in stripped:
                    m = _RE_RS_FN.search(clean)
                    if m:
                        _add_callable(m.group(1), "function", i, raw_sig)
                        continue

            elif lang == "go":
                if "type " in stripped:
                    m = _RE_GO_STRUCT.search(clean)
                    if m:
                        _push_container(m.group(1), "struct", i, raw_sig)
                        continue
                    m_if = _RE_GO_IFACE.search(clean)
                    if m_if:
                        _push_container(m_if.group(1), "interface", i, raw_sig)
                        continue
                if "func " in stripped:
                    mm = _RE_GO_METHOD.search(clean)
                    if mm:
                        _add_callable(mm.group(2), "method", i, raw_sig, explicit_owner=mm.group(1))
                        continue
                    mf = _RE_GO_FUNC.search(clean)
                    if mf:
                        _add_callable(mf.group(1), "function", i, raw_sig)
                        continue

            elif lang == "java":
                m = _RE_JAVA_DECL.search(clean)
                if m:
                    _push_container(m.group(2), m.group(1), i, raw_sig)
                    continue
                mm = _RE_JAVA_METHOD.search(clean)
                if mm and mm.group(1) not in _CALL_KEYWORDS:
                    _add_callable(mm.group(1), "method", i, raw_sig)
                    continue

            elif lang == "dart":
                m = _RE_DART_DECL.search(clean)
                if m:
                    _push_container(m.group(2), m.group(1), i, raw_sig)
                    continue
                mf = _RE_DART_FUNC.search(clean)
                if mf and mf.group(1) not in _CALL_KEYWORDS:
                    _add_callable(mf.group(1), "function", i, raw_sig)
                    continue

            elif lang == "kotlin":
                m = _RE_KT_DECL.search(clean)
                if m:
                    _push_container(m.group(2), m.group(1), i, raw_sig)
                    continue
                mf = _RE_KT_FUNC.search(clean)
                if mf:
                    _add_callable(mf.group(1), "function", i, raw_sig)
                    continue

            elif lang == "swift":
                m = _RE_SWIFT_DECL.search(clean)
                if m:
                    _push_container(m.group(2), m.group(1), i, raw_sig)
                    continue
                me = _RE_SWIFT_EXT.search(clean)
                if me:
                    _push_container(me.group(1), "extension", i, raw_sig, record_node=False)
                    continue
                mf = _RE_SWIFT_FUNC.search(clean)
                if mf:
                    _add_callable(mf.group(1), "function", i, raw_sig)
                    continue

            elif lang in ("c", "cpp"):
                m = _RE_CPP_DECL.search(clean)
                if m:
                    _push_container(m.group(2), m.group(1), i, raw_sig)
                    continue
                if "(" in clean and not stripped.startswith("#"):
                    mf = _RE_CPP_FUNC.search(clean)
                    if mf and mf.group(1) not in _CALL_KEYWORDS:
                        _add_callable(mf.group(1), "function", i, raw_sig)
                        continue

            elif lang == "csharp":
                m = _RE_CS_DECL.search(clean)
                if m:
                    _push_container(m.group(2), m.group(1), i, raw_sig)
                    continue
                mm = _RE_CS_METHOD.search(clean)
                if mm and mm.group(1) not in _CALL_KEYWORDS:
                    _add_callable(mm.group(1), "method", i, raw_sig)
                    continue

        # Populate phantom-free polyglot call edges strictly inside each brace-matched body span
        for node in file_nodes:
            if node.kind in ("function", "method"):
                node.calls = _extract_polyglot_calls(
                    clean_lines, node.line_number, node.end_line_number, node.name
                )

        self.file_symbols[rel_path] = file_nodes
        for node in file_nodes:
            self.symbols.setdefault(node.name, []).append(node)
            if "." in node.name:
                unqualified = node.name.rsplit(".", 1)[-1]
                self.symbols.setdefault(unqualified, []).append(node)

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
