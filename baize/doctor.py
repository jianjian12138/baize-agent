"""Environment doctor - the real gate.

Every check performs an actual probe (filesystem, interpreter, write test).
Exit code 0 = all required checks passed; 1 = at least one required check failed.
No simulated passes. A failing check prints the reason and how to fix it.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import ENV_FILE, ROOT, load_config, skill_library_paths


@dataclass
class CheckResult:
    name: str
    ok: bool
    required: bool
    detail: str = ""


@dataclass
class DoctorReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.ok for r in self.results if r.required)

    def add(self, name: str, ok: bool, required: bool, detail: str = "") -> None:
        self.results.append(CheckResult(name, ok, required, detail))


def run_checks(cfg: dict | None = None) -> DoctorReport:
    cfg = cfg or load_config()
    report = DoctorReport()

    # 1. Python version (>= 3.10 for modern syntax used in this repo)
    py_ok = sys.version_info >= (3, 10)
    report.add(
        "python>=3.10", py_ok, required=True,
        detail=f"found {sys.version_info.major}.{sys.version_info.minor}",
    )

    # 2. .env exists (copy from .env.example if missing)
    env_ok = ENV_FILE.exists()
    report.add(
        ".env present", env_ok, required=False,
        detail="copy .env.example to .env and adjust" if not env_ok else str(ENV_FILE),
    )

    # 3. Core directories exist
    for key in ("BAIZE_PERSISTENCE_DIR", "BAIZE_PROJECTS_DIR", "BAIZE_ASSETS_DIR"):
        p = Path(cfg[key])
        report.add(f"dir {key}", p.is_dir(), required=True, detail=str(p))

    # 4. Persistence directory is writable (real write probe)
    persistence = Path(cfg["BAIZE_PERSISTENCE_DIR"])
    writable = False
    if persistence.is_dir():
        try:
            with tempfile.NamedTemporaryFile(dir=persistence, delete=True):
                writable = True
        except OSError:
            writable = False
    report.add("persistence writable", writable, required=True, detail=str(persistence))

    # 5. Skill libraries reachable (required only if configured)
    libs = skill_library_paths(cfg)
    if not libs:
        report.add(
            "skill libraries", False, required=False,
            detail="SKILL_LIBRARY_PATHS is empty - skill index will be local only",
        )
    else:
        for lib in libs:
            report.add(
                f"skill library {lib}", lib.is_dir(), required=True,
                detail=str(lib),
            )

    # 6. Optional tooling (informational, never blocks)
    for tool in ("git", "node", "go"):
        found = shutil.which(tool) is not None
        report.add(f"tool {tool}", found, required=False,
                   detail="on PATH" if found else "not found (optional)")

    return report


def format_report(report: DoctorReport) -> str:
    lines = ["Baize Doctor Report", "=" * 40]
    for r in report.results:
        mark = "PASS" if r.ok else ("FAIL" if r.required else "WARN")
        lines.append(f"[{mark}] {r.name}  {('- ' + r.detail) if r.detail else ''}")
    lines.append("=" * 40)
    lines.append("RESULT: " + ("PASSED" if report.passed else "FAILED (fix FAIL items above)"))
    return "\n".join(lines)


def main() -> int:
    report = run_checks()
    print(format_report(report))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
