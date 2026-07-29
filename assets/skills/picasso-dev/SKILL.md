---
name: picasso-dev
description: Use when Picasso 项目需要统一推进新需求、需求变更、Bug 修复或 UI 优化，并希望按标准流程生成需求、方案、UI、任务、自测、审查、验收等产物后再进入开发。
---

# Picasso Dev

## 定位

`picasso-dev` 是 Picasso 项目的统一入口 skill。

它默认承担五件事：

1. 识别当前任务属于哪条开发链路
2. 创建或接管 `workspace/requests/<request-key>/` 目录
3. 组织完整交付物链路，而不是直接跳进写代码
4. 在合适阶段调用 `picasso-dev-task`、`picasso-dev-ui`、`picasso-dev-config`
5. 在需要时补充调用 `picasso-dev-methods`，收敛方法论执行方式

## 什么时候使用

出现以下任一情况，优先从本 skill 进入：

- 开始一个 Picasso 新需求
- 对已有需求做变更迭代
- 修复 Picasso 现有功能问题
- 优化 PC / 小程序 / App 页面体验
- 需要统一收口需求、方案、UI、任务、测试和验收产物

## 必须先读取

1. `../../profiles/picasso/profile.yaml`
2. `../../profiles/picasso/repo-map.md`
3. `../../profiles/picasso/execution-modes.md`
4. `../../shared/references/naming.md`
5. `../../shared/references/artifact-standard.md`
6. `../../profiles/picasso/environments.md`
7. `../../profiles/picasso/配置入口说明.md`
8. `../../shared/references/requirements/README.md`
9. `../../shared/references/requirements/Codex CLI 标准执行输入.md`
10. `../../shared/references/task/README.md`
11. `../../shared/references/quality/前端开发自测清单.md`
12. `../../shared/references/quality/两关制冒烟测试说明.md`
13. 根据任务类型读取对应工作流：
   - 新需求：`../../shared/workflow/new-feature.md`
   - 需求变更：`../../shared/workflow/change-request.md`
   - Bug 修复：`../../shared/workflow/bugfix.md`
   - UI 优化：`../../shared/workflow/ui-optimization.md`

若 `workspace/requests/<request-key>/` 已存在，还必须继续读取：

- `manifest.json`
- `00-需求总览.md`
- `*-需求文档.md`
- `*-技术方案.md`（如存在）
- `*-UI交互设计规范.md`（如存在）
- `stage-status.json`

## 路由原则

## 环境预检规则

在真正进入开发动作前，先判断当前任务属于哪类能力：

1. `docs`
   - 只生成需求、方案、UI、任务分解、培训材料
   - 不依赖完整开发环境
2. `dev`
   - 进入后端、前端、小程序、App 编码或本地联调
3. `db`
   - 需要查询本地数据库、执行 SQL 校验、验证本地数据
4. `deploy`
   - 需要本地启动、冒烟、本地发布准备

默认规则：

1. 纯文档任务可以跳过开发工具链体检
2. 一旦进入编码、SQL、部署，必须先自动执行 `doctor.sh`
3. `doctor` 未通过时，不继续真实开发，先修环境
4. skill 包内部问题要自行修复；外部软件缺失时，再一步步引导安装
5. 进入本地启动、联调、冒烟前，`deploy doctor` 必须同时校验运行编排变量

推荐命令：

```bash
bash install/doctor.sh --capability docs
bash install/doctor.sh --capability dev
bash install/doctor.sh --capability db
bash install/doctor.sh --capability deploy
```

## 执行自主规则

1. 进入真实开发后，routine 动作默认自主推进，不反复询问“要不要继续”
2. 默认自己处理：目录初始化、文档回填、脚本校验、阶段 gate、编译、自测、冒烟、本地启动
3. 若 `.env` 已配置运行编排入口，默认自动执行：启动后端 → 等待健康检查 → 启动前端 → 自动联调 → 自动登录拿 Token → 自动冒烟 → 自动收尾
4. 只有以下情况才升级给使用者：
   - 需求口径和范围不清
   - 账号、密码、权限缺失
   - 机器缺少外部开发环境且无法自动修复
   - 业务规则存在冲突，需要最终裁决
   - 本地运行编排已按规则配置但启动仍失败
5. 面向使用者的最终交付应尽量收敛为：
   - 功能已完成
   - 本地访问地址
   - 验证账号 / 密码
   - 关键验证路径

### 第一步：先识别需求类型

只允许落到以下四类之一：

1. `new-feature`
2. `change-request`
3. `bugfix`
4. `ui-optimization`

若用户输入不足以判断，先输出：

- 当前候选类型
- 判断依据
- 缺失信息
- 建议补充项

不要在类型不清楚时直接宣称进入开发。

### 第二步：再识别平台范围

在需求类型确定后，再识别涉及的平台：

- `backend`
- `pc`
- `miniapp`
- `mobile_app`
- `config`

平台范围要写入 `manifest.json`，并在产物中保持一致。

## 标准产物目录

统一使用：

```text
workspace/requests/<request-key>/
├── assets/
├── 00-需求总览.md
├── manifest.json
├── <功能名称>-需求文档.md
├── <功能名称>-任务分解.md
├── <功能名称>-技术方案.md
├── <功能名称>-UI交互设计规范.md
├── <功能名称>-测试用例.md
├── <功能名称>-实现控制总表.md
├── <功能名称>-页面接口验收总表.md
├── <功能名称>-开发放行报告.md
├── <功能名称>-覆盖率报告.md
├── <功能名称>-前端关键流程覆盖清单.md
├── <功能名称>-代码审查报告.md
├── <功能名称>-冒烟测试脚本.sh
├── <功能名称>-冒烟测试报告.md
├── <功能名称>-QA验收报告.md
├── <功能名称>-UI验收报告.md
├── <功能名称>-产品验收报告.md
├── <功能名称>-发布记录.md
├── logs/
└── stage-status.json
```

## 标准推进顺序

### 新需求

`需求分析 → 技术方案 → UI设计 → 任务拆解 → 编码开发 → 开发自测 → 代码审查 → 冒烟测试 → QA验证 → UI验收 → 产品验收 → 部署`

### 需求变更

`差异确认 → 影响分析 → 技术调整 → UI调整（如涉及）→ 任务拆解 → 开发 → 回归验证 → 验收`

### Bug 修复

`问题复现 → 根因定位 → 影响分析 → 修复方案 → 修复实现 → 回归验证 → 验收`

### UI 优化

`现状评估 → UI规范 → 页面优化 → 验收回归`

## Companion Skills 触发规则

### 调用 `picasso-dev-task`

当任务涉及以下任一场景时调用：

- 服务端接口、表结构、业务规则实现
- OpenSpec / 服务端任务推进
- 编码规则、删除策略、状态流转、接口设计

### 调用 `picasso-dev-ui`

当任务涉及以下任一场景时调用：

- 进入 UI 设计阶段
- 涉及原型还原、页面优化、视觉提升
- 涉及 PC / 小程序 / App 任一端的界面与交互

### 调用 `picasso-dev-config`

当任务涉及以下任一场景时调用：

- 菜单、字典、SQL、环境配置
- 联调、自测、测试所需初始化数据
- 配置项不完整导致页面或接口不可用

### 调用 `picasso-dev-methods`

当任务涉及以下任一场景时调用：

- 需要先规划、拆任务或收敛执行路径
- 需要补齐 TDD、回归验证、完成前验证
- 需要系统化排障，而不是直接猜测修改
- 需要处理 review 意见、判断是否采纳
- 需要多代理并行推进或使用隔离执行策略

## 阶段卡点

默认不允许跳过下列关键卡点：

1. `任务分解卡点`
   - PRD / 需求文档完成后，必须产出 `*-任务分解.md`
   - 任务默认切到 `30-60` 分钟可执行粒度
   - 每个任务必须写明：输入、输出、验收标准、证据要求、回流动作
2. `开发自测卡点`
   - 编码完成后，必须回填 `*-开发放行报告.md`
   - 未完成自测或存在 `❌ / 阻塞项`，默认不能进入 review
3. `覆盖率卡点`
   - 必须补 `*-覆盖率报告.md`
   - 必须补 `*-前端关键流程覆盖清单.md`
   - 后端覆盖率默认目标 `>= 90%`
   - 前端关键流程必须覆盖：列表加载、查询、新增、编辑、查看、删除、权限
4. `代码审查卡点`
   - 必须有 `*-代码审查报告.md`
   - 默认先找阻塞级问题，再讨论是否放行
   - 有 `P0 / 阻塞` 未关闭，禁止进入冒烟测试
5. `冒烟测试卡点`
   - 必须有 `*-冒烟测试脚本.sh`
   - 必须有 `*-冒烟测试报告.md`
   - 默认执行“两关制冒烟”：接口验证 + 页面集成验证
   - `stage-gate.py smoke` 默认会真实执行冒烟脚本，而不是只检查文件存在
   - 冒烟脚本默认应自动启动本地服务、自动联调、自动收尾
   - 未达到 `100% 通过`，禁止进入 QA 验证
6. `QA 验证卡点`
   - 必须有 `*-QA验收报告.md`
   - 只验证功能正确性、边界场景、回归影响和阻塞级问题
   - QA 未通过，禁止进入 UI 验收
7. `UI 验收卡点`
   - 必须有 `*-UI验收报告.md`
   - 只验证页面还原度、交互符合度、状态与异常反馈一致性
   - UI 未通过，禁止进入产品验收
8. `产品验收卡点`
   - 必须有 `*-产品验收报告.md`
   - 默认结论不是 `READY`，而是 `NEEDS_WORK`
   - 只有业务符合度、流程符合度和范围边界都确认后，才能进入发布准备
9. `发布卡点`
   - 必须有 `*-发布记录.md`
   - 必须明确目标环境、发布策略、回滚方式和发布后验证结果
   - 产品验收未通过前，禁止进入发布

## 默认放行立场

无论是单运行端、Claude Code + Codex 协作，还是 OpenClaw / 其他平台模式，默认放行结论都不是 `READY`，而是 `NEEDS_WORK`。

只有同时满足以下条件，才允许升级为 `READY`：

1. 关键文档和控制表已齐全
2. 开发自测报告无阻塞项
3. 覆盖率与前端关键流程覆盖达到标准
4. 代码审查无 `P0 / 阻塞`
5. 冒烟测试全通过
6. QA 验证无阻塞结论
7. UI 验收无页面和交互阻塞结论
8. 产品验收无业务阻塞结论

## 回流与升级原则

1. 没有证据的“通过”默认无效
2. QA 默认职责是先找问题，不是先证明开发通过
3. 同一任务连续失败 `3` 次，必须升级给 `PM / 架构` 重拆任务或重审方案
4. 高还原度页面必须把字段、交互、状态、异常路径逐条映射到控制文档
5. 涉及公共依赖未确认时，只能先做安全部分，禁止猜测公共接口后一次性写死实现

## 安全与边界

1. 不使用日期作为需求目录主键
2. 不把运行产物写入 `governance/`
3. 不把 skill 包维护记录写入 `workspace/`
4. 不默认操作生产数据库或生产服务器
5. 当前 skill 只允许 `local / dev` 作为可操作环境
6. `test / uat / prod` 只用于识别边界，不允许连接、查询、部署
7. 不在缺少需求基线时直接写业务代码
8. 涉及公共能力时，必须显式引用 `shared/references/requirements/` 下对应规则

## 快速动作

### 创建新需求骨架

优先使用：

```bash
python3 shared/scripts/init-request.py --key <request-key> --title "<中文标题>" --type new-feature --workspace "${PICASSO_WORKSPACE_DIR:-workspace}"
```

### 校验当前需求产物

```bash
python3 shared/scripts/validate-artifacts.py --request workspace/requests/<request-key> --type <request-type>
```

### 执行阶段 Gate

```bash
python3 shared/scripts/stage-gate.py dev workspace/requests/<request-key> --backend-project "$PICASSO_SERVER_CODE_DIR"
python3 shared/scripts/stage-gate.py review workspace/requests/<request-key>
python3 shared/scripts/stage-gate.py smoke workspace/requests/<request-key>
python3 shared/scripts/stage-gate.py smoke workspace/requests/<request-key> --skip-smoke-exec
python3 shared/scripts/stage-gate.py qa workspace/requests/<request-key>
python3 shared/scripts/stage-gate.py ui_acceptance workspace/requests/<request-key>
python3 shared/scripts/stage-gate.py product_acceptance workspace/requests/<request-key>
python3 shared/scripts/stage-gate.py release workspace/requests/<request-key>
```
