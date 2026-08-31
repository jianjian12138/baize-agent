#!/usr/bin/env python
"""Daily AI Intelligence & Evolution Radar Runner Script.

Usage:
  python scripts/daily_ai_radar.py
  python scripts/daily_ai_radar.py --output docs/radar
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from baize.intelligence_radar import generate_daily_evolution_report


def main():
    parser = argparse.ArgumentParser(description="Baize Daily AI Intelligence Radar")
    parser.add_argument("--output", default="docs/radar", help="Output directory for daily briefing markdown")
    args = parser.parse_args()

    print("[Baize Radar] 正在启动白泽全球 AI 演化雷达，全天候巡航 GitHub 竞品与全球顶尖 AI 思想领袖智库...")
    try:
        report_intel, report_rfc = generate_daily_evolution_report(args.output)
        print(f"[Baize Radar] ✅ 今日全球 AI 演化研报已生成: {report_intel}")
        print(f"[Baize Radar] 🛠️ 今日可升级借鉴功能方案 RFC: {report_rfc}")
        print(f"[Baize Radar] 📄 最新研报指针: docs/radar/LATEST.md")
        print(f"[Baize Radar] 📄 最新升级方案指针: docs/radar/UPGRADE_RFC_LATEST.md")
    except Exception as exc:
        print(f"[Baize Radar] ❌ 雷达生成失败: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
