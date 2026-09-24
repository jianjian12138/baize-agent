import tempfile
from pathlib import Path
from baize.test_impact import TestImpactMatrix, analyze_test_impact

def test_test_impact_file_level():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        
        # Source module
        (root / "calculator.py").write_text(
            "def add(a, b): return a + b\n"
            "def sub(a, b): return a - b\n",
            encoding="utf-8"
        )
        
        # Tests
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_calculator.py").write_text(
            "import calculator\n"
            "def test_add():\n"
            "    assert calculator.add(1, 2) == 3\n",
            encoding="utf-8"
        )
        (tests_dir / "test_unrelated.py").write_text(
            "def test_something():\n"
            "    assert True\n",
            encoding="utf-8"
        )
        
        matrix = TestImpactMatrix(root_dir=root)
        result = matrix.get_impacted_tests(changed_files=["calculator.py"])
        
        assert len(result.impacted_files) >= 1
        assert any("test_calculator.py" in f for f in result.impacted_files)
        assert not any("test_unrelated.py" in f for f in result.impacted_files)
        assert result.total_test_files == 2
        assert result.speedup_ratio >= 1.5

def test_test_impact_symbol_level():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_ops.py").write_text(
            "from math_ops import divide, multiply\n\n"
            "def test_div():\n"
            "    assert divide(4, 2) == 2\n\n"
            "def test_mul():\n"
            "    assert multiply(2, 3) == 6\n",
            encoding="utf-8"
        )
        
        matrix = TestImpactMatrix(root_dir=root)
        result = matrix.get_impacted_tests(changed_symbols=["divide"])
        
        assert len(result.impacted_files) == 1
        assert any("test_ops.py" in f for f in result.impacted_files)
        assert any("test_div" in c for c in result.impacted_test_cases)
        assert "pytest tests/test_ops.py" in result.recommended_command
        summary = result.format_summary()
        assert "TEST IMPACT ANALYSIS" in summary
