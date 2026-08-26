# V26-B2-B5 受控角色与验证闭环规格说明

> **版本**：v1.0  
> **状态**：APPROVED  
> **对应工作包**：战役 B / B2 原子执行、B3 验证执行器、B4 失败反馈、B5 安全策略  
> **前置规格**：[v26-contract.md](v26-contract.md), [v26-ledger.md](v26-ledger.md), [v26-role-policy.md](v26-role-policy.md)

---

## 1. 概述与目标

战役 B 建立真实的执行与核验闭环：
1. **B2 原子执行**：Executor 逐个原子任务领取执行，领取与开始写入账本，防越权与重复领取。
2. **B3 验证执行器**：优先执行机器门禁（checks）， checks 未过直接拒绝并跳过 LLM 取证；若任务声明了 evidence_paths，文件不存在或为空直接拒绝（NO FAKE DONE）。
3. **B4 失败反馈**：失败原因结构化回流重试；重试耗尽写入 `task_failed` 账本事件并标记状态，保留为项目事实。
4. **B5 安全策略**：RolePolicy allow_tools 与 workspace_scope 强制结合，越权工具与越界访问被阻断。

---

## 2. 行为规约

### 2.1 B2 原子执行与防重复领取
- 任务执行前检查：若任务已被 verified，跳过执行。
- 任务若指定 `allowed_roles` 且当前角色不在白名单内，拒绝领取（fail-closed）。
- 每次执行原子任务，依次在 RunLedger 写入 `task_claimed` 和 `task_started`。

### 2.2 B3 机器门禁优先（Machine Checks First & Evidence Guard）
- `verify_subtask` 首先运行 `checks`（`file_exists`, `file_contains`, `cmd_ok`）。
- 若任何 check 失败，直接返回 `verdict="fail"`，并将失败 detail 注入 `issues`，**不调用** Verifier LLM（节约成本且防止模型幻觉放行）。
- 若声明了 `evidence_paths`，验证所有路径在 workspace 中存在且大小 > 0；否则判为 `fail`（NO FAKE DONE）。
- 只有所有 checks 及 evidence 校验通过，才调用 Verifier LLM 作独立语义审核。

### 2.3 B4 结构化失败与重试回流
- 当验证失败且重试次数未用尽时，构造包含具体失败 check 及 issues 的 fix prompt。
- 重试次数达到 `max_retries` 仍未通过时：
  - 在 RunLedger 中记录 `task_failed`（包含 `issues` 和 `retries_used`）。
  - 任务停止，不伪造成功，项目留在明确可解释的失败状态。

### 2.4 B5 安全与工作区边界
- Role 声明 `workspace_scope` 时，Agent 在执行文件相关操作及 prompt 中受该范围约束。
- Role 声明 `allow_tools` 时，Agent 无法调用白名单之外的工具。

---

## 3. 测试映射

| 规约 | 测试 |
| --- | --- |
| B2 任务已 verified 时跳过执行 | `tests/test_v26_controlled_loop.py::test_b2_skip_already_verified` |
| B2 不在 allowed_roles 时拒绝执行 | `tests/test_v26_controlled_loop.py::test_b2_role_not_allowed_rejected` |
| B3 机器 checks 失败直接拒判不调 LLM | `tests/test_v26_controlled_loop.py::test_b3_machine_checks_fail_blocks_verifier` |
| B3 evidence_paths 文件不存在/空时拒判 | `tests/test_v26_controlled_loop.py::test_b3_missing_evidence_paths_rejected` |
| B4 重试注入结构化 issues 并在耗尽后记录 task_failed | `tests/test_v26_controlled_loop.py::test_b4_retry_feedback_and_exhaustion` |
| B5 allow_tools 阻断未授权工具调用 | `tests/test_v26_controlled_loop.py::test_b5_unauthorized_tool_blocked` |
