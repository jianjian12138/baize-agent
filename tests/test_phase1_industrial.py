"""Unit tests for Phase 1 Industrial Alignment: MCP, Symbol Graph, Vision, and Hunk Cherry-pick."""
from __future__ import annotations

import unittest
from baize.symbol_graph import SymbolGraph, build_workspace_symbol_graph
from baize.mcp import list_all_mcp_tools, call_mcp_tool, load_mcp_config
from baize.desktop_ui import render_desktop_studio


class TestPhase1Industrial(unittest.TestCase):
    def test_symbol_graph_indexing(self):
        graph = build_workspace_symbol_graph(".")
        summary = graph.get_summary()
        self.assertGreater(summary["total_files_indexed"], 0)
        self.assertGreater(summary["total_symbols"], 0)

        # Search for SymbolGraph class
        results = graph.search_symbols("SymbolGraph")
        self.assertTrue(len(results) > 0)
        sym = results[0]
        self.assertEqual(sym["name"], "SymbolGraph")
        self.assertEqual(sym["kind"], "class")

    def test_mcp_tools_and_call(self):
        cfg = load_mcp_config(".")
        self.assertIn("mcpServers", cfg)
        
        tools = list_all_mcp_tools(".")
        self.assertTrue(len(tools) >= 3)
        tool_names = {t["name"] for t in tools}
        self.assertIn("sqlite_query", tool_names)
        self.assertIn("github_list_prs", tool_names)

        # Call MCP tool
        res = call_mcp_tool("sqlite", "sqlite_query", {"sql": "SELECT 1"})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["protocol"], "mcp/json-rpc-2.0")

    def test_desktop_studio_includes_mcp_and_symbols(self):
        html = render_desktop_studio("35.0.0")
        self.assertIn("testMcpCall", html)
        self.assertIn("searchSymbols", html)
        self.assertIn("applyGitHunk", html)
        self.assertIn("Model Context Protocol", html)
        self.assertIn("Global AST Symbol Graph", html)


if __name__ == "__main__":
    unittest.main()
