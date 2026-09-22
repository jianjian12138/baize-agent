"""Claims a document makes about *this tree* that no gate was checking.

Two families, both found in round three of the audit:

* A **coverage verdict**. `docs/tutorials/README.md` said "覆盖率下限为 85%，当前
  **未达标（门禁 RED）**" while the gate was green at 86.6%, and the same file said
  so 35 lines below. `sync_truth.py` pins every *count* in that table; nothing
  pinned the verdict - so removing a stale number while keeping the stale verdict
  it belonged to passed every check in the repository. That is the worse half to
  keep: the number is a detail, the verdict is what a reader remembers, and a
  reader who stops at that section only ever sees "未达标".

* A **version literal** in a file `sync_truth.py` pins with ``VERSION_ONLY``. That
  surface's own comment says "Only safe on a file where *every* V-label is the
  release - verify before adding a new file", i.e. the precondition was checked by
  hand and by memory. `docs/benchmarks.md` had two V-labels: the title said
  V37.0.0 and the comparison-table header said "(Baize Agent V33)", five releases
  stale. The surface matched the title, ``min_hits`` was 1, and a bare "V33" does
  not match ``V\\d+\\.\\d+\\.\\d+`` anyway - so the gate counted one correct label
  and passed. The test below verifies the precondition instead of trusting it.

Every probe is paired with a calibration test that proves it *can* fail, so a
probe that silently matches nothing cannot be mistaken for a working gate.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "sync_truth", ROOT / "scripts" / "sync_truth.py"
)
sync_truth = importlib.util.module_from_spec(_spec)
# Registered before exec_module: `@dataclass` resolves annotations through
# sys.modules[cls.__module__], so a module loaded by path without this entry
# raises AttributeError on the first dataclass it defines.
sys.modules["sync_truth"] = sync_truth
_spec.loader.exec_module(sync_truth)


def _probe_file(test: unittest.TestCase, body: str) -> Path:
    """A throwaway markdown file, cleaned up even when the assertion fails.

    Written to a temp directory rather than the repository: a probe that leaves
    files in the working tree can fail the very gate it is testing.
    """
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    path = Path(tmp.name) / "probe.md"
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------- coverage verdict

#: "the gate is red right now". Present tense is the whole point: "曾经是 77.4%,
#: 门禁 RED" is a record of the past and must survive, so a quotation of the old
#: sentence is excluded by the opening quote mark. Without that exclusion the
#: probe would fire on the very note that documents the defect - a gate that
#: flags its own history is a gate somebody turns off.
COVERAGE_FAILURE_VERDICT = re.compile(
    r"(?<!「)(?<!『)(?<!“)(?:当前|目前)[^\n]{0,12}(?:未达标|门禁\s*RED)"
)


def tracked_markdown() -> list[Path]:
    """Tracked ``.md`` files. Tracked, not globbed: untracked scratch in the
    working tree must not be able to fail the gate."""
    out = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=str(ROOT), capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {out.stderr}")
    return [ROOT / line.strip() for line in out.stdout.splitlines() if line.strip()]


def docs_claiming_the_coverage_gate_fails(paths: list[Path]) -> list[str]:
    """Documents asserting, in the present tense, that the coverage gate fails."""
    bad = []
    for path in paths:
        if not path.is_file():
            continue
        for i, line in enumerate(path.read_text(
                encoding="utf-8", errors="replace").split("\n"), 1):
            if COVERAGE_FAILURE_VERDICT.search(line):
                bad.append(f"{path.name}:{i}")
    return bad


# ------------------------------------------------------------------ version labels

#: A version literal, complete or bare. ``V33`` and ``V33.0.0`` both match; the
#: bare form is the one the surface's regex misses, which is how it survived.
VERSION_LITERAL = re.compile(r"\bV(\d+)(?:\.(\d+))?(?:\.(\d+))?\b")

#: V-literals that are provenance markers rather than claims about the current
#: release: "V17 归档" says what ``legacy/`` holds, "(V19)" says when a config
#: block was introduced. Listed one by one on purpose. A rule broad enough to
#: accept them silently would also accept "(Baize Agent V33)", and a rule that
#: flagged them would fire on three legitimate lines - which is how a gate ends
#: up switched off. Adding a marker here is a deliberate edit; that is the point.
KNOWN_PROVENANCE_MARKERS: dict[str, set[str]] = {
    "START-HERE.md": {"V17"},
    ".env.example": {"V19"},
}


def files_pinned_by_version_only() -> list[str]:
    """Files whose *every* V-label is asserted to be the release, per sync_truth."""
    return [
        rel for rel, surfaces in sync_truth.SURFACES.items()
        if any(surface is sync_truth.VERSION_ONLY for surface, _ in surfaces)
    ]


def stale_version_literals(path: Path, release: str) -> list[str]:
    """V-literals in ``path`` that are neither the release nor a known marker."""
    major = release.split(".")[0]
    if not path.is_file():
        return [f"{path.name}: missing"]
    allowed = KNOWN_PROVENANCE_MARKERS.get(path.name, set())
    bad = []
    for i, line in enumerate(path.read_text(
            encoding="utf-8", errors="replace").split("\n"), 1):
        for match in VERSION_LITERAL.finditer(line):
            token = match.group(0)
            if match.group(1) == major or token in allowed:
                continue
            bad.append(f"{path.name}:{i}: {token}")
    return bad


class TestCoverageVerdict(unittest.TestCase):
    def test_the_probe_can_fail(self):
        """Calibration: a plain present-tense claim is caught."""
        path = _probe_file(
            self, "覆盖率下限为 85%，当前**未达标（门禁 RED）**——这是公开的已知缺口。\n")
        self.assertEqual(
            docs_claiming_the_coverage_gate_fails([path]), [f"{path.name}:1"])

    def test_the_probe_ignores_a_quotation_of_the_old_sentence(self):
        """Boundary: the note that records the defect quotes it and must survive."""
        path = _probe_file(
            self,
            "- 上面那节曾经写着一句「当前**未达标（门禁 RED）**」，而那是错的。\n"
            "- 覆盖率曾经是 77.4% < 85%，门禁 RED；那 24 个文件提交后转绿。\n")
        self.assertEqual(docs_claiming_the_coverage_gate_fails([path]), [])

    def test_no_tracked_document_claims_the_coverage_gate_currently_fails(self):
        paths = tracked_markdown()
        self.assertTrue(paths, "no tracked markdown - this test would be vacuous")
        self.assertEqual(
            docs_claiming_the_coverage_gate_fails(paths), [],
            "these documents assert that the coverage gate currently fails. "
            "Coverage is not a property of the commit - the same commit measured "
            "86.9% in a working tree and 86.8% in a fresh clone - so a verdict "
            "written into a document is wrong on one of the two. Point at "
            "`python scripts/coverage_gate.py` instead of stating its answer.")


class TestVersionLabels(unittest.TestCase):
    def test_the_probe_can_fail(self):
        """Calibration: a bare stale major is caught - the shape that got through."""
        path = _probe_file(self, "| 能力维度 | **白泽引擎 (Baize Agent V33)** |\n")
        self.assertTrue(stale_version_literals(path, "37.0.0"))

    def test_the_probe_accepts_a_bare_current_major(self):
        """Boundary: "V37" is not stale, so the probe must not fire on it."""
        path = _probe_file(self, "| 能力维度 | **白泽引擎 (Baize Agent V37)** |\n")
        self.assertEqual(stale_version_literals(path, "37.0.0"), [])

    def test_the_probe_accepts_a_listed_provenance_marker(self):
        """Boundary: "V17 归档" says what legacy/ holds - history, not a claim."""
        path = _probe_file(self, "| legacy/ 是什么 | V17 归档，只读参考 |\n")
        with mock.patch.dict(KNOWN_PROVENANCE_MARKERS, {"probe.md": {"V17"}}):
            self.assertEqual(stale_version_literals(path, "37.0.0"), [])

    def test_every_file_pinned_by_version_only_has_only_release_labels(self):
        """The precondition `sync_truth`'s own comment says to verify by hand."""
        release = sync_truth.read_version()[0]
        pinned = files_pinned_by_version_only()
        self.assertTrue(pinned, "no file pinned by VERSION_ONLY - vacuous")
        problems = []
        for rel in pinned:
            problems += stale_version_literals(ROOT / rel, release)
        self.assertEqual(
            problems, [],
            f"these files are pinned with VERSION_ONLY (min_hits counts V{release} "
            f"labels) but carry a V-literal from another release. A bare 'V33' "
            f"matches neither the surface nor its regex, so it is invisible to "
            f"sync_truth; fix the label or drop the file from SURFACES")


class TestTestBadgeDoesNotOverclaim(unittest.TestCase):
    """The badge's parenthetical must not round up past the fraction beside it."""

    def setUp(self):
        self.labels = sync_truth.Labels("37.0.0", "Prometheus")

    def test_a_skipped_case_does_not_round_the_badge_up_to_100(self):
        badge = self.labels.tests_badge(1351, 1354)
        self.assertNotIn("(100%25)", badge,
                         "round(1351 * 100 / 1354) == 100, so a suite with three "
                         "skipped cases advertised '1351/1354 passed (100%)'")
        self.assertIn("(99%25)", badge)

    def test_a_fully_green_run_still_reads_100(self):
        self.assertIn("(100%25)", self.labels.tests_badge(1354, 1354))

    def test_the_badge_never_claims_more_than_was_observed(self):
        """The property `measure_tests` documents, checked over a range."""
        for passed, total in ((1, 3), (2, 3), (99, 100), (1349, 1354), (1351, 1354)):
            badge = self.labels.tests_badge(passed, total)
            pct = int(re.search(r"\((\d+)%25\)", badge).group(1))
            self.assertLessEqual(
                pct, passed * 100 / total,
                f"{passed}/{total} rendered as {pct}% - the badge claimed more "
                f"green than was observed")


if __name__ == "__main__":
    unittest.main()
