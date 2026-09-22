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
import re
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from baize.intelligence_radar import (
    BENCHMARK_COMPETITORS,
    LUMINARIES_PROVENANCE,
    RADAR_ADVANTAGE_PROVENANCE,
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
        """It delegates to the competitor tracker; it does not rank by stars.

        The old assertion was `len(repos) == 5` and `"name" in repos[0]`, which
        passes for any function returning five dicts - so it could not see that
        the class did none of what its docstring claimed. Pinned instead: the rows
        *are* the competitor tracker's rows, in its order, and carry no star data.
        """
        with mock.patch.object(urllib.request, "urlopen", _ok_urlopen()):
            repos = GitHubAgentRadar.fetch_top_agent_repos(5)
            comps = BenchmarkCompetitorTracker.fetch_competitor_latest_activity(5)
        self.assertEqual([r["name"] for r in repos], [c["name"] for c in comps])
        self.assertNotIn(
            "stars", repos[0],
            "star data appeared - if the class now really ranks by stars, its "
            "docstring and this assertion both need updating")

    def test_only_the_commits_endpoint_is_requested(self):
        """The description must not promise an endpoint the code never calls.

        `BenchmarkCompetitorTracker`'s docstring claimed "release updates and
        architecture diffs" and its method docstring claimed releases; the only
        request either made was `/commits?per_page=1`. This pins the request
        surface, so a description cannot silently outrun it - and so implementing
        releases forces the docstring to move in the same commit.
        """
        seen = []

        def spy(req, *args, **kwargs):
            seen.append(getattr(req, "full_url", str(req)))
            return _FakeResponse(json.dumps([CANNED_COMMIT]).encode("utf-8"))

        with mock.patch.object(urllib.request, "urlopen", spy):
            BenchmarkCompetitorTracker.fetch_competitor_latest_activity(3)
        self.assertTrue(seen, "no request was made - this test would be vacuous")
        for url in seen:
            # Negative first, so the failure message names the endpoint that was
            # added rather than the one that went missing. Counter-proved by
            # inserting a real /releases request: this line fires and prints it.
            self.assertNotIn("/releases", url)
            self.assertNotIn("/compare", url)
            self.assertIn("/commits?", url)

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
        insights = LuminariesIntelTracker.get_insights()
        self.assertTrue(len(insights) >= 5)
        authors = [i["author"] for i in insights]
        self.assertTrue(any("Karpathy" in a for a in authors))
        self.assertTrue(any("Altman" in a for a in authors))
        self.assertTrue(any("贾扬清" in a for a in authors))

    def test_the_luminaries_rows_do_not_claim_to_be_recent(self):
        """The key was `recent_insight`, and there is no date anywhere in the list.

        A field name is a claim like any other. `get_latest_insights` said
        "latest" and returned a literal; nothing in this repository records when
        any of these five paragraphs was written, so "recent" was not merely
        unverified but unverifiable - and it is the word that let a static list
        be read as a news feed.
        """
        insights = LuminariesIntelTracker.get_insights()
        for row in insights:
            self.assertNotIn(
                "recent_insight", row,
                f"{row.get('author')!r} still carries a key claiming recency")
            self.assertIn("insight_summary", row)
            self.assertTrue(row["insight_summary"].strip())

    def test_the_report_does_not_quote_the_repository_s_own_prose(self):
        """Our paragraph, under a real person's name, wrapped in quotation marks.

        `- **最新洞见**：> *“...”*` renders as a citation, and the text is a literal
        in `intelligence_radar.py` with no recorded origin. Quotation marks are
        not decoration: they are the part that makes a reader believe the named
        person said it.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(urllib.request, "urlopen", _ok_urlopen()):
                report_intel, _ = generate_daily_evolution_report(output_dir=tmp_dir)
            content = Path(report_intel).read_text(encoding="utf-8")
        self.assertIn(LUMINARIES_PROVENANCE, content)
        self.assertNotIn("**最新洞见**", content)
        self.assertNotIn("> *“", content)
        # The prose itself is still published - just not as somebody's words.
        for row in LuminariesIntelTracker.get_insights():
            self.assertIn(row["insight_summary"], content)
            self.assertNotIn(f'*“{row["insight_summary"]}”*', content)

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
SKILLS_DIR = ROOT / "assets" / "skills"
PLACEHOLDER_MSG = "持续演进与功能迭代"
LUMINARIES_HEADING = "## 🧠 二、全球 AI 顶级思想领袖架构洞见与白泽践行"
SECTION_THREE_HEADING = "## 🛠️ 三、"
MISSION_MARK = "**雷达使命**"
MISSION_FALSE_CLAIM = "大佬前沿思想"
ADVANTAGE_COLUMN_MARK = "白泽压倒性优势"


def _reports_with_a_false_mission_line(directory: Path) -> list[str]:
    """Reports whose own first line claims the radar tracks luminary thought daily.

    The section-17 fix corrected section two and left the mission line above it
    claiming the opposite: "每日全天候跟踪 ... 全球顶尖 AI 大佬前沿思想". A report that
    contradicts itself on its own first page is worse than either half alone - the
    mission line is what a reader believes *before* they reach the note that
    corrects it, and a reader who stops early only ever sees the claim.

    Scope is files carrying the mission line, the same boundary rule as the other
    two probes: `UPGRADE_RFC_LATEST.md` has no mission line, and a file cannot
    mis-state a line it does not have.
    """
    bad = []
    for path in sorted(directory.glob("*.md")):
        for line in path.read_text(encoding="utf-8").split("\n"):
            if MISSION_MARK in line and MISSION_FALSE_CLAIM in line:
                bad.append(path.name)
                break
    return bad


# Italics wrapping quotation marks around a whole line: the epigraph convention.
# It reads as "somebody's words" while naming nobody, and nothing in this
# repository records a source for any of them. One of the six sat at the bottom of
# a skill named after a real person, where the surrounding prose supplied the
# attribution that the quote marks only implied.
UNATTRIBUTED_EPIGRAPH = re.compile(r"^\s*\*[\u201c\u201d](?P<body>.+)[\u201c\u201d]\*\s*$")


def _files_with_unattributed_epigraphs(root: Path) -> list[str]:
    bad = []
    for path in sorted(root.rglob("*.md")):
        for line in path.read_text(encoding="utf-8").split("\n"):
            if UNATTRIBUTED_EPIGRAPH.match(line):
                bad.append(str(path.relative_to(root)).replace("\\", "/"))
                break
    return bad


def _reports_missing_advantage_provenance(directory: Path) -> list[str]:
    """Reports whose "白泽压倒性优势" column carries no note saying what it is.

    That column is filled from ``BENCHMARK_COMPETITORS``, a hand-written
    constant, and it holds numbers no run produced: "响应速度快 10 倍", "<5ms",
    "100% 全量索引" - and until this round "Token 节省 70%", which the one
    measurement available (``scripts/measure_slicing.py``) contradicts outright:
    its measured lower bound is 0%. The table's other note covers the Commit
    column only, so a reader had no way to tell a fetched cell from a written
    one, and a number in a table reads as a measurement wherever it sits.

    Scope is files carrying the column, the same boundary rule as the other
    probes: ``UPGRADE_RFC_LATEST.md`` is a different document with no such column.
    """
    missing = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if ADVANTAGE_COLUMN_MARK not in text:
            continue
        if RADAR_ADVANTAGE_PROVENANCE not in text:
            missing.append(path.name)
    return missing


def _reports_missing_luminaries_origin(directory: Path) -> list[str]:
    """Reports with a luminaries section that never say where that section came from.

    The same failure as the commit column, one layer down. The five paragraphs are
    hand-written constants, but the renderer put each one inside “” under a real
    person's name - so the report presented this repository's prose as those
    people's words. Silence about the origin is the whole mechanism: with a note,
    a reader knows what they are reading; without one, the quotation marks decide.

    Scope is "files that contain the section". `UPGRADE_RFC_LATEST.md` has none,
    and a file cannot mis-state the origin of a section it does not have - the
    same boundary mistake as the commit-column probe's first version, so it is
    pinned by `test_the_luminaries_probe_ignores_a_report_without_the_section`.
    """
    missing = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if LUMINARIES_HEADING not in text:
            continue
        if LUMINARIES_PROVENANCE not in text:
            missing.append(path.name)
    return missing


def _luminaries_section(text: str) -> str | None:
    """Section two verbatim, or None when this file has no such section.

    Everything between the section-two heading and section three is static - no
    date, no fetched value - so a committed report and a fresh run must agree on
    it character for character. That is what makes an exact comparison possible
    instead of a marker check, which a hand-edited file would still pass.
    """
    start = text.find(LUMINARIES_HEADING)
    if start == -1:
        return None
    end = text.find(SECTION_THREE_HEADING, start)
    if end == -1:
        return None
    return text[start:end]


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

    # ---------------------------------------------- the luminaries section

    def test_the_luminaries_probe_can_fail(self):
        """Calibration: a probe that always finds nothing passes the rest by luck."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            (d / "DAILY_INTEL_20990201.md").write_text(
                f"{LUMINARIES_HEADING}\n\n"
                "### 👤 Someone\n- **最新洞见**：> *“a hand-written line”*\n",
                encoding="utf-8")
            self.assertEqual(_reports_missing_luminaries_origin(d),
                             ["DAILY_INTEL_20990201.md"])

    def test_the_luminaries_probe_ignores_a_report_without_the_section(self):
        """Boundary, pinned on purpose: the RFC pointer has no luminaries section,
        and a gate that fires on a legitimate file is how a gate gets switched off."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            (d / "UPGRADE_RFC_LATEST.md").write_text(
                "## 🛠️ 静态能力矩阵\n\n| a | b |\n", encoding="utf-8")
            self.assertEqual(_reports_missing_luminaries_origin(d), [])

    def test_every_committed_report_states_where_the_luminaries_section_came_from(self):
        reports = sorted(RADAR_DIR.glob("*.md"))
        self.assertTrue(reports, "no reports found - this test would be vacuous")
        self.assertEqual(
            _reports_missing_luminaries_origin(RADAR_DIR), [],
            "these committed reports print five hand-written paragraphs inside "
            "quotation marks under real people's names, and never say the text is "
            "this repository's own")

    def test_the_committed_luminaries_section_is_what_the_generator_now_emits(self):
        """The files must *equal* the renderer output, not merely contain a marker.

        A marker check passes on a file whose five paragraphs were hand-edited
        afterwards. Section two is fully static, so it can be compared exactly.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(urllib.request, "urlopen", _ok_urlopen()):
                report_intel, _ = generate_daily_evolution_report(output_dir=tmp_dir)
            fresh = _luminaries_section(
                Path(report_intel).read_text(encoding="utf-8"))
        self.assertIsNotNone(fresh, "the generator no longer emits the section")
        checked = 0
        for path in sorted(RADAR_DIR.glob("DAILY_INTEL_*.md")):
            section = _luminaries_section(path.read_text(encoding="utf-8"))
            if section is None:
                continue
            checked += 1
            self.assertEqual(
                section, fresh,
                f"{path.name}: section two is not what the current renderer "
                f"produces - the file was edited, or the renderer moved without it")
        self.assertTrue(checked, "no committed report had the section - vacuous")

    # ---------------------------------------------- the mission line

    def test_the_mission_line_probe_can_fail(self):
        """Calibration."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            (d / "DAILY_INTEL_20990301.md").write_text(
                f"> {MISSION_MARK}：每日全天候跟踪 ... 与全球顶尖 AI 大佬前沿思想，"
                f"为白泽智能体提供坚实的超越依据！\n", encoding="utf-8")
            self.assertEqual(_reports_with_a_false_mission_line(d),
                             ["DAILY_INTEL_20990301.md"])

    def test_the_mission_line_probe_ignores_a_report_without_one(self):
        """Boundary: the RFC pointer has no mission line."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            (d / "UPGRADE_RFC_LATEST.md").write_text(
                "## 🛠️ 静态能力矩阵\n\n| a | b |\n", encoding="utf-8")
            self.assertEqual(_reports_with_a_false_mission_line(d), [])

    def test_no_committed_report_claims_daily_luminary_tracking(self):
        reports = sorted(RADAR_DIR.glob("*.md"))
        self.assertTrue(reports, "no reports found - this test would be vacuous")
        self.assertEqual(
            _reports_with_a_false_mission_line(RADAR_DIR), [],
            "these reports open by claiming the radar tracks luminary thought "
            "daily, while section two is a hand-written constant that had not "
            "changed in 19 days")

    def test_the_current_reports_mission_line_is_what_the_generator_emits(self):
        """The four post-tracker reports must carry the renderer's line verbatim.

        `DAILY_INTEL_20260831.md` is excluded on purpose: it predates the
        competitor tracker and its first half describes a star-ranked Top-10
        search, which its own generator really did run (verified in `32f4d3a`).
        Only its luminary half was false, so only that half was corrected, and
        asserting identity with today's renderer would be wrong for it.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(urllib.request, "urlopen", _ok_urlopen()):
                report_intel, _ = generate_daily_evolution_report(output_dir=tmp_dir)
            fresh = next(ln for ln in Path(report_intel).read_text(
                encoding="utf-8").split("\n") if MISSION_MARK in ln)
        checked = 0
        for path in sorted(RADAR_DIR.glob("DAILY_INTEL_*.md")):
            if path.name == "DAILY_INTEL_20260831.md":
                continue
            line = next((ln for ln in path.read_text(encoding="utf-8").split("\n")
                         if MISSION_MARK in ln), None)
            if line is None:
                continue
            checked += 1
            self.assertEqual(line, fresh,
                             f"{path.name}: mission line is not the renderer's")
        self.assertTrue(checked, "no report had a mission line - vacuous")


    # ------------------------------------------- the advantage column's note

    def test_the_advantage_provenance_probe_can_fail(self):
        """Calibration."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            (d / "DAILY_INTEL_20990301.md").write_text(
                f"| 标杆竞品 | {ADVANTAGE_COLUMN_MARK} |\n"
                f"| --- | --- |\n"
                f"| Hermes | 白泽在 Windows 上响应速度快 10 倍！ |\n",
                encoding="utf-8")
            self.assertEqual(_reports_missing_advantage_provenance(d),
                             ["DAILY_INTEL_20990301.md"])

    def test_the_advantage_provenance_probe_ignores_a_report_without_the_column(self):
        """Boundary: the RFC document has no advantage column."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            (d / "UPGRADE_RFC_LATEST.md").write_text(
                "## 🛠️ 静态能力矩阵\n\n| a | b |\n", encoding="utf-8")
            self.assertEqual(_reports_missing_advantage_provenance(d), [])

    def test_no_committed_report_states_an_unmeasured_advantage(self):
        reports = sorted(RADAR_DIR.glob("*.md"))
        self.assertTrue(reports, "no reports found - this test would be vacuous")
        self.assertEqual(
            _reports_missing_advantage_provenance(RADAR_DIR), [],
            "these reports carry the 白泽压倒性优势 column without saying that "
            "it is hand-written product copy rather than a measurement")

    def test_no_committed_report_claims_a_token_saving_percentage(self):
        """The one figure in that column a measurement contradicts.

        `Token 节省 70%` sat beside a real measurement mechanism whose lower
        bound is 0%, so it was not merely unsourced - it was wrong for a
        measurable share of inputs. It is now a pointer at the measurement.
        """
        offenders = []
        for path in sorted(RADAR_DIR.glob("*.md")):
            for i, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
                if "节省 70%" in line or "压缩 70%" in line:
                    offenders.append(f"{path.name}:{i}")
        self.assertEqual(
            offenders, [],
            "these lines state a fixed token-saving percentage; the ratio is "
            "computed per call and measures 0% on a module with nothing to prune")


class TestAttributedProse(unittest.TestCase):
    """Prose this repository wrote, formatted so a reader attributes it elsewhere."""

    def test_the_epigraph_probe_can_fail(self):
        """Calibration."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            (d / "some_skill").mkdir()
            (d / "some_skill" / "SKILL.md").write_text(
                "*\u201cSome maxim nobody is named for.\u201d*\n", encoding="utf-8")
            self.assertEqual(_files_with_unattributed_epigraphs(d),
                             ["some_skill/SKILL.md"])

    def test_the_epigraph_probe_ignores_a_labelled_line(self):
        """The other half: a labelled line makes the same sentence legitimate."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            (d / "some_skill").mkdir()
            (d / "some_skill" / "SKILL.md").write_text(
                "*白泽手写整理，无注明出处：Some maxim nobody is named for.*\n",
                encoding="utf-8")
            self.assertEqual(_files_with_unattributed_epigraphs(d), [])

    def test_no_skill_ends_with_an_unattributed_quotation(self):
        self.assertTrue(SKILLS_DIR.is_dir(), "skills library not found")
        self.assertEqual(
            _files_with_unattributed_epigraphs(SKILLS_DIR), [],
            "these skill files end with an italic quotation naming no source; the "
            "epigraph format reads as somebody's words, and one of them sits in a "
            "skill named after a real person")


if __name__ == "__main__":
    unittest.main()
