"""Unit tests for ArchCacheManager and HierarchicalRepoMap (V39.0.0 Aegis)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from baize.arch_cache import ArchCacheManager
from baize.hierarchical_map import HierarchicalRepoMap, get_hierarchical_repo_map
from baize.symbol_graph import SymbolGraph


def test_arch_cache_incremental(tmp_path: Path):
    # Create sample files
    src_dir = tmp_path / "pkg"
    src_dir.mkdir()
    f1 = src_dir / "alpha.py"
    f1.write_text("class Alpha:\n    def run(self):\n        return 1\n", encoding="utf-8")
    
    cache_file = tmp_path / "arch_cache.json"
    mgr = ArchCacheManager(cache_file=cache_file)
    
    # 1. Initial sync
    g1 = mgr.sync_workspace(root_dir=tmp_path)
    assert "pkg/alpha.py" in g1.file_symbols
    assert len(mgr.cache_data) == 1
    assert cache_file.exists()
    
    # 2. Second sync without modification -> fast hit from cache
    mgr2 = ArchCacheManager(cache_file=cache_file)
    g2 = mgr2.sync_workspace(root_dir=tmp_path)
    assert "pkg/alpha.py" in g2.file_symbols
    assert "Alpha" in g2.symbols
    
    # 3. Modify f1
    time.sleep(0.05)
    f1.write_text("class Alpha:\n    def run(self):\n        return 2\n    def new_method(self):\n        pass\n", encoding="utf-8")
    g3 = mgr2.sync_workspace(root_dir=tmp_path)
    sym_names = [s.name for s in g3.file_symbols["pkg/alpha.py"]]
    assert "Alpha.new_method" in sym_names


def test_hierarchical_repo_map_rendering(tmp_path: Path):
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    (core_dir / "__init__.py").write_text('"""Core business domain logic"""\n', encoding="utf-8")
    (core_dir / "service.py").write_text(
        'class PaymentService:\n'
        '    """Processes online payments."""\n'
        '    def process(self, amount: float) -> bool:\n'
        '        return True\n',
        encoding="utf-8",
    )
    
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    (api_dir / "routes.py").write_text(
        'def handle_request(req):\n'
        '    """Entry route handler."""\n'
        '    pass\n',
        encoding="utf-8",
    )
    
    g = SymbolGraph(str(tmp_path))
    g.index_workspace()
    
    h_map = HierarchicalRepoMap(g, root_dir=tmp_path)
    rendered = h_map.render(token_budget=1000)
    
    # Verify L1 topology
    assert "=== 🌲 [BAIZE HIERARCHICAL REPO MAP · 全局分级架构导航图] ===" in rendered
    assert "[L1 系统模块拓扑与领域划分]:" in rendered
    assert "core/" in rendered
    assert "api/" in rendered
    
    # Verify L2 skeletons
    assert "[L2 核心架构接口与类骨架" in rendered
    assert "class PaymentService:" in rendered
    assert "def process(self, amount): ..." in rendered or "def process" in rendered
    assert "def handle_request" in rendered
    
    # Verify budget enforcement
    small_render = h_map.render(token_budget=100)
    assert len(small_render) <= 100 * 4 + 100
