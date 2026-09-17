#!/usr/bin/env python
"""Single source of truth for the release version and the test count.

Why this exists
---------------
Two numbers on the Baize front page used to be hand-typed in half a dozen
files. That is how ``README.md`` kept advertising ``V36.0.0 Titan`` for a
whole release after ``baize/__init__.py`` had already moved on, and how the
test badge ended up claiming ``53/53 passed (100%)`` while the suite actually
collects 650 cases. Hand-typed truth drifts; derived truth cannot.

The one literal
---------------
``baize/__init__.py`` owns the only version literals in the repo::

    __version__  = "37.0.0"
    __codename__ = "Prometheus"

Everything else is derived from them by this script:

    baize.manifest.json        "version"
    pyproject.toml             version (dynamic = ["version"], attr = baize.__version__)
    README.md / README_EN.md   title, version badge, tests badge, compare table
    AGENT.md                   protocol title
    docs/QUICKSTART_CN.md      version + codename
    docs/QUICKSTART_EN.md      version + codename
    docs/USAGE_GUIDE.md        title + Studio banner

Surface rules, not blanket substitution
---------------------------------------
An earlier draft of this script substituted ``V\\d+.\\d+.\\d+`` across whole
files. That silently rewrote *historical* version references too - the README
branch table's ``V26.0.0`` / ``V33.0.0`` rows became the current release. So
each rewrite is now declared as an explicit named surface with an expected
minimum match count, and ``PROTECTED_LITERALS`` asserts the historical
references survive verbatim. A doc that gets reshaped fails the gate instead of
being quietly mangled.

Scope boundary - what this script deliberately does NOT touch
-------------------------------------------------------------
Per-module docstrings and prose such as ``(V35.0.0 Industrial)``,
``(V36.0.0 Titan)`` or AGENT.md's "V33 原语集" are **provenance markers**: they
record which release era a feature landed in. Rewriting them to the current
release would falsify history, not unify it. Only *release-version
declarations* are owned here.

One consequence worth knowing: the ASCII banner in ``docs/USAGE_GUIDE.md``
draws a box around the version string, so a version/codename of a different
length shifts the right-hand border. The script does not re-pad box art -
check that one line by eye when the codename changes.

The test count is measured, never typed
---------------------------------------
The count comes from running the suite, so a red build produces a red badge
instead of a stale green one. The *collected* total is a property of the test
code and is identical on every platform - that is what ``--check`` enforces.
The passed/failed split is a measurement of the machine that ran ``sync``; CI
does not gate on it, because ``python``/``docker`` availability legitimately
changes the outcome between runners.

Usage
-----
    python scripts/sync_truth.py                    # measure, then rewrite every surface
    python scripts/sync_truth.py --check            # verify, exit 1 on drift (CI; ~2s)
    python scripts/sync_truth.py --check --with-tests   # strict: also require the passed count
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
VERSION_DECL = ROOT / "baize" / "__init__.py"

# ---------------------------------------------------------------- version read


def read_version() -> tuple[str, str]:
    """Return (version, codename) parsed straight from baize/__init__.py.

    Parsed with a regex rather than imported so the script works from a plain
    checkout, stays zero-dependency, and never executes package import side
    effects.
    """
    src = VERSION_DECL.read_text(encoding="utf-8")
    ver = re.search(r'^__version__\s*=\s*"([^"]+)"', src, re.M)
    cod = re.search(r'^__codename__\s*=\s*"([^"]+)"', src, re.M)
    if not ver or not cod:
        raise SystemExit(
            f"TRUTH ERROR: {VERSION_DECL} must declare both __version__ and "
            f"__codename__ as plain string literals"
        )
    version, codename = ver.group(1), cod.group(1)
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"TRUTH ERROR: __version__ {version!r} is not X.Y.Z")
    return version, codename


@dataclass(frozen=True)
class Labels:
    version: str
    codename: str

    @property
    def full(self) -> str:
        """V37.0.0 Prometheus"""
        return f"V{self.version} {self.codename}"

    @property
    def short(self) -> str:
        """V37 Prometheus - major only, as used in the compare-table header."""
        major = self.version.split(".")[0]
        return f"V{major} {self.codename}"

    def version_badge(self) -> str:
        return f"badge/version-V{self.version}--{self.codename}-orange"

    def tests_badge(self, passed: int, total: int) -> str:
        pct = round(passed * 100 / total) if total else 0
        if pct == 100:
            color = "brightgreen"
        elif pct >= 95:
            color = "yellow"
        else:
            color = "red"
        return f"badge/tests-{passed}%2F{total}%20passed%20({pct}%25)-{color}"


# ------------------------------------------------------------- surface rules


@dataclass(frozen=True)
class Surface:
    """One named place the release version appears, with its own pattern.

    ``min_hits`` is the contract: if the document is reshaped so the surface
    stops matching, that is a hard failure rather than a silent no-op.
    """

    name: str
    pattern: re.Pattern[str]
    render: Callable[[Labels, int, int], str]
    min_hits: int = 1


FULL_LABEL = Surface("full label", re.compile(r"V\d+\.\d+\.\d+ [A-Z][A-Za-z]+"),
                     lambda l, p, t: l.full)
# Short form is major-only: "V36 Titan". A pattern requiring "V36.0 Titan" would
# never match and would silently leave the compare-table header stale.
SHORT_LABEL = Surface("short label", re.compile(r"V\d+ [A-Z][A-Za-z]+"),
                      lambda l, p, t: l.short)
VERSION_BADGE = Surface("version badge", re.compile(r'badge/version-[^?\s"]*'),
                        lambda l, p, t: l.version_badge())
TESTS_BADGE = Surface("tests badge", re.compile(r'badge/tests-[^?\s"]*'),
                      lambda l, p, t: l.tests_badge(p, t))
PROTOCOL_TITLE = Surface("protocol title", re.compile(r"操作协议 V\d+\.\d+\.\d+"),
                         lambda l, p, t: f"操作协议 V{l.version}")
# A bare "V33.0.0" with no codename, as the older doc titles use. Only safe on a
# file where *every* V-label is the release - verify before adding a new file.
VERSION_ONLY = Surface("version only", re.compile(r"V\d+\.\d+\.\d+"),
                       lambda l, p, t: f"V{l.version}")

# file -> (surface, min_hits)
SURFACES: dict[str, list[tuple[Surface, int]]] = {
    "README.md": [(FULL_LABEL, 1), (SHORT_LABEL, 1), (VERSION_BADGE, 1), (TESTS_BADGE, 1)],
    "README_EN.md": [(FULL_LABEL, 1), (SHORT_LABEL, 1), (VERSION_BADGE, 1), (TESTS_BADGE, 1)],
    "AGENT.md": [(PROTOCOL_TITLE, 1)],
    "docs/QUICKSTART_CN.md": [(FULL_LABEL, 1)],
    "docs/QUICKSTART_EN.md": [(FULL_LABEL, 1)],
    "docs/USAGE_GUIDE.md": [(FULL_LABEL, 2)],  # doc title + Studio banner
    # Doc titles that name the release without the codename. Both were still
    # claiming V33.0.0 five releases after the fact - found by
    # skills/repo-truth-and-hygiene/scripts/audit_repo_truth.py [2].
    "START-HERE.md": [(VERSION_ONLY, 1)],
    "docs/benchmarks.md": [(VERSION_ONLY, 1)],
    # Found by an audit sweep for V-literals outside the gate: these three had
    # drifted to V25.0.0 / V33.0.0 while the release was V37.0.0, i.e. two of
    # them were four releases stale. Each file has exactly ONE V-label and it is
    # the release, which is the precondition VERSION_ONLY documents.
    ".env.example": [(VERSION_ONLY, 1)],
    "install/baize-desktop.bat": [(VERSION_ONLY, 1)],
    "install/baize-desktop.ps1": [(VERSION_ONLY, 1)],
}

# Historical version references that must survive every sync untouched. These
# are exactly what a blanket substitution would have destroyed.
PROTECTED_LITERALS: dict[str, list[str]] = {
    "README.md": [
        "V26.0.0「闭环事实内核」架构重构线",
        "V33.0.0 升级线",
    ],
    "README_EN.md": [
        'V26.0.0 "closed-loop fact kernel" architecture rewrite',
        "V33.0.0 upgrade line",
    ],
}


def rewrite_file(
    rel: str, text: str, lab: Labels, passed: int, total: int, skip: frozenset[str] = frozenset()
) -> tuple[str, list[str]]:
    """Apply every declared surface. Returns (new_text, problems)."""
    problems: list[str] = []
    out = text
    for surface, min_hits in SURFACES.get(rel, []):
        if surface.name in skip:
            continue
        out, n = surface.pattern.subn(surface.render(lab, passed, total), out)
        if n < min_hits:
            problems.append(
                f"{rel}: surface '{surface.name}' matched {n}x, expected >= {min_hits} "
                f"(pattern {surface.pattern.pattern!r}). Update SURFACES in this script "
                f"if the document was intentionally reshaped."
            )
    for lit in PROTECTED_LITERALS.get(rel, []):
        if lit not in out:
            problems.append(
                f"{rel}: protected historical reference disappeared: {lit!r}. "
                f"A surface rule is clobbering history - fix the rule, not the doc."
            )
    return out, problems


# --------------------------------------------------------------- test measure


_COLLECTED_MEMO: list[int | None] = [None]


def collected_count() -> int:
    """Collected test count, memoised.

    ``--collect-only`` is a subprocess call, and more than one count claim wants
    the same number; measuring it twice per gate run is pure waste. Memoised
    rather than cached to disk: a stale number on disk is how a badge starts
    lying.
    """
    if _COLLECTED_MEMO[0] is None:
        _COLLECTED_MEMO[0] = measure_tests(run=False)[1]
    return _COLLECTED_MEMO[0]


def _run_pytest(args: list[str]) -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        errors="replace",  # suite output contains CJK and machine-local paths
    )
    return proc.stdout + proc.stderr


def measure_tests(run: bool) -> tuple[int, int, int, int]:
    """Return ``(passed, total, skipped, failed)``. Exits when it cannot measure.

    The counts come from pytest's JUnit XML rather than from scraping stdout:
    one test prints a multi-kilobyte safe-delete JSON payload after the
    progress dots, and an earlier stdout-scraping version of this script lost
    the summary line behind it and reported "suite crashed" for a suite that had
    run fine. XML is structured output - it cannot be drowned out.

    Failures and skips are separated because they mean different things to the
    reader: a failure is ours to fix, a skip is an environment guard firing
    (e.g. PowerShell cannot launch absolute-path executables in a sandbox).
    Lumping them together produced a warning that told the reader to "fix" two
    tests that are not broken. Both still reduce the passed count, so the badge
    never claims more green than was actually observed.

    A guessed number is worse than no number (NO FAKE DONE), so an
    unmeasurable suite is a hard error rather than a silent fallback.
    """
    try:
        out = _run_pytest(["tests/", "-q", "--collect-only"])
    except FileNotFoundError:
        raise SystemExit(
            "TRUTH ERROR: pytest is not available in this interpreter; "
            "install it (`python -m pip install pytest`)"
        )
    m = re.search(r"(\d+)\s+tests?\s+collected", out)
    if not m:
        raise SystemExit("TRUTH ERROR: could not read the collected count from pytest:\n" + out[-2000:])
    total = int(m.group(1))

    if not run:
        return total, total, 0, 0

    import tempfile
    import xml.etree.ElementTree as ET

    with tempfile.TemporaryDirectory() as td:
        report = Path(td) / "truth.xml"
        _run_pytest(["tests/", "-q", f"--junitxml={report}"])
        if not report.exists():
            raise SystemExit("TRUTH ERROR: pytest produced no JUnit XML report")
        root = ET.parse(report).getroot()
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        if suite is None:
            raise SystemExit("TRUTH ERROR: JUnit XML has no <testsuite> element")
        attrs = suite.attrib
        n_tests = int(attrs.get("tests", 0))
        skipped = int(attrs.get("skipped", 0))
        failed = int(attrs.get("failures", 0)) + int(attrs.get("errors", 0))
    passed = n_tests - skipped - failed
    if n_tests == 0:
        raise SystemExit("TRUTH ERROR: JUnit XML reported 0 tests")
    return passed, total, skipped, failed


# -------------------------------------------------------------- json surfaces


def sync_manifest(lab: Labels) -> str | None:
    p = ROOT / "baize.manifest.json"
    if not p.exists():
        raise SystemExit("TRUTH ERROR: baize.manifest.json is missing")
    raw = p.read_text(encoding="utf-8")
    new = re.sub(r'("version"\s*:\s*")[^"]*(")', rf"\g<1>{lab.version}\g<2>", raw, count=1)
    if new == raw:
        return None
    p.write_text(new, encoding="utf-8")
    return f"baize.manifest.json: version -> {lab.version}"


def check_manifest(lab: Labels) -> list[str]:
    data = json.loads((ROOT / "baize.manifest.json").read_text(encoding="utf-8"))
    if data.get("version") != lab.version:
        return [f"baize.manifest.json: version={data.get('version')!r}, expected {lab.version!r}"]
    return []


def check_pyproject() -> list[str]:
    """pyproject.toml must stay dynamic so the version has exactly one literal."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    problems = []
    if not re.search(r'^dynamic\s*=\s*\[\s*"version"\s*\]', text, re.M):
        problems.append(
            'pyproject.toml: [project] must declare dynamic = ["version"] so the version '
            "is not duplicated as a literal"
        )
    if not re.search(r'^version\s*=\s*\{\s*attr\s*=\s*"baize\.__version__"\s*\}', text, re.M):
        problems.append(
            'pyproject.toml: [tool.setuptools.dynamic] version must be {attr = "baize.__version__"}'
        )
    return problems


# ------------------------------------------------------- hand-typed counts

# The counts below are the third class of drifting number: neither the version
# (owned by baize/__init__.py) nor the test total (measured by pytest), but
# counts of things that exist in the tree - config keys, CLI subcommands, tools,
# skills. docs/tutorials/README.md claims all of its numbers are "measured on
# this machine", so each one needs a measurement that can disagree with it.
#
# These are measured by parsing the source rather than importing the package,
# for the same reason read_version() parses instead of importing: a plain
# checkout with no install must still be able to run the gate, and importing
# baize has side effects.
#
# History: the table claimed "54 BAIZE_* keys" and "28 CLI subcommands" while
# the real values were 52 and 27. Both had been wrong for at least one release.
# The 54/52 pair is why the check below counts the BAIZE_ prefix separately
# from the total: `_DEFAULTS` also holds two unprefixed keys, and lumping them
# together is what produced a number that matched nothing.


def measure_config_keys() -> tuple[int, int]:
    """``(BAIZE_* key count, total _DEFAULTS entry count)``."""
    src = (ROOT / "baize" / "config.py").read_text(encoding="utf-8")
    keys = re.findall(r'^\s{4}"([A-Z][A-Z0-9_]*)"\s*:', src, re.M)
    if not keys:
        raise SystemExit(
            "TRUTH ERROR: found no config keys in baize/config.py. If _DEFAULTS was "
            "reformatted, update measure_config_keys() in this script."
        )
    return sum(1 for k in keys if k.startswith("BAIZE_")), len(keys)


def measure_subcommands() -> int:
    """Distinct argparse subcommand names registered in baize/cli.py."""
    src = (ROOT / "baize" / "cli.py").read_text(encoding="utf-8")
    subs = set(re.findall(r'add_parser\(\s*"([^"]+)"', src))
    if not subs:
        raise SystemExit(
            "TRUTH ERROR: found no add_parser() calls in baize/cli.py. If the CLI was "
            "restructured, update measure_subcommands() in this script."
        )
    return len(subs)


def measure_skills() -> int:
    """SKILL.md files under assets/, i.e. the bundled skill library."""
    return len(list((ROOT / "assets").rglob("SKILL.md")))


#: Tools registered only when an opt-in flag is set, so they are not part of the
#: default tool count. Listed explicitly rather than inferred: a new conditional
#: registration should surface as a count mismatch, not be silently absorbed.
OPT_IN_TOOLS = frozenset({"fetch_url"})


def measure_tools() -> tuple[int, int]:
    """``(enabled by default, total registered)``."""
    src = (ROOT / "baize" / "tools.py").read_text(encoding="utf-8")
    names = set(re.findall(r'reg\.register\(\s*"([^"]+)"', src))
    if not names:
        raise SystemExit(
            "TRUTH ERROR: found no reg.register() calls in baize/tools.py. If the "
            "registry was restructured, update measure_tools() in this script."
        )
    return len(names - OPT_IN_TOOLS), len(names)


@dataclass(frozen=True)
class CountClaim:
    """One hand-typed count in a document, with the measurement backing it.

    ``pattern`` must capture the advertised number in group 1, and is anchored on
    the row's label so that reshaping the table fails loudly instead of matching
    a number somewhere else in the file.
    """

    doc: str
    what: str
    pattern: re.Pattern[str]
    measure: Callable[[], int]
    detail: str


def count_claims() -> list[CountClaim]:
    return [
        CountClaim(
            "docs/tutorials/README.md",
            "BAIZE_* config keys",
            re.compile(r"配置项 \| \*\*(\d+) 个\*\* `BAIZE_\*` 键"),
            lambda: measure_config_keys()[0],
            "baize/config.py _DEFAULTS, keys starting with BAIZE_",
        ),
        CountClaim(
            "docs/tutorials/README.md",
            "total _DEFAULTS entries",
            re.compile(r"共 (\d+) 项"),
            lambda: measure_config_keys()[1],
            "baize/config.py _DEFAULTS, all entries",
        ),
        CountClaim(
            "docs/tutorials/README.md",
            "CLI subcommands",
            re.compile(r"CLI 子命令 \| \*\*(\d+) 个\*\*"),
            measure_subcommands,
            "distinct add_parser() names in baize/cli.py",
        ),
        CountClaim(
            "docs/tutorials/README.md",
            "bundled skills",
            re.compile(r"内置技能 \| \*\*(\d+) 个\*\*"),
            measure_skills,
            "assets/**/SKILL.md",
        ),
        CountClaim(
            "docs/tutorials/README.md",
            "default tools",
            re.compile(r"内置工具 \| \*\*(\d+) 个\*\*"),
            lambda: measure_tools()[0],
            "reg.register() calls in baize/tools.py minus OPT_IN_TOOLS",
        ),
        CountClaim(
            "docs/tutorials/README.md",
            "opt-in tools total",
            re.compile(r"`BAIZE_ALLOW_FETCH_URL=1` 后 (\d+) 个"),
            lambda: measure_tools()[1],
            "all reg.register() calls in baize/tools.py",
        ),
        # The tutorial's own fact table was ungated, and drifted: it advertised
        # "683 collected / 681 passed / 2 skipped" and a 77.4% coverage RED long
        # after the suite had reached 1278 and the gate had gone green. Only the
        # collected count is gated - passed and skipped need a full run, which
        # this cheap gate deliberately does not do - so the row states only the
        # number that can be checked here.
        CountClaim(
            "docs/tutorials/01-认识白泽引擎.md",
            "test cases collected",
            re.compile(r"测试用例 \| \*\*(\d+) 个收集"),
            collected_count,
            "pytest tests/ --collect-only",
        ),
    ]


def check_count_claims() -> list[str]:
    """Verify every CountClaim against its measurement."""
    problems: list[str] = []
    for claim in count_claims():
        path = ROOT / claim.doc
        if not path.exists():
            problems.append(f"{claim.doc}: missing, cannot verify '{claim.what}'")
            continue
        text = path.read_text(encoding="utf-8")
        m = claim.pattern.search(text)
        if not m:
            problems.append(
                f"{claim.doc}: could not find the '{claim.what}' claim "
                f"(pattern {claim.pattern.pattern!r}). If the table was reshaped, "
                f"update count_claims() in this script."
            )
            continue
        advertised = int(m.group(1))
        actual = claim.measure()
        if advertised != actual:
            problems.append(
                f"{claim.doc}: claims {advertised} {claim.what}, measured {actual} "
                f"({claim.detail})"
            )
    return problems


# ------------------------------------------------------------------- pipeline


def do_sync(lab: Labels, passed: int, total: int,
            skipped: int = 0, failed: int = 0) -> int:
    changes: list[str] = []
    problems: list[str] = []

    for rel in SURFACES:
        p = ROOT / rel
        before = p.read_text(encoding="utf-8")
        after, probs = rewrite_file(rel, before, lab, passed, total)
        problems += probs
        if after != before:
            p.write_text(after, encoding="utf-8")
            changes.append(f"{rel}: release surface -> {lab.full}")

    msg = sync_manifest(lab)
    if msg:
        changes.append(msg)

    if problems:
        print("TRUTH SYNC FAILED:\n")
        for pr in problems:
            print("  " + pr)
        return 1

    print(f"version   : {lab.full}   (baize/__init__.py is the only literal)")
    print(f"tests     : {passed}/{total} passed")
    if changes:
        for c in changes:
            print("  sync  " + c)
    else:
        print("  sync  nothing to do - every derived surface already matched")
    if failed or skipped:
        bits = []
        if failed:
            bits.append(f"{failed} FAILED")
        if skipped:
            bits.append(f"{skipped} skipped by an environment guard")
        print(
            f"WARN  {', '.join(bits)}; the badge records only the {passed} that ran and "
            f"passed, so it stays honest."
        )
        if failed:
            print("      Fix the failures to raise the badge.")
        if skipped:
            print("      Skipped tests need the capability they guard, not a code change.")
    return 0


def do_check(lab: Labels, passed: int, total: int, strict_tests: bool) -> int:
    """Verify derived surfaces.

    Two tiers, because the two numbers have different stability:

    * the version is fully deterministic - always gated;
    * the *collected* test total is a property of the test code and is the same
      on every platform - always gated;
    * the passed/failed *split* depends on the machine (``python`` on PATH,
      ``docker`` installed), so it is only gated under ``--with-tests``, which
      CI does not use.
    """
    problems: list[str] = []
    # Without a measured numerator the tests badge cannot be compared, so the
    # badge surface is skipped and only its denominator is validated below.
    skip = frozenset() if strict_tests else {TESTS_BADGE.name}

    for rel in SURFACES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        expected, probs = rewrite_file(rel, text, lab, passed, total, skip=skip)
        problems += probs
        if expected != text:
            for i, (got, want) in enumerate(zip(text.splitlines(), expected.splitlines()), 1):
                if got != want:
                    problems.append(
                        f"{rel}:{i}\n      got  {got.strip()}\n      want {want.strip()}"
                    )
                    break

    problems += check_manifest(lab)
    problems += check_pyproject()
    problems += check_count_claims()

    # Denominator check: the README must advertise the number of cases the
    # suite actually collects.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"badge/tests-(\d+)%2F(\d+)", readme)
    if not m:
        problems.append("README.md: no parsable tests badge found")
    else:
        got_passed, got_total = int(m.group(1)), int(m.group(2))
        if got_total != total:
            problems.append(
                f"README.md: tests badge advertises {got_total} cases, the suite collects {total}"
            )
        if strict_tests and got_passed != passed:
            problems.append(
                f"README.md: tests badge advertises {got_passed} passed, this machine measured "
                f"{passed}/{total}"
            )

    if problems:
        print("TRUTH CHECK FAILED - derived surfaces drifted from baize/__init__.py:\n")
        for pr in problems:
            print("  " + pr)
        print("\nRun `python scripts/sync_truth.py` to regenerate them.")
        return 1

    print(f"TRUTH CHECK PASSED: {lab.full}, {total} tests collected, "
          f"{len(count_claims())} count claims verified, no drift")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify only, do not write")
    ap.add_argument(
        "--with-tests",
        action="store_true",
        help="with --check: also run the suite and require the passed count to match "
        "(machine-dependent; CI deliberately does not use this)",
    )
    args = ap.parse_args(argv[1:])

    if args.with_tests and not args.check:
        raise SystemExit("TRUTH ERROR: --with-tests is only meaningful with --check")

    lab = Labels(*read_version())

    if args.check:
        if args.with_tests:
            passed, total, skipped, failed = measure_tests(run=True)
        else:
            passed, total, skipped, failed = 0, measure_tests(run=False)[1], 0, 0
        return do_check(lab, passed, total, strict_tests=args.with_tests)

    passed, total, skipped, failed = measure_tests(run=True)
    return do_sync(lab, passed, total, skipped=skipped, failed=failed)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
