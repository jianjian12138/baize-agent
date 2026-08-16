# AGENT.md — Baize Agent 操作协议 V22.0.0

本协议适用于两类使用者：
- **外部 AI 客户端**（Claude Code / Codex / WorkBuddy 等）接入本仓库时；
- **baize 自带 Agent 运行时**（`baize run` / `baize team`）——其系统提示词由
  `baize/agent.py: build_system_prompt()` 自动注入本协议核心规约。

## 0. 会话启动序列

1. 运行 `python -m baize doctor`，未通过则先修复环境，不得开始业务工作。
2. 运行 `python -m baize memory recall <本次任务关键词>`，恢复历史上下文
   （baize Agent 启动时自动执行并注入首轮提示词）。
3. 若涉及新领域，运行 `python -m baize index search <关键词>` 检索可用技能并加载对应
   SKILL.md（baize Agent 可直接调用内置 `search_skills` 工具）。

## 1. 角色分工（多 Agent 团队时）

| 角色 | 职责 | 关键产出 | V19 执行器 |
|------|------|----------|-----------|
| Director（规划） | 需求澄清、任务分解、主要矛盾识别 | JSON 任务计划 | `orchestrator.plan()` |
| Executor（执行） | 编码实现，遵循外科手术式变更 | 代码 + 对应测试 | `orchestrator` 派生的执行 Agent |
| Verifier（验证） | 独立核验执行结果，输出 verdict | pass/fail + evidence + issues | `orchestrator` 派生的验证 Agent |
| Memory（记忆） | 会话结束前沉淀结论 | `baize memory remember/log` | 编排结果自动落盘 |

单 Agent 场景下按上述顺序逐一切换角色执行；`baize team "<goal>"` 则由编排器自动完成
整条 Director→Executor→Verifier 链路，验证失败自动带 issues 重试。

## 2. 流水线门禁（NO FAKE DONE）

- 项目进度以 `manifest.json` 为唯一事实，格式见 `baize/manifest.py` 模块文档。
- phase 标记 `done` 的唯一途径：列出的 evidence 文件全部物理存在，且
  `python -m baize manifest validate <manifest>` 返回 VALID。
- 多 Agent 编排中，Executor 的「完成」声明必须经 Verifier 独立核验为 pass 才算数
  （由 `baize/orchestrator.py` 强制执行，`tests/test_orchestrator.py` 覆盖）。
- 严禁在代码中写入模拟通过（`assert True` 占位、`return True # Simulated`、
  用 MagicMock 屏蔽真实导入）。发现即视为 P0 缺陷。

## 3. 编码规约

- **澄清优先**：需求模糊时列出 Options 与用户确认，不猜。
- **最小 diff**：不改无关行、不动无关缩进与注释。
- **测试先行**：新功能先写失败测试，实现后转绿；测试必须发起真实调用。
- **路径可移植**：严禁硬编码盘符路径；一律走 `.env` / `baize/config.py`。
- **密钥红线**：密钥只进 `.env`（已 gitignore），严禁提交或硬编码。
- **沙箱红线**：Agent 工具默认限制在 `BAIZE_WORKSPACE_DIR` 内；
  `BAIZE_ALLOW_OUTSIDE_WORKSPACE=1` 仅限明确知晓风险时开启。

## 4. Agent 内置工具（V19）

`baize/tools.py` 提供 9 个内置工具，全部经沙箱与 deny-list 防护：

| 工具 | 用途 |
|------|------|
| read_file / write_file / list_dir | 工作区文件读写与浏览（沙箱内） |
| bash | 受限 shell（危险命令 deny-list 拦截，60s 超时） |
| search_skills / load_skill | 检索技能索引 → 按需加载完整 SKILL.md（渐进披露） |
| memory_recall / memory_log | 跨会话记忆读写 |
| save_skill | 自进化：把新工作流沉淀为技能并即时重建索引（hermes 式） |

manifest 门禁通过 `bash` 工具执行 `python -m baize manifest validate <path>` 完成。

## 5. 方法论技能（决策辅助）

| 场景 | 加载技能 |
|------|----------|
| 项目启动 / 需求不明 | `assets/skills/strategic/maozx-investigation` |
| 任务优先级冲突 | `assets/skills/strategic/maozx-main-contradiction` |
| 大型重构 / 长周期项目 | `assets/skills/strategic/maozx-long-war` |
| 代码变更 | `assets/skills/karpathy_coding` |
| 任务拆分 | `assets/skills/atomic_decomposition` |
| 完成前自检 | `assets/skills/verification_expert` |

## 6. 会话收尾序列

1. 运行全部相关测试，记录真实结果。
2. 更新 manifest 状态并 validate。
3. `python -m baize memory log "<本次完成事项>"`；重要结论另行 `remember`。
4. baize Agent 会话转录自动保存在 `persistence/sessions/*.jsonl`，
   可用 `python -m baize sessions <id>` 审计，`--resume <id>` 续跑。

## 7. V22 插件化架构（可选扩展，不破零依赖与 fail-closed）

V22 引入统一组件契约 + 组合内核，把每个核心单元（model / tool / skill / session /
sandbox / loop / scheduler / ui / storage）描述成可配置的组件，由 `CompositionKernel`
从 `BAIZE_COMPONENTS` 装配。**默认行为不变**；仅当你显式要替换某内置单元时才介入。

- **组件（Component）**：一份 `KIND` + `build(cfg)` 工厂契约，实例需满足对应 `Protocol`。
  写自定义组件三步：声明 `KIND` → 方法签名符合协议 → 提供 `build` 工厂。
  完整最小可运行示例与注册方式见 **[教程 08 · 写一个 baize 组件](../docs/tutorials/08-写一个baize组件.md)**。
- **两套隔离语义（关键）**：
  - 经 `BAIZE_COMPONENTS` 的**显式覆盖**构建/类型失败 → **整体 fail-closed，启动阻断**（绝不静默降级到内置）；
  - `baize/plugins/` + `BAIZE_PLUGINS_DIR` 的**自动发现**组件失败 → **记录 + 跳过**，host 不崩（**绝不默认可信**）。
- **命名模式 = 组件集**：`BAIZE_MODE` ∈ {`coding`/`eval`/`autonomous`/`safe-review`}
  是预设的（组件集 + 自治级别 + 工具 allow-list + plan_mode）配置 bundle；
  显式 `BAIZE_MODE` **优先于标量自治滑块**，未指定时回退滑块。
- **诚实自检**：扩展后跑 `python -m baize gate`，门禁会真实装配默认 runtime、校验 9 类
  `Protocol`、验证 4 种模式 bundle，并复测覆盖率（≥85%）——不假绿。
