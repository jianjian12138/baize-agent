# V26-B1 RolePolicy 强制注入规格说明

> **版本**：v1.0  
> **状态**：APPROVED  
> **对应工作包**：战役 B / B1 RolePolicy 真实注入  
> **前置规格**：[v26-contract.md](v26-contract.md)（A1 契约）

---

## 1. 背景与目标

V25 的 `Role` 有 `tools` 字段，但从未被 orchestrator 的 `_spawn()` 读取注入
到 Agent 的工具白名单；`workspace_scope` 和 `memory_visibility` 字段根本不
存在。这导致 executor 在理论上可以调用任意工具，"角色策略" 是宣传而非事实。

B1 的最小实现：
1. 在 `Role` 上补全 V26 新字段（`allow_tools`、`workspace_scope`、`memory_visibility`）
2. `Orchestrator._spawn(role)` 读取 team_config 里对应 Role 的策略并注入到 Agent
3. 没有对应 Role 声明 → fail-closed（降级到 allow_tools 全开 + 警告）

---

## 2. 新字段（Role dataclass）

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `allow_tools` | `list[str]` | `[]` | 允许使用的工具名白名单，空列表 = 不限 |
| `workspace_scope` | `str` | `""` | 允许读写的路径前缀（相对 workspace root），空 = 不限 |
| `memory_visibility` | `str` | `"read"` | `read \| write \| none` 三值枚举 |

**后向兼容**：`tools` 字段继续存在（V25 兼容），但 `allow_tools` 是 V26 规范字段；
若同时存在取 `allow_tools`（新字段优先）。

---

## 3. Orchestrator._spawn(role_name) 注入规则

```
查找 self.team_config.roles 中 role.name == role_name 的 Role
  找到 → 用 role.allow_tools（或回退 role.tools）过滤 Agent 的 ToolRegistry
  未找到 → 全工具开放（allow_tools = []），记录 obs.warn
  memory_visibility == "none" → 不注入 recall_context
```

具体注入方式（最小侵入）：
- 在 `_spawn()` 中创建一个 **子集 registry**，只包含 `allow_tools` 列出的工具
- 如果 `allow_tools` 为空，使用原始 registry（不限制）
- `workspace_scope` 以 `extra_system` 形式注入 Agent 的 system prompt 追加
- `memory_visibility == "none"` 通过在 `_spawn()` 返回的 Agent 上设置
  `agent._no_memory = True`，`_run_loop` 检查此标志跳过 `recall_context`

---

## 4. fail-closed 规则

- `memory_visibility` 不在 `{read, write, none}` → 视为 `none` 并写 warning
- `allow_tools` 中包含未注册工具名 → 静默跳过（该工具不存在无法注入）
- 未找到 Role 声明（空 team_config）→ 继续但不限制（原有行为，不能强行拒绝已有用法）

---

## 5. 接口变更

### Role（baize/team.py）

```python
@dataclass
class Role:
    name: str
    description: str = ""
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)   # V25 兼容保留
    model: str | None = None
    # V26-B1 新字段
    allow_tools: list[str] = field(default_factory=list)
    workspace_scope: str = ""
    memory_visibility: str = "read"   # read | write | none
```

### Orchestrator（baize/orchestrator.py）

```python
def _spawn(self, role_name: str) -> Agent:
    """V26-B1: spawn with RolePolicy enforcement."""
    ...  # 见 §3
```

---

## 6. 约束

- **不引入新依赖**：只用 stdlib
- **不修改 Agent 构造器签名**：通过注入参数而非继承
- **`memory_visibility` 的 `write` 值**：保留定义，暂不实现差异行为（战略放弃）
- **未接线字段不宣传为能力**：`workspace_scope` 只注入 system prompt，不强制文件系统隔离（OS 级沙盒不在 V26 范围）

---

## 7. 测试映射

| 规约 | 测试 |
| --- | --- |
| allow_tools 过滤 agent registry | `tests/test_v26_role_policy.py::test_allow_tools_filters_registry` |
| allow_tools 空 = 不限 | `tests/test_v26_role_policy.py::test_empty_allow_tools_no_restriction` |
| 未找到 Role → 不限 | `tests/test_v26_role_policy.py::test_unknown_role_no_restriction` |
| workspace_scope 注入 system prompt | `tests/test_v26_role_policy.py::test_workspace_scope_injected` |
| memory_visibility=none 跳过 recall | `tests/test_v26_role_policy.py::test_memory_visibility_none_skips_recall` |
| memory_visibility 非法值 → none | `tests/test_v26_role_policy.py::test_invalid_memory_visibility_fallback` |
| allow_tools 优先于 tools | `tests/test_v26_role_policy.py::test_allow_tools_takes_priority_over_tools` |
| Role.from_dict 向前兼容 | `tests/test_v26_role_policy.py::test_role_from_dict_new_fields` |
