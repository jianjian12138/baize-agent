"""V45 Nexus end-to-end tests: Polyglot ProjectProfile, Persistent LSP Pool & Semantic Nav."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from baize.codebase.diagnostics import LspSessionPool, diagnose_file, diagnose_workspace
from baize.codebase.impact import TestImpactMatrix
from baize.codebase.project_profile import clear_profile_cache, detect_project_profile, run_polyglot_gate
from baize.codebase.symbol_graph import SymbolGraph


MOCK_LSP_SERVER = textwrap.dedent("""
import json, sys

def read_msg():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        s = line.decode("ascii", errors="replace").strip()
        if s == "":
            break
        if ":" in s:
            k, v = s.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    n = int(headers.get("content-length", "0"))
    if n <= 0:
        return None
    body = sys.stdin.buffer.read(n)
    return json.loads(body.decode("utf-8"))

def send_msg(obj):
    body = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write((f"Content-Length: {len(body)}" + chr(13) + chr(10) + chr(13) + chr(10)).encode("ascii") + body)
    sys.stdout.buffer.flush()

docs = {}
while True:
    msg = read_msg()
    if msg is None:
        break
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params") or {}
    if method == "initialize":
        send_msg({"jsonrpc": "2.0", "id": req_id, "result": {"capabilities": {}}})
    elif method in ("textDocument/didOpen", "textDocument/didChange"):
        td = params.get("textDocument") or {}
        uri = td.get("uri", "")
        text = td.get("text") or ((params.get("contentChanges") or [{}])[0].get("text", ""))
        docs[uri] = text
        diags = []
        if "BAD_SYMBOL" in text:
            diags.append({
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 10}},
                "severity": 1,
                "code": "MOCK001",
                "source": "mock-lsp",
                "message": "undefined symbol BAD_SYMBOL",
            })
        send_msg({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": uri, "diagnostics": diags}})
    elif method == "textDocument/definition":
        uri = (params.get("textDocument") or {}).get("uri", "")
        send_msg({"jsonrpc": "2.0", "id": req_id, "result": [
            {"uri": uri, "range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 12}}}
        ]})
    elif method == "textDocument/references":
        uri = (params.get("textDocument") or {}).get("uri", "")
        send_msg({"jsonrpc": "2.0", "id": req_id, "result": [
            {"uri": uri, "range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 12}}},
            {"uri": uri, "range": {"start": {"line": 2, "character": 0}, "end": {"line": 2, "character": 8}}},
        ]})
    elif method == "textDocument/hover":
        send_msg({"jsonrpc": "2.0", "id": req_id, "result": {
            "contents": {"kind": "markdown", "value": "def greet(name: str) -> str"}
        }})
    elif method == "textDocument/rename":
        uri = (params.get("textDocument") or {}).get("uri", "")
        new_name = params.get("newName", "renamed")
        send_msg({"jsonrpc": "2.0", "id": req_id, "result": {
            "changes": {
                uri: [
                    {"range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 9}}, "newText": new_name},
                    {"range": {"start": {"line": 2, "character": 0}, "end": {"line": 2, "character": 5}}, "newText": new_name},
                ]
            }
        }})
    elif method == "shutdown":
        send_msg({"jsonrpc": "2.0", "id": req_id, "result": None})
    elif method == "exit":
        break
""").lstrip()


class TestV45PolyglotLspAndProfile(unittest.TestCase):
    def tearDown(self) -> None:
        clear_profile_cache()

    def test_detect_project_profile_multi_language_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # 1. TypeScript + pnpm
            ts_dir = root / "ts_app"
            ts_dir.mkdir()
            (ts_dir / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
            (ts_dir / "tsconfig.json").write_text("{}", encoding="utf-8")
            (ts_dir / "package.json").write_text(json.dumps({
                "name": "kitchen-app",
                "scripts": {"test": "vitest run", "build": "vite build", "lint": "eslint ."},
            }), encoding="utf-8")
            prof_ts = detect_project_profile(ts_dir, use_cache=False)
            self.assertIn("typescript", prof_ts.languages)
            self.assertEqual(prof_ts.package_manager, "pnpm")
            self.assertEqual(prof_ts.test_cmd, ["pnpm", "test"])
            self.assertEqual(prof_ts.build_cmd, ["pnpm", "run", "build"])
            self.assertIn("[ProjectProfile]", prof_ts.format_for_context())

            # 2. Go module
            go_dir = root / "go_svc"
            go_dir.mkdir()
            (go_dir / "go.mod").write_text("module example.com/svc\n\ngo 1.22\n", encoding="utf-8")
            prof_go = detect_project_profile(go_dir, use_cache=False)
            self.assertEqual(prof_go.primary_language, "go")
            self.assertEqual(prof_go.test_cmd, ["go", "test", "./..."])

            # 3. Rust Cargo
            rs_dir = root / "rs_cli"
            rs_dir.mkdir()
            (rs_dir / "Cargo.toml").write_text("[package]\nname = \"demo\"\n", encoding="utf-8")
            prof_rs = detect_project_profile(rs_dir, use_cache=False)
            self.assertEqual(prof_rs.primary_language, "rust")
            self.assertEqual(prof_rs.test_cmd, ["cargo", "test"])

            # 4. Flutter / Dart
            fl_dir = root / "recipe_mobile"
            fl_dir.mkdir()
            (fl_dir / "pubspec.yaml").write_text("name: recipe_app\ndependencies:\n  flutter:\n    sdk: flutter\n", encoding="utf-8")
            prof_fl = detect_project_profile(fl_dir, use_cache=False)
            self.assertIn("dart", prof_fl.languages)
            self.assertEqual(prof_fl.package_manager, "flutter")

    def test_persistent_lsp_session_pool_semantic_ops_and_rename(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            srv = ws / "mock_lsp.py"
            srv.write_text(MOCK_LSP_SERVER, encoding="utf-8")
            src = ws / "sample.py"
            src.write_text("def greet(name: str) -> str:\n    return name\ngreet('world')\n", encoding="utf-8")

            pool = LspSessionPool(idle_timeout=60.0)
            try:
                cmd = [sys.executable, str(srv)]
                c1 = pool.get_or_start(src, workspace=ws, cmd=cmd, timeout=5.0)
                self.assertIsNotNone(c1)
                assert c1 is not None
                # Second lookup must reuse the exact same warm process
                c2 = pool.get_or_start(src, workspace=ws, cmd=cmd, timeout=5.0)
                self.assertIs(c1, c2)
                self.assertEqual(pool.status()["active_count"], 1)

                defs = c1.definition(src, 3, 1)
                self.assertEqual(len(defs), 1)
                self.assertEqual(defs[0]["file"], "sample.py")
                self.assertEqual(defs[0]["line"], 1)

                refs = c1.references(src, 1, 5)
                self.assertEqual(len(refs), 2)

                hov = c1.hover(src, 1, 5)
                self.assertIn("def greet", hov["contents"])

                # Preview rename (apply=False) does not mutate disk
                prev = c1.rename(src, 1, 5, "hello", apply=False)
                self.assertTrue(prev["ok"])
                self.assertFalse(prev["applied"])
                self.assertIn("def greet", src.read_text(encoding="utf-8"))

                # Apply rename mutates disk cleanly
                applied = c1.rename(src, 1, 5, "hello", apply=True)
                self.assertTrue(applied["ok"])
                self.assertTrue(applied["applied"])
                updated = src.read_text(encoding="utf-8")
                self.assertIn("def hello", updated)
                self.assertIn("hello('world')", updated)

                # Publish diagnostics on updated file with BAD_SYMBOL
                src.write_text("BAD_SYMBOL = 1\n", encoding="utf-8")
                diags = c1.diagnose_file(src, keep_alive=True)
                self.assertTrue(any(d.code == "MOCK001" for d in diags))
            finally:
                stopped = pool.shutdown_all()
                self.assertEqual(stopped, 1)
                self.assertEqual(pool.status()["active_count"], 0)

    def test_polyglot_symbol_graph_calls_and_test_impact_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "cart.ts").write_text(
                "export function calcTax(x: number) { return x * 0.1; }\n"
                "export function checkoutTotal(x: number) {\n"
                "  return x + calcTax(x);\n"
                "}\n",
                encoding="utf-8",
            )
            (ws / "cart.test.ts").write_text(
                "import { checkoutTotal } from './cart';\n"
                "test('total', () => { expect(checkoutTotal(10)).toBe(11); });\n",
                encoding="utf-8",
            )
            (ws / "recipe.dart").write_text(
                "class RecipeCard {}\nString formatStep(int n) { return helperStep(n); }\n",
                encoding="utf-8",
            )

            sg = SymbolGraph(str(ws))
            sg.index_workspace()
            self.assertIn("typescript", sg.languages_detected)
            self.assertIn("dart", sg.languages_detected)
            ct_nodes = sg.symbols.get("checkoutTotal", [])
            self.assertEqual(len(ct_nodes), 1)
            self.assertIn("calcTax", ct_nodes[0].calls)

            tia = TestImpactMatrix(root_dir=ws)
            res = tia.get_impacted_tests(changed_files=["cart.ts"])
            self.assertIn("cart.test.ts", res.impacted_files)
            self.assertIn("vitest", res.recommended_command)

    def test_run_polyglot_gate_and_diagnose_workspace_on_python(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "pyproject.toml").write_text("[project]\nname = \"tiny\"\n", encoding="utf-8")
            (ws / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
            rep = diagnose_workspace(ws)
            self.assertTrue(rep["ok"])
            self.assertEqual(rep["files_checked"], 1)
            gate = run_polyglot_gate(ws, timeout=15)
            self.assertIn("profile", gate)
            self.assertIn("python", gate["profile"]["languages"])


if __name__ == "__main__":
    unittest.main()
