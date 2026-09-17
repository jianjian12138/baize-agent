"""Regression tests for the skill-harvest -> index rebuild hand-off.

Found by actually running `baize run` end to end: the log said

    [harvester] failed to rebuild index: module 'baize.skill_index'
    has no attribute 'build'

`skill_harvester` called `skill_index.build()`, but the module exposes
`build_index()`. The AttributeError was swallowed by a broad `except Exception`
that only logged a warning, so the failure was invisible: every distilled skill
was written to disk and then never entered the index, i.e. never findable again.

The assertion that matters is not "the function was called" but "the harvested
skill can be found afterwards" - that is the actual contract, and it is what
would have caught the typo.
"""
from __future__ import annotations

import unittest

from baize import skill_index
from baize.skill_harvester import SkillHarvester


class TestHarvestRebuildsIndex(unittest.TestCase):
    def test_skill_index_exposes_the_name_the_harvester_calls(self):
        """Pin the API name so a rename cannot silently re-break the call site."""
        self.assertTrue(
            hasattr(skill_index, "build_index"),
            "skill_harvester calls skill_index.build_index(); keep them in sync")

    def test_harvester_calls_an_existing_skill_index_attribute(self):
        """Any skill_index.<attr> referenced in the harvester must exist.

        This is the generic form of the bug: a wrong attribute name is only
        caught at runtime, and here runtime failures were being logged away.

        Parsed with ``ast`` rather than a regex: a regex over the raw source
        also matches ``skill_index.py`` in comments and docstrings and reports
        a bogus ``py`` attribute.
        """
        import ast
        from pathlib import Path

        src = Path(skill_index.__file__).parent.joinpath(
            "skill_harvester.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        referenced = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "skill_index"
        }
        self.assertTrue(referenced, "expected the harvester to use skill_index")
        missing = sorted(n for n in referenced if not hasattr(skill_index, n))
        self.assertEqual(missing, [],
                         f"skill_harvester references non-existent "
                         f"skill_index attribute(s): {missing}")


if __name__ == "__main__":
    unittest.main()
