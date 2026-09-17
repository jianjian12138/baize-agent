#!/usr/bin/env python
"""Fail the build if an endpoint reports success it did not achieve.

Why this exists
---------------
Seven routes in ``baize/serve.py`` answered ``HTTP 200`` with a hardcoded success
payload while doing no work at all:

    /api/ci/autofix           -> {"status": "pr_opened", "pr_number": 43, ...}
    /api/git/apply_hunk       -> {"status": "applied", ...}
    /api/vision/analyze       -> {"status": "analyzed", "components_detected": [...]}
    /api/webhook/dispatch     -> {"status": "dispatched", ...}
    /team/dag                 -> {"executed_nodes": [{"verdict": "pass"}, ...]}
    /v30/speculative/merge    -> {"status": "merged", "churn_lines": 4, ...}
    /v30/causal/heal          -> {"status": "healed", "tests_passed": 4, ...}

Every value in those bodies was a literal typed into the file. No PR was opened,
no patch was applied, no model was called, no test was run - and the Studio UI
rendered the literals as real outcomes. This is the "NO FAKE DONE" rule violated
at the API layer, which is worse than violating it in a docstring: a docstring
misleads a reader, an endpoint misleads a program.

They now answer ``501 Not Implemented`` and are declared in
``baize/serve.STUB_ROUTES``.

What this gate does
-------------------
Not a source-code heuristic. Heuristics on "does this look fabricated" cry wolf
and get switched off. Instead it starts the real server on an ephemeral port and
makes the real requests, so it fails on behaviour rather than on shape:

  1. every path in STUB_ROUTES answers 501 with the documented body shape;
  2. no stub response carries a fabricated artefact (key set is pinned exactly);
  3. the fabrication literals that used to live in serve.py are gone from source;
  4. a route that genuinely does work still answers 200, so the gate cannot pass
     by breaking the server;
  5. `baize speculative` prints its "hardcoded fixture" warning, because the CLI
     path has the same defect in a different form.

Usage
-----
    python scripts/check_endpoint_honesty.py        # exit 1 on any violation

Exit codes: 0 honest, 1 dishonest, 2 could not run.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: A token is required to reach any POST route, because the service is
#: fail-closed. This value is local to the gate process and guards nothing.
GATE_TOKEN = "endpoint-honesty-gate-not-a-secret"

#: Literals that constituted fabricated evidence. Each is an exact source
#: fragment from the pre-fix code, so a match is unambiguous - no guessing about
#: intent. Kept as source text rather than as "keys we dislike" because real
#: routes legitimately return keys like `status` and `tests_passed`.
#:
#: Deliberately NOT included: the bare fragment ``"verdict": "pass"``. It appears
#: legitimately in baize/agent.py (a prompt telling the verifier which JSON shape
#: to emit) and in baize/orchestrator.py (a ledger entry written only after
#: verify_subtask actually ran). A first draft of this gate did include it and
#: produced exactly the false positives this comment warns about. The /team/dag
#: fabrication is pinned instead by the longer fragment below, which only the
#: hardcoded body contained.
FABRICATION_MARKERS = [
    '"pr_number": 43',
    "已自动创建修复分支并在",
    "已成功单行精准合并至本地工作区",
    "components_detected",
    '"verdict": "pass", "time_ms": 230',
    "已成功推送到",
    '"status": "dispatched"',
    '"status": "analyzed"',
    '"status": "healed"',
    "全绿通过",
    "全部通过物理门禁核验",
    "已成功将胜出时间线",
    # --- second pass: four more endpoints that fabricated success -----------
    # Found while writing the route tests that were meant to raise serve.py
    # coverage. The audit's list was a sample, not a census.
    "已成功动态热加载至当前智能体 ToolRegistry 沙箱",   # /api/tools/import
    "细粒度路径 RBAC 权限与物理门禁加密签名水印已生效",   # /api/security/rbac
    '"faults_injected": 5',                              # /api/chaos/simulate
    '"recovery_rate": "100%"',
    "抗脆弱物理门禁 100% 满分通过",
    # /v30/speculative: three timelines constructed in the handler.
    'SpeculativeTimeline(timeline_id="t1"',
    # Overclaims, fixed in place rather than stubbed:
    '"routed_model"',       # nothing was routed - it is a classifier
    '"saved_cost_ratio"',   # a cost saving that was never measured
    '"relevance": 0.92',    # a fixed score attached to every substring hit
    '"source": "knowledge_base"',  # invented when nothing matched
    # GET /api/windows/status served these two as fact. "Bypass (Isolated
    # Sandboxed)" claimed an OS boundary that does not exist on Windows, and
    # "WSL2 Active" was returned from the *failure* branch of the probe.
    "Isolated Sandboxed",
    "WSL2 Active",
    # The desktop UI substituted this when the version probe returned null.
    "PowerShell 5.1",
    # --- third pass: the Phase 3 "industrial" cluster ----------------------
    # baize/mutation.py scored every input 100% by dividing the mutant count by
    # itself, and emitted `assert True` as the "synthesized guardrail test".
    "killed_count = len(mutants)",
    "assert True",
    # baize/byzantine.py returned two literal APPROVEs, so every request reached
    # consensus, and hashed the current time into a field named "signature".
    '"bft_signature"',
    '"fuzzing_rounds": 50',          # no fuzzer ran
    '"vulnerabilities_found": 0',
    '"invariants_satisfied": 6',     # no invariant was counted
    # baize/tool_market.py stamped a verification result and a download count on
    # every record while running no gate and counting nothing.
    "self.verified_gate: bool = True",
    "self.downloads: int = 12",
    "已通过物理门禁认证",
]

#: Exact key set a stub response may carry. Anything else is a fabricated field
#: smuggled back in alongside the 501.
STUB_BODY_KEYS = {"error", "status", "path", "reason", "message"}

#: A route that really does work. If this stops answering 200 the gate is passing
#: for the wrong reason.
CONTROL_ROUTE = "/api/context/slice"
CONTROL_PAYLOAD = {"code": "def f():\n    return 1", "focus_symbol": "f"}


def _request(base: str, path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {GATE_TOKEN}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def strip_documentation(text: str) -> str:
    """Return ``text`` with comments and docstrings removed, positions preserved.

    A marker that documents a *removed* fabrication legitimately appears in the
    explanation of that fix - the powershell fix has to say that the field used to
    read ``Bypass (Isolated Sandboxed)``, and the mutation fix has to say that the
    emitted test used to be ``assert True``, or the next reader will re-add them.
    A gate that forbids quoting the bug it fixed would force the explanation to be
    deleted, which is the opposite of the point.

    So documentation is excluded; code and non-docstring string literals are not.
    Both halves are removed rather than just comments because a docstring is a
    string literal to ``tokenize`` - ``assert True`` inside a module docstring is
    prose, while ``"assert True"`` inside a function body is the bug.

    Implemented with ``ast`` for the docstrings and ``tokenize`` for the comments,
    rather than "skip lines starting with #", so a ``#`` inside a string literal
    is not mistaken for a comment.
    """
    import io
    import tokenize

    lines = text.splitlines(keepends=True)

    def blank(start: tuple[int, int], end: tuple[int, int]) -> None:
        for row in range(start[0], end[0] + 1):
            line = lines[row - 1]
            first = start[1] if row == start[0] else 0
            last = end[1] if row == end[0] else len(line.rstrip("\n"))
            lines[row - 1] = line[:first] + " " * (last - first) + line[last:]

    try:
        tree = ast.parse(text)
    except SyntaxError:
        # A file we cannot parse is not a file we should silently pass: fall back
        # to the raw text and let the markers speak.
        return text

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        blank((first.value.lineno, first.value.col_offset),
              (first.value.end_lineno, first.value.end_col_offset))

    stripped = "".join(lines)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(stripped).readline):
            if tok.type != tokenize.COMMENT:
                continue
            row, col = tok.start
            end_col = tok.end[1] if tok.end[0] == row else len(lines[row - 1])
            lines[row - 1] = lines[row - 1][:col] + lines[row - 1][end_col:]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return text
    return "".join(lines)


def check_source_markers() -> list[str]:
    """No fabrication literal may survive in executable code anywhere in the
    package. Comments and docstrings are excluded - see
    :func:`strip_documentation`."""
    problems = []
    for p in sorted((ROOT / "baize").rglob("*.py")):
        text = p.read_text(encoding="utf-8", errors="replace")
        code = strip_documentation(text)
        for marker in FABRICATION_MARKERS:
            if marker in code:
                problems.append(
                    f"{p.relative_to(ROOT)}: still contains fabricated-evidence "
                    f"literal {marker!r}"
                )
    return problems


def check_cli_fixture_warning() -> list[str]:
    """`baize speculative` must announce that its data is a hardcoded fixture."""
    proc = subprocess.run(
        [sys.executable, "-m", "baize", "speculative", "honesty-gate"],
        cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=180,
    )
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        return [f"`baize speculative` exited {proc.returncode}; cannot verify honesty"]
    missing = [phrase for phrase in ("hardcoded demo fixture", "preset fixture")
               if phrase not in out]
    if missing:
        return [
            "`baize speculative` no longer warns that its numbers are a hardcoded "
            f"fixture (missing {missing}). The three timelines in cmd_speculative "
            "are literals - restore the warning or implement it for real."
        ]
    return []


def check_live_routes() -> list[str]:
    """Start the real server and probe every stub route plus one control route."""
    os.environ["BAIZE_AUTH_TOKEN"] = GATE_TOKEN
    try:
        from http.server import ThreadingHTTPServer

        from baize.serve import STUB_ROUTES, Handler
    except Exception as exc:  # noqa: BLE001 - any import failure is the gate failing
        return [f"could not import the server to probe it: {exc!r}"]

    if not STUB_ROUTES:
        return [
            "baize/serve.STUB_ROUTES is empty. If the stubs were genuinely "
            "implemented, delete them from this gate's expectations; if they were "
            "deleted, restore the 501s - they did not become real."
        ]

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    problems: list[str] = []
    try:
        for path in sorted(STUB_ROUTES):
            code, body = _request(base, path, {})
            if code != 501:
                problems.append(
                    f"{path}: answered {code}, expected 501 - a stub must not "
                    f"report success"
                )
                continue
            if body.get("error") != "not_implemented":
                problems.append(
                    f"{path}: 501 body has error={body.get('error')!r}, expected "
                    f"'not_implemented'"
                )
            extra = set(body) - STUB_BODY_KEYS
            if extra:
                problems.append(
                    f"{path}: stub body carries unexpected fields {sorted(extra)} - "
                    f"fabricated artefacts must not ride along with the 501"
                )
            if not body.get("reason"):
                problems.append(f"{path}: stub body has no 'reason' explaining what is missing")

        code, body = _request(base, CONTROL_ROUTE, CONTROL_PAYLOAD)
        if code != 200:
            problems.append(
                f"control route {CONTROL_ROUTE} answered {code}, expected 200 - the "
                f"gate would otherwise pass by breaking the server"
            )
    finally:
        srv.shutdown()
        srv.server_close()
    return problems


def main(argv: list[str]) -> int:
    checks = [
        ("source fabrication markers", check_source_markers),
        ("live stub routes", check_live_routes),
        ("CLI fixture warning", check_cli_fixture_warning),
    ]
    problems: list[str] = []
    for name, fn in checks:
        try:
            found = fn()
        except Exception as exc:  # noqa: BLE001
            found = [f"{name}: check crashed with {exc!r}"]
        problems += found
        print(f"  [{'FAIL' if found else ' ok '}] {name}")

    if problems:
        print(f"\nENDPOINT HONESTY GATE FAILED: {len(problems)} problem(s)\n")
        for p in problems:
            print("  " + p)
        print(
            "\nA route must not report an outcome it did not produce. Either "
            "implement the work, or answer 501 and declare it in "
            "baize/serve.STUB_ROUTES."
        )
        return 1

    print("\nENDPOINT HONESTY GATE PASSED: no endpoint reports unearned success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
