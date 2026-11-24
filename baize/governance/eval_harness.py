"""Real multi-file coding evaluation harness with regression comparison.

Runs curated, isolated multi-file coding benchmarks (bug fixes, refactors,
boundary-case tests, persistence fixes) inside temporary workspaces verified by
real physical ``unittest`` execution. Supports two execution modes:
- ``live``: drives the real ``Agent`` against any configured ``LLMClient``
  endpoint, recording Pass@1, step count, tool calls, latency, token usage,
  cache hit ratio, and rollback status.
- ``oracle``: executes each task's physical verification against the reference
  solution (and verifies the baseline fails first!) so the harness itself can
  be regression-tested deterministically in CI without an API key.

All results are persisted to append-only JSONL (``persistence/eval_runs.jsonl``)
so engineers can compare two engine/prompt versions with ``compare_runs()``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..core.config import load_config

__all__ = [
    "EvalTask",
    "EvalTaskResult",
    "EvalRunSummary",
    "BUILTIN_EVAL_TASKS",
    "run_eval_suite",
    "load_eval_runs",
    "compare_runs",
]


@dataclass(frozen=True)
class EvalTask:
    task_id: str
    title: str
    category: str  # bugfix | refactor | testing | persistence
    goal: str
    initial_files: dict[str, str]
    test_command: list[str]
    oracle_files: dict[str, str]


@dataclass
class EvalTaskResult:
    task_id: str
    title: str
    category: str
    baseline_failed: bool
    passed: bool
    steps: int = 0
    tool_calls: int = 0
    duration_ms: float = 0.0
    stopped_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    rollback_triggered: bool = False
    verify_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalRunSummary:
    eval_run_id: str
    mode: str  # live | oracle
    model: str
    created_at: float
    total_tasks: int
    passed_tasks: int
    pass_rate: float
    avg_steps: float
    avg_duration_ms: float
    total_prompt_tokens: int
    total_completion_tokens: int
    results: list[EvalTaskResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["results"] = [r.to_dict() for r in self.results]
        return d

    def format_summary(self) -> str:
        lines = [
            f"=== Baize Coding Eval [{self.eval_run_id}] mode={self.mode} model={self.model} ===",
            f"Pass@1: {self.passed_tasks}/{self.total_tasks} ({self.pass_rate * 100:.1f}%) "
            f"| avg_steps={self.avg_steps:.2f} | avg_ms={self.avg_duration_ms:.1f}ms "
            f"| tokens={self.total_prompt_tokens}+{self.total_completion_tokens}",
        ]
        for r in self.results:
            mark = "PASS" if r.passed else "FAIL"
            lines.append(
                f"  [{mark}] {r.task_id:<18} ({r.category:<11}) "
                f"steps={r.steps:<2} {r.duration_ms:6.1f}ms reason={r.stopped_reason}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Built-in curated multi-file real engineering tasks
# ---------------------------------------------------------------------------
BUILTIN_EVAL_TASKS: list[EvalTask] = [
    EvalTask(
        task_id="bugfix_rate_limit",
        title="Fix off-by-one sliding window rate limiter",
        category="bugfix",
        goal=(
            "Fix the bug in app/limiter.py where allow() permits one extra request "
            "beyond max_requests and fails to evict expired timestamps cleanly. "
            "Run tests/test_limiter.py to verify."
        ),
        initial_files={
            "app/__init__.py": "",
            "app/limiter.py": (
                "class WindowLimiter:\n"
                "    def __init__(self, max_requests: int, window_s: float):\n"
                "        self.max_requests = max_requests\n"
                "        self.window_s = window_s\n"
                "        self._hits = []\n"
                "    def allow(self, now: float) -> bool:\n"
                "        # BUG: uses <= instead of < and forgets strict cutoff\n"
                "        self._hits = [t for t in self._hits if now - t <= self.window_s]\n"
                "        if len(self._hits) <= self.max_requests:\n"
                "            self._hits.append(now)\n"
                "            return True\n"
                "        return False\n"
            ),
            "tests/test_limiter.py": (
                "import unittest\n"
                "from app.limiter import WindowLimiter\n"
                "class TestLimiter(unittest.TestCase):\n"
                "    def test_exact_limit(self):\n"
                "        lim = WindowLimiter(2, 10.0)\n"
                "        self.assertTrue(lim.allow(1.0))\n"
                "        self.assertTrue(lim.allow(2.0))\n"
                "        self.assertFalse(lim.allow(3.0))\n"
                "    def test_window_expiry(self):\n"
                "        lim = WindowLimiter(1, 10.0)\n"
                "        self.assertTrue(lim.allow(0.0))\n"
                "        self.assertFalse(lim.allow(9.9))\n"
                "        self.assertTrue(lim.allow(10.0))\n"
                "if __name__ == '__main__': unittest.main()\n"
            ),
        },
        test_command=[sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        oracle_files={
            "app/limiter.py": (
                "class WindowLimiter:\n"
                "    def __init__(self, max_requests: int, window_s: float):\n"
                "        self.max_requests = max_requests\n"
                "        self.window_s = window_s\n"
                "        self._hits = []\n"
                "    def allow(self, now: float) -> bool:\n"
                "        self._hits = [t for t in self._hits if now - t < self.window_s]\n"
                "        if len(self._hits) < self.max_requests:\n"
                "            self._hits.append(now)\n"
                "            return True\n"
                "        return False\n"
            ),
        },
    ),
    EvalTask(
        task_id="refactor_pricing",
        title="Multi-file discount calculation refactor preserving callers",
        category="refactor",
        goal=(
            "Fix app/pricing.py and app/invoice.py so percentage discounts clamp to [0, 100] "
            "and never produce negative totals, while keeping invoice summaries accurate. "
            "Verify with tests/test_pricing.py."
        ),
        initial_files={
            "app/__init__.py": "",
            "app/pricing.py": (
                "def apply_discount(subtotal: float, pct: float) -> float:\n"
                "    return round(subtotal * (1 - pct / 100.0), 2)\n"
            ),
            "app/invoice.py": (
                "from app.pricing import apply_discount\n"
                "def build_invoice(items: list[tuple[str, float]], pct: float = 0.0) -> dict:\n"
                "    sub = round(sum(p for _, p in items), 2)\n"
                "    return {'subtotal': sub, 'total': apply_discount(sub, pct)}\n"
            ),
            "tests/test_pricing.py": (
                "import unittest\n"
                "from app.invoice import build_invoice\n"
                "class TestPricing(unittest.TestCase):\n"
                "    def test_clamps_over_100(self):\n"
                "        inv = build_invoice([('a', 50.0)], 150.0)\n"
                "        self.assertEqual(inv['total'], 0.0)\n"
                "    def test_clamps_negative_pct(self):\n"
                "        inv = build_invoice([('a', 50.0)], -20.0)\n"
                "        self.assertEqual(inv['total'], 50.0)\n"
                "    def test_normal_discount(self):\n"
                "        inv = build_invoice([('a', 100.0)], 15.0)\n"
                "        self.assertEqual(inv['total'], 85.0)\n"
                "if __name__ == '__main__': unittest.main()\n"
            ),
        },
        test_command=[sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        oracle_files={
            "app/pricing.py": (
                "def apply_discount(subtotal: float, pct: float) -> float:\n"
                "    clamped = max(0.0, min(100.0, pct))\n"
                "    return max(0.0, round(subtotal * (1 - clamped / 100.0), 2))\n"
            ),
        },
    ),
    EvalTask(
        task_id="persistence_kv",
        title="Fix atomic JSON persistence corruption on empty/missing file",
        category="persistence",
        goal=(
            "Fix app/kv.py so load() handles missing or empty files gracefully without "
            "raising JSONDecodeError and save() writes atomically. Verify with tests/test_kv.py."
        ),
        initial_files={
            "app/__init__.py": "",
            "app/kv.py": (
                "import json\nfrom pathlib import Path\n"
                "class KVStore:\n"
                "    def __init__(self, path: Path):\n"
                "        self.path = Path(path)\n"
                "    def load(self) -> dict:\n"
                "        return json.loads(self.path.read_text(encoding='utf-8'))\n"
                "    def set(self, k: str, v) -> None:\n"
                "        data = self.load()\n"
                "        data[k] = v\n"
                "        self.path.write_text(json.dumps(data), encoding='utf-8')\n"
            ),
            "tests/test_kv.py": (
                "import tempfile, unittest\nfrom pathlib import Path\n"
                "from app.kv import KVStore\n"
                "class TestKV(unittest.TestCase):\n"
                "    def test_missing_file_defaults_empty(self):\n"
                "        with tempfile.TemporaryDirectory() as td:\n"
                "            st = KVStore(Path(td) / 'sub' / 'db.json')\n"
                "            self.assertEqual(st.load(), {})\n"
                "            st.set('x', 42)\n"
                "            self.assertEqual(st.load()['x'], 42)\n"
                "    def test_empty_file_defaults_empty(self):\n"
                "        with tempfile.TemporaryDirectory() as td:\n"
                "            p = Path(td) / 'db.json'\n"
                "            p.write_text('', encoding='utf-8')\n"
                "            st = KVStore(p)\n"
                "            self.assertEqual(st.load(), {})\n"
                "if __name__ == '__main__': unittest.main()\n"
            ),
        },
        test_command=[sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        oracle_files={
            "app/kv.py": (
                "import json, os\nfrom pathlib import Path\n"
                "class KVStore:\n"
                "    def __init__(self, path: Path):\n"
                "        self.path = Path(path)\n"
                "    def load(self) -> dict:\n"
                "        if not self.path.is_file():\n"
                "            return {}\n"
                "        raw = self.path.read_text(encoding='utf-8').strip()\n"
                "        return json.loads(raw) if raw else {}\n"
                "    def set(self, k: str, v) -> None:\n"
                "        data = self.load()\n"
                "        data[k] = v\n"
                "        self.path.parent.mkdir(parents=True, exist_ok=True)\n"
                "        tmp = self.path.with_suffix(self.path.suffix + '.tmp')\n"
                "        tmp.write_text(json.dumps(data), encoding='utf-8')\n"
                "        os.replace(tmp, self.path)\n"
            ),
        },
    ),
    EvalTask(
        task_id="bugfix_path_guard",
        title="Fix path traversal check in safe_join utility",
        category="bugfix",
        goal=(
            "Fix app/paths.py so safe_join() rejects '..' traversal and sibling prefix "
            "bypasses (e.g. '/tmp/root_evil' matching '/tmp/root'). Verify with tests/test_paths.py."
        ),
        initial_files={
            "app/__init__.py": "",
            "app/paths.py": (
                "from pathlib import Path\n"
                "def safe_join(root: Path, rel: str) -> Path:\n"
                "    base = Path(root).resolve()\n"
                "    cand = (base / rel).resolve()\n"
                "    if not str(cand).startswith(str(base)):\n"
                "        raise ValueError('traversal')\n"
                "    return cand\n"
            ),
            "tests/test_paths.py": (
                "import tempfile, unittest\nfrom pathlib import Path\n"
                "from app.paths import safe_join\n"
                "class TestPaths(unittest.TestCase):\n"
                "    def test_blocks_sibling_prefix(self):\n"
                "        with tempfile.TemporaryDirectory() as td:\n"
                "            root = Path(td) / 'ws'\n"
                "            root.mkdir()\n"
                "            with self.assertRaises(ValueError):\n"
                "                safe_join(root, '../ws_evil/secret.txt')\n"
                "    def test_allows_child(self):\n"
                "        with tempfile.TemporaryDirectory() as td:\n"
                "            root = Path(td) / 'ws'\n"
                "            root.mkdir()\n"
                "            p = safe_join(root, 'a/b.py')\n"
                "            self.assertEqual(p.name, 'b.py')\n"
                "if __name__ == '__main__': unittest.main()\n"
            ),
        },
        test_command=[sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        oracle_files={
            "app/paths.py": (
                "from pathlib import Path\n"
                "def safe_join(root: Path, rel: str) -> Path:\n"
                "    base = Path(root).resolve()\n"
                "    cand = (base / rel).resolve()\n"
                "    if cand != base and base not in cand.parents:\n"
                "        raise ValueError('traversal')\n"
                "    return cand\n"
            ),
        },
    ),
]


def _write_files(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _run_verify(root: Path, cmd: list[str] | str, timeout: int = 30) -> tuple[bool, str]:
    import shlex as _shlex
    argv = _shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        argv, cwd=str(root), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    out = (proc.stdout + "\n" + proc.stderr).strip()
    return proc.returncode == 0, out[-800:]


def _eval_log_path(cfg: dict[str, str]) -> Path:
    base = Path(cfg.get("BAIZE_PERSISTENCE_DIR", "persistence"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "eval_runs.jsonl"


def run_eval_suite(
    *,
    mode: str = "oracle",
    task_ids: list[str] | None = None,
    cfg: dict[str, str] | None = None,
    persist: bool = True,
    runner: Callable[[EvalTask, Path], dict[str, Any]] | None = None,
    tasks: list[EvalTask] | None = None,
) -> EvalRunSummary:
    """Execute the coding eval suite in ``oracle`` or ``live`` mode."""
    cfg = cfg or load_config()
    source_tasks = list(tasks) if tasks is not None else list(BUILTIN_EVAL_TASKS)
    tasks = [
        t for t in source_tasks
        if not task_ids or t.task_id in task_ids
    ]
    model_name = "oracle" if mode == "oracle" else (cfg.get("BAIZE_MODEL") or "configured-llm")
    results: list[EvalTaskResult] = []

    for task in tasks:
        t0 = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix=f"baize-eval-{task.task_id}-") as td:
            ws = Path(td)
            _write_files(ws, task.initial_files)
            # Confirm baseline fails (so a passing result proves real work)
            base_ok, _ = _run_verify(ws, task.test_command)
            baseline_failed = not base_ok

            steps = 0
            tool_calls = 0
            stopped_reason = "oracle_applied"
            prompt_tokens = 0
            completion_tokens = 0
            rollback_triggered = False

            if runner is not None:
                info = runner(task, ws)
                steps = int(info.get("steps", 0))
                tool_calls = int(info.get("tool_calls", 0))
                stopped_reason = str(info.get("stopped_reason", "runner"))
                prompt_tokens = int(info.get("prompt_tokens", 0))
                completion_tokens = int(info.get("completion_tokens", 0))
                rollback_triggered = bool(info.get("rollback_triggered", False))
            elif mode == "oracle":
                _write_files(ws, task.oracle_files)
                steps = 1
                tool_calls = len(task.oracle_files)
            elif mode == "live":
                from ..core.agent import Agent
                from ..core.llm import LLMClient
                from ..execution.tools import default_registry

                run_cfg = dict(cfg)
                run_cfg["BAIZE_WORKSPACE_DIR"] = str(ws)
                client = LLMClient(run_cfg)
                if not client.configured:
                    raise RuntimeError("live eval requires a configured LLM endpoint")
                agent = Agent(
                    role="executor",
                    cfg=run_cfg,
                    client=client,
                    registry=default_registry(str(ws)),
                )
                ares = agent.run(task.goal)
                steps = ares.steps
                tool_calls = ares.tool_calls
                stopped_reason = ares.stopped_reason
                telem = client.telemetry() if hasattr(client, "telemetry") else {}
                prompt_tokens = int(telem.get("prompt_tokens", 0))
                completion_tokens = int(telem.get("completion_tokens", 0))
                rollback_triggered = bool(getattr(ares, "rolled_back", False))
            else:
                raise ValueError(f"unsupported eval mode: {mode!r}")

            passed, verify_out = _run_verify(ws, task.test_command)
            results.append(EvalTaskResult(
                task_id=task.task_id,
                title=task.title,
                category=task.category,
                baseline_failed=baseline_failed,
                passed=baseline_failed and passed,
                steps=steps,
                tool_calls=tool_calls,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                stopped_reason=stopped_reason,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                rollback_triggered=rollback_triggered,
                verify_output=verify_out,
            ))

    n = len(results)
    passed_n = sum(1 for r in results if r.passed)
    summary = EvalRunSummary(
        eval_run_id=f"eval-{int(time.time())}-{uuid.uuid4().hex[:6]}",
        mode=mode,
        model=model_name,
        created_at=time.time(),
        total_tasks=n,
        passed_tasks=passed_n,
        pass_rate=(passed_n / n) if n else 0.0,
        avg_steps=(sum(r.steps for r in results) / n) if n else 0.0,
        avg_duration_ms=(sum(r.duration_ms for r in results) / n) if n else 0.0,
        total_prompt_tokens=sum(r.prompt_tokens for r in results),
        total_completion_tokens=sum(r.completion_tokens for r in results),
        results=results,
    )
    if persist:
        log_path = _eval_log_path(cfg)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(summary.to_dict(), ensure_ascii=False) + "\n")
    return summary


def load_eval_runs(cfg: dict[str, str] | None = None) -> list[dict[str, Any]]:
    cfg = cfg or load_config()
    p = _eval_log_path(cfg)
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def compare_runs(run_a: dict[str, Any], run_b: dict[str, Any]) -> dict[str, Any]:
    """Compare two recorded eval runs (B vs A) and surface regressions/improvements."""
    res_a = {r["task_id"]: r for r in run_a.get("results", [])}
    res_b = {r["task_id"]: r for r in run_b.get("results", [])}
    regressions = [tid for tid in res_a if res_a[tid].get("passed") and not res_b.get(tid, {}).get("passed")]
    improvements = [tid for tid in res_b if res_b[tid].get("passed") and not res_a.get(tid, {}).get("passed")]
    return {
        "base_run": run_a.get("eval_run_id"),
        "candidate_run": run_b.get("eval_run_id"),
        "pass_rate_delta": round(float(run_b.get("pass_rate", 0.0)) - float(run_a.get("pass_rate", 0.0)), 4),
        "avg_steps_delta": round(float(run_b.get("avg_steps", 0.0)) - float(run_a.get("avg_steps", 0.0)), 3),
        "avg_duration_ms_delta": round(float(run_b.get("avg_duration_ms", 0.0)) - float(run_a.get("avg_duration_ms", 0.0)), 2),
        "regressions": regressions,
        "improvements": improvements,
    }


# ---------------------------------------------------------------------------
# V41: SWE-bench Style External JSONL Dataset Loader & Tool Profile Comparison
# ---------------------------------------------------------------------------

def load_external_eval_tasks(dataset_path: str | Path) -> list[EvalTask]:
    """Load real coding evaluation tasks from an external JSONL file."""
    import shlex

    p = Path(dataset_path)
    if not p.is_file():
        raise FileNotFoundError(f"Eval dataset not found: {p}")
    tasks: list[EvalTask] = []
    for lineno, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        obj = json.loads(line)
        tid = str(obj.get("task_id") or f"ext_{lineno:03d}")
        files = obj.get("initial_files") if isinstance(obj.get("initial_files"), dict) else (
            obj.get("files") if isinstance(obj.get("files"), dict) else {}
        )
        oracle_files = obj.get("oracle_files") if isinstance(obj.get("oracle_files"), dict) else {}
        raw_cmd = obj.get("test_command") or obj.get("verify_cmd") or [sys.executable, "-m", "unittest"]
        test_command = [str(c) for c in raw_cmd] if isinstance(raw_cmd, list) else shlex.split(str(raw_cmd))
        tasks.append(EvalTask(
            task_id=tid,
            title=str(obj.get("title") or tid),
            category=str(obj.get("category") or "external"),
            goal=str(obj.get("goal") or ""),
            initial_files={str(k): str(v) for k, v in files.items()},
            test_command=test_command,
            oracle_files={str(k): str(v) for k, v in oracle_files.items()},
        ))
    return tasks


def run_profile_comparison(
    *,
    profiles: tuple[str, ...] = ("minimal", "tiered", "full"),
    mode: str = "oracle",
    tasks: list[EvalTask] | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare schema token overhead and eval results across V41 tool profiles."""
    from ..core.context_engine import ToolProfileManager
    from ..execution.tools import default_registry

    cfg = cfg or load_config()
    all_schemas = default_registry().schemas()
    by_profile: dict[str, dict[str, Any]] = {}
    for prof in profiles:
        mgr = ToolProfileManager(all_schemas, profile=prof)
        prof_cfg = dict(cfg)
        prof_cfg["BAIZE_TOOL_PROFILE"] = prof
        summary = run_eval_suite(mode=mode, tasks=tasks, cfg=prof_cfg, persist=False)
        by_profile[prof] = {
            "profile": prof,
            "active_tools": len(mgr.active_names),
            "deferred_tools": len(mgr.deferred_names),
            "schema_tokens": mgr.schema_token_estimate(),
            "passed_tasks": summary.passed_tasks,
            "total_tasks": summary.total_tasks,
            "pass_rate": summary.pass_rate,
            "avg_steps": summary.avg_steps,
            "avg_duration_ms": summary.avg_duration_ms,
        }
    full_tok = by_profile.get("full", {}).get("schema_tokens", 0)
    tiered_tok = by_profile.get("tiered", {}).get("schema_tokens", 0)
    savings_pct = round((1.0 - tiered_tok / full_tok) * 100.0, 2) if full_tok > 0 else 0.0
    return {
        "mode": mode,
        "profiles": by_profile,
        "tiered_savings_pct": savings_pct,
    }


# ---------------------------------------------------------------------------
# V44 Atlas: SQLite WAL Eval History Store + Self-Contained CodingBench Suite
# ---------------------------------------------------------------------------

class EvalHistoryStore:
    """Persistent SQLite WAL store tracking benchmark runs & pass-rate regressions."""

    def __init__(self, db_path: str | Path | None = None, *, cfg: dict[str, Any] | None = None) -> None:
        import sqlite3
        c = cfg if cfg is not None else load_config()
        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            self.db_path = Path(c.get("BAIZE_PERSISTENCE_DIR", "persistence")) / "eval_history.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path), timeout=10.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS eval_runs (
                    run_id TEXT PRIMARY KEY,
                    ts REAL NOT NULL,
                    suite TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    model TEXT NOT NULL,
                    total_tasks INTEGER NOT NULL,
                    passed_tasks INTEGER NOT NULL,
                    pass_rate REAL NOT NULL,
                    avg_duration_ms REAL NOT NULL,
                    estimated_usd REAL NOT NULL,
                    report_json TEXT NOT NULL
                )
                """
            )

    def record(self, report: dict[str, Any]) -> None:
        import sqlite3
        with sqlite3.connect(str(self.db_path), timeout=10.0) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_runs
                (run_id, ts, suite, mode, model, total_tasks, passed_tasks,
                 pass_rate, avg_duration_ms, estimated_usd, report_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(report["run_id"]),
                    float(report["ts"]),
                    str(report["suite"]),
                    str(report["mode"]),
                    str(report["model"]),
                    int(report["total_tasks"]),
                    int(report["passed_tasks"]),
                    float(report["pass_rate"]),
                    float(report.get("avg_duration_ms", 0.0)),
                    float(report.get("estimated_usd", 0.0)),
                    json.dumps(report, ensure_ascii=False),
                ),
            )

    def recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        import sqlite3
        with sqlite3.connect(str(self.db_path), timeout=10.0) as conn:
            rows = conn.execute(
                """
                SELECT run_id, ts, suite, mode, model, total_tasks, passed_tasks,
                       pass_rate, avg_duration_ms, estimated_usd
                FROM eval_runs ORDER BY ts DESC LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [
            {
                "run_id": r[0],
                "ts": float(r[1]),
                "suite": r[2],
                "mode": r[3],
                "model": r[4],
                "total_tasks": int(r[5]),
                "passed_tasks": int(r[6]),
                "pass_rate": float(r[7]),
                "avg_duration_ms": float(r[8]),
                "estimated_usd": float(r[9]),
            }
            for r in rows
        ]


CODING_BENCH_TASKS: list[EvalTask] = [
    EvalTask(
        task_id="cb-01-off-by-one",
        title="Fix inclusive range off-by-one bug",
        category="bugfix",
        goal="Fix sum_inclusive(n) in calc.py so sum_inclusive(5) returns 15.",
        initial_files={
            "calc.py": "def sum_inclusive(n: int) -> int:\n    return sum(range(1, n))\n",
            "test_calc.py": "from calc import sum_inclusive\nassert sum_inclusive(5) == 15\nassert sum_inclusive(1) == 1\n",
        },
        test_command=[sys.executable, "test_calc.py"],
        oracle_files={
            "calc.py": "def sum_inclusive(n: int) -> int:\n    return sum(range(1, n + 1))\n",
        },
    ),
    EvalTask(
        task_id="cb-02-security-traversal",
        title="Block path traversal in file loader",
        category="security",
        goal="Harden safe_join(root, rel) in loader.py to raise ValueError on .. escapes.",
        initial_files={
            "loader.py": "from pathlib import Path\ndef safe_join(root: str, rel: str) -> Path:\n    return Path(root) / rel\n",
            "test_loader.py": (
                "from loader import safe_join\n"
                "assert safe_join('/tmp/base', 'a/b.txt').name == 'b.txt'\n"
                "try:\n    safe_join('/tmp/base', '../../etc/passwd')\n    raise AssertionError('must reject')\n"
                "except ValueError:\n    pass\n"
            ),
        },
        test_command=[sys.executable, "test_loader.py"],
        oracle_files={
            "loader.py": (
                "from pathlib import Path\n"
                "def safe_join(root: str, rel: str) -> Path:\n"
                "    base = Path(root).resolve()\n"
                "    cand = (base / rel).resolve()\n"
                "    if base != cand and base not in cand.parents:\n"
                "        raise ValueError('path traversal rejected')\n"
                "    return cand\n"
            ),
        },
    ),
    EvalTask(
        task_id="cb-03-refactor-cache",
        title="Deduplicate normalize_key helper across modules",
        category="refactor",
        goal="Ensure normalize_key strips whitespace and lowercases consistently.",
        initial_files={
            "keys.py": "def normalize_key(k: str) -> str:\n    return k.strip()\n",
            "test_keys.py": "from keys import normalize_key\nassert normalize_key('  AbC \\n') == 'abc'\n",
        },
        test_command=[sys.executable, "test_keys.py"],
        oracle_files={
            "keys.py": "def normalize_key(k: str) -> str:\n    return k.strip().lower()\n",
        },
    ),
    EvalTask(
        task_id="cb-04-syntax-heal",
        title="Repair broken Python syntax in router.py",
        category="diagnostics",
        goal="Fix the syntax error in router.py so route_path works.",
        initial_files={
            "router.py": "def route_path(p: str) -> str\n    return p.strip('/') or 'root'\n",
            "test_router.py": "from router import route_path\nassert route_path('/api/v1/') == 'api/v1'\nassert route_path('/') == 'root'\n",
        },
        test_command=[sys.executable, "test_router.py"],
        oracle_files={
            "router.py": "def route_path(p: str) -> str:\n    return p.strip('/') or 'root'\n",
        },
    ),
]


def run_coding_benchmark(
    *,
    mode: str = "offline",
    cfg: dict[str, Any] | None = None,
    persist_history: bool = True,
) -> dict[str, Any]:
    """Run V44 Coding Benchmark (offline oracle/harness verification OR live LLM)."""
    import uuid
    c = cfg if cfg is not None else load_config()
    eff_mode = "oracle" if mode in ("offline", "oracle") else "live"
    summary = run_eval_suite(mode=eff_mode, tasks=CODING_BENCH_TASKS, cfg=c, persist=False)
    model_label = "offline-oracle" if eff_mode == "oracle" else str(c.get("BAIZE_MODEL_NAME") or "live")
    store = EvalHistoryStore(cfg=c)
    prev = store.recent(limit=1)
    prev_rate = prev[0]["pass_rate"] if prev else None
    report = {
        "run_id": f"eval-{uuid.uuid4().hex[:8]}",
        "ts": round(time.time(), 3),
        "suite": "coding_v44",
        "mode": mode,
        "model": model_label,
        "total_tasks": summary.total_tasks,
        "passed_tasks": summary.passed_tasks,
        "pass_rate": summary.pass_rate,
        "regression_delta": round(summary.pass_rate - prev_rate, 4) if prev_rate is not None else 0.0,
        "regressed": bool(prev_rate is not None and summary.pass_rate < prev_rate),
        "avg_duration_ms": summary.avg_duration_ms,
        "estimated_usd": 0.0,
        "tasks": [
            {
                "task_id": r.task_id,
                "title": r.title,
                "category": r.category,
                "passed": r.passed,
                "duration_ms": r.duration_ms,
                "error": r.stopped_reason,
            }
            for r in summary.results
        ],
    }
    if persist_history:
        store.record(report)
    return report



# ===========================================================================
# V49.0.0 Zenith: Multi-File Cross-Module Engineering Benchmark
# ===========================================================================

MULTI_FILE_BENCH_TASKS: list[EvalTask] = [
    EvalTask(
        task_id="mf_auth_token_service",
        title="Fix cross-module HMAC token verification and expiry check",
        category="multi_file_security",
        goal="Fix token signing and expiration verification across auth/crypto.py and auth/service.py so tests/test_auth.py passes.",
        initial_files={
            "auth/__init__.py": "",
            "auth/crypto.py": (
                "import hashlib, hmac\n"
                "def sign_payload(payload: str, secret: str) -> str:\n"
                "    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()\n"
                "def verify_sig(payload: str, sig: str, secret: str) -> bool:\n"
                "    return sign_payload(payload, secret) != sig\n"
            ),
            "auth/service.py": (
                "from auth.crypto import sign_payload, verify_sig\n"
                "def issue_token(user: str, exp: int, secret: str) -> str:\n"
                "    body = f'{user}:{exp}'\n"
                "    return f'{body}.{sign_payload(body, secret)}'\n"
                "def authenticate(token: str, now: int, secret: str) -> str | None:\n"
                "    if '.' not in token: return None\n"
                "    body, sig = token.rsplit('.', 1)\n"
                "    if not verify_sig(body, sig, secret): return None\n"
                "    user, exp_s = body.split(':', 1)\n"
                "    if int(exp_s) > now: return None\n"
                "    return user\n"
            ),
            "tests/test_auth.py": (
                "import sys; sys.path.insert(0, '.')\n"
                "from auth.service import issue_token, authenticate\n"
                "tok = issue_token('alice', 2000, 'sec')\n"
                "assert authenticate(tok, 1500, 'sec') == 'alice'\n"
                "assert authenticate(tok, 2500, 'sec') is None\n"
                "assert authenticate(tok + 'x', 1500, 'sec') is None\n"
            ),
        },
        test_command=[sys.executable, "tests/test_auth.py"],
        oracle_files={
            "auth/crypto.py": (
                "import hashlib, hmac\n"
                "def sign_payload(payload: str, secret: str) -> str:\n"
                "    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()\n"
                "def verify_sig(payload: str, sig: str, secret: str) -> bool:\n"
                "    return hmac.compare_digest(sign_payload(payload, secret), sig)\n"
            ),
            "auth/service.py": (
                "from auth.crypto import sign_payload, verify_sig\n"
                "def issue_token(user: str, exp: int, secret: str) -> str:\n"
                "    body = f'{user}:{exp}'\n"
                "    return f'{body}.{sign_payload(body, secret)}'\n"
                "def authenticate(token: str, now: int, secret: str) -> str | None:\n"
                "    if '.' not in token: return None\n"
                "    body, sig = token.rsplit('.', 1)\n"
                "    if not verify_sig(body, sig, secret): return None\n"
                "    user, exp_s = body.split(':', 1)\n"
                "    if int(exp_s) <= now: return None\n"
                "    return user\n"
            ),
        },
    ),
    EvalTask(
        task_id="mf_pricing_discount_pipeline",
        title="Fix multi-module cart pricing, discount cap, and tax rounding",
        category="multi_file_domain",
        goal="Fix cart subtotal calculation in billing/pricing.py and discount capping in billing/discounts.py so tests/test_billing.py passes.",
        initial_files={
            "billing/__init__.py": "",
            "billing/discounts.py": (
                "def apply_coupon(cents: int, pct: int) -> int:\n"
                "    pct = min(max(pct, 0), 100)\n"
                "    return cents + (cents * pct) // 100\n"
            ),
            "billing/pricing.py": (
                "from billing.discounts import apply_coupon\n"
                "def checkout_total(items: list[tuple[int, int]], coupon_pct: int, tax_bps: int) -> int:\n"
                "    sub = sum(price for price, qty in items)\n"
                "    discounted = apply_coupon(sub, coupon_pct)\n"
                "    tax = (discounted * tax_bps + 5000) // 10000\n"
                "    return discounted + tax\n"
            ),
            "tests/test_billing.py": (
                "import sys; sys.path.insert(0, '.')\n"
                "from billing.pricing import checkout_total\n"
                "assert checkout_total([(1000, 2), (500, 1)], 10, 800) == 2430\n"
                "assert checkout_total([(1000, 1)], 150, 1000) == 0\n"
            ),
        },
        test_command=[sys.executable, "tests/test_billing.py"],
        oracle_files={
            "billing/discounts.py": (
                "def apply_coupon(cents: int, pct: int) -> int:\n"
                "    pct = min(max(pct, 0), 100)\n"
                "    return max(0, cents - (cents * pct) // 100)\n"
            ),
            "billing/pricing.py": (
                "from billing.discounts import apply_coupon\n"
                "def checkout_total(items: list[tuple[int, int]], coupon_pct: int, tax_bps: int) -> int:\n"
                "    sub = sum(price * qty for price, qty in items)\n"
                "    discounted = apply_coupon(sub, coupon_pct)\n"
                "    tax = (discounted * tax_bps + 5000) // 10000\n"
                "    return discounted + tax\n"
            ),
        },
    ),
    EvalTask(
        task_id="mf_cache_repository_invalidation",
        title="Fix cross-module cache invalidation on repository write",
        category="multi_file_state",
        goal="Fix cache invalidation between storage/cache.py and storage/repo.py so updated records are never served stale in tests/test_repo.py.",
        initial_files={
            "storage/__init__.py": "",
            "storage/cache.py": (
                "class SimpleCache:\n"
                "    def __init__(self): self._d = {}\n"
                "    def get(self, k): return self._d.get(k)\n"
                "    def set(self, k, v): self._d[k] = v\n"
                "    def delete(self, k): pass\n"
            ),
            "storage/repo.py": (
                "from storage.cache import SimpleCache\n"
                "class UserRepo:\n"
                "    def __init__(self):\n"
                "        self._db = {}\n"
                "        self._cache = SimpleCache()\n"
                "    def save(self, uid: str, name: str) -> None:\n"
                "        self._db[uid] = name\n"
                "    def get(self, uid: str) -> str | None:\n"
                "        hit = self._cache.get(uid)\n"
                "        if hit is not None: return hit\n"
                "        val = self._db.get(uid)\n"
                "        if val is not None: self._cache.set(uid, val)\n"
                "        return val\n"
            ),
            "tests/test_repo.py": (
                "import sys; sys.path.insert(0, '.')\n"
                "from storage.repo import UserRepo\n"
                "r = UserRepo()\n"
                "r.save('u1', 'Alice')\n"
                "assert r.get('u1') == 'Alice'\n"
                "r.save('u1', 'Alice-Updated')\n"
                "assert r.get('u1') == 'Alice-Updated'\n"
            ),
        },
        test_command=[sys.executable, "tests/test_repo.py"],
        oracle_files={
            "storage/cache.py": (
                "class SimpleCache:\n"
                "    def __init__(self): self._d = {}\n"
                "    def get(self, k): return self._d.get(k)\n"
                "    def set(self, k, v): self._d[k] = v\n"
                "    def delete(self, k): self._d.pop(k, None)\n"
            ),
            "storage/repo.py": (
                "from storage.cache import SimpleCache\n"
                "class UserRepo:\n"
                "    def __init__(self):\n"
                "        self._db = {}\n"
                "        self._cache = SimpleCache()\n"
                "    def save(self, uid: str, name: str) -> None:\n"
                "        self._db[uid] = name\n"
                "        self._cache.delete(uid)\n"
                "    def get(self, uid: str) -> str | None:\n"
                "        hit = self._cache.get(uid)\n"
                "        if hit is not None: return hit\n"
                "        val = self._db.get(uid)\n"
                "        if val is not None: self._cache.set(uid, val)\n"
                "        return val\n"
            ),
        },
    ),
]


def run_multi_file_benchmark(*, mode: str = "offline", cfg: dict[str, Any] | None = None, persist_history: bool = True) -> dict[str, Any]:
    """Run V49 Multi-File Cross-Module Engineering Benchmark (offline oracle or live LLM)."""
    import uuid
    c = cfg if cfg is not None else load_config()
    eff_mode = "oracle" if mode in ("offline", "oracle") else "live"
    summary = run_eval_suite(mode=eff_mode, tasks=MULTI_FILE_BENCH_TASKS, cfg=c, persist=False)
    model_label = "offline-oracle" if eff_mode == "oracle" else str(c.get("BAIZE_MODEL_NAME") or "live")
    store = EvalHistoryStore(cfg=c)
    report = {
        "run_id": f"eval-mf-{uuid.uuid4().hex[:8]}",
        "ts": round(time.time(), 3),
        "suite": "multi_file_v49",
        "mode": mode,
        "model": model_label,
        "total_tasks": summary.total_tasks,
        "passed_tasks": summary.passed_tasks,
        "pass_rate": summary.pass_rate,
        "avg_duration_ms": summary.avg_duration_ms,
        "tasks": [
            {"task_id": r.task_id, "title": r.title, "category": r.category, "passed": r.passed, "duration_ms": r.duration_ms, "error": r.stopped_reason}
            for r in summary.results
        ],
    }
    if persist_history:
        store.record(report)
    return report
