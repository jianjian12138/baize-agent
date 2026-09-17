"""Anti-Fragile AST Mutation Testing & Counterfactual Guardrail Generator.

Pure Python standard library — zero third-party dependencies.

WHAT THIS ACTUALLY DOES
-----------------------
It flips comparison and arithmetic operators in the submitted source, loads the
original and each mutant into the constrained namespace from
``baize/safe_exec.py``, calls both with a fixed probe corpus and compares the
results. A mutant whose behaviour differs on at least one probe is *killed*; one
that agrees on every probe is *survived*. ``mutation_score`` is
``killed / (killed + survived)`` over the probes that actually ran.

The emitted guardrail test is not text anyone has to trust: it embeds the source
under test verbatim, so it runs standalone, and it is executed against the
original (must pass) and against every killed mutant (must fail) before it is
returned. The verdict of those runs is reported in ``guardrail_verification``.

WHAT IT DOES NOT ESTABLISH
--------------------------
See :data:`LIMITATIONS`. The short version: the probe corpus is fixed rather than
derived from the code under test, so a mutant can survive because no probe
happens to cross its boundary. A high score is evidence about *this corpus*, not
proof that the code is correct.

WHY THIS FILE WAS REWRITTEN
---------------------------
The previous revision computed ``killed_count = len(mutants)``, i.e. it reported
a 100% mutation score without ever executing a single mutant, and emitted
``assert True`` as the "synthesized guardrail test". ``README.md`` advertised
that constant as a product feature ("AST 变异测试网 (100% 击杀率)"). Reporting
100% because the arithmetic is ``n / n`` is the exact failure mode ``AGENT.md``
calls NO FAKE DONE: the number looked like evidence and was never measured.
"""
from __future__ import annotations

import ast
import inspect
import itertools
from typing import Any, Callable

__all__ = [
    "ARITHMETIC_FLIPS",
    "COMPARISON_FLIPS",
    "LIMITATIONS",
    "MAX_ASSERTIONS",
    "MAX_MUTANTS",
    "MAX_PROBES",
    "PROBE_POOL",
    "Mutant",
    "run_ast_mutation_arena",
]

#: Operator flips the arena applies, keyed by the AST operator class that
#: ``ast.Compare``/``ast.BinOp`` carries. The site scan and the rewrite both read
#: from this table, so they cannot disagree about which positions are mutable.
#: Values are ``(replacement_class, original_symbol, mutated_symbol)``.
COMPARISON_FLIPS: dict[type, tuple[type, str, str]] = {
    ast.Lt: (ast.GtE, "<", ">="),
    ast.LtE: (ast.Gt, "<=", ">"),
    ast.Gt: (ast.LtE, ">", "<="),
    ast.GtE: (ast.Lt, ">=", "<"),
    ast.Eq: (ast.NotEq, "==", "!="),
    ast.NotEq: (ast.Eq, "!=", "=="),
}

#: ``*`` and ``/`` are deliberately absent. On a numeric corpus those flips die
#: from ``ZeroDivisionError`` far more often than from a boundary disagreement,
#: which raises the score without adding signal about the code under test.
ARITHMETIC_FLIPS: dict[type, tuple[type, str, str]] = {
    ast.Add: (ast.Sub, "+", "-"),
    ast.Sub: (ast.Add, "-", "+"),
}

#: Values each parameter is called with. Centred on the ``> 60`` / ``>= 10``
#: style predicates this codebase actually writes, plus empty and one-character
#: strings (so ``len(x)`` boundaries are reachable) and ``None`` (so equality
#: mutants have something to disagree about).
PROBE_POOL: tuple[Any, ...] = (-1, 0, 1, 2, 60, 61, 100, "", "a", None)

#: Upper bound on probes for a multi-parameter target, so the cartesian product
#: cannot make a single request expensive. The slice is evenly spaced, not the
#: first N, so the high values are still represented.
MAX_PROBES = 200

#: Upper bound on mutants executed per call. A source file with hundreds of
#: operators would otherwise turn one request into thousands of calls.
MAX_MUTANTS = 25

#: Upper bound on assertions in the emitted guardrail test, so the generated
#: module stays readable. Discriminating probes are emitted first.
MAX_ASSERTIONS = 12

#: Machine-readable statement of what a score from this module does not mean.
#: Returned in every result so a caller cannot read the number as a verdict.
LIMITATIONS: tuple[str, ...] = (
    "the probe corpus is fixed, not derived from the submitted code, so a mutant "
    "can survive simply because no probe crosses its boundary",
    "probes are passed positionally, so a target with keyword-only parameters "
    "raises TypeError on every probe and no mutant can be killed",
    "only <, <=, >, >=, ==, !=, + and - are mutated; *, / and every other "
    "operator are left untouched",
    "the probes run in-process with no wall-clock bound - a target that never "
    "returns blocks the calling thread, unlike baize/tools.py which runs user "
    "code in a subprocess with a timeout",
    "the emitted guardrail test asserts behaviour observed on this probe corpus, "
    "so it locks in whatever the original did, correct or not",
    f"at most {MAX_MUTANTS} mutants are executed per call; sites beyond that are "
    "counted but not run",
)

#: Return types compared by value. Everything else is reduced to its type name:
#: two distinct objects of the same class whose ``repr`` embeds an address would
#: otherwise look like different behaviour on every call and manufacture kills
#: that no test could reproduce.
_SAFE_SCALARS = (bool, int, float, complex, str, bytes, type(None))


class Mutant:
    """One operator flip and the evidence for its verdict.

    ``status`` starts as ``"pending"``: nothing in this class decides whether a
    mutant is killed. :func:`run_ast_mutation_arena` runs it and sets the field
    from the observed behaviour. An earlier revision hardcoded ``"killed"`` in
    ``__init__``, which is why the score was always 100%.
    """

    def __init__(self, mutant_id: int, original_op: str, mutated_op: str,
                 line_no: int, description: str):
        self.mutant_id = mutant_id
        self.original_op = original_op
        self.mutated_op = mutated_op
        self.line_no = line_no
        self.description = description
        #: pending | killed | survived | error
        self.status: str = "pending"
        #: Index into the probe corpus that first disagreed, when killed.
        self.killed_by: int | None = None
        #: The probe that disagreed and both observed outcomes, when killed.
        self.counterexample: dict[str, Any] | None = None
        #: Why this mutant could not be run, when errored.
        self.error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mutant_id": self.mutant_id,
            "original_op": self.original_op,
            "mutated_op": self.mutated_op,
            "line_no": self.line_no,
            "description": self.description,
            "status": self.status,
        }
        if self.counterexample is not None:
            out["counterexample"] = self.counterexample
        if self.error is not None:
            out["error"] = self.error
        return out


class _SiteScan(ast.NodeVisitor):
    """Collect every flippable operator position, in traversal order."""

    def __init__(self) -> None:
        self.sites: list[dict[str, Any]] = []

    def visit_Compare(self, node: ast.Compare) -> None:
        for index, op in enumerate(node.ops):
            flip = COMPARISON_FLIPS.get(type(op))
            if flip is not None:
                self.sites.append({
                    "owner": "Compare", "op_index": index, "new_op": flip[0],
                    "original": flip[1], "mutated": flip[2], "lineno": node.lineno,
                })
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        flip = ARITHMETIC_FLIPS.get(type(node.op))
        if flip is not None:
            self.sites.append({
                "owner": "BinOp", "op_index": 0, "new_op": flip[0],
                "original": flip[1], "mutated": flip[2], "lineno": node.lineno,
            })
        self.generic_visit(node)


class _SiteRewriter(ast.NodeTransformer):
    """Flip exactly the site at ``index``.

    The counting in the two ``visit_*`` methods below mirrors :class:`_SiteScan`
    exactly - same node types, same order, same ``generic_visit`` placement - so
    site ``i`` here is site ``i`` there. Nothing else links the two passes, which
    is why they are written next to each other.
    """

    def __init__(self, index: int) -> None:
        self.index = index
        self.seen = 0
        self.applied = False

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        for index, op in enumerate(node.ops):
            if type(op) not in COMPARISON_FLIPS:
                continue
            if self.seen == self.index:
                node.ops[index] = COMPARISON_FLIPS[type(op)][0]()
                self.applied = True
                self.seen += 1
                self.generic_visit(node)
                return node
            self.seen += 1
        self.generic_visit(node)
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        if type(node.op) in ARITHMETIC_FLIPS:
            if self.seen == self.index:
                node.op = ARITHMETIC_FLIPS[type(node.op)][0]()
                self.applied = True
                self.seen += 1
                self.generic_visit(node)
                return node
            self.seen += 1
        self.generic_visit(node)
        return node


def _canonical(value: Any) -> tuple[str, str]:
    """A comparable fingerprint of a return value.

    Scalars compare by ``repr``, which is exact. Anything else is reduced to its
    type name - see :data:`_SAFE_SCALARS`.
    """
    if isinstance(value, _SAFE_SCALARS):
        return ("scalar", repr(value))
    return ("opaque", type(value).__name__)


def _outcome(fn: Callable[..., Any], args: tuple) -> tuple[str, str, Any]:
    """Call ``fn`` and describe what happened as ``(kind, detail, value)``.

    ``except BaseException`` on purpose: submitted code is allowed to raise
    ``SystemExit`` or a custom ``BaseException``, and letting one escape would
    take down the caller instead of being recorded as a distinguishable outcome.
    """
    try:
        value = fn(*args)
    except BaseException as exc:  # noqa: BLE001 - submitted code may raise anything
        return ("raise", type(exc).__name__, None)
    return ("value", _canonical(value)[1], value)


def _key(outcome: tuple[str, str, Any]) -> tuple[str, str]:
    """Comparison key. Excludes the raw value so two opaque objects of the same
    class are not reported as different behaviour."""
    return (outcome[0], outcome[1])


def _render_outcome(outcome: tuple[str, str, Any]) -> str:
    kind, detail, _ = outcome
    return f"raises {detail}" if kind == "raise" else detail


def _positional_arity(fn: Callable[..., Any]) -> int:
    """How many positional arguments to pass, from the real signature."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return 1
    count = 0
    variadic = False
    for param in sig.parameters.values():
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
            count += 1
        elif param.kind is param.VAR_POSITIONAL:
            variadic = True
    if count == 0 and variadic:
        return 1
    return count


def _probe_corpus(arity: int) -> list[tuple]:
    if arity <= 0:
        return [()]
    if arity == 1:
        return [(value,) for value in PROBE_POOL]
    pool = (-1, 0, 1, 60, 61)
    probes = list(itertools.product(pool, repeat=arity))
    if len(probes) > MAX_PROBES:
        step = len(probes) / MAX_PROBES
        probes = [probes[int(i * step)] for i in range(MAX_PROBES)]
    return probes


def _load_function(source: str, fn_name: str) -> tuple[Callable[..., Any] | None, str | None]:
    """Load ``fn_name`` from ``source`` inside the constrained namespace.

    Submitted code is executed here, so it goes through ``safe_exec`` for the
    same reason ``run_python`` does. ``safe_exec`` is a guardrail rather than a
    sandbox - see its module docstring - and the access-control gate in
    ``baize/serve.py`` is the real boundary.
    """
    from .safe_exec import exec_restricted

    try:
        namespace = exec_restricted(source)
    except BaseException as exc:  # noqa: BLE001 - report, do not propagate
        return None, f"{type(exc).__name__}: {exc}"
    fn = namespace.get(fn_name)
    if fn is None:
        return None, f"{fn_name!r} is not defined by the submitted source"
    if not callable(fn):
        return None, f"{fn_name!r} is not callable (it is a {type(fn).__name__})"
    return fn, None


def _mutate_source(code: str, index: int) -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    rewriter = _SiteRewriter(index)
    rewriter.visit(tree)
    if not rewriter.applied:
        return None
    try:
        return ast.unparse(tree)
    except (ValueError, RecursionError):
        return None


def _tuple_src(args: tuple) -> str:
    if len(args) == 1:
        return f"({args[0]!r},)"
    return "(" + ", ".join(repr(a) for a in args) + ")"


def _guardrail_header(fn_name: str, probes: list[tuple], discriminating: list[int],
                      verification: dict[str, Any] | None) -> str:
    """Describe only what the emitted module was actually shown to do.

    ``verification`` is ``None`` on the draft pass and the real report on the
    returned pass, so the header cannot claim a run that has not happened.
    """
    lines = [
        "# Anti-Fragile Counterfactual Guardrail Test",
        "# Generated by baize.mutation.run_ast_mutation_arena.",
        f"# Target: {fn_name}    probes observed: {len(probes)}",
        "#",
        f"# {len(set(discriminating))} of those probes distinguished at least one mutant.",
        "# Every assertion below is an input/output pair observed on the ORIGINAL",
        "# source, which is included verbatim below so this file runs standalone.",
    ]
    if verification is None:
        lines.append("# Verification result: not run yet.")
    elif not verification.get("executed"):
        lines.append("# Verification result: this module was NOT executed.")
    elif verification.get("passes_original") is not True:
        lines.append(
            "# Verification result: FAILED against the original - "
            f"{verification.get('detail')}"
        )
    else:
        fails_killed = verification.get("fails_every_killed_mutant")
        if fails_killed is True:
            lines.append(
                "# Verification result: executed against the original (passes) and "
                "against every killed mutant (fails)."
            )
        elif fails_killed is None:
            lines.append(
                "# Verification result: executed against the original (passes). No "
                "mutant was killed, so this module fails on nothing."
            )
        else:
            lines.append(
                f"# Verification result: executed, but {verification.get('detail')}"
            )
    return "\n".join(lines) + "\n"


def _guardrail_body(fn_name: str, probes: list[tuple],
                    outcomes: list[tuple[str, str, Any]],
                    discriminating: list[int]) -> str:
    """The executable part: one assertion per observed input/output pair.

    Probes that actually distinguished a mutant come first, because those are
    what make this a guardrail rather than a snapshot. Plain ``assert`` and no
    ``pytest`` import, so :func:`_execute_module` can run the text inside the
    constrained namespace. Emitting text nobody ran is how the previous revision
    produced ``assert True``.
    """
    order: list[int] = []
    for index in discriminating:
        if index not in order:
            order.append(index)
    for index in range(len(probes)):
        if index not in order:
            order.append(index)
    emitted = order[:MAX_ASSERTIONS]

    lines = [
        "def _expect_raise(fn, args, exc_name):",
        "    try:",
        "        fn(*args)",
        "    except BaseException as exc:",
        "        if exc.__class__.__name__ == exc_name:",
        "            return",
        "        raise AssertionError(",
        "            f\"expected {exc_name}, got {exc.__class__.__name__}\")",
        "    raise AssertionError(f\"expected {exc_name}, nothing was raised\")",
        "",
        "",
        f"def test_{fn_name}_observed_boundaries():",
    ]
    if not emitted:
        lines.append("    raise AssertionError('no probe ran, so nothing is asserted')")
    for index in emitted:
        args = probes[index]
        kind, detail, _ = outcomes[index]
        if kind == "value":
            lines.append(f"    assert {fn_name}({', '.join(repr(a) for a in args)}) == {detail}")
        else:
            lines.append(f"    _expect_raise({fn_name}, {_tuple_src(args)}, {detail!r})")
    lines += [
        "",
        "",
        'if __name__ == "__main__":',
        f"    test_{fn_name}_observed_boundaries()",
        '    print("guardrail test passed")',
        "",
    ]
    return "\n".join(lines)


def _compose_guardrail(source: str, fn_name: str, probes: list[tuple],
                       discriminating: list[int],
                       verification: dict[str, Any] | None, body: str) -> str:
    """Assemble a standalone module: header, the source under test, then asserts.

    Embedding ``source`` is what makes the artefact runnable - a test that
    references a function defined nowhere cannot be executed by the person who
    receives it, and an artefact nobody can run is not evidence.
    """
    return (
        _guardrail_header(fn_name, probes, discriminating, verification)
        + "\n# --- source under test, verbatim ---\n"
        + source.rstrip("\n")
        + "\n\n# --- observed behaviour on the probe corpus ---\n"
        + body
    )


def _execute_module(module: str, test_name: str) -> tuple[bool, str | None]:
    """Execute an emitted module in the constrained namespace and run its test.

    ``__name__`` is not in ``SAFE_BUILTINS`` - it is a module global, not a
    builtin - so the module's ``if __name__ == "__main__"`` guard raises
    NameError unless it is seeded. Seeding it keeps the module runnable standalone
    *and* executable here, which is what lets the verification run the text
    instead of trusting it.
    """
    from .safe_exec import exec_restricted

    try:
        namespace = exec_restricted(module, seed={"__name__": "__guardrail__"})
    except BaseException as exc:  # noqa: BLE001
        return False, f"the emitted module failed to load: {type(exc).__name__}: {exc}"
    test = namespace.get(test_name)
    if not callable(test):
        return False, f"the emitted module does not define {test_name}"
    try:
        test()
    except BaseException as exc:  # noqa: BLE001
        return False, f"{test_name} raised {type(exc).__name__}: {exc}"
    return True, None


def _verify_guardrail(original_source: str, fn_name: str, probes: list[tuple],
                      discriminating: list[int], body: str,
                      killed: list[tuple[int, str]]) -> dict[str, Any]:
    """Prove the emitted module does what its header claims it does.

    The original must pass and every killed mutant must fail. Both are measured by
    executing the module text, not asserted by construction.

    Measured on a draft whose header reads "not run yet" - the returned module
    differs from it by one comment line, the one that reports this result. A
    comment cannot change behaviour, so the measurement carries over; the
    ``measured_on`` field says so rather than leaving the reader to infer it.
    """
    test_name = f"test_{fn_name}_observed_boundaries"
    report: dict[str, Any] = {
        "executed": False,
        "passes_original": None,
        "fails_every_killed_mutant": None,
        "detail": None,
        "measured_on": (
            "a module identical to the returned one except for the header comment "
            "line that reports this result"
        ),
    }
    if not body.strip():
        report["detail"] = "no test body was emitted"
        return report
    report["executed"] = True

    draft = _compose_guardrail(original_source, fn_name, probes, discriminating, None, body)
    passed, error = _execute_module(draft, test_name)
    report["passes_original"] = passed
    if not passed:
        report["detail"] = error
        return report

    if not killed:
        report["detail"] = "no mutant was killed, so the module has nothing to fail on"
        return report

    still_passing = []
    for mutant_id, mutant_source in killed:
        module = _compose_guardrail(
            mutant_source, fn_name, probes, discriminating, None, body
        )
        ok, _ = _execute_module(module, test_name)
        if ok:
            still_passing.append(mutant_id)
    report["fails_every_killed_mutant"] = not still_passing
    if still_passing:
        report["detail"] = (
            f"the emitted module also passes mutants {still_passing}, which the "
            f"arena counted as killed - the score and the test disagree"
        )
    return report


def run_ast_mutation_arena(code: str, target_fn_name: str = "calculate") -> dict[str, Any]:
    """Flip every mutable operator in ``code`` and run it against a probe corpus.

    Returns the per-mutant verdicts, the score derived from them, and a guardrail
    test built only from observations that were actually made. ``mutation_score``
    is ``None`` whenever no mutant ran - never a default of 100.
    """
    if not code or not code.strip():
        return {
            "status": "empty",
            "target_function": target_fn_name,
            "total_mutants_generated": 0,
            "mutants_executed": 0,
            "mutants": [],
            "mutation_score": None,
            "message": "no source was submitted, so no mutant was generated or run",
        }

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {
            "status": "parse_error",
            "target_function": target_fn_name,
            "total_mutants_generated": 0,
            "mutants_executed": 0,
            "mutants": [],
            "mutation_score": None,
            "error": f"{type(exc).__name__}: {exc}",
            "message": "the submitted source does not parse, so no mutant was run",
        }

    scan = _SiteScan()
    scan.visit(tree)
    sites = scan.sites
    if not sites:
        return {
            "status": "no_mutation_sites",
            "target_function": target_fn_name,
            "total_mutants_generated": 0,
            "mutants_executed": 0,
            "mutants": [],
            "mutation_score": None,
            "message": (
                "no comparison or arithmetic operator in the submitted source can be "
                "flipped, so there is nothing to mutate. An earlier revision invented "
                "two mutants here and reported a 100% score."
            ),
        }

    original_fn, load_error = _load_function(code, target_fn_name)
    if original_fn is None:
        return {
            "status": "target_not_found",
            "target_function": target_fn_name,
            "total_mutants_generated": len(sites),
            "mutants_executed": 0,
            "mutants": [],
            "mutation_score": None,
            "error": load_error,
            "message": f"no mutant was run: {load_error}",
        }

    probes = _probe_corpus(_positional_arity(original_fn))
    original_outcomes = [_outcome(original_fn, args) for args in probes]

    mutants: list[Mutant] = []
    for index, site in enumerate(sites[:MAX_MUTANTS], start=1):
        mutants.append(Mutant(
            mutant_id=index,
            original_op=site["original"],
            mutated_op=site["mutated"],
            line_no=site["lineno"],
            description=(
                f"第 {site['lineno']} 行 {site['owner']}：{site['original']} → {site['mutated']}"
            ),
        ))

    killed = survived = errored = 0
    discriminating: list[int] = []
    killed_sources: list[tuple[int, str]] = []

    for index, mutant in enumerate(mutants):
        mutated_source = _mutate_source(code, index)
        if mutated_source is None:
            mutant.status = "error"
            mutant.error = "the mutation site could not be rewritten"
            errored += 1
            continue

        mutant_fn, error = _load_function(mutated_source, target_fn_name)
        if mutant_fn is None:
            mutant.status = "error"
            mutant.error = f"the mutant failed to load: {error}"
            errored += 1
            continue

        first_disagreement: tuple[int, tuple[str, str, Any]] | None = None
        for probe_index, args in enumerate(probes):
            observed = _outcome(mutant_fn, args)
            if _key(observed) != _key(original_outcomes[probe_index]):
                first_disagreement = (probe_index, observed)
                break

        if first_disagreement is None:
            mutant.status = "survived"
            survived += 1
            continue

        probe_index, observed = first_disagreement
        mutant.status = "killed"
        mutant.killed_by = probe_index
        mutant.counterexample = {
            "args": [repr(a) for a in probes[probe_index]],
            "original": _render_outcome(original_outcomes[probe_index]),
            "mutant": _render_outcome(observed),
        }
        killed += 1
        discriminating.append(probe_index)
        killed_sources.append((mutant.mutant_id, mutated_source))

    executed = killed + survived
    score = round((killed / executed) * 100, 1) if executed else None

    body = _guardrail_body(target_fn_name, probes, original_outcomes, discriminating)
    verification = _verify_guardrail(
        code, target_fn_name, probes, discriminating, body, killed_sources
    )
    test_code = _compose_guardrail(
        code, target_fn_name, probes, discriminating, verification, body
    )

    limitations = list(LIMITATIONS)
    truncated = len(sites) - len(mutants)
    if truncated > 0:
        limitations.append(
            f"{truncated} further mutation site(s) were found but not executed "
            f"(the cap is {MAX_MUTANTS} per call)"
        )

    if score is None:
        message = (
            f"生成 {len(sites)} 个变异位点，但没有一个变异体被成功执行，"
            f"因此没有击杀率可报。加载失败 {errored} 个。"
        )
    else:
        message = (
            f"执行 {executed} 个变异体：击杀 {killed} 个、存活 {survived} 个"
            + (f"、加载失败 {errored} 个" if errored else "")
            + f"；探针 {len(probes)} 个。击杀率 {score}%。"
            + "该数字只说明这些探针能否区分这些变异体，不代表代码正确。"
        )

    return {
        "status": "success",
        "target_function": target_fn_name,
        "total_mutants_generated": len(sites),
        "mutants_executed": executed,
        "mutants_killed": killed,
        "mutants_survived": survived,
        "mutants_errored": errored,
        "mutation_score": f"{score}%" if score is not None else None,
        "score_basis": "killed / (killed + survived) over the probe corpus below",
        "probe_corpus_size": len(probes),
        "probe_corpus_preview": [repr(args) for args in probes[:MAX_ASSERTIONS]],
        "mutants": [mutant.to_dict() for mutant in mutants],
        "synthesized_guardrail_test": test_code,
        "guardrail_verification": verification,
        "limitations": limitations,
        "message": message,
    }
