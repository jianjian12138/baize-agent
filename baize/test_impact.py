"""Test Impact Analysis (TIA) & Regression Matrix Engine (V39.0.0 Aegis).

Pure Python standard library — zero third-party dependencies.
Identifies precisely which test cases exercise modified source files or symbols,
enabling sub-second feedback loops and preventing regressions in 100k+ line codebases.
"""
from __future__ import annotations

import ast
import collections
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ROOT, load_config

__all__ = [
    "TestImpactResult",
    "TestImpactMatrix",
    "analyze_test_impact",
]


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

        ignore_dirs = {".git", ".pytest_cache", ".venv", "venv", "node_modules", "persistence", "dist", "build"}
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ignore_dirs]
            for file in files:
                if file.startswith("test_") and file.endswith(".py") or file.endswith("_test.py"):
                    full_p = Path(root) / file
                    try:
                        rel_p = str(full_p.relative_to(self.root_dir)).replace("\\", "/")
                    except Exception:
                        rel_p = str(full_p).replace("\\", "/")
                    self._test_files.append(rel_p)
                    self._parse_test_file(full_p, rel_p)

        self._indexed = True

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

            # Heuristic match by naming convention (e.g. calculator.py -> test_calculator.py)
            for t in self._test_files:
                t_stem = Path(t).stem
                if t_stem == f"test_{stem}" or t_stem == f"{stem}_test":
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

        # Recommend pytest command
        targets_str = " ".join(impacted_files) if impacted_files else ""
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
    if target_clean.endswith((".py", ".ts", ".js", ".go", ".rs")) or "/" in target_clean or "\\" in target_clean:
        return matrix.get_impacted_tests(changed_files=[target_clean])
    return matrix.get_impacted_tests(changed_symbols=[target_clean])
