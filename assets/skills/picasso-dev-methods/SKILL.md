---
name: picasso-dev-methods
description: Use when Picasso 开发链路需要补齐方法论能力，如规划、任务拆分、TDD、系统化排障、完成前验证、代码审查处理、多代理并行与隔离策略，并要求这些方法在 skill 包内自包含、可迁移。
---

# Picasso Dev Methods

## 定位

`picasso-dev-methods` 是 `picasso-dev-skill` 的方法层。

它不替代 `picasso-dev` 主流程，而是把通用的高价值工程方法内化进包里，供 Claude Code、Codex、OpenCode、OpenClaw 等不同执行端统一复用。执行端可以单独使用，也可以协作使用。

## 使用边界

1. 主流程入口仍然是 `../picasso-dev/SKILL.md`
2. 本 skill 只负责“怎么做更稳”，不负责替代需求产物链路
3. 所有方法都必须服从 Picasso 既有规则：
   - 需求产物写入 `../../workspace/requests/<request-key>/`
   - 编码 / SQL / 部署前先过 `doctor.sh`
   - 默认 `local-only`
   - 阶段推进以 `stage-gate.py` 为准

## 适用场景

出现以下任一情况时，应补充读取本 skill：

- 需要先做规划、拆分执行路径，再进入开发
- 需要把功能改造成可测试、可回归的实现
- 需要系统化定位 bug，而不是直接拍脑袋改代码
- 需要在宣称“完成”前做真实验证
- 需要处理 review 意见、确认是否该采纳
- 需要多代理并行推进，或需要 worktree / 隔离执行策略
- 需要对照外部文章 / skill，把方法能力吸收进 Picasso 包内

## 方法索引

按需继续读取：

1. `references/planning.md`
2. `references/tdd.md`
3. `references/debugging.md`
4. `references/verification.md`
5. `references/review.md`
6. `references/parallel-and-isolation.md`

## 默认执行原则

1. 先识别当前问题属于哪类方法问题，再选择对应参考
2. 优先把方法落实到当前需求目录中的真实产物、脚本、测试和验证记录
3. 不把宿主机外部 skill 当成运行依赖
4. 如需引入外部 skill 内容，先登记到 `../../governance/vendor-skills.yaml`
5. 如需长期收编外部方法，优先内化到本 skill 的 `references/`，而不是运行时引用外部路径

## 与适配层关系

本 skill 提供“通用方法”。

不同运行端的接入说明在仓库根目录适配层中维护：

- `../../.claude-plugin/`
- `../../.codex/`
- `../../.opencode/`
- `../../.openclaw/`

这些目录只负责说明各端如何接入 Picasso 方法层，不得复制出多套相互冲突的主流程。
