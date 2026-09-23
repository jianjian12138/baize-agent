# AGENT.md — Baize Agent 操作协议 V38.0.0

本协议适用于两类使用者：
- **外部 AI 客户端**（Claude Code / Codex / WorkBuddy 等）接入本仓库时；
- **baize 自带 Agent 运行时**（`baize` 交互终端 / `baize run` / `baize team`）——其系统提示词由
  `baize/agent.py: build_system_prompt()` 自动注入本协议核心规约。

## 0. 会话启动序列

1. 运行 `python -m baize doctor`，未通过则先修复环境，不得开始业务工作。
2. 运行 `python -m baize memory recall <本次任务关键词>`，恢复历史上下文
   （baize Agent 启动时自动执行并注入首轮提示词）。
3. 若涉及新领域，运行 `python -m baize index search <关键词>` 检索可用技能并加载对应
   SKILL.md（baize Agent 可直接调用内置 `search_skills` 工具）。

## 1. 角色分工（多 Agent 团队时）

| 角色 | 职责 | 关键产出 | 核心执行器 |
|------|------|----------|-----------|
| Director（规划） | 需求澄清、任务分解、依赖拓扑分析 | DAG 任务计划 (`depends_on`) | `orchestrator.plan()` |
| Executor（执行） | 编码实现，遵循外科手术式变更 | 代码 + 对应测试 | `orchestrator` 派生的执行 Agent (支持并发) |
| Verifier（验证） | 独立核验执行结果，输出 verdict | pass/fail + evidence + issues | `orchestrator` 派生的验证 Agent |
| Memory（记忆） | 会话结束前沉淀结论 | `baize memory remember/log/archive` | 编排结果自动落盘 |

单 Agent 场景下按上述顺序逐一切换角色执行；`baize team "<goal>"` 则由编排器自动完成
整条 Director→Executor→Verifier DAG 并行执行链路，验证失败自动带 issues 局部重试。

## 2. 流水线门禁（NO FAKE DONE）

- 项目进度以 `manifest.json` 为唯一事实，格式见 `baize/manifest.py` 模块文档。
- phase 标记 `done` 的唯一途径：列出的 evidence 文件全部物理存在，且
  `python -m baize manifest validate <manifest>` 返回 VALID。
- 多 Agent 编排中，Executor 的「完成」声明必须经 Verifier 独立核验为 pass 才算数
  （由 `baize/orchestrator.py` 强制执行，`tests/test_orchestrator.py` 覆盖）。
- 严禁在代码中写入模拟通过（`assert True` 占位、`return True # Simulated`、
  用 MagicMock 屏蔽真实导入）。发现即视为 P0 缺陷。
- **HTTP 端点同样受此约束。** 一个返回 200 + 硬编码成功负载的桩，比文档写错更严重：
  文档误导读者，端点误导程序。尚未实现的端点必须返回 501 并在
  `baize/serve.py: STUB_ROUTES` 中声明；`make honesty` 会真实启动服务逐个探测这些
  路由，并扫描源码里是否残留旧的编造字面量。当前共 11 条。
- **写方法必须鉴权。** `do_POST` / `do_DELETE` 等状态变更方法必须调用
  `_is_authorized()`；`tests/test_serve.py::test_every_write_method_checks_authorisation`
  直接读源码断言这一点（`do_DELETE` 曾经完全没有鉴权检查，行为测试一直没发现，
  因为没人发过 DELETE）。
- **门禁自身也要被验证。** 新增/修改门禁脚本时必须用反证法确认它**会失败**：
  把问题重新注入一次，确认门禁报红，再还原。只会变绿的门禁等于没有门禁。
- **指标必须是被测出来的，不能是算出来的。** 一个除以自身的比率（`n / n`）永远等于
  100%，而它看起来和实测值一模一样。`baize/mutation.py` 曾经报"100% 击杀率"，因为它算的是
  `killed_count = len(mutants)`——从未执行过任何变异体。任何分数、比率、通过率都要能追到
  一次真实运行，且**没有运行时要报 `None`，不要报 100%**。
- **名字必须诚实。** 字段叫 `*_signature` 就必须是签名（有密钥、可验证）；没有就改名或加
  `signed: false`。`BFT-SIG-***` 曾经是 `sha256(goal + votes + time.time())`——一个时间戳哈希，
  每次调用都不同，连内容摘要都不是。同理 `verified_gate: True` 而没有任何校验、
  `downloads: 12` 而没有任何计数，都是伪造的证据。
- **导入的每个名字都必须存在。** `from .x import Y` 里 `Y` 不存在时，端点在**首次被调用时**
  才炸（`CausalDebugger` 就是这样，`/v30/causal` 每次请求都 ImportError）。
  `scripts/check_module_attrs.py` 现在会检查这一点，不要绕过它。
- **请求里的字符串不许直接进文件名或写盘的源码。** `target_function` 曾经既进
  `test_causal_{fn}.py` 的文件名、又进写盘的 Python 源码正文，一个换行就能把代码注入到
  会被 pytest 收集的文件里。所有这类值先做 `isidentifier()` / 白名单校验，写盘前再做一次
  路径包含性检查，输出目录要进 `.gitignore`。

## 3. 编码规约

- **澄清优先**：需求模糊时列出 Options 与用户确认，不猜。
- **最小 diff**：优先使用 `patch_file` 进行精准局部修改，不改无关行、不动无关缩进与注释。
- **测试先行**：新功能先写失败测试，实现后转绿；测试必须发起真实调用。
- **路径可移植**：严禁硬编码盘符路径；一律走 `.env` / `baize/config.py`。
- **密钥红线**：密钥只进 `.env`（已 gitignore），严禁提交或硬编码。
- **沙箱红线**：文件类工具（read_file / write_file / patch_file / list_dir）
  默认限制在 `BAIZE_WORKSPACE_DIR` 内，越界抛 `PermissionError`；
  `BAIZE_ALLOW_OUTSIDE_WORKSPACE=1` 仅限明确知晓风险时开启。
  **`bash` 不受此限制**——它只把 cwd 钉在工作区，绝对路径照样可达。

## 4. Agent 内置工具（V33 原语集）

`baize/tools.py` 提供内置原语工具。**先说边界，再说能力**：

- 操作系统级沙箱**默认关闭**。只有 `BAIZE_SANDBOX_ENABLED=1` 才走
  `baize/sandbox.py`（Linux Landlock / macOS Seatbelt）；Windows 上该模块
  诚实降级为 `logical-only` 并返回 `degraded=True`，即**没有** OS 边界。
- `bash` 的 deny-list 是**防误操作的护栏，不是安全边界**。实测 35 条破坏性
  变体中仅拦截 18 条（51%）：引号拆分、`${HOME}` 展开、长选项、变量间接、
  base64 管道、`find -delete`、`shred`、`diskpart`、`Remove-Item -Recurse`
  全部可达。机器可读的完整披露见 `tools.EXECUTION_BOUNDARY`，`GET /health`
  会原样返回。
- `run_python` 的 AST 检查同样是**护栏而非沙箱**：它按名字过滤语法，
  `getattr`、`__subclasses__` 遍历、字符串拼接属性名都能绕过（审计已证
  端到端绕过）。真正起作用的是独立进程 + 环境变量脱敏 + `-I` + cwd 限定
  + 超时强杀。
- 结论：把 `bash` / `run_python` 当作「Agent 能以当前用户权限执行任何东西」
  来评估信任。

| 工具 | 用途 |
|------|------|
| read_file / write_file | 工作区文件读写（支持 `start_line`/`end_line` 切片读取） |
| patch_file | 精准差量补丁（字符串精确替换/统一 diff，换行容错） |
| list_dir | 工作区目录浏览 |
| bash | 执行 shell 命令。deny-list 护栏拦截常见灾难命令（51% 覆盖，见上），超时强杀整棵进程树。**不构成安全边界** |
| git | 安全子集 Git 操作（仅只读及 commit，shell=False，白名单子命令 + 拒绝选项注入） |
| run_python | 独立进程执行 Python 片段：环境变量脱敏 + `-I` + cwd 限定工作区 + 超时强杀。AST 检查是护栏，不是沙箱 |
| fetch_url | 网页内容安全提取（HTTP/HTTPS 验证，HTML 清洗） |
| search_skills / load_skill | 检索技能索引 → 按需加载完整 SKILL.md（渐进披露） |
| memory_recall / memory_log | 跨会话持久记忆检索与记录 |
| save_skill | 自进化：把新工作流沉淀为标准 YAML 技能并即时索引 |

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
  完整最小可运行示例见 **`examples/logged_sandbox.py`**，注册方式见 **`baize/plugin.py`**。
  （V22 时代的 `docs/tutorials/08-写一个baize组件.md` 已在 V24 瘦身中移除。）
- **两套隔离语义（关键）**：
  - 经 `BAIZE_COMPONENTS` 的**显式覆盖**构建/类型失败 → **整体 fail-closed，启动阻断**（绝不静默降级到内置）；
  - `baize/plugins/` + `BAIZE_PLUGINS_DIR` 的**自动发现**组件失败 → **记录 + 跳过**，host 不崩（**绝不默认可信**）。
- **命名模式 = 组件集**：`BAIZE_MODE` ∈ {`coding`/`eval`/`autonomous`/`safe-review`}
  是预设的（组件集 + 自治级别 + 工具 allow-list + plan_mode）配置 bundle；
  显式 `BAIZE_MODE` **优先于标量自治滑块**，未指定时回退滑块。
- **诚实自检**：扩展后跑 `python -m baize gate`，门禁会真实装配默认 runtime、校验 9 类
  `Protocol`、验证 4 种模式 bundle，并复测覆盖率（≥85%）——不假绿。
