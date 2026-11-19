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


def _run_verify(root: Path, cmd: list[str], timeout: int = 30) -> tuple[bool, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        cmd, cwd=str(root), env=env, capture_output=True, text=True,
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
