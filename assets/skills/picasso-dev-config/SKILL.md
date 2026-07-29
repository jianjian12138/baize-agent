---
name: picasso-dev-config
description: Use when Picasso 开发链路中需要处理菜单、字典、SQL、环境配置、初始化数据或联调配置，避免因配置缺失导致页面入口、枚举值或接口能力不完整。
---

# Picasso Dev Config

## 定位

`picasso-dev-config` 是 Picasso 开发链路中的配置协同 skill。

它用于处理：

- 菜单配置
- 字典配置
- SQL / DDL / 初始化数据
- 本地联调环境补齐

## 必须先读取

1. `../../profiles/picasso/profile.yaml`
2. `../../profiles/picasso/environments.md`
3. 当前需求目录中的：
   - `manifest.json`
   - `00-需求总览.md`
   - `*-需求文档.md`
   - `*-技术方案.md`
   - `*-任务分解.md`
4. 模板：
   - `../../shared/templates/config/MENU_DATA.md`
   - `../../shared/templates/config/DICT_DATA.md`
   - `../../shared/templates/config/sql-change.sql`

## 什么时候使用

出现以下任一情况时调用：

- 页面入口依赖菜单配置
- 字段枚举依赖字典配置
- 服务端设计涉及新表、增量字段、初始化数据
- 前端联调或测试依赖配置补齐
- 用户明确要求执行配置协同

## 默认输出

按需产出：

- `MENU_DATA.md`
- `DICT_DATA.md`
- `sql-change.sql`

必要时补充：

- 环境执行说明
- 风险说明
- 回滚说明

## 执行原则

1. 当前 skill 只允许 `local / dev` 作为可操作环境
2. 不连接 `test / uat / prod`
3. 执行任何 SQL 前必须明确目标环境，默认只能是本地
4. 进入 SQL / 数据查询前，先通过 `bash install/doctor.sh --capability db`
5. 菜单、字典、SQL 必须和当前需求绑定，不能散落在对话里
6. 配置不完整时，不允许宣称“可联调”或“可验收”

## 完成标准

1. 页面入口可达
2. 必要字典值完整
3. 表结构 / 初始化数据准备完成
4. 风险点已显式记录
