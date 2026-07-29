---
name: picasso-dev-task
description: Use when Picasso 需求涉及服务端接口、数据库表结构、删除策略、编码规则、OpenSpec 任务推进或后端实现联动，需要把业务需求翻译成服务端可执行任务和技术方案。
---

# Picasso Dev Task

## 定位

`picasso-dev-task` 是 Picasso 服务端开发 companion skill。

它负责：

- 理解 `*-需求文档.md` 中的业务规则
- 产出服务端技术设计和任务拆解
- 必要时生成菜单、字典、SQL 等配置资料
- 为服务端实现和联调提供边界清晰的输入

## 必须先读取

1. `../../profiles/picasso/profile.yaml`
2. `../../profiles/picasso/repo-map.md`
3. `../../profiles/picasso/tech-stack.md`
4. `../../profiles/picasso/配置入口说明.md`
5. `../../shared/references/requirements/README.md`
6. `../../shared/references/task/README.md`
7. 按需继续读取：
   - `../../shared/references/task/服务端任务路径布局.md`
   - `../../shared/references/task/服务端任务门槛校验.md`
   - `../../shared/references/task/服务端设计约束.md`
   - `../../shared/references/task/服务端任务状态管理.md`
   - `../../shared/references/task/服务端任务归档恢复与撤销.md`
   - `../../shared/references/task/服务端需求变更流程.md`
   - `../../shared/references/task/服务端快捷触发语义.md`
   - `../../shared/references/task/服务端 Codex 协作规范.md`
   - `../../shared/references/task/子产品与模块映射.md`
8. 当前需求目录：
   - `manifest.json`
   - `00-需求总览.md`
   - `*-需求文档.md`
9. 如已有设计基线，再读取：
   - `*-技术方案.md`
   - `*-任务分解.md`
   - `*-实现控制总表.md`
   - `*-页面接口验收总表.md`

## 核心职责

### 1. 服务端技术设计

输出并维护：

- `*-技术方案.md`
- 按需生成 `MENU_DATA.md / DICT_DATA.md / sql-change.sql`

必须覆盖：

- 模块边界
- 主表 / 子表关系
- 字段与状态定义
- 删除策略
- 编码生成策略
- 接口清单
- 异常与边界处理

### 2. 服务端任务拆解

输出并维护：

- `*-任务分解.md`
- 必要时维护 `${PICASSO_SERVER_TASK_DIR}/active/<任务名>/status.md`

任务拆解必须包含：

- 后端实现项
- 配置联动项
- 联调事项
- 验证事项

并且必须在以下节点同步回写 `status.md`：

- proposal / specs / design 生成或确认时
- `tasks.md` 生成后
- 每批编码任务结束后
- 需求变更时
- 任务归档前后

### 3. 配置资料预判

若设计中涉及菜单、字典、SQL，必须显式标记，并触发 `picasso-dev-config`。

### 4. 公共规则引用

涉及以下能力时，技术方案中必须显式引用：

- 异步导入导出
- 动态规则编码
- 内部编码生成
- 枚举 + 字典联动
- 服务端任务路径布局
- 服务端设计约束
- Codex 协作边界

### 5. OpenSpec 规则

- 新增任务前，先读取 `${PICASSO_SERVER_CODE_DIR}/openspec/specs/`
- 归档必须使用 `openspec archive`
- 编写新的 proposal / specs / design / tasks 之前，先回 `master` 更新基线，再切到任务分支

### 6. 生命周期规则

- `incoming -> active -> archived` 是唯一标准流转
- 已归档任务发生变更时，先恢复到 `active/`
- 撤销任务只在用户明确要求时执行，且不默认强推回滚远程

## 执行规则

1. 先复用既有服务端实现和既有规格，不从零假设
2. 接口路径、权限、状态值、编码场景不清楚时必须留待确认
3. 若需求涉及主子表、引用校验、删除策略，必须写清真实执行规则
4. `*-技术方案.md` 先确认，再允许进入正式编码
5. 编码模型只负责代码、编译、测试和必要 SQL，不负责流程性文档最终定稿
6. 需求变更必须先出影响分析，再改 design / tasks / code

## 默认输出

- `*-技术方案.md`
- `*-任务分解.md`
- `*-实现控制总表.md`
- `*-页面接口验收总表.md`
- 如涉及配置，给出 `MENU_DATA.md / DICT_DATA.md / sql-change.sql`

## 何时结束

当且仅当以下条件满足时，`picasso-dev-task` 才算完成本阶段：

1. 服务端实现边界清楚
2. 核心接口清单清楚
3. 风险和待确认项已列出
4. 下游前端 / 端侧已能基于当前方案继续工作
