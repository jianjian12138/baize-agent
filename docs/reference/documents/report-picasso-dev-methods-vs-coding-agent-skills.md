# Picasso Dev Methods 与文章推荐 Skills 对照

## 对照来源

- 文章：[精选 Skills 推荐：10 个让 Coding Agent 如虎添翼的 Skills](https://linux.do/t/topic/1802808)

## 结论摘要

`picasso-dev-skill` 现在已经具备文章里最值得吸收的核心方法能力，但不是把外部 skill 原样复制进来，而是收敛成 Picasso 包内自包含的方法层。

## 逐项对照

| 文章能力 | 当前承接情况 | 承接位置 | 说明 |
|---|---|---|---|
| Planning / 写计划 | 已具备 | `skills/picasso-dev-methods/references/planning.md` | 与 `picasso-dev` 主流程、任务分解、实现控制总表联动 |
| TDD | 已具备 | `skills/picasso-dev-methods/references/tdd.md` | 收敛为“先定义验证，再做实现” |
| Systematic Debugging | 已具备 | `skills/picasso-dev-methods/references/debugging.md` | 强制复现、定位、修复、回归闭环 |
| Verification Before Completion | 已具备 | `skills/picasso-dev-methods/references/verification.md` | 与 `doctor.sh`、`stage-gate.py`、冒烟、验收链路联动 |
| Receiving Code Review | 已具备 | `skills/picasso-dev-methods/references/review.md` | 不再机械照改，要求基于事实判断 |
| Parallel / Isolation | 已具备 | `skills/picasso-dev-methods/references/parallel-and-isolation.md` | 支持多代理协作，但维持单主入口 |
| Skill Creator | 部分具备 | `skills/picasso-dev-maintainer/SKILL.md` | 承接维护、治理、变更记录，但未复制外部 skill-creator 全量能力 |
| Superpowers / SuperClaude 框架 | 不直接引入 | `governance/vendor-skills.yaml` | 只借鉴“显式适配层 + 清晰分层”，不引入外部总控框架 |

## 为什么不原样引入

1. 你的包要跨机器迁移，不能依赖宿主机已有 skill
2. `picasso-dev` 已经是主流程骨架，没必要再让外部 framework 接管
3. 外部内容真正有价值的是方法，不是整套命令壳

## 这次额外吸收的结构经验

借鉴了 `Superpowers` 里“主规则层 + 适配层”的表达方式，补了：

- `.claude-plugin/`
- `.codex/`
- `.opencode/`
- `.openclaw/`

这样目录更清晰，但主规则仍集中在：

- `skills/`
- `shared/`
- `profiles/`
- `governance/`

## 最终判断

如果问题是“文章里那些真正提升 Coding Agent 工程质量的方法，我这个包现在有没有”，答案是：

**核心方法能力基本都具备了。**

如果问题是“是否把文章里的外部 skill / framework 原样搬进来了”，答案是：

**没有，也不建议那样做。**
