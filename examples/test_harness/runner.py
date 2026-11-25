#!/usr/bin/env python3
"""Reusable Baize Test Harness CLI — works with built-in demo OR any real business service.

Usage:
  # 1) Out-of-the-box demo run (no setup needed)
  python3 examples/test_harness/runner.py --suite all

  # 2) Plug in your real business service via config file
  python3 examples/test_harness/runner.py --config path/to/my-service.harness.json --json --junit .artifacts/junit.xml

  # 3) Point directly at an already-running staging/local URL
  python3 examples/test_harness/runner.py --config my-service.harness.json --base-url http://127.0.0.1:8080 --suite smoke

Exit codes:
  0 = all selected scenarios passed
  1 = business/contract assertion failure
  2 = environment or infrastructure failure
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from core.config import load_harness_config
from core.engine import load_scenarios, run_harness, write_junit_xml


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Baize Reusable Deterministic Test Harness")
    p.add_argument(
        "--config",
        default=str(HERE / "harness.config.json"),
        help="path to harness JSON config (default: built-in demo config)",
    )
    p.add_argument("--base-url", default="", help="override target base URL (switches target mode to external)")
    p.add_argument("--suite", default="all", help="filter by suite tag (default: all, e.g. smoke|e2e|fault)")
    p.add_argument("--scenario", action="append", default=[], help="run only specific scenario id(s)")
    p.add_argument("--artifacts-dir", default="", help="directory for JSON reports & logs (default: <config_dir>/.artifacts)")
    p.add_argument("--junit", default="", help="optional path to export JUnit XML report for CI/CD")
    p.add_argument("--json", action="store_true", help="output machine-readable JSON report to stdout")
    p.add_argument("--list", action="store_true", help="list configured scenarios and exit")
    args = p.parse_args(argv)

    cfg, cfg_dir = load_harness_config(args.config)
    if args.list:
        scenarios = load_scenarios(cfg, cfg_dir)
        items = [{"id": s.get("id"), "suite": s.get("suite", "e2e"), "description": s.get("description", "")} for s in scenarios]
        if args.json:
            print(json.dumps(items, indent=2, ensure_ascii=False))
        else:
            for item in items:
                print(f"{item['id']} [{item['suite']}]  {item['description']}")
        return 0

    artifacts_dir = Path(args.artifacts_dir).resolve() if args.artifacts_dir else (cfg_dir / ".artifacts")
    report = run_harness(
        cfg=cfg,
        config_dir=cfg_dir,
        artifacts_dir=artifacts_dir,
        suite=args.suite,
        scenario_ids=args.scenario or None,
        override_base_url=args.base_url.strip(),
    )
    if args.junit:
        write_junit_xml(report, Path(args.junit).resolve())

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"Test Harness [{report['service']} | {report['suite']}]: "
            f"{report['passed']}/{report['total']} passed ({report['duration_ms']}ms)"
        )
        for r in report["results"]:
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"  [{mark}] {r['scenario_id']} ({r['duration_ms']}ms)")
            if r["failure_reason"]:
                print(f"         reason: {r['failure_reason']}")
        print(f"Evidence bundle: {artifacts_dir / 'latest_report.json'}")
    return int(report["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
