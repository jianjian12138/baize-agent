# V26-A1 原子任务契约（ProjectContract）规格说明

> **版本**：v1.0  
> **状态**：APPROVED（实施前置规格）  
> **对应升级计划工作包**：战役 A / A1 契约  
> **前置规格**：[spec.md](spec.md)（baize-agent 基础规格）

---

## 1. 背景与目标

V25 的 orchestrator 以 JSON plan 驱动任务，但每个任务的边界、权限、预期产物和
验证标准靠协议文本和模型自觉衔接，缺乏机器可执行的契约。A1 引入轻量
`ProjectContract`，将这些隐性约定编译为可校验的 JSON schema，不取代 manifest，
不新建第二套项目状态系统。

---

## 2. 记录职责

契约文件（`task_decomposition.json`）是 §3.1 四类记录中的**第二类**：
- 只作为 manifest evidence（P4 的原子任务 evidence 路径指向它）
- **不能**改变 manifest phase 状态（只有 manifest 本身可以）
- **不取代** `persistence/runs/<run-id>.jsonl` 账本

---

## 3. 数据模型

### 3.1 AtomicTask

```json
{
  "id": "string（在同一 contract 内唯一，建议格式 T-01）",
  "goal": "string（非空，明确可验证的单一目标）",
  "prerequisites": ["T-01", "...（前置任务 id 列表，可为空）"],
  "allowed_roles": ["executor", "...（允许执行此任务的角色名，空=不限）"],
  "allowed_tools": ["bash", "read_file", "...（允许使用的工具名，空=不限）"],
  "workspace_scope": "string（允许读写的路径前缀，空=不限，如 'src/'）",
  "expected_artifacts": [
    {
      "description": "string",
      "path": "string（相对于 workspace root）"
    }
  ],
  "evidence_paths": ["string（相对路径，验收后必须存在且非空的文件）"],
  "checks": [
    {
      "type": "file_exists | file_contains | cmd_ok",
      "path": "string（file_exists/file_contains 时必填）",
      "text": "string（file_contains 时必填）",
      "cmd":  "string（cmd_ok 时必填）",
      "description": "string（人工审查说明，可选）"
    }
  ],
  "verifier_criterion": "string（Verifier LLM 判断依据，非空）",
  "failure_reasons": ["string（已知失败原因，供重试时注入）"],
  "max_retries": "integer（>= 0，默认 1）",
  "skill_candidate_condition": "string（何种情况下生成 skill candidate，可为空）",
  "status": "pending | in_progress | verified | done | failed"
}
```

### 3.2 ProjectContract

```json
{
  "run_id": "string（关联 persistence/runs/<run-id>.jsonl）",
  "project": "string（项目名，与 manifest.project 一致）",
  "goal": "string（整体目标）",
  "created_at": "ISO-8601 时间戳",
  "tasks": ["AtomicTask 对象列表，至少 1 个"]
}
```

---

## 4. 状态迁移规则

```
pending → in_progress   （Executor claim 任务时）
in_progress → verified  （所有 checks 通过 + Verifier LLM pass）
verified → done         （写回 manifest；verified 只存在于运行账本）
in_progress → failed    （重试耗尽）
```

**约束**：
- `verified` 状态只在 `persistence/runs/<run-id>.jsonl` 中出现（作为 `state_transition` 事件）
- 写回 manifest 时用 `done`，不在 manifest 中引入 `verified` 状态
- 未经独立 Verifier evidence 不得迁移到 `verified`

---

## 5. 校验规则（validate_contract）

| 规则 | 错误级别 |
| --- | --- |
| `tasks` 不得为空 | ERROR |
| 每个 `AtomicTask.id` 在 contract 内唯一 | ERROR |
| `goal`、`verifier_criterion` 不得为空字符串 | ERROR |
| `max_retries` 必须为 >= 0 的整数 | ERROR |
| `checks[].type` 必须为 `file_exists | file_contains | cmd_ok` | ERROR |
| `checks` 为 `file_contains` 时必须有 `text` 字段 | ERROR |
| `checks` 为 `cmd_ok` 时必须有 `cmd` 字段 | ERROR |
| `prerequisites` 中的 id 必须能在同一 contract 内找到 | ERROR |
| `status` 必须为合法值 | ERROR |
| `evidence_paths` 为空但 `status=verified/done` | WARNING |
| `allowed_roles` 为空（不限角色）但 `workspace_scope` 非空 | WARNING |

未知字段：静默忽略（向前兼容）。

---

## 6. 公共接口

```python
# baize/contract.py — 只用 stdlib

def load_contract(path: str | Path) -> ProjectContract: ...
    """从 JSON 文件加载契约。文件不存在或 JSON 非法时抛 FileNotFoundError / ValueError。"""

def save_contract(contract: ProjectContract, path: str | Path) -> None: ...
    """序列化并原子写入 JSON 文件。"""

def validate_contract(contract: ProjectContract) -> ValidationResult: ...
    """返回 (errors: list[str], warnings: list[str])。errors 非空表示契约无效。"""

@dataclass
class AtomicTask: ...      # 见 §3.1 字段
@dataclass
class ProjectContract: ... # 见 §3.2 字段
@dataclass
class ValidationResult:
    errors: list[str]
    warnings: list[str]
    @property
    def ok(self) -> bool: ...
```

---

## 7. 边界与约束

- **零依赖**：`baize/contract.py` 只使用 `json`、`dataclasses`、`pathlib`（stdlib）
- **不取代 manifest**：contract 是 manifest 的 evidence，不是第二个状态源
- **fail-closed**：未知 check type 校验为 ERROR，不静默通过
- **向前兼容**：未知字段静默忽略，允许未来增加字段

---

## 8. 测试映射

| 规约 | 测试 |
| --- | --- |
| 有效 schema 加载/序列化 | `tests/test_contract.py::test_valid_contract_roundtrip` |
| 缺少必填字段 → ERROR | `tests/test_contract.py::test_invalid_missing_goal` |
| task id 重复 → ERROR | `tests/test_contract.py::test_duplicate_task_id` |
| check type 非法 → ERROR | `tests/test_contract.py::test_invalid_check_type` |
| file_contains 缺 text → ERROR | `tests/test_contract.py::test_file_contains_missing_text` |
| prerequisites 悬空 id → ERROR | `tests/test_contract.py::test_dangling_prerequisite` |
| evidence_paths 空但 status=done → WARNING | `tests/test_contract.py::test_done_without_evidence_warning` |
| max_retries 负数 → ERROR | `tests/test_contract.py::test_negative_max_retries` |
| 未知字段静默忽略 | `tests/test_contract.py::test_unknown_fields_ignored` |
