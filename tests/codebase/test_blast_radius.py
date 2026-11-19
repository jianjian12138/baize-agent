import tempfile
from pathlib import Path
from baize.codebase.impact import BlastRadiusAnalyzer, RiskLevel

def test_blast_radius_direct_callers():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        
        # Module A defines calculate_tax
        (root / "module_a.py").write_text(
            "def calculate_tax(amount: float) -> float:\n"
            "    return amount * 0.1\n",
            encoding="utf-8"
        )
        
        # Module B calls calculate_tax
        (root / "module_b.py").write_text(
            "from module_a import calculate_tax\n\n"
            "def process_order(total: float):\n"
            "    tax = calculate_tax(total)\n"
            "    return total + tax\n",
            encoding="utf-8"
        )
        
        analyzer = BlastRadiusAnalyzer(workspace_root=str(root))
        report = analyzer.analyze_symbol(str(root / "module_a.py"), "calculate_tax")
        
        assert len(report.direct_callers) >= 1
        caller_names = [c.caller_name for c in report.direct_callers]
        assert "process_order" in caller_names
        assert report.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM)

def test_blast_radius_transitive_callers():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        
        # A -> B -> C
        (root / "core.py").write_text(
            "def base_func():\n    return 42\n",
            encoding="utf-8"
        )
        (root / "service.py").write_text(
            "from core import base_func\n"
            "def middle_service():\n"
            "    return base_func() * 2\n",
            encoding="utf-8"
        )
        (root / "controller.py").write_text(
            "from service import middle_service\n"
            "def handle_request():\n"
            "    return middle_service()\n",
            encoding="utf-8"
        )
        
        analyzer = BlastRadiusAnalyzer(workspace_root=str(root))
        report = analyzer.analyze_symbol(str(root / "core.py"), "base_func")
        
        direct = [c.caller_name for c in report.direct_callers]
        transitive = report.transitive_callers
        
        assert "middle_service" in direct
        assert "handle_request" in transitive
        assert report.total_impact_count == 2

def test_analyze_code_diff_contract_breaking():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        
        target_file = root / "api.py"
        old_code = "def query(term: str):\n    return term\n"
        target_file.write_text(old_code, encoding="utf-8")
        
        (root / "caller.py").write_text(
            "from api import query\n"
            "def search():\n"
            "    return query('hello')\n",
            encoding="utf-8"
        )
        
        # Add required parameter without default -> CRITICAL
        new_code = "def query(term: str, auth_token: str):\n    return term + auth_token\n"
        
        analyzer = BlastRadiusAnalyzer(workspace_root=str(root))
        reports = analyzer.analyze_code_diff(str(target_file), old_code, new_code)
        
        assert len(reports) > 0
        report = reports[0]
        assert report.risk_level == RiskLevel.CRITICAL
        assert len(report.contract_violations) > 0
        warning = report.format_warning()
        assert "BLAST RADIUS" in warning
        assert "CRITICAL" in warning


def test_analyze_change_impact_unifies_blast_and_tests():
    """Unified analyze_change_impact chains BlastRadiusAnalyzer -> TestImpactMatrix."""
    from baize.codebase.impact import analyze_change_impact

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "core_lib.py").write_text(
            "def compute_score(x: int) -> int:\n    return x * 2\n",
            encoding="utf-8",
        )
        (root / "service.py").write_text(
            "from core_lib import compute_score\n"
            "def rank_item(x: int) -> int:\n"
            "    return compute_score(x) + 1\n",
            encoding="utf-8",
        )
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_service.py").write_text(
            "from service import rank_item\n"
            "def test_rank():\n"
            "    assert rank_item(2) == 5\n",
            encoding="utf-8",
        )

        combined = analyze_change_impact(
            "compute_score",
            str(root / "core_lib.py"),
            root_dir=str(root),
        )
        assert combined.blast_radius is not None
        assert combined.blast_radius.total_impact_count >= 1
        assert any("test_service.py" in t for t in combined.test_impact.impacted_files)
        payload = combined.to_dict()
        assert payload["blast_radius"]["target_symbol"] == "compute_score"
        assert payload["test_impact"]["impacted_files"]


def test_codebase_shared_skip_dirs_and_supported_exts():
    """SKIP_DIRS and SUPPORTED_EXTS have one single source of truth in symbol_graph."""
    from baize.codebase import arch_cache, impact, symbol_graph, workspace_search

    assert arch_cache._SUPPORTED_EXTS is symbol_graph.SUPPORTED_EXTS
    assert arch_cache._SKIP_DIRS is symbol_graph.SKIP_DIRS
    assert impact.SKIP_DIRS is symbol_graph.SKIP_DIRS
    assert workspace_search.SKIP_DIRS == symbol_graph.SKIP_DIRS - {"persistence"}


def test_unified_repo_map_exports_hierarchical_and_slicer():
    """baize.codebase.repo_map unifies flat map, L0/L1/L2 hierarchical map, and AST slicer."""
    from baize.codebase.repo_map import (
        HierarchicalRepoMap,
        RepoMapGenerator,
        slice_code_context,
    )

    sample = (
        "def helper(a):\n"
        "    return a + 1\n\n"
        "def target(x):\n"
        "    return helper(x) * 2\n\n"
        "def unrelated(z):\n"
        "    return z - 99\n"
    )
    sliced = slice_code_context(sample, focus_symbol="target")
    assert "def target" in sliced["sliced_code"]
    assert sliced["sliced_chars"] <= sliced["original_chars"]
    assert RepoMapGenerator is not None
    assert HierarchicalRepoMap is not None
