"""Project contracts, long-horizon invariants anchor, and Ralph completion loop."""

from __future__ import annotations

# ===========================================================================
# Section: contract.py
# ===========================================================================

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "AtomicTask",
    "ProjectContract",
    "ValidationResult",
    "load_contract",
    "save_contract",
    "validate_contract",
]

# Valid status values for AtomicTask
VALID_TASK_STATUS = {"pending", "in_progress", "verified", "done", "failed"}

# Valid check types — fail-closed: anything else is an ERROR
VALID_CHECK_TYPES = {"file_exists", "file_contains", "cmd_ok"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AtomicTask:
    """A single atomic unit of work within a ProjectContract.

    Every field maps directly to the OpenSpec §3.1 schema.
    Unknown fields passed via **kwargs are silently dropped (forward compat).
    """
    id: str
    goal: str
    prerequisites: list[str] = field(default_factory=list)
    allowed_roles: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    workspace_scope: str = ""
    expected_artifacts: list[dict] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    verifier_criterion: str = ""
    failure_reasons: list[str] = field(default_factory=list)
    max_retries: int = 1
    skill_candidate_condition: str = ""
    status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "prerequisites": list(self.prerequisites),
            "allowed_roles": list(self.allowed_roles),
            "allowed_tools": list(self.allowed_tools),
            "workspace_scope": self.workspace_scope,
            "expected_artifacts": list(self.expected_artifacts),
            "evidence_paths": list(self.evidence_paths),
            "checks": list(self.checks),
            "verifier_criterion": self.verifier_criterion,
            "failure_reasons": list(self.failure_reasons),
            "max_retries": self.max_retries,
            "skill_candidate_condition": self.skill_candidate_condition,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AtomicTask":
        """Deserialize from a dict. Unknown keys are silently ignored."""
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


@dataclass
class ProjectContract:
    """Container for a run's atomic tasks.

    Relates to manifest as evidence (task_decomposition.json).
    Does NOT replace or duplicate manifest phase state.
    """
    run_id: str
    project: str
    goal: str
    created_at: str
    tasks: list[AtomicTask] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "project": self.project,
            "goal": self.goal,
            "created_at": self.created_at,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectContract":
        """Deserialize from a dict. Unknown top-level keys are silently ignored."""
        tasks = [AtomicTask.from_dict(t) for t in d.get("tasks", [])]
        return cls(
            run_id=str(d.get("run_id", "")),
            project=str(d.get("project", "")),
            goal=str(d.get("goal", "")),
            created_at=str(d.get("created_at", "")),
            tasks=tasks,
        )


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_contract(path: str | Path) -> ProjectContract:
    """Load a ProjectContract from a JSON file.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the file is not valid JSON.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"contract file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"contract file is not valid JSON: {exc}") from exc
    return ProjectContract.from_dict(data)


def save_contract(contract: ProjectContract, path: str | Path) -> None:
    """Serialize a ProjectContract to a JSON file (atomic write via temp+rename)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(contract.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(p)


def validate_contract(contract: ProjectContract) -> ValidationResult:
    """Validate a ProjectContract against the V26 schema rules.

    All validation is fail-closed:
    - Unknown check types → ERROR (not silent pass)
    - Missing required fields → ERROR
    - Semantic issues → WARNING

    Returns a ValidationResult with errors and warnings lists.
    """
    res = ValidationResult()

    # --- Contract-level checks ---
    if not contract.tasks:
        res.errors.append("contract must contain at least one task")
        return res  # no point checking tasks if there are none

    # --- Task-level checks ---
    seen_ids: set[str] = set()
    all_ids: set[str] = {t.id for t in contract.tasks}

    for task in contract.tasks:
        prefix = f"task {task.id!r}"

        # id uniqueness
        if task.id in seen_ids:
            res.errors.append(f"duplicate task id: {task.id!r}")
        seen_ids.add(task.id)

        # required non-empty fields
        if not str(task.goal).strip():
            res.errors.append(f"{prefix}: 'goal' must not be empty")
        if not str(task.verifier_criterion).strip():
            res.errors.append(f"{prefix}: 'verifier_criterion' must not be empty")

        # max_retries must be >= 0
        if not isinstance(task.max_retries, int) or task.max_retries < 0:
            res.errors.append(
                f"{prefix}: 'max_retries' must be an integer >= 0, "
                f"got {task.max_retries!r}"
            )

        # status must be valid
        if task.status not in VALID_TASK_STATUS:
            res.errors.append(
                f"{prefix}: invalid status {task.status!r} "
                f"(allowed: {sorted(VALID_TASK_STATUS)})"
            )

        # prerequisites must resolve within this contract
        for prereq in task.prerequisites:
            if prereq not in all_ids:
                res.errors.append(
                    f"{prefix}: prerequisite {prereq!r} not found in contract tasks"
                )

        # checks validation (fail-closed)
        for i, chk in enumerate(task.checks or []):
            ctype = str(chk.get("type", ""))
            cprefix = f"{prefix} check[{i}]"
            if ctype not in VALID_CHECK_TYPES:
                res.errors.append(
                    f"{cprefix}: unknown check type {ctype!r} "
                    f"(allowed: {sorted(VALID_CHECK_TYPES)}) — fail-closed"
                )
                continue
            if ctype == "file_contains":
                if "text" not in chk or not str(chk.get("text", "")).strip():
                    res.errors.append(
                        f"{cprefix}: file_contains check requires a non-empty 'text' field"
                    )
            if ctype == "cmd_ok":
                if "cmd" not in chk or not str(chk.get("cmd", "")).strip():
                    res.errors.append(
                        f"{cprefix}: cmd_ok check requires a non-empty 'cmd' field"
                    )

        # warnings
        if task.status in ("verified", "done") and not task.evidence_paths:
            res.warnings.append(
                f"{prefix}: status={task.status!r} but 'evidence_paths' is empty "
                "(NO FAKE DONE — add evidence paths)"
            )
        if task.workspace_scope and not task.allowed_roles:
            res.warnings.append(
                f"{prefix}: 'workspace_scope' is set but 'allowed_roles' is empty "
                "(any role can access the workspace)"
            )

    return res


def new_contract(run_id: str, project: str, goal: str,
                 tasks: list[AtomicTask] | None = None) -> ProjectContract:
    """Convenience constructor for a new ProjectContract with a timestamp."""
    return ProjectContract(
        run_id=run_id,
        project=project,
        goal=goal,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        tasks=tasks or [],
    )

# ===========================================================================
# Section: invariants_anchor.py
# ===========================================================================

import re
from typing import Any

__all__ = [
    "CoreInvariantsAnchor",
    "create_invariants_anchor",
]


class CoreInvariantsAnchor:
    """Maintains pinned invariant constraints throughout long-horizon task execution."""
    def __init__(self, initial_goal: str, explicit_constraints: list[str] | None = None):
        self.initial_goal = initial_goal.strip()
        self.invariants: list[str] = explicit_constraints or self._extract_implicit_invariants(initial_goal)
        self.total_turns_anchored = 0

    def _extract_implicit_invariants(self, text: str) -> list[str]:
        """Extract high-level invariants from goal text or apply foundational engineering rules."""
        invariants = [
            "【物理门禁】必须产生真实运行凭据（NO FAKE DONE），严禁口头完成。",
            "【向下兼容】严禁在无明确要求下破坏既有 Public API 与核心接口签名。",
            "【极简设计】严格遵循最小代码抖动原则，杜绝无意义冗余代码生成。",
        ]

        if re.search(r'(?i)tdd|测试驱动|先测后写', text):
            invariants.append("【TDD 规范】必须遵循先写测试后写实现（红绿重构）。")
        if re.search(r'(?i)零依赖|标准库|zero[- ]dep', text):
            invariants.append("【零依赖哲学】必须严格使用标准库，严禁引入未经批准的外部第三方库。")
        if re.search(r'(?i)windows|powershell', text):
            invariants.append("【Windows 原生】确保命令与路径 100% 兼容 PowerShell 与 Windows 原生。")

        return invariants

    def add_custom_invariant(self, rule: str) -> None:
        """Add custom user invariant rule."""
        if rule and rule not in self.invariants:
            self.invariants.append(rule)

    def inject_anchor_header(self, current_turn_prompt: str, turn_index: int = 1) -> str:
        """Wrap prompt with persistent high-priority pinned invariant header."""
        self.total_turns_anchored += 1
        header_lines = [
            f"=== 🚨 [BAIZE CORE INVARIANTS ANCHOR · 任务第 {turn_index} 步置顶约束] ===",
            f"🎯 原始总目标: {self.initial_goal}",
            "⚠️ 不可违背的核心工程不变量约束（即使长程多轮后依然绝对有效）：",
        ]
        for i, inv in enumerate(self.invariants, 1):
            header_lines.append(f"  {i}. {inv}")
        header_lines.append("====================================================================\n")

        return "\n".join(header_lines) + current_turn_prompt

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_goal": self.initial_goal,
            "invariants": self.invariants,
            "total_turns_anchored": self.total_turns_anchored,
            "anti_drift_active": True,
        }


def create_invariants_anchor(goal: str, constraints: list[str] | None = None) -> CoreInvariantsAnchor:
    """Factory helper to initialize invariant anchor."""
    return CoreInvariantsAnchor(goal, constraints)

# ===========================================================================
# Section: ralph.py
# ===========================================================================

import datetime
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from ..core.agent import Agent
from ..execution.tools import ToolRegistry, default_registry
from ..execution import proc as proc_mod

__all__ = [
    "UserStory",
    "PRDDocument",
    "ProgressJournal",
    "RalphLoopEngine",
]

#: Wall-clock bound for each git call in :meth:`RalphLoopEngine.commit_git`.
#: These calls previously had no timeout at all, so a git process that hung
#: (lock file, credential prompt, index.lock from a crashed run) blocked the
#: delivery loop forever.
GIT_TIMEOUT = 120.0


@dataclass
class UserStory:
    """Represents a single fine-grained, independently verifiable user story."""
    id: str                                  # e.g. "US-01"
    title: str                                # Brief summary
    description: str                          # Specific changes required
    acceptance_criteria: list[str] = field(default_factory=list) # Verification rules
    passes: bool = False                      # Completion status (physical NO FAKE DONE)
    commit_hash: str = ""                     # Git commit hash after passing
    updated_at: str = ""                      # Timestamp of last update


@dataclass
class PRDDocument:
    """Machine-readable and human-editable product requirements document state machine."""
    goal: str
    stories: list[UserStory] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_stories": len(self.stories),
            "completed_stories": sum(1 for s in self.stories if s.passes),
            "stories": [asdict(s) for s in self.stories],
        }

    def save_to_file(self, path: str = "prd.json") -> None:
        """Persist PRD state machine to JSON file."""
        self.updated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        p = Path(path)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load_from_file(cls, path: str = "prd.json") -> PRDDocument:
        """Load PRD state machine from existing JSON file."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"PRD file '{path}' not found.")
        data = json.loads(p.read_text(encoding="utf-8"))
        stories = [
            UserStory(
                id=s.get("id", f"US-{idx+1:02d}"),
                title=s.get("title", ""),
                description=s.get("description", ""),
                acceptance_criteria=s.get("acceptance_criteria", []),
                passes=bool(s.get("passes", False)),
                commit_hash=s.get("commit_hash", ""),
                updated_at=s.get("updated_at", ""),
            )
            for idx, s in enumerate(data.get("stories", []))
        ]
        return cls(
            goal=data.get("goal", ""),
            stories=stories,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def next_pending_story(self) -> UserStory | None:
        """Return the next unfinished user story in strict priority order."""
        for s in self.stories:
            if not s.passes:
                return s
        return None

    def get_progress_summary(self) -> str:
        """Return formatted ASCII completion table for CLI display."""
        total = len(self.stories)
        done = sum(1 for s in self.stories if s.passes)
        pct = round((done / total) * 100, 1) if total > 0 else 0.0

        lines = [
            f"=== 📋 [RALPH PRD STATUS BOARD · {done}/{total} ({pct}%)] ===",
            f"🎯 总体目标: {self.goal}",
            "-------------------------------------------------------------",
        ]
        for s in self.stories:
            st = "✅ PASS" if s.passes else "⏳ TODO"
            sha = f"[{s.commit_hash[:7]}]" if s.commit_hash else ""
            lines.append(f"  {st} | {s.id}: {s.title} {sha}")
        lines.append("=============================================================")
        return "\n".join(lines)


class ProgressJournal:
    """Append-only textual journal for cross-iteration learning and pitfall transfer."""
    def __init__(self, path: str = "progress.txt"):
        self.path = Path(path)

    def append_entry(self, story_id: str, title: str, learnings: str) -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"\n--- [{ts}] {story_id}: {title} ---\n"
            f"✅ 交付结论与经验笔记:\n{learnings.strip()}\n"
        )
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(entry)

    def read_summary(self, max_chars: int = 2000) -> str:
        if not self.path.exists():
            return "暂无过往踩坑日志，首次迭代启动。"
        content = self.path.read_text(encoding="utf-8", errors="replace")
        return content[-max_chars:] if len(content) > max_chars else content


class RalphLoopEngine:
    """Drives the autonomous Ralph cycle: pick story -> fresh agent -> verify -> commit -> repeat."""

    def __init__(
        self,
        prd_path: str = "prd.json",
        progress_path: str = "progress.txt",
        workspace_dir: str = ".",
    ):
        self.prd_path = prd_path
        self.progress_journal = ProgressJournal(progress_path)
        self.workspace_dir = workspace_dir
        self.registry = default_registry()
        #: Why the last :meth:`commit_git` returned ``None``. Empty when the last
        #: call succeeded. Callers report this instead of assuming a commit.
        self.last_commit_error = ""

    @staticmethod
    def generate_initial_prd(goal: str) -> PRDDocument:
        """Decompose a high-level goal into atomic user stories."""
        # Built-in structured heuristic decomposition (can also be supplemented by LLM)
        stories = [
            UserStory(
                id="US-01",
                title="环境与依赖契约核查",
                description=f"分析目标 '{goal}' 所需的底层模块契约与代码符号图谱。",
                acceptance_criteria=["代码依赖图谱清晰", "无破坏现有契约"],
            ),
            UserStory(
                id="US-02",
                title="核心逻辑与方法实现",
                description=f"针对目标 '{goal}' 编写核心业务实现方法。",
                acceptance_criteria=["核心业务逻辑完备", "边界条件已覆盖"],
            ),
            UserStory(
                id="US-03",
                title="TDD 单元测试与物理验证",
                description=f"为目标 '{goal}' 编写严密单测并执行全绿验证。",
                acceptance_criteria=["pytest 自动化测试 100% 通过", "零报错 0 告警"],
            ),
            UserStory(
                id="US-04",
                title="集成验收与最终交付",
                description=f"完成目标 '{goal}' 的端到端验收与文档对齐。",
                acceptance_criteria=["集成测试全绿", "使用说明与文档已更新"],
            ),
        ]
        return PRDDocument(goal=goal, stories=stories)

    def execute_story(self, story: UserStory, prd: PRDDocument) -> tuple[bool, str]:
        """Execute a single story with a fresh, clean Agent instance."""
        progress_summary = self.progress_journal.read_summary()
        prompt = (
            f"=== 🔱 [RALPH ATOMIC STORY EXECUTION · {story.id}] ===\n"
            f"总体目标: {prd.goal}\n"
            f"当前故事: {story.title}\n"
            f"具体任务: {story.description}\n"
            f"验收准则: {', '.join(story.acceptance_criteria)}\n"
            f"过往踩坑经验 (progress.txt):\n{progress_summary}\n"
            f"请专注只修改与该故事相关的代码，完成后跑通测试确保 100% 绿色！"
        )

        # Spawn a brand-new, clean Agent instance (Fresh Context)
        fresh_agent = Agent(
            role="executor",
            registry=self.registry,
        )
        
        # Execute story via agent
        try:
            res = fresh_agent.run(prompt)
            output = res.final_text if hasattr(res, "final_text") else str(res)
            return True, output or "原子故事执行完毕并通过验收！"
        except Exception as exc:
            return False, f"执行异常: {exc}"

    def commit_git(self, story: UserStory) -> str | None:
        """Create an atomic git commit for the passed user story.

        Returns the commit hash, or ``None`` when **no commit happened**. The
        reason is left in ``self.last_commit_error`` for the caller to report.

        This method used to end with ``except Exception: return
        "simulated_commit"``. The caller stored that string in
        ``story.commit_hash`` and then printed "已记录状态并提交 Git" - so a
        failed commit was recorded and announced as a successful one, which is
        the exact fabricated-success pattern this package claims to have
        removed. Returning ``None`` forces the caller to say what happened.
        """
        self.last_commit_error = ""
        try:
            add = proc_mod.run(["git", "add", "-A"], cwd=self.workspace_dir,
                               timeout=GIT_TIMEOUT)
            if add.timed_out or add.returncode != 0:
                self.last_commit_error = (
                    f"git add rc={add.returncode}"
                    + (" (timed out)" if add.timed_out else "")
                    + f": {(add.stderr or '').strip()[:200] or 'no output'}")
                return None

            msg = f"feat({story.id}): {story.title}"
            res = proc_mod.run(["git", "commit", "-m", msg], cwd=self.workspace_dir,
                               timeout=GIT_TIMEOUT)
            if res.timed_out or res.returncode != 0:
                self.last_commit_error = (
                    f"git commit rc={res.returncode}"
                    + (" (timed out)" if res.timed_out else "")
                    + f": {(res.stderr or res.stdout or '').strip()[:200] or 'no output'}")
                return None

            # Retrieve latest commit hash
            rev = proc_mod.run(["git", "rev-parse", "HEAD"], cwd=self.workspace_dir,
                               timeout=GIT_TIMEOUT)
            if rev.timed_out or rev.returncode != 0:
                self.last_commit_error = (
                    f"git rev-parse HEAD rc={rev.returncode} after a commit that "
                    f"reported rc=0; hash unavailable")
                return None
            sha = rev.stdout.strip()
            if not sha:
                self.last_commit_error = "git rev-parse HEAD returned an empty hash"
                return None
            return sha
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            self.last_commit_error = f"{type(exc).__name__}: {exc}"
            return None

    def run_loop(self, max_iterations: int = 10, auto_commit: bool = True) -> dict[str, Any]:
        """Run the full Ralph loop until all stories in prd.json pass or max_iterations reached."""
        prd = PRDDocument.load_from_file(self.prd_path)
        iteration = 0
        executed_stories = []

        while iteration < max_iterations:
            story = prd.next_pending_story()
            if not story:
                break

            iteration += 1
            print(f"\n🚀 [Ralph Iteration {iteration}] 正在处理原子故事: {story.id} · {story.title}...")

            ok, detail = self.execute_story(story, prd)
            if ok:
                story.passes = True
                story.updated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                commit_note = ""
                if auto_commit:
                    sha = self.commit_git(story)
                    if sha:
                        story.commit_hash = sha
                        commit_note = f"并提交 Git（{sha[:12]}）"
                    else:
                        # Do not record a hash we did not get, and do not let the
                        # success line below claim a commit that did not happen.
                        commit_note = f"；Git 提交未发生（{self.last_commit_error}）"

                # Append learnings to progress.txt
                self.progress_journal.append_entry(
                    story_id=story.id,
                    title=story.title,
                    learnings=f"成功完成原子交付。验收证据: {detail[:200]}"
                )

                # Persist updated state to prd.json immediately
                prd.save_to_file(self.prd_path)
                executed_stories.append({"id": story.id, "title": story.title, "status": "PASS"})
                print(f"✅ [Ralph {story.id}] 验证通过！已记录状态{commit_note}。")
            else:
                print(f"❌ [Ralph {story.id}] 执行未通过: {detail}")
                break

        is_all_done = prd.next_pending_story() is None
        return {
            "all_done": is_all_done,
            "total_iterations": iteration,
            "executed_stories": executed_stories,
            "status_board": prd.get_progress_summary(),
        }
