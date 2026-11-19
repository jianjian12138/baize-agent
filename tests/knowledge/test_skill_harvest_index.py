"""Regression tests for the skill-harvest -> index rebuild hand-off."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from baize.knowledge import skills
from baize.knowledge.skills import SkillHarvester


class TestHarvestRebuildsIndex(unittest.TestCase):
    def test_skills_exposes_build_index_and_harvester(self):
        """Pin the API name so a rename cannot silently re-break the call site."""
        self.assertTrue(
            hasattr(skills, "build_index"),
            "SkillHarvester calls build_index(); keep them in sync",
        )
        self.assertIsNotNone(SkillHarvester)

    def test_harvester_calls_existing_build_index_helper(self):
        """SkillHarvester must invoke build_index() directly inside skills.py."""
        src = Path(skills.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        harvester_cls = next(
            n for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == "SkillHarvester"
        )
        called = {
            node.func.id
            for node in ast.walk(harvester_cls)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("build_index", called)
        self.assertTrue(hasattr(skills, "build_index"))


if __name__ == "__main__":
    unittest.main()
