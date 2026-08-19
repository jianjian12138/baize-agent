---
name: baize-engine
description: 白泽引擎主技能——12 阶段研发流水线规约与技能调度入口。适用于在本仓库内启动、推进或验收任何开发项目。
version: 24.0.0
---

# SKILL.md — 白泽 12 阶段研发流水线 V24.0.0

## 流水线定义（P1–P12）

| 阶段 | 名称 | 准出证据（写入 manifest evidence） |
|------|------|------------------------------------|
| P1 | 需求对齐 | 需求文档 |
| P2 | 技术方案 | 技术方案文档 |
| P3 | UI/UX 设计 | 设计规范文档 |
| P4 | 任务分解 | 任务分解文档 / task_decomposition.json |
| P5 | 测试挂架注入 | 可运行的测试脚本文件 |
| P6 | 核心实现 | 源代码文件 |
| P7 | 数据与资产落地 | schema / 迁移脚本 / 种子数据 |
| P8 | 代码审查 | 审查报告 |
| P9 | 冒烟测试 | 冒烟测试报告 |
| P10 | 数据库迁移对齐 | schema 终版 |
| P11 | 前端联调 | 联调涉及的视图/接口文件 |
| P12 | 验收与交付 | 验收报告 |

**阶段推进规则**：更新 `manifest.json` 后必须执行
`python -m baize manifest validate <path>` 且结果为 VALID，方可宣布阶段完成。

## 技能调度

1. **本地方法论技能**：`assets/skills/`（毛选战略 11 项、卡帕西编码、picasso-dev 系列、原子分解、验证专家等）。
2. **外部技能库**：由 `.env` 的 `SKILL_LIBRARY_PATHS` 声明
   （默认 `D:/picasso-dev-skill/skills` 与 `D:/skills`，索引后去重为 249 唯一技能）。
3. **检索方式**：`python -m baize index search <关键词>`，命中后读取对应 SKILL.md 并遵循其指令
   （baize Agent 内可直接调用 `search_skills` 工具）。
4. **索引刷新**：技能库有增删后运行 `python -m baize index build`。
5. **自进化（V19）**：Agent 完成新颖工作流后，用内置 `save_skill` 工具沉淀为新技能，
   下次 `index build` 后即可被全体 Agent 检索复用。

## 执行方式（V19 双模式）

| 模式 | 命令 | 适用场景 |
|------|------|----------|
| 外部客户端加载 | AI 客户端读取本文件 + AGENT.md 后按规约操作 | Claude Code / WorkBuddy 等会话内 |
| 自主 Agent | `python -m baize run "<goal>"` | 单任务自主执行（含工具调用与会话持久化） |
| 多 Agent 团队 | `python -m baize team "<goal>"` | 需规划→执行→独立核验的复杂任务 |

## 与运行时的对应关系

| 规约 | 强制执行者 | 测试 |
|------|-----------|------|
| 环境就绪才开工 | `baize/doctor.py`（exit code） | `tests/test_doctor.py` |
| NO FAKE DONE（证据） | `baize/manifest.py` | `tests/test_manifest.py` |
| NO FAKE DONE（独立核验） | `baize/orchestrator.py` | `tests/test_orchestrator.py` |
| 技能动态发现 | `baize/skill_index.py` | `tests/test_skill_index.py` |
| 跨会话记忆 | `baize/memory.py` | `tests/test_memory.py` |
| 自主循环与会话持久化 | `baize/agent.py` | `tests/test_agent.py` |
| 工具沙箱与 deny-list | `baize/tools.py` | `tests/test_tools.py` |
| 模型无关接入 | `baize/llm.py` | `tests/test_llm.py` |
| 统一组件契约 + 组合内核（V22） | `baize/component.py` | `tests/test_component.py` |
| 命名模式 = 组件集（V22） | `baize/modes.py` | `tests/test_modes.py` |
| 组件自动发现 / 钩子体系（V22 硬化） | `baize/plugin.py` | `tests/test_plugin_discovery.py` |
| 诚实门禁（含组件+模式校验，V22 扩） | `baize/gate.py` | `tests/test_gate.py` |
