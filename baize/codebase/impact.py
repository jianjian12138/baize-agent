"""Unified Pre-flight Change Impact Engine (Blast Radius + Test Impact Analysis).

Pure Python standard library — zero third-party dependencies.
Combines two complementary pre-flight analyses over the shared codebase index:

1. **Call-Hierarchy Blast Radius** (``BlastRadiusAnalyzer``, ``analyze_blast_radius``):
   Computes direct callers, depth-2 transitive dependents, and breaking signature
   contract changes before edits land.
2. **Test Impact Analysis / TIA** (``TestImpactMatrix``, ``analyze_test_impact``):
   Indexes test AST imports and calls via fast ``os.scandir`` (sharing
   ``symbol_graph.SKIP_DIRS``) to select the minimal regression test subset.
3. **Unified Change Impact** (``ChangeImpactReport``, ``analyze_change_impact``):
   Runs blast-radius analysis first, then feeds both the target and its impacted
   caller files into ``TestImpactMatrix`` for end-to-end transitive test coverage.
"""
from __future__ import annotations

import ast
import collections
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.config import ROOT, load_config
from .arch_cache import get_cached_symbol_graph
from .symbol_graph import SKIP_DIRS, SymbolGraph, SymbolNode

__all__ = [
    "RiskLevel",
    "CallerReference",
    "BlastRadiusReport",
    "BlastRadiusAnalyzer",
    "analyze_blast_radius",
    "TestImpactResult",
    "TestImpactMatrix",
    "analyze_test_impact",
    "ChangeImpactReport",
    "analyze_change_impact",
]


# ---------------------------------------------------------------------------
# 1. Call-Hierarchy Blast Radius & Contract Violation Analyzer
# ---------------------------------------------------------------------------

class RiskLevel:
    """Standard risk levels for blast radius classification."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class CallerReference:
    """Reference to a specific caller invocation location."""
    file_path: str
    line_number: int
    caller_symbol: str
    snippet: str = ""

    @property
    def caller_name(self) -> str:
        """Alias for caller_symbol."""
        return self.caller_symbol

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "caller_symbol": self.caller_symbol,
            "snippet": self.snippet,
        }


@dataclass(frozen=True)
class BlastRadiusReport:
    """Evaluation of the potential impact of changing a symbol or file."""
    target_symbol: str
    target_file: str
    direct_callers: list[CallerReference] = field(default_factory=list)
    transitive_callers: list[str] = field(default_factory=list)
    impacted_files: list[str] = field(default_factory=list)
    risk_level: str = "LOW"  # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    contract_risks: list[str] = field(default_factory=list)
    summary: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_symbol": self.target_symbol,
            "target_file": self.target_file,
            "direct_callers_count": len(self.direct_callers),
            "direct_callers": [c.to_dict() for c in self.direct_callers],
            "transitive_callers_count": len(self.transitive_callers),
            "transitive_callers": self.transitive_callers[:15],
            "impacted_files": self.impacted_files,
            "risk_level": self.risk_level,
            "contract_risks": self.contract_risks,
            "summary": self.summary,
            "latency_ms": round(self.latency_ms, 2),
        }

    @property
    def total_impact_count(self) -> int:
        """Total number of direct and transitive callers."""
        return len(self.direct_callers) + len(self.transitive_callers)

    @property
    def contract_violations(self) -> list[str]:
        """Alias for contract_risks."""
        return self.contract_risks

    def format_warning(self) -> str:
        """Format an impactful warning block for agent observation."""
        if not self.direct_callers and not self.contract_risks:
            return ""

        lines = [
            f"[💥 BLAST RADIUS ADVISORY · 变更影响面预警 | 风险等级: {self.risk_level}]",
            f"目标符号: `{self.target_symbol}` ({self.target_file or '未知文件'})",
            f"直接受波及调用方 ({len(self.direct_callers)} 处):",
        ]
        for c in self.direct_callers[:8]:
            lines.append(f"  - {c.file_path}:{c.line_number} (在 `{c.caller_symbol}` 中调用)")
        if len(self.direct_callers) > 8:
            lines.append(f"  ... 另有 {len(self.direct_callers) - 8} 处调用方")

        if self.impacted_files:
            lines.append(f"受波及跨模块文件 ({len(self.impacted_files)} 个): {', '.join(self.impacted_files[:5])}")

        if self.contract_risks:
            lines.append("⚠️ 契约风险检测:")
            for r in self.contract_risks:
                lines.append(f"  * {r}")

        lines.append("💡 防御规约: 请核对上述调用方是否依赖原有参数签名或返回值结构，防止引入远端次生 Bug。")
        return "\n".join(lines)


class BlastRadiusAnalyzer:
    """Analyzes symbol usage and calculates call-hierarchy blast radius."""

    def __init__(
        self,
        graph: SymbolGraph | None = None,
        workspace_root: str | Path | None = None,
    ):
        if graph is not None:
            self.graph = graph
        else:
            root_path = Path(workspace_root) if workspace_root else ROOT
            self.graph = SymbolGraph(root_dir=root_path)
            self.graph.build()
        self._inverted_calls: dict[str, list[CallerReference]] = collections.defaultdict(list)
        self._indexed = False

    def build_inverted_index(self) -> None:
        """Build map of called_symbol -> list[CallerReference]."""
        if self._indexed:
            return

        for file_path, nodes in self.graph.file_symbols.items():
            for caller_node in nodes:
                for call_name in caller_node.calls:
                    # Strip method receiver prefix (e.g. self.foo -> foo)
                    simple_name = call_name.split(".")[-1]
                    ref = CallerReference(
                        file_path=file_path,
                        line_number=caller_node.line_number,
                        caller_symbol=caller_node.name,
                    )
                    self._inverted_calls[simple_name].append(ref)
                    if simple_name != call_name:
                        self._inverted_calls[call_name].append(ref)

        self._indexed = True

    def analyze_symbol(self, symbol_name: str, target_file: str = "") -> BlastRadiusReport:
        """Compute direct and transitive callers for a specific symbol."""
        # Detect if caller passed (file, symbol) instead of (symbol, file)
        if ("." in symbol_name or "/" in symbol_name or "\\" in symbol_name) and (
            symbol_name.endswith((".py", ".ts", ".js", ".go", ".rs", ".java")) or "/" in symbol_name or "\\" in symbol_name
        ):
            if target_file and not (target_file.endswith((".py", ".ts", ".js", ".go", ".rs", ".java")) or "/" in target_file or "\\" in target_file):
                symbol_name, target_file = target_file, symbol_name

        t0 = time.perf_counter()
        self.build_inverted_index()

        norm_target_file = target_file.replace("\\", "/")
        if self.graph.root_dir:
            try:
                norm_target_file = str(Path(target_file).resolve().relative_to(self.graph.root_dir)).replace("\\", "/")
            except Exception:
                norm_target_file = target_file.replace("\\", "/")

        simple_name = symbol_name.split(".")[-1]
        direct_refs = self._inverted_calls.get(simple_name, [])

        # Filter out self-calls within the same node
        direct = [
            r for r in direct_refs
            if not ((r.file_path == norm_target_file or Path(r.file_path).name == Path(norm_target_file).name)
                    and r.caller_symbol == symbol_name)
        ]

        # Transitive callers (depth 2)
        transitive_set = set()
        for d in direct:
            trans = self._inverted_calls.get(d.caller_symbol.split(".")[-1], [])
            for tr in trans:
                if tr.caller_symbol != symbol_name and tr.caller_symbol != d.caller_symbol:
                    transitive_set.add(tr.caller_symbol)

        # Unique impacted files
        impacted_files = sorted(list(set(
            c.file_path for c in direct
            if c.file_path != norm_target_file and Path(c.file_path).name != Path(norm_target_file).name
        )))

        # Risk classification
        caller_count = len(direct)
        if caller_count == 0:
            risk = "LOW"
        elif caller_count < 4 and len(impacted_files) <= 1:
            risk = "LOW"
        elif caller_count < 10 and len(impacted_files) <= 3:
            risk = "MEDIUM"
        elif caller_count < 25 or len(impacted_files) <= 6:
            risk = "HIGH"
        else:
            risk = "CRITICAL"

        latency = (time.perf_counter() - t0) * 1000
        summary = (
            f"Symbol '{symbol_name}' has {caller_count} direct callers across "
            f"{len(impacted_files)} external files. Risk: {risk}."
        )

        return BlastRadiusReport(
            target_symbol=symbol_name,
            target_file=target_file,
            direct_callers=direct,
            transitive_callers=sorted(list(transitive_set)),
            impacted_files=impacted_files,
            risk_level=risk,
            contract_risks=[],
            summary=summary,
            latency_ms=latency,
        )

    def analyze_code_diff(
        self,
        file_path: str,
        old_code: str,
        new_code: str,
    ) -> list[BlastRadiusReport]:
        """Analyze changed function signatures in diff and return reports."""
        t0 = time.perf_counter()
        reports = []

        try:
            old_tree = ast.parse(old_code)
            new_tree = ast.parse(new_code)
        except Exception:
            return reports

        def get_funcs(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
            res = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    res[node.name] = node
            return res

        old_funcs = get_funcs(old_tree)
        new_funcs = get_funcs(new_tree)

        for name, old_f in old_funcs.items():
            if name in new_funcs:
                new_f = new_funcs[name]
                # Compare arguments
                old_args = [a.arg for a in old_f.args.args]
                new_args = [a.arg for a in new_f.args.args]
                old_defaults_len = len(old_f.args.defaults)
                new_defaults_len = len(new_f.args.defaults)

                risks = []
                # Check for removed parameters
                for arg in old_args:
                    if arg not in new_args:
                        risks.append(f"参数 `{arg}` 被移除，可能破坏下游传递该参数的调用方")

                # Check for new non-default parameters
                new_req_count = len(new_args) - new_defaults_len
                old_req_count = len(old_args) - old_defaults_len
                if new_req_count > old_req_count:
                    risks.append(f"新增了必填参数（无默认值），可能导致既有未提供该参数的调用方 TypeError")

                if risks:
                    rep = self.analyze_symbol(name, target_file=file_path)
                    object.__setattr__(rep, "contract_risks", risks)
                    if rep.direct_callers:
                        object.__setattr__(rep, "risk_level", "CRITICAL")
                    reports.append(rep)
            else:
                # Deleted function
                rep = self.analyze_symbol(name, target_file=file_path)
                object.__setattr__(rep, "contract_risks", [f"函数 `{name}` 被彻底删除，若仍有调用方将引发 NameError/AttributeError"])
                object.__setattr__(rep, "risk_level", "CRITICAL" if rep.direct_callers else "LOW")
                reports.append(rep)

        return reports


def analyze_blast_radius(
    target_symbol: str,
    target_file: str = "",
    workspace_dir: str | Path | None = None,
    cfg: dict | None = None,
) -> BlastRadiusReport:
    """Convenience helper to analyze blast radius for a symbol."""
    graph = get_cached_symbol_graph(root_dir=workspace_dir, cfg=cfg)
    analyzer = BlastRadiusAnalyzer(graph)
    return analyzer.analyze_symbol(target_symbol, target_file=target_file)



# ---------------------------------------------------------------------------
# 2. Test Impact Analysis (TIA) — upgraded to os.scandir & shared SKIP_DIRS
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TestImpactResult:
    """Result of Test Impact Analysis."""
    __test__ = False
    changed_targets: list[str]
    impacted_files: list[str] = field(default_factory=list)
    impacted_test_cases: list[str] = field(default_factory=list)
    recommended_command: str = ""
    total_test_files: int = 0
    latency_ms: float = 0.0

    @property
    def speedup_ratio(self) -> float:
        """Estimated ratio of tests skipped vs total tests."""
        if not self.total_test_files:
            return 1.0
        skipped = max(0, self.total_test_files - len(self.impacted_files))
        return round(self.total_test_files / max(1, len(self.impacted_files)), 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_targets": self.changed_targets,
            "impacted_files": self.impacted_files,
            "impacted_test_cases": self.impacted_test_cases[:30],
            "impacted_test_cases_count": len(self.impacted_test_cases),
            "recommended_command": self.recommended_command,
            "total_test_files": self.total_test_files,
            "speedup_ratio": self.speedup_ratio,
            "latency_ms": round(self.latency_ms, 2),
        }

    def format_summary(self) -> str:
        lines = [
            f"[🎯 TEST IMPACT ANALYSIS (TIA) | 变更测试影响域]",
            f"变更目标: {', '.join(self.changed_targets)}",
            f"波及测试集: {len(self.impacted_files)} / {self.total_test_files} 个测试文件 (提速 ~{self.speedup_ratio}x)",
        ]
        if self.impacted_files:
            lines.append("受波及测试文件:")
            for f in self.impacted_files[:6]:
                lines.append(f"  - {f}")
            if len(self.impacted_files) > 6:
                lines.append(f"  ... 另有 {len(self.impacted_files) - 6} 个测试文件")
        if self.impacted_test_cases:
            lines.append(f"受波及具体用例 ({len(self.impacted_test_cases)} 项):")
            for t in self.impacted_test_cases[:8]:
                lines.append(f"  * {t}")
            if len(self.impacted_test_cases) > 8:
                lines.append(f"  ... 另有 {len(self.impacted_test_cases) - 8} 项用例")
        if self.recommended_command:
            lines.append(f"推荐执行命令: `{self.recommended_command}`")
        return "\n".join(lines)


class TestImpactMatrix:
    """Indexes test suite AST dependencies and resolves regression impact."""
    __test__ = False

    def __init__(self, root_dir: str | Path | None = None):
        self.root_dir = Path(root_dir).resolve() if root_dir else ROOT
        self._test_files: list[str] = []
        # file_path -> list[imported_module_name]
        self._test_imports: dict[str, list[str]] = collections.defaultdict(list)
        # symbol_name -> list[test_case_id]
        self._symbol_to_tests: dict[str, list[str]] = collections.defaultdict(list)
        # module_stem -> list[test_file]
        self._module_to_test_files: dict[str, list[str]] = collections.defaultdict(list)
        self._indexed = False

    def build_matrix(self) -> None:
        """Scan workspace and parse test files AST."""
        if self._indexed:
            return

        def _scan(dir_path: Path) -> None:
            try:
                entries = list(os.scandir(dir_path))
            except OSError:
                return
            for entry in entries:
                name = entry.name
                if name.startswith(".") or name in SKIP_DIRS:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    _scan(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    if self._is_test_filename(name):
                        full_p = Path(entry.path)
                        try:
                            rel_p = str(full_p.relative_to(self.root_dir)).replace("\\", "/")
                        except Exception:
                            rel_p = str(full_p).replace("\\", "/")
                        self._test_files.append(rel_p)
                        if name.endswith(".py"):
                            self._parse_test_file(full_p, rel_p)
                        else:
                            self._parse_polyglot_test_file(full_p, rel_p)

        _scan(self.root_dir)

        self._indexed = True

    @staticmethod
    def _is_test_filename(name: str) -> bool:
        low = name.lower()
        if (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py"):
            return True
        for suffix in (
            ".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx",
            ".test.js", ".spec.js", ".test.jsx", ".spec.jsx",
            "_test.go", "_test.rs", "_test.dart",
            "test.java", "tests.java", "it.java",
        ):
            if low.endswith(suffix):
                return True
        return False

    def _parse_polyglot_test_file(self, full_path: Path, rel_path: str) -> None:
        """Lightweight import & identifier indexer for TS/JS/Go/Rust/Java/Dart tests."""
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        imported: set[str] = set()
        # JS/TS/Dart/Java/Rust import patterns
        for pat in (
            r"""from\s+['"]([^'"]+)['"]""",
            r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
            r"""import\s+['"]([^'"]+)['"]""",
            r"""^\s*import\s+([A-Za-z0-9_.]+);""",
            r"""^\s*use\s+([A-Za-z0-9_:]+);""",
        ):
            for m in re.finditer(pat, content, re.MULTILINE):
                raw = m.group(1).strip()
                imported.add(raw)
                stem = Path(raw.replace("::", "/").replace(".", "/")).stem
                if stem:
                    self._module_to_test_files[stem].append(rel_path)

        # Map test file's own subject stem (e.g. cart.test.ts -> cart, auth_test.go -> auth)
        fname = full_path.name
        subject = re.sub(
            r"(\.(?:test|spec)\.(?:ts|tsx|js|jsx)|_test\.(?:go|rs|dart)|(?:Tests|Test|IT)\.java)$",
            "",
            fname,
            flags=re.IGNORECASE,
        )
        if subject and subject != fname:
            self._module_to_test_files[subject].append(rel_path)

        # Index called identifiers inside test bodies
        for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", content):
            sym = m.group(1)
            if sym not in ("describe", "it", "test", "expect", "assert", "if", "for", "while", "func", "fn"):
                self._symbol_to_tests[sym].append(f"{rel_path}::{sym}")
        self._test_imports[rel_path] = sorted(imported)

    def _parse_test_file(self, full_path: Path, rel_path: str) -> None:
        """Extract imports and function-level symbol calls from test file."""
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=rel_path)
        except Exception:
            return

        imported_modules = set()

        class TestVisitor(ast.NodeVisitor):
            def __init__(self, matrix: TestImpactMatrix):
                self.matrix = matrix
                self.current_test: str | None = None
                self.current_class: str | None = None

            def visit_Import(self, node: ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
                    # Extract last stem
                    stem = alias.name.split(".")[-1]
                    self.matrix._module_to_test_files[stem].append(rel_path)
                self.generic_visit(node)

            def visit_ImportFrom(self, node: ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)
                    stem = node.module.split(".")[-1]
                    self.matrix._module_to_test_files[stem].append(rel_path)
                for alias in node.names:
                    # direct imported symbol
                    self.matrix._symbol_to_tests[alias.name].append(f"{rel_path}::{alias.name}")
                self.generic_visit(node)

            def visit_ClassDef(self, node: ast.ClassDef):
                old = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = old

            def visit_FunctionDef(self, node: ast.FunctionDef):
                self._handle_test_func(node)
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
                self._handle_test_func(node)
                self.generic_visit(node)

            def _handle_test_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
                is_test = node.name.startswith("test")
                if not is_test:
                    return

                case_id = f"{rel_path}::{self.current_class}::{node.name}" if self.current_class else f"{rel_path}::{node.name}"
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            self.matrix._symbol_to_tests[child.func.id].append(case_id)
                        elif isinstance(child.func, ast.Attribute):
                            self.matrix._symbol_to_tests[child.func.attr].append(case_id)

        visitor = TestVisitor(self)
        visitor.visit(tree)
        self._test_imports[rel_path] = sorted(list(imported_modules))

    def get_impacted_tests(
        self,
        changed_files: list[str] | None = None,
        changed_symbols: list[str] | None = None,
    ) -> TestImpactResult:
        """Calculate the minimal test subset impacted by changed files or symbols."""
        t0 = time.perf_counter()
        self.build_matrix()

        changed_files = changed_files or []
        changed_symbols = changed_symbols or []

        impacted_files_set = set()
        impacted_cases_set = set()

        for f in changed_files:
            p = Path(f)
            stem = p.stem
            # Direct module name match
            for t_file in self._module_to_test_files.get(stem, []):
                impacted_files_set.add(t_file)

            norm_f = str(f).replace("\\", "/")
            # If changed file itself is a test file, add it
            if norm_f in self._test_files:
                impacted_files_set.add(norm_f)
            else:
                for t in self._test_files:
                    if Path(t).name == p.name and (p.name.startswith("test_") or p.name.endswith("_test.py")):
                        impacted_files_set.add(t)

            # Heuristic match by naming convention across Python/TS/JS/Go/Rust/Java/Dart
            for t in self._test_files:
                t_path = Path(t)
                t_stem = t_path.stem
                t_name_low = t_path.name.lower()
                if (
                    t_stem in (f"test_{stem}", f"{stem}_test", f"{stem}.test", f"{stem}.spec", f"{stem}Test", f"{stem}Tests")
                    or t_name_low.startswith(f"{stem.lower()}.test.")
                    or t_name_low.startswith(f"{stem.lower()}.spec.")
                ):
                    impacted_files_set.add(t)

        for sym in changed_symbols:
            simple_sym = sym.split(".")[-1]
            cases = self._symbol_to_tests.get(simple_sym, [])
            for c in cases:
                impacted_cases_set.add(c)
                # extract file part
                file_part = c.split("::")[0]
                impacted_files_set.add(file_part)

        impacted_files = sorted(list(impacted_files_set))
        impacted_cases = sorted(list(impacted_cases_set))

        # Recommend language-appropriate test runner command
        targets_str = " ".join(impacted_files) if impacted_files else ""
        if impacted_files and all(f.endswith((".ts", ".tsx", ".js", ".jsx")) for f in impacted_files):
            cmd = f"npx vitest run {targets_str}"
        elif impacted_files and all(f.endswith("_test.go") for f in impacted_files):
            pkgs = sorted({str(Path(f).parent).replace("\\", "/") for f in impacted_files})
            cmd = "go test " + " ".join(f"./{p}" if p != "." else "." for p in pkgs)
        elif impacted_files and all(f.endswith(".rs") for f in impacted_files):
            cmd = "cargo test"
        elif impacted_files and all(f.endswith(".dart") for f in impacted_files):
            cmd = f"dart test {targets_str}"
        elif impacted_files and all(f.endswith(".java") for f in impacted_files):
            classes = ",".join(Path(f).stem for f in impacted_files)
            cmd = f"mvn test -Dtest={classes}"
        else:
            cmd = f"pytest {targets_str}" if targets_str else "pytest"

        latency = (time.perf_counter() - t0) * 1000
        all_targets = [str(x) for x in (changed_files + changed_symbols)]

        return TestImpactResult(
            changed_targets=all_targets,
            impacted_files=impacted_files,
            impacted_test_cases=impacted_cases,
            recommended_command=cmd,
            total_test_files=len(self._test_files),
            latency_ms=latency,
        )


def analyze_test_impact(
    target: str,
    root_dir: str | Path | None = None,
) -> TestImpactResult:
    """Analyze impacted tests for a file path or symbol name."""
    matrix = TestImpactMatrix(root_dir=root_dir)
    target_clean = target.strip()
    if target_clean.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".dart", ".c", ".cpp")) or "/" in target_clean or "\\" in target_clean:
        return matrix.get_impacted_tests(changed_files=[target_clean])
    return matrix.get_impacted_tests(changed_symbols=[target_clean])



# ---------------------------------------------------------------------------
# 3. Unified Pre-flight Change Impact (Blast Radius -> Transitive TIA)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChangeImpactReport:
    """Combined pre-flight report joining call-hierarchy blast radius with TIA."""
    blast_radius: BlastRadiusReport | None
    test_impact: TestImpactResult
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "blast_radius": self.blast_radius.to_dict() if self.blast_radius else None,
            "test_impact": self.test_impact.to_dict(),
            "latency_ms": round(self.latency_ms, 2),
        }


def analyze_change_impact(
    target_symbol: str = "",
    target_file: str = "",
    root_dir: str | Path | None = None,
    cfg: dict | None = None,
) -> ChangeImpactReport:
    """Run unified blast-radius + transitive test-impact analysis in one call."""
    t0 = time.perf_counter()
    blast: BlastRadiusReport | None = None
    changed_files: list[str] = [target_file] if target_file else []
    changed_symbols: list[str] = [target_symbol] if target_symbol else []

    if target_symbol:
        blast = analyze_blast_radius(
            target_symbol=target_symbol,
            target_file=target_file,
            workspace_dir=root_dir,
            cfg=cfg,
        )
        # Feed impacted caller files & callers transitively into TIA!
        for f in blast.impacted_files:
            if f not in changed_files:
                changed_files.append(f)
        for c in blast.direct_callers:
            if c.caller_symbol not in changed_symbols:
                changed_symbols.append(c.caller_symbol)

    tia = TestImpactMatrix(root_dir=root_dir).get_impacted_tests(
        changed_files=changed_files,
        changed_symbols=changed_symbols,
    )
    elapsed = (time.perf_counter() - t0) * 1000.0
    return ChangeImpactReport(
        blast_radius=blast,
        test_impact=tia,
        latency_ms=elapsed,
    )
