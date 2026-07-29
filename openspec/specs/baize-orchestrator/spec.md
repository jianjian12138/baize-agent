# baize-orchestrator 规格说明

## 概述

多 Agent 编排器：Director 规划 → Executor 执行 → Verifier 独立核验。
「NO FAKE DONE」从文档口号变为可执行门禁——执行者的完成声明必须经独立验证
Agent 判为 pass 才算数，fail 时自动携带 issues 重试。

## 接口

- `Orchestrator(cfg, client, registry, on_event, max_retries_per_task=1)`
- `Orchestrator.plan(goal) -> (plan, session_id)`：
  plan 为 `[{"id", "task", "verify"}, ...]`（1–6 个子任务）。
- `Orchestrator.run(goal) -> OrchestratorResult`
  （`success / plan / reports / session_ids`；report 含
  `task_id / task / verdict / evidence / issues / retried`）。
- `_extract_json(text) -> dict | None`：容忍 markdown 代码围栏。
- CLI：`baize team "<goal>"`。

## 行为规约

1. Director 输出无法解析为 JSON 计划时，降级为单任务计划（goal 本身 + manual review），不中断。
2. 每个子任务派生独立的 Executor 会话执行，再派生独立的 Verifier 会话核验——
   Verifier 不信任 Executor 的自述，须自行读文件/跑命令取证。
3. Verifier 输出 `{"verdict": "pass"|"fail", "evidence", "issues"}`；
   fail 时将 issues 反馈给 Executor 重试，最多 `max_retries_per_task` 次。
4. 重试耗尽仍 fail 的任务标记失败，整体 `success=False`。
5. 全部任务 pass 时 `success=True`；编排结果（含成败）写入持久记忆。
6. 每个 Agent 会话独立持久化，`session_ids` 可回溯审计每一步。

## 边界与异常

- Verifier 输出非法 JSON 时按 fail 处理（保守判定，不放水）。
- 计划为空时直接成功返回空报告。

## 测试映射

| 规约 | 测试 |
|------|------|
| 1 | `tests/test_orchestrator.py::test_plan_fallback_when_director_rambles` |
| 2, 5 | `tests/test_orchestrator.py::test_full_run_all_pass` |
| 3 | `tests/test_orchestrator.py::test_failed_verification_triggers_retry_then_pass` |
| 4 | `tests/test_orchestrator.py::test_retry_exhausted_marks_failure` |
| JSON 提取 | `tests/test_orchestrator.py::test_extract_json_variants` |
| CLI | `tests/test_cli.py::test_cli_team_scripted_success` |
