"""Pre-flight Blast Radius & Call Hierarchy Impact Analyzer (V39.0.0 Aegis).

Pure Python standard library — zero third-party dependencies.
Calculates direct callers, transitive dependents, and contract risk before
code changes are executed, preventing regression bugs in 100k+ line codebases.
"""
from __future__ import annotations

import ast
import collections
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ROOT, load_config
from .symbol_graph import SymbolGraph, SymbolNode
from .arch_cache import get_cached_symbol_graph

__all__ = [
    "RiskLevel",
    "CallerReference",
    "BlastRadiusReport",
    "BlastRadiusAnalyzer",
    "analyze_blast_radius",
]


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
