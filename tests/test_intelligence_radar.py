"""Unit tests for Global AI Evolution & Intelligence Radar with Benchmark Competitor Tracking."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from baize.intelligence_radar import (
    BenchmarkCompetitorTracker,
    GitHubAgentRadar,
    LuminariesIntelTracker,
    generate_daily_evolution_report,
)


class TestIntelligenceRadar(unittest.TestCase):
    def test_github_agent_radar_fetch(self):
        repos = GitHubAgentRadar.fetch_top_agent_repos(5)
        self.assertIsInstance(repos, list)
        self.assertTrue(len(repos) > 0)
        self.assertIn("name", repos[0])

    def test_benchmark_competitor_tracker(self):
        comps = BenchmarkCompetitorTracker.fetch_competitor_latest_activity(10)
        self.assertEqual(len(comps), 10)
        names = [c["name"] for c in comps]
        self.assertTrue(any("Hermes" in n for n in names))
        self.assertTrue(any("DeepSeek" in n for n in names))
        self.assertTrue(any("OpenHands" in n for n in names))
        self.assertTrue(any("Claude Code" in n for n in names))
        self.assertTrue(any("Pi" in n for n in names))

    def test_luminaries_intel_tracker(self):
        insights = LuminariesIntelTracker.get_latest_insights()
        self.assertTrue(len(insights) >= 5)
        authors = [i["author"] for i in insights]
        self.assertTrue(any("Karpathy" in a for a in authors))
        self.assertTrue(any("Altman" in a for a in authors))
        self.assertTrue(any("贾扬清" in a for a in authors))

    def test_generate_daily_evolution_report(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_intel, report_rfc = generate_daily_evolution_report(output_dir=tmp_dir)
            self.assertTrue(Path(report_intel).exists())
            self.assertTrue(Path(report_rfc).exists())
            content = Path(report_intel).read_text(encoding="utf-8")
            self.assertIn("白泽全球 AI 标杆竞品追踪与思想雷达日报", content)
            self.assertIn("Hermes Agent", content)
            self.assertIn("DeepSeek", content)
            self.assertIn("OpenHands", content)
            self.assertIn("Claude Code", content)


if __name__ == "__main__":
    unittest.main()
