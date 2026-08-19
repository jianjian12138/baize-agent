# 第 7 篇：让多个白泽协作 —— Director / Executor / Verifier 团队

> 适用读者：想了解 `python -m baize team` 背后机制的小白，或想用多 Agent 做复杂任务的人。本篇讲清编排器（Orchestrator）和协作记忆。

---

## 7.1 为什么需要"团队"

单个 Agent 能干不少事，但面对**复杂、需要质量保证**的任务（如"做一个完整接口并端到端验证"），一个人容易又当运动员又当裁判，质量难保证。白泽借鉴了软件工程中"规划/执行/验收"分离的成熟做法，把任务交给一个**三角色团队**：

```
        你的目标（goal）
              │
              ▼
   ┌──────────────────────┐
   │  Director 规划者      │  把目标拆成"可独立验证"的子任务清单
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │  Executor 执行者      │  逐个子任务写代码、调工具、跑测试
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │  Verifier 验收者      │  独立用工具核验每个子任务是否真的达成
   └──────────┬───────────┘
              ▼
      全部通过？ ──是──▶ 整体 SUCCESS
          │否（有未达成项）
          ▼
   把问题注入 Executor 修复目标 → 重试（有界）
```

这个编排逻辑在 `baize/orchestrator.py` 里。

---

## 7.2 三个角色各司其职

### Director（规划者）
- 收到大目标，输出一个**子任务清单**。
- 每个子任务包含：`id`、`task`（干什么）、`verify`（怎么算完成）、`checks`（可选的确定性检查）。
- 如果 Director 规划失败（模型没给出有效结构），会**降级为单任务 fallback**——保证至少有一个可执行的子任务，而不是直接崩溃。

### Executor（执行者）
- 拿到一个子任务，像第 4 篇讲的那样进入自主循环，写代码、调工具。
- 完成后把结果交给 Verifier。

### Verifier（验收者）—— 最关键的角色
- **不轻信 Executor 的"口头结论"**。
- 它会**独立调用工具**去验证：比如 Executor 说"测试通过了"，Verifier 会真去跑 `pytest` 看输出。
- 支持**确定性检查**（checks）：例如 `{"type": "http_status", "expect": 200}`，Verifier 会真的发请求核对。
- 解析 Executor 的结论为结构化 JSON（`verdict` / `evidence` / `issues` / `session_id`）。
- 没通过就把 `issues` 注入 Executor 的修复目标，进入**有界重试**。

---

## 7.3 怎么用 team 模式

```bash
python -m baize team "实现用户登录接口并端到端验证"
```

屏幕上会显示每个子任务的验收结果（详见第 3 篇 3.3 节）。整体结论：

```
overall: SUCCESS (3 sessions)     # 全部子任务通过
# 或
overall: FAILED (3 sessions)      # 有未达成项（会显示具体 issue）
```

> 退出码：全部成功返回 0，否则返回 1。自动化脚本可据此判断。

---

## 7.4 确定性检查（checks）是什么

这是 Verifier 的"硬指标"。Director 在规划时可以为子任务声明**确定性检查**——这些是客观可验证的断言，不通就直接判失败，不依赖模型"主观判断"。

示例（内部生成的子任务结构示意）：

```json
{
  "id": 1,
  "task": "实现 POST /login 接口",
  "verify": "接口能正确返回 JWT",
  "checks": [
    {"type": "http_status", "expect": 200}
  ]
}
```

Verifier 收到后会**真的发请求**，确认返回 200。这比"模型觉得应该 OK 了"可靠得多。

---

## 7.5 失败自动重试（有界）

如果 Verifier 判某个子任务失败：

1. 收集所有 `issues`。
2. 把它们注入 Executor 的下一步修复目标。
3. Executor 重试（最多 `BAIZE_LLM_MAX_RETRIES` 次）。
4. 重试用尽仍失败 → 该子任务标为 FAIL，整体判 FAILED。

> "有界"很重要：它防止 Agent **无限循环重试**拖垮资源。重试次数是配置项，不是无限。

---

## 7.6 协作记忆（team_memory）—— 团队共享白板

多 Agent 协作时，角色之间需要共享上下文（"规划者知道的事，执行者/验收者也该知道"）。白泽用 `team_memory` 模块实现了一个**共享白板**（blackboard）。

它是什么：
- 一个 append-only 的共享笔记文件（`persistence/team_memory/<team_id>.jsonl`）。
- 任意角色可以往上面写"笔记"，其他角色读得到。
- 支持 `role`（谁写的）、`tags`（标签）。

命令行查看：

```bash
# 看某个团队的共享白板
python -m baize team-memory show default

# 看统计
python -m baize team-memory stats default

# 清空（一般用于测试或新任务前）
python -m baize team-memory clear default
```

> 对小白：把它想象成"团队共用的便利贴墙"。Director 把计划贴上去，Executor 把进度贴上去，Verifier 把验收结论贴上去——大家看同一面墙协作。

---

## 7.7 自定义验收钩子（verify_hooks）

进阶用法：你可以给 Orchestrator 注入**自定义的验收钩子**（`verify_hooks`），做领域专用的硬门禁。钩子是一个函数：

```python
def my_gate(sub, executor_summary) -> tuple[bool, str]:
    # 返回 (是否通过, 说明)
    if "DANGER" in executor_summary:
        return False, "发现危险操作"
    return True, "ok"

orch = Orchestrator(client=client, verify_hooks=[my_gate])
```

任何钩子返回不通过 → 该子任务判失败。这让"业务规则"能被硬嵌入验收流程。

---

## 7.8 什么时候用 team，什么时候用 run

| 场景 | 推荐 |
|------|------|
| 单一、明确的小任务（写个函数、补个注释） | `run` |
| 复杂、多步骤、需要质量把关（做功能、修 bug、重构） | `team` |
| 想看"规划-执行-验收"全过程 | `team` |
| 想最快出结果 | `run` |

---

## 7.9 本篇小结

- `team` 模式 = Director（规划）→ Executor（执行）→ Verifier（验收）三角色协作。
- **Verifier 独立用工具验证**，支持确定性检查（checks），不轻信 Executor。
- 失败**有界重试**（最多 `BAIZE_LLM_MAX_RETRIES` 次），防止无限循环。
- 协作记忆（`team_memory`）是团队的"共享白板"，`show/stats/clear` 可管理。
- 可注入自定义验收钩子（`verify_hooks`）做领域硬门禁。

下一篇，我们讲**交互层**——TUI 进度、Web 仪表盘、协作记忆，让你"看得见"白泽在干什么。
