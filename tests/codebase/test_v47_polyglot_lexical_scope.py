"""V47.0.0 Horizon tests: zero-dependency polyglot lexical scope, spans, phantom-free calls & imports."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from baize.codebase.symbol_graph import SymbolGraph, strip_comments_and_strings


class TestV47PolyglotLexicalScope(unittest.TestCase):
    def test_strip_comments_and_strings_preserves_line_numbers(self):
        src = "\n".join([
            'import { foo } from "./foo"; // comment with fakeCall()',
            '/* multi-line block comment',
            '   hiddenCall(123)',
            '   class GhostClass {}',
            '*/',
            'const msg = "stringCall() and \\"escaped\\"";',
            'const tpl = `line1',
            '  templateCall()',
            '  line3`;',
            'function realFn() { actualCall(); }',
        ])
        cleaned = strip_comments_and_strings(src, "typescript")
        self.assertEqual(len(cleaned.splitlines()), len(src.splitlines()))
        self.assertNotIn("fakeCall", cleaned)
        self.assertNotIn("hiddenCall", cleaned)
        self.assertNotIn("GhostClass", cleaned)
        self.assertNotIn("stringCall", cleaned)
        self.assertNotIn("templateCall", cleaned)
        self.assertIn("actualCall()", cleaned)

    def test_typescript_nested_class_methods_spans_calls_and_imports(self):
        ts_code = """import { RecipeRepo } from './repo';
const helper = require('./helper');
// import { FakeImport } from './ignored';

export class KitchenService {
  async cook(dishId: string): Promise<void> {
    // phantomCommentCall();
    const note = "phantomStringCall()";
    /* blockPhantomCall() */
    const item = fetchRecipe(dishId);
    saveOrder(item);
  }

  cancel(orderId: string): void {
    abortOrder(orderId);
  }
}

export const formatDish = (name: string) => {
  return normalizeTitle(name);
};
"""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "kitchen.ts").write_text(ts_code, encoding="utf-8")
            g = SymbolGraph(td)
            g.index_workspace()

        self.assertIn("./repo", g.file_imports["kitchen.ts"])
        self.assertIn("./helper", g.file_imports["kitchen.ts"])
        self.assertNotIn("./ignored", g.file_imports["kitchen.ts"])

        cook_defs = g.find_definitions("KitchenService.cook")
        self.assertEqual(len(cook_defs), 1)
        cook = cook_defs[0]
        self.assertEqual(cook["kind"], "method")
        self.assertEqual(cook["line_number"], 6)
        self.assertEqual(cook["end_line_number"], 12)
        self.assertIn("fetchRecipe", cook["calls"])
        self.assertIn("saveOrder", cook["calls"])
        self.assertNotIn("phantomCommentCall", cook["calls"])
        self.assertNotIn("phantomStringCall", cook["calls"])
        self.assertNotIn("blockPhantomCall", cook["calls"])
        self.assertNotIn("abortOrder", cook["calls"])

        self.assertEqual(len(g.find_definitions("cook")), 1)
        self.assertEqual(len(g.find_definitions("KitchenService.cancel")), 1)
        self.assertIn("abortOrder", g.find_definitions("KitchenService.cancel")[0]["calls"])

        fmt_defs = g.find_definitions("formatDish")
        self.assertEqual(len(fmt_defs), 1)
        self.assertIn("normalizeTitle", fmt_defs[0]["calls"])

    def test_rust_impl_methods_nested_comments_raw_strings_and_imports(self):
        rs_code = '''use crate::db::Pool;
mod metrics;

pub struct OrderEngine {
    id: u64,
}

impl OrderEngine {
    pub fn process(&self) {
        /* outer /* nestedCommentCall() */ still comment */
        let s = r#"rawStringCall()"#;
        validate_order(self.id);
        commit_tx();
    }
}
'''
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "engine.rs").write_text(rs_code, encoding="utf-8")
            g = SymbolGraph(td)
            g.index_workspace()

        self.assertIn("crate::db::Pool", g.file_imports["engine.rs"])
        self.assertIn("metrics", g.file_imports["engine.rs"])
        defs = g.find_definitions("OrderEngine.process")
        self.assertEqual(len(defs), 1)
        d = defs[0]
        self.assertEqual(d["kind"], "method")
        self.assertGreater(d["end_line_number"], d["line_number"])
        self.assertIn("validate_order", d["calls"])
        self.assertIn("commit_tx", d["calls"])
        self.assertNotIn("nestedCommentCall", d["calls"])
        self.assertNotIn("rawStringCall", d["calls"])

    def test_go_receiver_methods_and_multiline_imports(self):
        go_code = '''package api

import (
    "context"
    "net/http"
)

type Server struct {
    addr string
}

func (s *Server) HandleHealth(w http.ResponseWriter, r *http.Request) {
    // ignoredCall()
    writeJSON(w, "ok")
}
'''
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "server.go").write_text(go_code, encoding="utf-8")
            g = SymbolGraph(td)
            g.index_workspace()

        self.assertIn("context", g.file_imports["server.go"])
        self.assertIn("net/http", g.file_imports["server.go"])
        defs = g.find_definitions("Server.HandleHealth")
        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0]["kind"], "method")
        self.assertIn("writeJSON", defs[0]["calls"])
        self.assertNotIn("ignoredCall", defs[0]["calls"])

    def test_java_and_dart_and_cpp_scopes_and_imports(self):
        java_code = '''import java.util.List;
public class CartController {
    public int total() {
        return computeSum();
    }
}
'''
        dart_code = """import 'package:flutter/material.dart';
class RecipeCard {
  void buildView() {
    renderBadge();
  }
}
"""
        cpp_code = '''#include "engine.h"
class AudioMixer {
    int mix() {
        return blendFrames();
    }
};
'''
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "CartController.java").write_text(java_code, encoding="utf-8")
            (Path(td) / "recipe_card.dart").write_text(dart_code, encoding="utf-8")
            (Path(td) / "mixer.cpp").write_text(cpp_code, encoding="utf-8")
            g = SymbolGraph(td)
            g.index_workspace()

        self.assertIn("java.util.List", g.file_imports["CartController.java"])
        self.assertEqual(len(g.find_definitions("CartController.total")), 1)
        self.assertIn("computeSum", g.find_definitions("CartController.total")[0]["calls"])

        self.assertIn("package:flutter/material.dart", g.file_imports["recipe_card.dart"])
        self.assertEqual(len(g.find_definitions("RecipeCard.buildView")), 1)
        self.assertIn("renderBadge", g.find_definitions("RecipeCard.buildView")[0]["calls"])

        self.assertIn("engine.h", g.file_imports["mixer.cpp"])
        self.assertEqual(len(g.find_definitions("AudioMixer.mix")), 1)
        self.assertIn("blendFrames", g.find_definitions("AudioMixer.mix")[0]["calls"])


if __name__ == "__main__":
    unittest.main()
