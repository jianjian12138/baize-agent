---
name: picasso-dev-maintainer
description: Use when modifying picasso-dev-skill 自身的 skill、模板、脚本、README、profile 或规则文件，并需要同步维护 CHANGELOG、更新记录、决策记录和迁移说明。
---

# Picasso Dev Maintainer

## 定位

`picasso-dev-maintainer` 只负责维护技能包本身，不负责业务需求开发。

它用于：

- 新增或修改 skill
- 调整模板、脚本、README、profile
- 记录变更原因、影响范围和迁移说明

## 必须先读取

1. `../../AGENTS.md`
2. `../../governance/INDEX.md`
3. `../../governance/CHANGELOG.md`
4. `../../governance/maintainers.md`
5. 最近一条更新记录：`../../governance/updates/`

## 强制规则

修改以下任一内容时，必须补维护记录：

- `skills/`
- `profiles/`
- `shared/`
- `install/`
- `README.md`
- `AGENTS.md`

## 默认动作

1. 更新 `governance/updates/chg-xxxx-*.md`
2. 更新 `governance/CHANGELOG.md`
3. 若影响结构或规则，补 `governance/decisions/`
4. 如有兼容性变化，补迁移说明

## 更新记录模板

更新记录至少包含：

- 提交人
- 日期
- 影响范围
- 变更原因
- 本次修改
- 对使用者的影响
- 后续建议
