"""Unit tests for Global AI Evolution & Intelligence Radar with Benchmark Competitor Tracking.

These tests never touch the network. They used to call the real GitHub API (5 + 10 + 10
requests per run), which had two consequences: the suite itself exhausted the anonymous
rate limit, and the only observable difference between "the tracker worked" and "every
request 403'd" was a coverage number - the assertions below could not see it either,
because they only measured the length of a module-level constant. A fake transport makes
the parse path measurable and the result deterministic.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from baize.intelligence_radar import (
    BENCHMARK_COMPETITORS,
    BenchmarkCompetitorTracker,
    GitHubAgentRadar,
    LuminariesIntelTracker,
    generate_daily_evolution_report,
)

# A payload shaped like `GET /repos/{repo}/commits?per_page=1`.
CANNED_COMMIT = {
    "sha": "abcdef1234567890abcdef1234567890abcdef12",
    "commit": {
        "message": "fix: a real commit subject\n\nbody line",
        "author": {"date": "2026-01-02T03:04:05Z"},
    },
}


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ok_urlopen(payload=CANNED_COMMIT):
    body = json.dumps([payload]).encode("utf-8")
    return mock.Mock(return_value=_FakeResponse(body))


def _rate_limited_urlopen():
    return mock.Mock(side_effect=urllib.error.HTTPError(
        "https://api.github.com/x", 403, "rate limit exceeded", {}, None))


def _first_ok_then_rate_limited():
    """Fresh counter per use: the report generator calls the tracker again."""
    state = {"n": 0}

    def flaky(req, *a, **k):
        state["n"] += 1
        if state["n"] == 1:
            return _ok_urlopen()(req, *a, **k)
        raise urllib.error.HTTPError("https://api.github.com/x", 403,
                                     "rate limit exceeded", {}, None)

    return flaky


class TestIntelligenceRadar(unittest.TestCase):
    def test_github_agent_radar_fetch(self):
        with mock.patch.object(urllib.request, "urlopen", _ok_urlopen()):
            repos = GitHubAgentRadar.fetch_top_agent_repos(5)
        self.assertIsInstance(repos, list)
        self.assertEqual(len(repos), 5)
        self.assertIn("name", repos[0])

    def test_benchmark_competitor_tracker(self):
        with mock.patch.object(urllib.request, "urlopen", _ok_urlopen()):
            comps = BenchmarkCompetitorTracker.fetch_competitor_latest_activity(10)
        self.assertEqual(len(comps), 10)
        names = [c["name"] for c in comps]
        self.assertTrue(any("Hermes" in n for n in names))
        self.assertTrue(any("DeepSeek" in n for n in names))
        self.assertTrue(any("OpenHands" in n for n in names))
        self.assertTrue(any("Claude Code" in n for n in names))
        self.assertTrue(any("Pi" in n for n in names))

    def test_a_successful_fetch_actually_parses_the_response(self):
        """The old assertions could not fail here: they measured a static list."""
        with mock.patch.object(urllib.request, "urlopen", _ok_urlopen()):
            comps = BenchmarkCompetitorTracker.fetch_competitor_latest_activity(1)
        row = comps[0]
        self.assertIs(row["fetched"], True)
        self.assertEqual(row["fetch_error"], "")
        self.assertEqual(row["latest_sha"], "abcdef1")          # 7-char short sha
        self.assertEqual(row["latest_commit_date"], "2026-01-02")
        self.assertEqual(row["latest_commit_msg"], "fix: a real commit subject")
        # The placeholder must not survive a successful fetch.
        self.assertNotEqual(row["latest_sha"], "main")
        self.assertNotEqual(row["latest_commit_msg"], "持续演进与功能迭代")

    def test_a_rate_limited_fetch_is_not_reported_as_a_commit(self):
        """403 means "we could not look" - never "the competitor stopped committing"."""
        with mock.patch.object(urllib.request, "urlopen", _rate_limited_urlopen()):
            comps = BenchmarkCompetitorTracker.fetch_competitor_latest_activity(3)
        for row in comps:
            self.assertIs(row["fetched"], False)
            self.assertIn("403", row["fetch_error"])
        self.assertEqual(sum(1 for c in comps if c["fetched"]), 0)

    def test_the_report_does_not_present_a_placeholder_as_a_commit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(urllib.request, "urlopen", _rate_limited_urlopen()):
                report_intel, _ = generate_daily_evolution_report(output_dir=tmp_dir)
            content = Path(report_intel).read_text(encoding="utf-8")
        self.assertIn("未获取", content)
        self.assertIn("403", content)
        # The fabricated row is gone: no placeholder rendered as a commit subject.
        self.assertNotIn("持续演进与功能迭代", content)
        self.assertNotIn("`main` (", content)

    def test_the_report_says_how_many_rows_were_actually_fetched(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(urllib.request, "urlopen", _rate_limited_urlopen()):
                report_intel, _ = generate_daily_evolution_report(output_dir=tmp_dir)
            content = Path(report_intel).read_text(encoding="utf-8")
        self.assertIn("仅 **0 个**成功读取 GitHub API", content)
        self.assertIn("不是「没有变更」", content)

    def test_a_partially_fetched_run_does_not_claim_a_complete_survey(self):
        """1 success + N-1 failures must read as 1/N, not as a full survey."""
        with mock.patch.object(urllib.request, "urlopen", _first_ok_then_rate_limited()):
            comps = BenchmarkCompetitorTracker.fetch_competitor_latest_activity(4)
        self.assertEqual(sum(1 for c in comps if c["fetched"]), 1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(urllib.request, "urlopen", _first_ok_then_rate_limited()):
                report_intel, _ = generate_daily_evolution_report(output_dir=tmp_dir)
            content = Path(report_intel).read_text(encoding="utf-8")
        self.assertIn("1 个**成功读取 GitHub API", content)
        self.assertNotIn("均成功读取 GitHub API", content)

    def test_a_fully_fetched_run_says_so(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(urllib.request, "urlopen", _ok_urlopen()):
                report_intel, _ = generate_daily_evolution_report(output_dir=tmp_dir)
            content = Path(report_intel).read_text(encoding="utf-8")
        self.assertIn("均成功读取 GitHub API", content)
        self.assertNotIn("未获取", content)

    def test_luminaries_intel_tracker(self):
        insights = LuminariesIntelTracker.get_latest_insights()
        self.assertTrue(len(insights) >= 5)
        authors = [i["author"] for i in insights]
        self.assertTrue(any("Karpathy" in a for a in authors))
        self.assertTrue(any("Altman" in a for a in authors))
        self.assertTrue(any("贾扬清" in a for a in authors))

    def test_generate_daily_evolution_report(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(urllib.request, "urlopen", _ok_urlopen()):
                report_intel, report_rfc = generate_daily_evolution_report(output_dir=tmp_dir)
            self.assertTrue(Path(report_intel).exists())
            self.assertTrue(Path(report_rfc).exists())
            content = Path(report_intel).read_text(encoding="utf-8")
            self.assertIn("白泽全球 AI 标杆竞品追踪与思想雷达日报", content)
            self.assertIn("Hermes Agent", content)
            self.assertIn("DeepSeek", content)
            self.assertIn("OpenHands", content)
            self.assertIn("Claude Code", content)
            # ...and the fetched values reached the rendered table.
            self.assertIn("abcdef1", content)
            self.assertIn("fix: a real commit subject", content)
            rfc = Path(report_rfc).read_text(encoding="utf-8")
            self.assertIn("静态能力矩阵", rfc)

    def test_every_competitor_row_carries_the_fetch_verdict(self):
        """Consumers must be able to tell a measured row from an unmeasured one."""
        with mock.patch.object(urllib.request, "urlopen", _ok_urlopen()):
            comps = BenchmarkCompetitorTracker.fetch_competitor_latest_activity(
                len(BENCHMARK_COMPETITORS))
        for row in comps:
            self.assertIn("fetched", row)
            self.assertIn("fetch_error", row)
            self.assertIsInstance(row["fetched"], bool)


# ------------------------------------------------- committed report artifacts
#
# Everything above calls the generator, so it only ever sees a *fresh* report.
# The two reports the generator printed before the placeholder fix are still in
# the repository, and nothing looked at them - the same shape as `.gitignore` not
# applying retroactively: a gate over the code path says nothing about what is
# already on disk. Observed in the real files: ten rows of a column titled
# "最新 Commit / 动态" holding `main` / the generation date / 持续演进与功能迭代,
# with no statement anywhere that nothing had been fetched.

ROOT = Path(__file__).resolve().parent.parent
RADAR_DIR = ROOT / "docs" / "radar"
PLACEHOLDER_MSG = "持续演进与功能迭代"


def _reports_missing_provenance(directory: Path) -> list[str]:
    """Daily reports that carry a commit column but never say how much of it is real.

    A report full of placeholder cells is not wrong by itself - the fetch may
    have failed, and that is a fact worth recording. What is wrong is a report
    that *stays silent* about it: a placeholder cell and a fetched cell render
    identically, so silence is what turns an outage into a survey.

    Scope is the competitor report shape - a table with a column titled
    "最新 Commit / 动态". `DAILY_INTEL_20260831.md` is a different report (a star
    ranking that no code in this repository generates), so it has no commit
    column and is deliberately out of scope: a file cannot mis-state the
    provenance of a column it does not have. This scope was got wrong once - the
    first version of this probe reported 0831 - so the boundary is pinned by
    `test_the_probe_ignores_a_report_without_a_commit_column` below.
    """
    missing = []
    for path in sorted(directory.glob("DAILY_INTEL_*.md")):
        text = path.read_text(encoding="utf-8")
        if "最新 Commit / 动态" not in text:
            continue
        if "**数据完整性**" not in text:
            missing.append(path.name)
    return missing


class TestCommittedRadarReports(unittest.TestCase):
    def test_the_probe_can_fail(self):
        """Calibration: a probe that always finds nothing would pass everything
        below by accident."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            (d / "DAILY_INTEL_20990101.md").write_text(
                "| 标杆竞品 | 官方仓库 | 最新 Commit / 动态 | 焦点 | 优势 |\n"
                f"| **X** | `main` (2099-01-01)<br>*{PLACEHOLDER_MSG}* |\n",
                encoding="utf-8")
            self.assertEqual(_reports_missing_provenance(d),
                             ["DAILY_INTEL_20990101.md"])

    def test_the_probe_does_not_fire_on_a_report_that_states_its_provenance(self):
        """The other half: the probe must not report a file that is honest."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            (d / "DAILY_INTEL_20990102.md").write_text(
                "| 标杆竞品 | 官方仓库 | 最新 Commit / 动态 | 焦点 | 优势 |\n"
                "> **数据完整性**：10 个竞品中仅 **0 个**成功读取 GitHub API。\n",
                encoding="utf-8")
            self.assertEqual(_reports_missing_provenance(d), [])

    def test_the_probe_ignores_a_report_without_a_commit_column(self):
        """Scope, pinned because I got it wrong: the first version of this probe
        reported `DAILY_INTEL_20260831.md`, which is a star ranking with no commit
        column and no generator in this repository. A gate that fires on a
        legitimate file is how a gate gets switched off."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            (d / "DAILY_INTEL_20990103.md").write_text(
                "| 排名 | 仓库名称 | ⭐ Stars | 技术特点 | 建议 |\n"
                "| **1** | **[a/b](https://github.com/a/b)** | `238,722` | x | y |\n",
                encoding="utf-8")
            self.assertEqual(_reports_missing_provenance(d), [])

    def test_every_committed_daily_report_states_its_provenance(self):
        reports = sorted(RADAR_DIR.glob("DAILY_INTEL_*.md"))
        self.assertTrue(reports, "no daily reports found - this test would be vacuous")
        self.assertEqual(
            _reports_missing_provenance(RADAR_DIR), [],
            "these committed reports never say how much of their Commit column was "
            "actually fetched, so a placeholder cell reads exactly like a real one")

    def test_a_report_with_placeholders_cannot_claim_a_complete_survey(self):
        """The two claims are mutually exclusive, and only this checks it."""
        for path in sorted(RADAR_DIR.glob("DAILY_INTEL_*.md")):
            text = path.read_text(encoding="utf-8")
            if PLACEHOLDER_MSG in text:
                self.assertNotIn(
                    "均成功读取 GitHub API", text,
                    f"{path.name} contains placeholder commit cells and also claims "
                    f"that every competitor was fetched successfully")


if __name__ == "__main__":
    unittest.main()
