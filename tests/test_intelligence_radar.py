"""Unit tests for Global AI Evolution & Intelligence Radar."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from baize.intelligence_radar import (
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

    def test_luminaries_intel_tracker(self):
        insights = LuminariesIntelTracker.get_latest_insights()
        self.assertTrue(len(insights) >= 5)
        authors = [i["author"] for i in insights]
        self.assertTrue(any("Karpathy" in a for a in authors))
        self.assertTrue(any("Altman" in a for a in authors))
        self.assertTrue(any("贾扬清" in a for a in authors))

    def test_generate_daily_evolution_report(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_file = generate_daily_evolution_report(output_dir=tmp_dir)
            self.assertTrue(Path(report_file).exists())
            content = Path(report_file).read_text(encoding="utf-8")
            self.assertIn("白泽全球 AI 前沿演进与思想雷达日报", content)
            self.assertIn("Andrej Karpathy", content)
            self.assertIn("Sam Altman", content)


if __name__ == "__main__":
    unittest.main()
