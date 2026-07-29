# Picasso Dev Skill v1 设计说明

## 目标

构建一套面向 Picasso 项目的标准化开发技能包，支持：

- 单模型独立开发
- Claude + Codex 协作开发
- OpenClaw 等平台挂载
- PC / 小程序 / 移动端 / 后端协同开发

## 核心设计

1. `picasso-dev` 作为统一入口
2. `picasso-dev-task / ui / config / maintainer` 作为 companion skills
3. `workspace/` 作为运行产物目录
4. `governance/` 作为技能包维护记录目录
5. 使用英文代号作为需求目录主键

## 当前 v1 范围

- Picasso 专用版本先跑通
- 不抽象通用客户版
- 不依赖 OpenClaw 或 `codex-plugin-cc`
- 默认兼容单模型工作方式
