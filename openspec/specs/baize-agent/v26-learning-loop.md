# V26-C1-C5 学习闭环与知识质量规格说明

> **版本**：v1.0  
> **状态**：APPROVED  
> **对应工作包**：战役 C / C1 记忆分层、C2 收尾器、C3 Skill 审核、C4 复用反馈、C5 质量门  
> **前置规格**：[v26-contract.md](v26-contract.md), [v26-ledger.md](v26-ledger.md), [v26-controlled-roles.md](v26-controlled-roles.md)

---

## 1. 概述与目标

战役 C 建立真实的自进化与知识沉淀闭环：
1. **C1 记忆分层**：区分事实 (`fact`)、决策 (`decision`)、假设 (`assumption`)、教训 (`lesson`)，记录 `run_id`、`task_id`、`evidence` 来源链。
2. **C2 收尾器**：verified task 生成 skill candidate 或结构化记忆，必须携带已通过验证的 evidence 来源。
3. **C3 Skill 审核**：`verify_skill_draft` 审核新技能草案，要求具备来源 (source run/task)、依赖、边界、验证命令，无 evidence 拒绝入库。
4. **C4 复用反馈**：`record_usage` 记录 skill 执行成败与原因，提供有效性评分；audit_index 汇报真实有效性。
5. **C5 质量门完整性**：gate 增加闭环完整性检测 (`check_loop_integrity`)，检查 run ledger 与 manifest 的事实一致性。

---

## 2. 行为规约

### 2.1 C1 记忆分层与来源追溯
- `log_event(text, tags, category="fact", run_id=None, task_id=None, evidence=None, cfg=None)`
- `category` 允许值：`fact` | `decision` | `assumption` | `lesson`（其他值 fail-closed 归为 `fact`）。
- `recall(query, cfg, limit, tags, category=None)` 支持按分类筛选，返回命中项保留 `category`、`run_id`、`task_id`、`evidence` 溯源字段。

### 2.2 C2 收尾器与候选产生
- 仅在任务通过所有 checks 及 verifier 后（`task_verified`），才在 RunLedger 中记录 `skill_candidate` 事件。
- 候选必须包含 `task_id` 及验证 evidence 路径。

### 2.3 C3 技能入库审核
- `verify_skill_draft(draft: dict) -> tuple[bool, str]`
- 必填字段：`name`, `description`, `source_run`, `source_task`, `evidence`, `verification_cmd`。
- 若缺少任一来源证据或命令，返回 `(False, "reason")`，禁止入库。

### 2.4 C4 复用反馈与降权
- `record_usage(skill_name: str, success: bool, reason: str = "", cfg=None) -> None`
- 写入 `persistence/skill_feedback.jsonl`。
- `skill_stats(cfg=None) -> dict` 计算每个技能的调用量与成功率。

### 2.5 C5 质量门完整性检查 (Loop Integrity)
- `check_loop_integrity(manifest_path="baize.manifest.json", cfg=None) -> dict`
- 检查项：
  1. `manifest` 中的 `done` phase 若引用了 run_id / contract，对应 ledger 必须存在且有 `run_completed` 或 `task_verified` 记录。
  2. 账本中存在未解释的 `task_failed` 时给出 WARNING 或 FAIL。
- 集成进 `check_quality` 和 `run_gate`。

---

## 3. 测试映射

| 规约 | 测试 |
| --- | --- |
| C1 log_event/recall 记忆分层与来源追溯 | `tests/test_v26_learning_loop.py::test_c1_memory_layered_lineage` |
| C2 verified task 产出带 evidence 的候选 | `tests/test_v26_learning_loop.py::test_c2_skill_candidate_requires_evidence` |
| C3 verify_skill_draft 拦截无 evidence 草案 | `tests/test_v26_learning_loop.py::test_c3_verify_skill_draft_rejects_missing_evidence` |
| C4 record_usage 记录反馈并计算有效性 | `tests/test_v26_learning_loop.py::test_c4_skill_feedback_and_stats` |
| C5 gate 闭环完整性检查通过/拦截 | `tests/test_v26_learning_loop.py::test_c5_gate_loop_integrity` |
