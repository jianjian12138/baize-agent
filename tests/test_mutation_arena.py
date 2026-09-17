"""The mutation arena must measure a score, not announce one.

The revision this file guards against computed ``killed_count = len(mutants)``
and emitted ``assert True`` as the "synthesized guardrail test", so every input
scored 100% and the emitted test asserted nothing. Both are NO FAKE DONE
violations, and both are invisible to a test that only checks the response has
the right keys - which is exactly what ``tests/test_phase3_industrial.py`` did.

So these tests check values, not shapes: a mutant that cannot be distinguished
must score below 100, the score must be absent when nothing ran, and the emitted
module must be executed here - standalone and under pytest - rather than read.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from baize import mutation
from baize.mutation import (
    LIMITATIONS,
    MAX_MUTANTS,
    MAX_PROBES,
    PROBE_POOL,
    Mutant,
    run_ast_mutation_arena,
)

SCORE_CODE = "def check_score(s):\n    return True if s > 60 else False"
ADD_CODE = "def add(a, b):\n    return a + b if a > 0 else 0"


def _run_module(path, *extra):
    return subprocess.run(
        [sys.executable, str(path), *extra],
        capture_output=True, text=True, timeout=180, cwd=str(path.parent),
    )


class TestTheScoreIsMeasured:
    def test_mutant_status_starts_pending_so_nothing_decides_it_up_front(self):
        mutant = Mutant(1, ">", "<=", 2, "desc")
        assert mutant.status == "pending"

    @pytest.mark.parametrize(
        "code, fn_name, expected",
        [
            # `x + 0` and `x - 0` agree on every probe, so the arithmetic flip is
            # undetectable: a measured arena scores this 0%, a fabricated one
            # scored it 100%.
            ("def f(x):\n    return x + 0", "f", "0.0%"),
            (SCORE_CODE, "check_score", "100.0%"),
            (ADD_CODE, "add", "100.0%"),
        ],
    )
    def test_score_follows_from_the_verdicts(self, code, fn_name, expected):
        assert run_ast_mutation_arena(code, fn_name)["mutation_score"] == expected

    def test_executed_is_the_sum_of_killed_and_survived(self):
        res = run_ast_mutation_arena(ADD_CODE, "add")
        assert res["mutants_executed"] == res["mutants_killed"] + res["mutants_survived"]

    def test_every_mutant_carries_a_verdict_that_was_observed(self):
        res = run_ast_mutation_arena(ADD_CODE, "add")
        assert res["mutants"], "expected at least one mutant"
        for mutant in res["mutants"]:
            assert mutant["status"] in {"killed", "survived", "error"}
            if mutant["status"] == "killed":
                assert mutant["counterexample"], "a kill must name the probe that showed it"
            else:
                assert "counterexample" not in mutant

    def test_a_killed_mutant_reports_the_probe_and_both_outcomes(self):
        res = run_ast_mutation_arena(SCORE_CODE, "check_score")
        killed = [m for m in res["mutants"] if m["status"] == "killed"]
        assert killed, "expected the > -> <= flip to be killed"
        example = killed[0]["counterexample"]
        assert example["original"] != example["mutant"]
        assert example["args"]
        assert res["score_basis"].startswith("killed / (killed + survived)")

    @pytest.mark.parametrize(
        "code, fn_name, expected_status",
        [
            ("", "f", "empty"),
            ("   \n  ", "f", "empty"),
            ("def (", "f", "parse_error"),
            ("def f(x):\n    return x", "f", "no_mutation_sites"),
            ("def other(x):\n    return x > 1", "f", "target_not_found"),
        ],
    )
    def test_no_score_is_reported_when_no_mutant_ran(self, code, fn_name, expected_status):
        res = run_ast_mutation_arena(code, fn_name)
        assert res["status"] == expected_status
        assert res["mutation_score"] is None
        assert res["mutants_executed"] == 0

    def test_the_arena_does_not_invent_mutants_for_code_it_cannot_flip(self):
        res = run_ast_mutation_arena("def f(x):\n    return x", "f")
        assert res["total_mutants_generated"] == 0
        assert res["mutants"] == []
        assert "invented" in res["message"]


class TestTheSubmittedCodeRunsConstrained:
    def test_a_module_level_import_outside_the_allowlist_is_refused(self):
        res = run_ast_mutation_arena("import os\n\ndef f(x):\n    return x > 1", "f")
        assert res["status"] == "target_not_found"
        assert "ImportError" in res["error"]

    def test_open_is_unavailable_so_a_payload_cannot_read_a_file(self):
        code = 'def f(x):\n    return x > 1 and open("/etc/passwd")'
        res = run_ast_mutation_arena(code, "f")
        assert res["status"] == "success"
        killed = [m for m in res["mutants"] if m["status"] == "killed"]
        assert killed, "the flip that stops short-circuiting must be detectable"
        # NameError, not file contents: `open` is absent from SAFE_BUILTINS.
        assert "NameError" in killed[0]["counterexample"]["mutant"]


class TestTheEmittedGuardrailTest:
    def test_it_contains_no_placeholder_assertion(self):
        res = run_ast_mutation_arena(SCORE_CODE, "check_score")
        body = res["synthesized_guardrail_test"]
        assert "assert True" not in body
        assert "assert False" not in body
        assert "assert check_score(" in body

    def test_it_embeds_the_source_under_test(self):
        res = run_ast_mutation_arena(ADD_CODE, "add")
        assert ADD_CODE in res["synthesized_guardrail_test"]

    def test_it_runs_standalone(self, tmp_path):
        res = run_ast_mutation_arena(ADD_CODE, "add")
        path = tmp_path / "guardrail_add.py"
        path.write_text(res["synthesized_guardrail_test"], encoding="utf-8")
        proc = _run_module(path)
        assert proc.returncode == 0, proc.stderr
        assert "guardrail test passed" in proc.stdout

    def test_pytest_collects_it_and_it_passes(self, tmp_path):
        res = run_ast_mutation_arena(SCORE_CODE, "check_score")
        path = tmp_path / "guardrail_score.py"
        path.write_text(res["synthesized_guardrail_test"], encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", path.name, "-q",
             "-p", "no:cacheprovider", "--no-header"],
            capture_output=True, text=True, timeout=180, cwd=str(tmp_path),
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_it_fails_on_a_mutant_the_arena_killed(self, tmp_path):
        res = run_ast_mutation_arena(SCORE_CODE, "check_score")
        assert res["mutants"][0]["status"] == "killed"
        mutant_source = mutation._mutate_source(SCORE_CODE, 0)
        assert mutant_source is not None
        module = res["synthesized_guardrail_test"].replace(SCORE_CODE, mutant_source)
        assert module != res["synthesized_guardrail_test"]
        path = tmp_path / "mutant_guardrail.py"
        path.write_text(module, encoding="utf-8")
        proc = _run_module(path)
        assert proc.returncode != 0, (
            "the guardrail test passed a mutant the arena called killed"
        )

    def test_the_verification_report_is_measured_not_asserted(self):
        res = run_ast_mutation_arena(ADD_CODE, "add")
        report = res["guardrail_verification"]
        assert report["executed"] is True
        assert report["passes_original"] is True
        assert report["fails_every_killed_mutant"] is True
        assert report["measured_on"]

    def test_the_header_does_not_claim_a_run_that_could_not_happen(self):
        res = run_ast_mutation_arena("def f(x):\n    return x + 0", "f")
        header = res["synthesized_guardrail_test"].splitlines()
        assert any("fails on nothing" in line for line in header)
        assert not any("every killed mutant (fails)" in line for line in header)


class TestHonestLimits:
    def test_limitations_are_returned(self):
        res = run_ast_mutation_arena(ADD_CODE, "add")
        assert res["limitations"][:len(LIMITATIONS)] == list(LIMITATIONS)
        assert any("fixed" in item for item in res["limitations"])
        assert any("no wall-clock bound" in item for item in res["limitations"])

    def test_the_mutant_cap_is_enforced_and_disclosed(self):
        code = "def f(x):\n    return " + " or ".join(f"x > {i}" for i in range(MAX_MUTANTS + 5))
        res = run_ast_mutation_arena(code, "f")
        assert res["total_mutants_generated"] == MAX_MUTANTS + 5
        assert res["mutants_executed"] <= MAX_MUTANTS
        assert len(res["mutants"]) == MAX_MUTANTS
        assert any("not executed" in item for item in res["limitations"])

    def test_the_probe_corpus_is_bounded(self):
        assert len(mutation._probe_corpus(1)) == len(PROBE_POOL)
        assert len(mutation._probe_corpus(4)) <= MAX_PROBES
        assert mutation._probe_corpus(0) == [()]

    def test_arity_comes_from_the_real_signature(self):
        zero = run_ast_mutation_arena("def f():\n    return 1 > 0", "f")
        assert zero["probe_corpus_size"] == 1
        variadic = run_ast_mutation_arena("def f(*args):\n    return 1 > 0", "f")
        assert variadic["probe_corpus_size"] == len(PROBE_POOL)


class TestSiteScanAndRewriteAgree:
    """The scan and the rewrite are separate passes held together by convention.

    If they ever disagree about ordering, a mutant silently mutates the wrong
    operator - and every test above still passes, because a flip happened and a
    verdict was produced. This is the check that keeps the two in step.
    """

    @pytest.mark.parametrize(
        "code",
        [
            SCORE_CODE,
            ADD_CODE,
            "def g(a, b, c):\n    return a < b < c",
            "def h(a):\n    if a >= 1 and a <= 9:\n        return a - 1\n    return a + 1",
            "def k(a):\n    return (a + 1) * (a - 1) if a != 0 else 0",
        ],
    )
    def test_each_index_flips_exactly_one_site(self, code):
        tree = __import__("ast").parse(code)
        scan = mutation._SiteScan()
        scan.visit(tree)
        sites = scan.sites
        assert sites, f"no site found in {code!r}"

        rendered = set()
        for index in range(len(sites)):
            mutated = mutation._mutate_source(code, index)
            assert mutated is not None, f"site {index} was not rewritten"
            rendered.add(mutated)
        assert len(rendered) == len(sites), (
            "two sites produced the same mutated source, so the index does not "
            "identify a unique operator"
        )

    def test_a_chained_comparison_mutates_each_operator_separately(self):
        code = "def g(a, b, c):\n    return a < b < c"
        res = run_ast_mutation_arena(code, "g")
        assert res["total_mutants_generated"] == 2
        assert {m["line_no"] for m in res["mutants"]} == {2}
        assert {m["original_op"] for m in res["mutants"]} == {"<"}
        # Both operators flip the same way, so the two mutants must differ in
        # *which* operator moved - that is what the site index has to track.
        assert len({mutation._mutate_source(code, i) for i in (0, 1)}) == 2

    def test_an_unrewritable_index_returns_none_rather_than_a_wrong_flip(self):
        assert mutation._mutate_source(ADD_CODE, 99) is None


def test_no_placeholder_assertion_survives_in_the_package():
    """`assert True` is AGENT.md's named example of a test that proves nothing."""
    from pathlib import Path

    root = Path(mutation.__file__).resolve().parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip() == "assert True":
                offenders.append(f"{path.relative_to(root)}:{number}")
    assert not offenders, f"placeholder assertion(s) in the package: {offenders}"
