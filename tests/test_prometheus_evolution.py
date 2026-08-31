"""Unit tests for Baize Prometheus Strategic Evolution: Repo Map PageRank, Doc Crawler, Browser Verify & Docker Sandbox."""
from __future__ import annotations

import unittest
from baize.symbol_graph import SymbolGraph, SymbolNode
from baize.repo_map import RepoMapGenerator
from baize.doc_crawler import DocHTMLToMarkdownParser, DocCrawlerRegistry
from baize.browser_verify import verify_frontend_code
from baize.docker_sandbox import DockerSandboxDriver


class TestPrometheusEvolution(unittest.TestCase):
    def test_pagerank_repo_map_generation(self):
        graph = SymbolGraph(".")
        n1 = SymbolNode("UserService", "class", "services/user.py", 10, 50, signature="class UserService")
        n1.calls = ["db_query", "log_event"]
        n2 = SymbolNode("db_query", "function", "db/query.py", 5, 20, signature="def db_query(sql)")
        n3 = SymbolNode("log_event", "function", "utils/logger.py", 1, 10, signature="def log_event(msg)")

        graph.symbols["UserService"] = [n1]
        graph.symbols["db_query"] = [n2]
        graph.symbols["log_event"] = [n3]
        graph.file_symbols["services/user.py"] = [n1]
        graph.file_symbols["db/query.py"] = [n2]
        graph.file_symbols["utils/logger.py"] = [n3]

        gen = RepoMapGenerator(graph)
        scores = gen.compute_pagerank()

        self.assertEqual(len(scores), 3)
        self.assertIn("db_query", scores)
        # db_query has incoming references from UserService so it gets weighted
        self.assertGreater(scores["db_query"], 0.0)

        repo_map = gen.generate_repo_map(max_symbols=10)
        self.assertIn("BAIZE PAGERANK REPO MAP", repo_map)
        self.assertIn("class UserService", repo_map)
        self.assertIn("def db_query(sql)", repo_map)

    def test_doc_html_to_markdown_parser(self):
        sample_html = """
        <html>
          <head><title>FastAPI Tutorial</title><style>body { color: red; }</style></head>
          <body>
            <nav><a href="/home">Home</a></nav>
            <h1>FastAPI Overview</h1>
            <p>FastAPI is a modern, fast web framework for building APIs with Python.</p>
            <pre><code>from fastapi import FastAPI
app = FastAPI()</code></pre>
            <footer>Copyright 2026</footer>
          </body>
        </html>
        """
        parser = DocHTMLToMarkdownParser()
        parser.feed(sample_html)
        md = parser.get_markdown()

        self.assertEqual(parser.page_title, "FastAPI Tutorial")
        self.assertIn("# FastAPI Overview", md)
        self.assertIn("FastAPI is a modern, fast web framework", md)
        self.assertIn("from fastapi import FastAPI", md)
        self.assertNotIn("Copyright 2026", md)  # footer stripped
        self.assertNotIn("color: red", md)  # style stripped

    def test_doc_crawler_registry(self):
        docs = DocCrawlerRegistry.list_indexed_docs()
        self.assertIsInstance(docs, list)

    def test_browser_verify_frontend_code(self):
        # 1. Clean HTML
        clean_html = """
        <!DOCTYPE html>
        <html>
        <body>
          <div id="app">Hello</div>
          <script>
            const el = document.getElementById("app");
            console.log(el.innerText);
          </script>
        </body>
        </html>
        """
        r1 = verify_frontend_code(clean_html, "clean.html")
        self.assertTrue(r1["is_clean"])
        self.assertEqual(len(r1["console_errors"]), 0)

        # 2. Buggy HTML (missing DOM element referred in JS)
        buggy_html = """
        <!DOCTYPE html>
        <html>
        <body>
          <div id="header">Header</div>
          <script>
            const el = document.getElementById("missing_button");
            el.click();
          </script>
        </body>
        </html>
        """
        r2 = verify_frontend_code(buggy_html, "buggy.html")
        self.assertFalse(r2["is_clean"])
        self.assertTrue(any("missing_button" in err for err in r2["console_errors"]))
        self.assertIn("BROWSER VERIFICATION FAILED", r2["feedback_prompt"])

    def test_docker_sandbox_driver_fallback(self):
        driver = DockerSandboxDriver(workspace=".")
        # Local fallback execution test
        res = driver.run("echo 'sandbox test'")
        self.assertEqual(res["returncode"], 0)
        self.assertIn("driver", res)


if __name__ == "__main__":
    unittest.main()
