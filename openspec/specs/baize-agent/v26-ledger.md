# V26-A2 运行账本（Run Ledger）规格说明

> **版本**：v1.0  
> **状态**：APPROVED  
> **对应升级计划工作包**：战役 A / A2 运行账本  
> **前置规格**：[v26-contract.md](v26-contract.md)（A1 契约）

---

## 1. 背景与目标

V25 已有 `persistence/sessions/` 记录模型交互原文，但缺少一条**任务级别的
append-only 运行账本**，导致：
- 中断后无法判断哪些任务已经 verified，哪些还未完成
- 工具调用结果、状态迁移、失败原因没有独立的可审计记录

A2 引入 `RunLedger`，写入 `persistence/runs/<run-id>.jsonl`，与 Session 并存
但职责不同（Session 记录模型对话，RunLedger 记录任务事件）。

---

## 2. 记录职责（升级计划 §3.1 第三类）

| 属性 | 规则 |
| --- | --- |
| 路径 | `persistence/runs/<run-id>.jsonl` |
| 格式 | append-only JSONL，每行一个事件 JSON |
| 能否改变 manifest 状态 | **否**，只能证明状态迁移 |
| 能否替代 manifest | **否** |
| 能否替代 Session | **否** |

---

## 3. 事件类型

所有事件共享基础字段：

```json
{
  "ts":         "ISO-8601（秒级）",
  "event":      "事件类型（见下）",
  "run_id":     "string",
  "task_id":    "string | null（适用时）",
  "payload":    {}
}
```

| `event` | 触发时机 | 必填 payload 字段 |
| --- | --- | --- |
| `plan_created` | Director 生成计划后 | `goal, task_count` |
| `task_started` | Executor 开始执行任务 | `task_id, role` |
| `task_claimed` | Executor claim 任务（防重复领取） | `task_id, role` |
| `tool_result` | 工具调用完成 | `task_id, tool, ok, summary` |
| `task_verified` | Verifier pass + all checks pass | `task_id, evidence, verdict` |
| `state_transition` | 任务状态变更 | `task_id, from_status, to_status` |
| `task_failed` | 任务失败（重试耗尽） | `task_id, issues, retries_used` |
| `skill_candidate` | verified task 后生成候选 | `task_id, candidate_description` |
| `run_completed` | 整个 run 完成 | `success, total_tasks, passed_tasks` |

---

## 4. 核心接口

```python
# baize/run_ledger.py — 只用 stdlib

class RunLedger:
    def __init__(self, run_id: str, cfg: dict | None = None): ...
        """初始化账本，写入目录 persistence/runs/（自动创建）。"""

    @property
    def path(self) -> Path: ...

    def append(self, event: str, payload: dict,
               task_id: str | None = None) -> None: ...
        """追加一条事件到 JSONL 文件（原子写入，不可回滚）。"""

    def events(self) -> list[dict]: ...
        """读取全部事件（用于 replay/report）。"""

    def replay(self) -> dict: ...
        """从账本重建当前运行状态。

        返回：
        {
          "run_id": str,
          "goal": str | None,
          "claimed_tasks": set[str],        # 已被 claim 的任务 id
          "verified_tasks": set[str],        # 已通过验证的任务 id
          "failed_tasks": set[str],          # 已失败的任务 id
          "in_progress_tasks": set[str],     # 进行中的任务 id
          "skill_candidates": list[dict],    # 技能候选列表
          "completed": bool,
        }
        """

    def current_unfinished(self) -> list[str]: ...
        """返回尚未 verified 或 failed 的任务 id 列表。"""

    def is_task_claimed(self, task_id: str) -> bool: ...
        """任务是否已被 claim（防重复领取）。"""

    def is_task_verified(self, task_id: str) -> bool: ...
        """任务是否已经过独立验证通过。"""


def get_ledger(run_id: str, cfg: dict | None = None) -> RunLedger: ...
    """工厂函数：返回指定 run_id 的 RunLedger 实例。"""

def list_runs(cfg: dict | None = None) -> list[str]: ...
    """列出 persistence/runs/ 下所有 run_id（按时间排序）。"""
```

---

## 5. 恢复语义

`replay()` 的状态重建规则：
- `task_claimed` → 加入 `claimed_tasks`
- `task_started` → 加入 `in_progress_tasks`
- `task_verified` → 加入 `verified_tasks`，从 `in_progress_tasks` 移除
- `task_failed` → 加入 `failed_tasks`，从 `in_progress_tasks` 移除
- 已在 `verified_tasks` 的任务：resume 时跳过，不重复执行
- `plan_created` 的 `goal` 字段 → `replay()["goal"]`

---

## 6. 约束

- **只追加**：账本文件只 append，不修改、不删除已有行
- **零依赖**：只用 `json`、`pathlib`、`time`（stdlib）
- **fail-closed**：损坏的 JSONL 行在 `replay()` 时跳过并记录 warning，不影响其余行
- **不重复 claim**：`is_task_claimed()` 返回 True 时拒绝再次 claim

---

## 7. 测试映射

| 规约 | 测试 |
| --- | --- |
| append 写入、events 读取 | `tests/test_run_ledger.py::test_append_and_read_events` |
| replay 重建 verified/failed 状态 | `tests/test_run_ledger.py::test_replay_state` |
| current_unfinished 返回正确列表 | `tests/test_run_ledger.py::test_current_unfinished` |
| is_task_claimed / is_task_verified | `tests/test_run_ledger.py::test_claim_and_verify_flags` |
| 损坏 JSONL 行跳过不崩溃 | `tests/test_run_ledger.py::test_corrupt_line_skipped` |
| list_runs 列出全部 run | `tests/test_run_ledger.py::test_list_runs` |
| resume 跳过已 verified 任务 | `tests/test_run_ledger.py::test_resume_skips_verified` |
