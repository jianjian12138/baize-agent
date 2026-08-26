# Baize Agent V25 升级计划(可执行版)

> 本文档为执行版 V25 升级计划,聚合 `docs/V25-arch-design/` 8 份架构设计稿(已 commit,commit `9191798`)与微信《Traycer》行业对比,作为 V25.0.0 落地的总执行单。
>
> **用户诉求**:"整合 V25 升级方案,然后进行升级。"
>
> **与上游关系**:本计划是 `_集成汇总.md`(G6 集成交付)的**执行细化版**,所有裁决/红线/门禁与集成汇总一致;新增「微信文章借鉴」与「根目录文件清理」两节(用户本次任务新增输入)。

---

## 0. 元信息

```yaml
标题: Baize Agent V25 升级计划(可执行版)
版本: v1.0
状态: 已批准(用户 2026-08-20 批准,启动 W1→W4 编码,严禁 Git 提交)
创建日期: 2026-08-20
项目路径: D:\tc\baize-agent
目标版本: V24.0.0 → V25.0.0
升级主题: 生态接入 + 可见性
红线: A 零依赖 / B NO FAKE DONE / C ext fail-closed / D 外科手术 / E fail-closed 安全
基线: pytest 422 passed / 1 skipped / 0 failed
专家组: 4 人(测试/技能/架构/Agent)平均 ≥ 9.5/10
```

### 主文档索引

| 编号 | 文档 | 角色 | 状态 |
| --- | --- | --- | --- |
| 总纲 | `docs/V25-arch-design/_集成汇总.md` | G6 集成交付 | 已 commit |
| 现状 | `docs/V25-arch-design/material_digest.md` | G1 资料摘要 | 已 commit |
| 调研 | `docs/V25-arch-design/research_report.md` | G2 行业调研 | 已 commit |
| 架构 | `docs/V25-arch-design/高层架构设计.md` | G3 高层架构 | 已 commit |
| 系统 | `docs/V25-arch-design/系统设计.md` | G4 系统设计 | 已 commit |
| 故事 | `docs/V25-arch-design/UserStory.md` | G4 UserStory | 已 commit |
| 部署 | `docs/V25-arch-design/部署设计.md` | G5 部署设计 | 已 commit |
| 安全 | `docs/V25-arch-design/安全设计.md` | G5 安全设计 | 已 commit |
| **执行单** | **`docs/baize-agent-V25升级计划.md`(本文)** | **执行细化** | **本次新建** |
| 评审 | `docs/V25-专家评审.md` | 验收基线 | 本次新建 |

---

## 1. 现状摘要(基于 V24.0.0 实际仓库)

| 能力域 | 现状(已落地) | 来源 |
| --- | --- | --- |
| 运行时 | 纯 Python stdlib、零第三方依赖(审计面极小) | M1 D1/D3/D6/D18 |
| 自主循环 | 反思规划 + 自循环 + 长程记忆压缩 + 死循环检测 | M1 D4 agent |
| LLM 客户端 | OpenAI 兼容端点 + OpenAI/Anthropic/Ollama 适配器 + `BAIZE_MODEL_ROUTER` + SSE 流式 + 速率限制 | M1 D4 llm |
| 工具系统 | 9 原语 + `ToolRegistry` 单例 + 沙箱 deny-list fail-closed + `save_skill` 自进化 | M1 D4 tools |
| 多智能体 | orchestrator Director→Executor→Verifier(独立核验)+ `team_memory` 黑板 | M1 D4 orchestrator |
| 数据层 | vector(TF-IDF,已有 `get_backend()`)/rag/graph/bench | M1 D4 数据层 |
| 交互层 | TUI + Web Dashboard + REST serve | M1 D4 交互层 |
| 工程化 | observability + `logging_setup`(JSON+脱敏)+ chaos + plugin + `config_schema` | M1 D4 工程化 |
| 校验 | doctor + manifest(NO FAKE DONE 证据)+ skill_index + memory | M1 D4 校验 |
| 测试 | 422 passed / 1 skipped / 0 failed | M1 D6/D14 |

### 1.1 已识别差距与优先级

| 优先级 | 差距 | 出处 |
| --- | --- | --- |
| P0 | 可见性/GitHub 元数据(star=1、forks=0) | M2 调研 |
| P1 | 文档/版本号陈旧(操作手册 V19、Dockerfile LABEL 20.0.0、.env.example 头 V19) | M3 架构 F3 |
| P2 | MCP 兼容缺失(V24 瘦身删 `mcp.py`,真缺口) | M2 D8 §P2 |
| P3 | 模型供应商假绿(provider_capabilities 恒返 True、Anthropic 流式未实装、DeepSeek `reasoning_content` 未捕获) | M2 D8 §P3 |
| P4 | 稠密向量后端缺失(推迟 V26) | M2 D8 §P4 |
| P5 | 多智能体薄配置层缺失 | M2 D8 §P5 |
| P6 | 扩展总线碎片化风险(统一收口) | M2 D8 §P6 |

---

## 2. 升级目标与价值定位

**V25 = 生态接入 + 可见性**(不破坏零依赖红线)。

升级后 Baize 将成为唯一**「纯 stdlib 零依赖 + NO FAKE DONE 可验证门禁 + MCP 兼容」三者兼得**的 Agent 运行时。

### 2.1 北极星指标

| 指标 | 当前 | V25 目标 |
| --- | --- | --- |
| GitHub stars | 1 | ≥10(3 个月内,纯可见性驱动) |
| topics 数 | 6(已部分执行) | ≥10 完整覆盖 |
| MCP 真实参考 server 联调 | 0 | 至少 1 个真实 server 联调通过 |
| 测试基线 | 422/1skip/0fail | 不破(零回归) |
| 文档版本号统一度 | 3 处不一致(Dockerfile/.env.example/操作手册) | 100%(全部 25.0.0) |
| 假绿消除(供应商能力) | provider_capabilities 恒返 True | 如实上报 |

---

## 3. MVP 路线(F1–F7,W1–W4)

### 3.1 F1 元数据止血(W1,P0 最高 ROI)

- 补全 GitHub topics 至 10+(现 6,补:`agent`、`mcp`、`zero-dependency`、`llm`、`autonomous`、`ai-agent`、`chinese`、`self-hosted`、`verified`、`pure-python`)
- 开启 GitHub Discussions
- before-after 截图(1 star 现状 vs 升级后)
- 文件落点:仅 GitHub UI,无代码变更

### 3.2 F2 README 重写(W1,P0)

- 修正误数 448→422/1skip/UNKNOWN(NO FAKE DONE 口径)
- 版本号徽章统一 25.0.0
- 新增「MCP 兼容」段、「Spec-driven + Verifier」段、「Stage-Gated Releases」段
- 移除「覆盖率 87.6%」等未经核验的数字
- 文件落点:`README.md`(徽章/章节/误数段)
- 借鉴微信文章《Traycer》措辞(详见 §10)

### 3.3 F3 MCP 兼容(W2–W3,P2 必修,最核心)

- 文件落点:`baize/ext/mcp/`(新增,核心 `baize/` 永不 import 此目录)
  - `transport.py` — stdio JSON-RPC 2.0 + **Content-Length 分帧**(纯 stdlib `subprocess`+`json`,无新依赖)
  - `client.py` — **initialize 握手**(protocolVersion 协商 + capabilities 交换 + `notifications/initialized`)
  - `server.py` — 暴露 baize skills 给 Claude Desktop/Cursor
- 接入既有 `ToolRegistry`(复用 register/execute,**不另立工具表**)
- 对真实 MCP 参考 server 联调通过(非 mock,**物理证据**)
- 静态 grep 门禁(`baize/*.py` 无顶层 `import baize.ext`)
- 红线:**A 零依赖**(纯 stdlib)/ **C ext fail-closed**(延迟 import + 缺失 skip)/ **B NO FAKE DONE**(联调通过是物理证据)

### 3.4 F4 多智能体薄配置层(W2,P5)

- 文件落点:`baize/team.py`(新增,**勿重写** orchestrator)
- role→system_prompt+tools 映射(纯 stdlib 解析或改用 JSON,绕过 PyYAML 红线 A,对应 TC-4)
- 复用 orchestrator + Verifier + team_memory
- 红线:**A/D**(最小 diff)/ **C**(ext 隔离)

### 3.5 F5 供应商补丁(W2–W3,P3)

- 文件落点:`baize/ext/providers/`(新增),核心 `baize/llm.py` **不动**
- Anthropic 流式实装 + `max_tokens` 参数化(去除 4096 硬编码)
- DeepSeek `reasoning_content` 字段捕获与透出
- `provider_capabilities` 如实上报(消除恒返 True 假绿)
- `baize/ext/providers/` 仅放非 OpenAI 兼容厂商薄适配(OpenAI/Anthropic/Ollama 留在 `llm.py`,对应 X6 修正)
- 红线:**B 不假绿**/ **A 零依赖**(纯 stdlib)

### 3.6 F6 统一扩展总线收口(W3,P6)

- 全部经 `plugin.discover` + `CompositionKernel.add_component`
- 禁各阶段自起 `import baize.ext`(除 `tools.register_mcp_client` 函数体内延迟 import 唯一例外)
- 红线:**A/C**(收口点)

### 3.7 F7 ext 测试守卫(W3–W4,P1 必修)

- `pyproject.toml` `norecursedirs` 补 `baize/ext/`(避免默认发现破坏零回归)
- ext 测试 `importorskip` 守卫(缺失 skip 不阻断 422 基线)
- CI 新增静态 grep 门禁(`baize/*.py` 无顶层 `import baize.ext`)
- 红线:**A/C**(门禁)

---

## 4. 完整版(F8–F9,V26 推迟,W5–W8)

| 编号 | 功能 | 推迟理由 |
| --- | --- | --- |
| F8 | 稠密向量后端(llama_index/chromadb 可选 import) | 需引入新依赖,违反红线 A 零依赖(可后置);扩展既有 `get_backend()` 懒探测,**不改** VectorBackend 抽象(对应 X7 修正) |
| F9 | 非 OpenAI 兼容厂商重适配(gemini/bedrock) | V25 仅薄适配,V26 全量 |

---

## 5. 演进纪律与红线 A–E(来自集成汇总 §5.2)

| 红线 | 内容 | V25 落实 | 检验手段 |
| --- | --- | --- | --- |
| A | 运行时零第三方依赖 | CI ast 扫描 + 静态 grep 门禁 | 评审 M-02/M-06 |
| B | NO FAKE DONE | manifest + gate + doctor + pytest 实数 | 评审 V-04/P-01/02/03 + 自测回归 |
| C | baize/ext/ fail-closed | 延迟 import + importorskip + norecursedirs | 评审 M-01/G-01/02/03 |
| D | 外科手术式 + 显式优先 | 最小 diff + BAIZE_MODE/BAIZE_COMPONENTS 优先于标量 | 评审 T-03/P-04 + diff 审查 |
| E | fail-closed 安全观 | 沙箱默认开 + deny-list + 未配置 exit 2 + 插件绝不默认可信 | 评审 E-04 + 沙箱单测 |

---

## 6. CI/CD 门禁(新增)

| 阶段 | 动作 | 门禁 | 红线 |
| --- | --- | --- | --- |
| 零依赖校验(现有) | ast 扫描 `baize/` 无非 stdlib import | 红线 A | A |
| **静态 grep 门禁(V25 新增)** | `baize/*.py` 无顶层 `import baize.ext` | CI 强制 | A/C |
| Doctor + Gate | `baize doctor` PASSED + `gate quality` ≥ 0.8 | B 不假绿 | B |
| pytest | 422/1skip/0fail | 基线不破 | B |
| **ext 测试守卫(V25 新增)** | importorskip,缺失 skip 不阻断 | fail-closed | C |
| 版本号统一 | 8 处版本字符串全为 25.0.0(`pyproject` / `manifest` / `__init__` / `README` / `Dockerfile LABEL` / `.env.example` 头 / 全部 docs 头 / `SKILL.md`) | 100% 统一 | D |

---

## 7. 退出标准(必达)

- MCP 真实参考 server 联调通过(非 mock)— 物理证据
- 422/1skip/0fail 零回归
- `gate quality` ≥ 0.8
- `doctor` PASS
- 静态 grep 门禁 CI 强制
- 文档版本号 100% 统一
- 4 人专家组评分 ≥ 9.5/10(详见 `docs/V25-专家评审.md`)

---

## 8. 风险与依赖

| 风险 | 概率 | 影响 | 缓解 |
| --- | --- | --- | --- |
| MCP 协议实现细节出错(分帧/握手) | 中 | F3 联调失败 | 提前对真实 server 联调,不依赖 mock |
| ext/ 被错误地 import 到核心 | 低 | 红线 A/C 破 | 静态 grep 门禁 CI 强制 |
| 422 基线被破坏 | 中 | B 红线破 | F7 守卫必先于 F3 实施 |
| TC-1/2/3/4 已裁决(2026-08-20 全部接受建议) | 已消除 | 评审口径已统一 | — |
| 依赖外部 MCP server 联调 | 中 | F3 延期 | 至少选定 1 个稳定参考 server(`modelcontextprotocol/servers` 仓的 filesystem/git/fetch) |

### 8.1 外部依赖

- GitHub 元数据修改权限(U-01 已部分执行)
- 真实 MCP 参考 server(选 candidates:`modelcontextprotocol/servers` 仓的 `filesystem` / `git` / `fetch`)
- 用户对 TC-1/2/3/4 的裁决(已完成:全部接受建议,见 §12)

---

## 9. 实施排期(week-based,严禁未经批准启动)

| Week | 主任务 | 完成判据 |
| --- | --- | --- |
| W1 | F1 元数据 + F2 README + 起步 `baize/ext/` 空壳 + TC-1/2/3/4 裁决 | 文档版本号 100% 统一,`baize/ext/` 目录 git ls-files 可见(空壳) |
| W2 | F3 MCP transport/client(server 暂 mock) + F5 供应商补丁 + F4 team 薄配置 | 单元测试 PASS,静态 grep 门禁 PASS |
| W3 | F3 MCP 真实 server 联调 + F6 收口 + F7 守卫 + README 终版 | 真实联调通过,422/1skip/0fail,doctor PASS,gate ≥ 0.8 |
| W4 | 4 人专家组验收(详见 `V25-专家评审.md`)+ 整改闭环 + V25.0.0 tag | ≥ 9.5/10 评分 + tag 推送 + release notes |

> **强约束**:上述排期需用户批准后方可启动编码;编码期间**严禁 Git 提交**,所有变更暂存于工作区,每步带「文件:行号证据 + 自测回归」。

---

## 10. 微信文章《Traycer》对 V25 的借鉴与不借鉴

> 来源:https://mp.weixin.qq.com/s/Qhj1O60AIJV6QWZmajrz5Q(2026-06-25,小K,标题《Traycer:AI Agent 的"神经中枢"!Spec 驱动开发 + 统一上下文 + Epic 模式 + 多 Agent 编排 + 内置验证,6 天干完 5 个月活的实战工作流》)
> 项目:https://github.com/traycerai/traycer

### 10.1 一句话

Traycer 是「Agent 编排层 + BYOA + Spec 驱动 + 验证内置」的 **TypeScript/Electron** 桌面应用,核心 Host 以**签名二进制分发**(不开源)。它的"统一上下文 + 验证门 + 多 Agent 循环"思路与 Baize V25 的"NO FAKE DONE + orchestrator + Verifier 独立核验"高度同源,但技术栈与红线完全不同。

### 10.2 可借鉴(5 点,纳入 V25 措辞与卖点)

| Traycer 概念 | Baize V25 对应 | 落地形式 |
| --- | --- | --- |
| **BYOA**(Bring Your Own Agent) | 已有 OpenAI/Anthropic/Ollama 适配器 + V25 F5 补全 | README 新增"BYOA + 多 LLM 路由"作为卖点 |
| **Unified Context**(跨 Provider 共享上下文) | baize-memory + team_memory 黑板 | README 新增"统一上下文"段 |
| **Spec-driven Development**(PRD/Tech Spec/Artifact) | baize 已有 PRD.md + V25 8 份 design 稿 | 强化"Spec-driven + Verifier"为对外叙事 |
| **Built-in Verification**(severity 分类评论) | NO FAKE DONE + 独立核验 + chaos 真实验证 | 强化"可证明的诚实"为对外叙事 |
| **Epic Mode**(计划 + 阶段验证门) | baize gate + doctor + 阶段性升级(P0→P4) | 强化"Stage-Gated Releases"为对外叙事 |

### 10.3 不借鉴(技术冲突 / 理念冲突,5 点)

| Traycer 做法 | 与 Baize 冲突 | 不借鉴理由 |
| --- | --- | --- |
| TypeScript + Electron + Bun/Node 24 | 红线 A 零依赖 | 违反"零第三方运行时依赖" |
| 核心 Host 以**签名二进制**分发,不开源 | 红线 B(可证明的诚实) | "可审计 + 可验证"要求源码可见 |
| 商业订阅 + credits 计费 | 纯开源定位 | 与 Baize"纯 stdlib + 免费"定位冲突 |
| 实时协作 / 看板 / Tiptap 富文档 | 库而非协作平台 | Baize 是运行时/库,不是桌面协作产品 |
| 跨设备云同步 | 本地优先 | 强化"in-memory 处理,代码仅内存"叙事 |

### 10.4 对 V25 文案/可见性的具体增益

- README 新增 **「BYOA + 多 LLM 路由」** 标题(与 Traycer 同源但更轻)
- README 新增 **「Spec-driven + Verifier」** 段落(凸显 baize 8 份 design + 独立核验)
- README 新增 **「Stage-Gated Releases」** 段落(P0→P4 + gate)
- topics 新增 `mcp`、`spec-driven`、`verified`、`byoa`、`stage-gated` 等
- **不引入** Electron / **不引入** 订阅 / **不引入** 云同步(坚守红线)

---

## 10.5 竞品新增:PenguinHarness(用户决策:纳入 V25 竞品对标)

> 用户 2026-08-20 询问 PenguinHarness(LlamaFactory 作者开源的"Agent 造 Agent"自进化闭环项目)对 V25 是否帮助;经分析结论:**仅在概念/定位/竞品对标层面有帮助,技术栈冲突红线 A**,用户授权"你来决定"→ 采纳:将其纳入 V25 竞品对标(新增 B6),并在 `research_report.md` / `_集成汇总.md` 竞品表补充,本计划新增本节。

**可借鉴(概念层,与 Baize 现有 Verifier / NO FAKE DONE 同源):**
- **CONTRACT.md 反 Reward-Hacking 契约**:把"诚实"写进可执行契约,与 Baize NO FAKE DONE 门禁(manifest + doctor + gate + pytest 实数)理念同源,强化 V25 对外"可证明的诚实"叙事。
- **自进化闭环(Agent 造 Agent)**:低成本生成完整 RAG 应用,与 Baize `save_skill` 自进化(沉淀新技能)同源但层次不同(项目级 vs 技能级)。
- **文件系统即真相**:状态落盘、可审计,与 Baize 白盒 + manifest 证据同源。

**不借鉴(技术冲突 / 红线冲突,反例):**
- **嵌入 Node 运行时**:PenguinHarness 依赖 Node 执行环境,直接冲突 Baize **红线 A 零依赖**(纯 Python stdlib)。V25 MCP(F3)坚持纯 stdlib `subprocess`+`json`,不嵌入任何运行时。
- **成本叙事(0.2 元 Token 造 Agent)**:属营销叙事,与 Baize"不假绿、不声称未验证数字"冲突,不引入。

**结论**:PenguinHarness 不进入 V25 实现范围(技术栈冲突),仅作竞品对标与"诚实门禁"叙事佐证;其 CONTRACT.md 思路在 V25 对外文案中作为"可证明诚实"的同行印证引用,不复制代码。

---

## 11. 根目录文件清单结论(用户截图 15 文件)

| 文件 | 必要性 | 处理 | 理由 |
| --- | --- | --- | --- |
| `.coveragerc` | 建议保留 | 保留(可选合并到 `pyproject.toml` `[tool.coverage]`) | 删除有回归风险,收益低;V25 NO FAKE DONE 标 UNKNOWN 不依赖此文件 |
| `.dockerignore` | 必留 | 保留 | Dockerfile 标配 |
| `.env.example` | 必留 | 保留 + 头部版本号 V19→25.0.0 | 配置入口 + 升级必统一 |
| `.gitignore` | 必留 | 保留 | Git 标配 |
| `AGENT.md` | 必留 | 保留 | AI Agent 上下文入口,现代项目标配 |
| `baize.manifest.json` | 必留 | 保留 + version 24.0.0→25.0.0 | NO FAKE DONE 物理核验证据 |
| `CONTRIBUTING.md` | 建议保留 | 保留 | 开源贡献入口 + 可见性 |
| `Dockerfile` | 必留 | 保留 + LABEL 20.0.0→25.0.0 | 部署形态 + 升级必统一 |
| `LICENSE` | 必留 | 保留 | 开源法律要求 |
| `Makefile` | 建议保留 | 保留 | 便捷命令封装 |
| `PRD.md` | 必留 | 保留 | 产品需求,核心文档 |
| `pyproject.toml` | 必留 | 保留 + version 24.0.0→25.0.0 + `norecursedirs` 补 ext | 项目元数据 + V25 升级点(F7 守卫) |
| `README.md` | 必留 | 保留 + 重写(F2) | 项目门面 |
| `SKILL.md` | 必留 | 保留 + 头版本号 → 25.0.0 | 技能元信息 |
| `START-HERE.md` | 必留 | 保留 | 新手入门,面向小白 |

**结论:15 个文件全部保留,无删除项。** 仅需版本号统一与内容修订(共 8 处版本号改写,详见 §2.1 与 §6)。

---

## 12. 待澄清项(TC-1–TC-4,已于 2026-08-20 用户裁决:全部接受建议方案)

| 编号 | 待澄清 | 裁决(用户接受建议) | 落地影响 |
| --- | --- | --- | --- |
| TC-1 | 技能计数 249 vs 250 | `baize skill audit` 实时输出为唯一来源 | 不硬编码计数,README 以实时 audit 为准 |
| TC-2 | 覆盖率口径:README UNKNOWN vs CI 80% 行覆盖 | 维持 NO FAKE DONE 口径(标 UNKNOWN,不假绿) | README 不声称覆盖率数字 |
| TC-3 | 阈值不一致:CI 80 / .env.example 85 / gate quality 0.7 | 统一为 `gate quality` ≥ 0.8 | README/CI/.env.example 文案统一为 ≥0.8 |
| TC-4 | `roles.yaml` YAML 解析 vs 红线 A 禁 PyYAML | 改用纯 stdlib 简易解析器或 JSON(系统设计 M2 已明确) | F4 team 用 JSON 或 stdlib 解析,不引入 PyYAML |

---

## 13. 引用

- `docs/V25-arch-design/_集成汇总.md`(G6 集成交付,已 commit `9191798`)
- `docs/V25-arch-design/material_digest.md`
- `docs/V25-arch-design/research_report.md`
- `docs/V25-arch-design/高层架构设计.md`
- `docs/V25-arch-design/系统设计.md`
- `docs/V25-arch-design/UserStory.md`
- `docs/V25-arch-design/部署设计.md`
- `docs/V25-arch-design/安全设计.md`
- `docs/V25-专家评审.md`(本次同时段新建)
- 微信《Traycer:AI Agent 的"神经中枢"!》https://mp.weixin.qq.com/s/Qhj1O60AIJV6QWZmajrz5Q(2026-06-25)
- Traycer 项目:https://github.com/traycerai/traycer

---

> **下一步(已批准)**:按 W1→W4 顺序启动编码;编码期间**严禁 Git 提交**,所有变更暂存于工作区,每步带「文件:行号证据 + 自测回归」,4 人专家组按 `docs/V25-专家评审.md` 评分 ≥ 9.5/10 方可 tag。
