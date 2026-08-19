# Baize Agent V23 升级路线图

> 主题：**从「收集型技能包」升级为「自治型技能引擎」**
> 依据：与 pi-agent / hermes-agent / deepseek-harness 的差距分析 + 4 篇业界文章（Cole 33 skills / AI Labs 方案侦察 / superpowers vs mattpocock / mobile-app-autotest）的借鉴 + 现有 280 个 skills 的审计。

## 一、三问结论摘要

### 1.1 与主流 Agent 的差距（V23 视角）

**差异化优势（必须保留并强化）**
- 纯 stdlib、零运行时依赖、原生 Windows（hermes 强制 WSL2、deepseek-harness 需 Node≥22.19，均弱于我们）
- `manifest` 证据物理核验 + `NO FAKE DONE` + `Verifier` 硬化（与 mobile-app-autotest 的「manifest 先行 + 质量门禁」思想一致，我们领先）
- V22 组合内核 `component`/`modes` fail-closed、插件防御性隔离
- `load_skill` 工具「按需加载正文」（与 Cole 文章的「常驻仅 4200 token、触发才加载」一致，已是优势）
- 长程记忆压缩 + RAG 数据层

**真实短板（V23 要补）**
1. **无「自主创建 skill」能力** —— pi-agent 有 Skills/Extensions/Pi Packages，Cole 有 `skills-create`；我们是「收集 + 检索」，缺「运行时沉淀新 skill」。这是与初衷最大的偏离。
2. **技能库治理缺失** —— 跨库重复（280 文件 / 252 唯一名）、frontmatter 不规范、结构不一致、`skill_index` 去重「先到先得」可能保留劣质版本。
3. **索引检索为子串匹配**（`skill_index.search` 是 `keyword in haystack`），非语义/向量；虽 `rag` 模块有 TF-IDF，但索引自身弱。
4. **无「方案侦察 / 避免重复造轮子」** —— Agent 默认从零构建，不主动检索已有实现（文章 2 痛点）。
5. **无阶段路由 / 需求澄清前置** —— Director 缺 grill→PRD→issue 的澄清环节（文章 3）。
6. **无 meta-skill 审计 / 漂移检测** —— 无法验证某个 skill 是否还值得保留（文章 1 的 `ablate-ai-layer` / `rules-check-drift`）。
7. **无技能分发 / 市场生态** —— pi 有 Pi Packages、hermes 有插件市场；我们是本地文件夹。

### 1.2 四篇文章可用点

| 文章 | 核心可借鉴能力 | V23 落点 |
|---|---|---|
| Cole 33 skills | 双循环（外层规划/内层实现）、validation-first（先定测试再写码）、按需加载、**meta-skill 审计（ablate/rules-check-drift）**、skills-create | V23.2 自创建 + V23.3 审计；双循环可融入 modes |
| AI Labs 方案侦察 | Advise Project Approach（先搜已有方案）、NeuroArchive（arXiv 子 Agent 并行读论文）、Head Start 路由层、GitHub Stars 陷阱、中文生态搜索源 | V23.4 任务前 pre-flight 侦察；加中文源（Gitee/阿里云/掘金/知乎） |
| superpowers vs mattpocock | 阶段路由（先澄清再执行）、grill 需求澄清、to-prd/to-issues 沉淀、ask-matt 路由 | V23.5 强化 Director 澄清环节 + modes 路由 |
| mobile-app-autotest | manifest 先行（事实来源）、多维质量门禁（低于阈值不交付）、产物分层、中文交付 | 验证方向正确；V23.6 加多维质量评分门禁 |

### 1.3 现有 skills 审计（是否偏离初衷 / 是否加强 / 是否需优化）

- **规模**：`assets/skills` 23、`picasso-dev-skill` 13、`skills` 244，共 280 个 SKILL.md / 252 唯一名。
- **冗余**：`picasso-dev-*` 7 个同时存在于 3 个库、`maozx-*` 8 个存在于 2 个库；`maozx-investigation` 两副本**逐字相同** = 纯复制。
- **卫生**：`skills/` 库 19 个缺 `name`、18 个缺 `description`；`assets/skills` 6 个缺 `description` —— 直接拉低检索/评分质量（`skill_index` 靠 frontmatter）。
- **结构**：`skills/` 全平铺无分类；`assets/skills` 分 `skills/`+`strategic/`；`picasso-dev-skill` 分 `skills/`+`baize-agent-main/` —— 三库不一致。
- **是否加强 Agent**：**是**。抽样 `karpathy_coding`（外科手术式变更）、`maozx-investigation`（调查先行）质量高，直接支撑核心原则。但前提是索引质量过关。
- **是否偏离初衷**：**部分偏离**。「自主创建 skills（类似 pi-agent）」当前是「收集 + 检索」，**没有自创建机制**——这是真偏离。但「收集内置方法论库」与「运行时自主沉淀」不矛盾，应并存；缺的是后者。
- **是否需优化**：**是**，优先级见 V23.1 / V23.3。

## 二、V23 目标

把技能层从「静态收集的知识库」升级为「自治引擎」：
1. **治理**：去重合并、修复 frontmatter、统一结构、索引语义化。
2. **自治**：运行时能基于完成任务**自主沉淀新 SKILL.md**（对齐 pi-agent 初衷）。
3. **审计**：meta-skill 自动验证每个 skill 是否被引用 / 是否有效，标记僵尸。
4. **侦察**：任务开始前先检索已有方案，避免重复造轮子（含中文生态）。
5. **编排**：Director 前置需求澄清，modes 路由更细。
6. **门禁**：多维质量评分（低于阈值不交付）。

## 三、里程碑

### V23.1 技能库治理（低风险，先做）
- 合并跨库重复副本（保留最规范版本：`picasso-dev-skill` 全有 name+description；删 `skills/`、`assets/skills` 中的冗余副本）。
- 补齐缺失 frontmatter（脚本批量回填 name=目录名、description=首段）。
- 统一三库结构：`skills/` 也按主题分子目录（或收敛为单一库 + `SKILL_LIBRARY_PATHS` 引用）。
- `skill_index` 去重改为「取最规范版本」（name+description 齐全者优先，而非先到先得）。
- 验收：`python -m baize index build` 后 `count` 显著下降、`duplicates_deduped` 归零、无缺 frontmatter。

### V23.2 自主创建 skill（对齐初衷，核心）
- 新增 `baize skill create <name>` + Agent 运行时工具 `create_skill`（基于完成任务，结合 `memory` 长程压缩，把「有效经验」写成新 SKILL.md 并写入技能库、重建索引）。
- 借鉴 Cole `skills-create`：SKILL.md 模板（name/description/level/domain + 结构化正文）+ references 拆分。
- 写入默认落在用户技能库（不污染内置 `assets/skills`），`SKILL_LIBRARY_PATHS` 已支持。
- 验收：Agent 完成一个任务后能自动产出可索引、可被后续任务检索到的新 skill。

### V23.3 Skill 审计 / 漂移检测（meta-skill）
- 新增 `baize skill audit`：统计每个 skill 被检索/加载/命中的频次，标记「长期零命中」僵尸 skill；对比 skill 内容与当前代码/配置是否仍成立（ablate 思想）。
- 输出 `skill_audit.json` + 中文摘要（呼应 mobile-app-autotest 的「中文交付」）。
- 验收：audit 能列出 N 个零命中 skill 并给出处置建议（保留/合并/弃用）。

### V23.4 方案侦察 pre-flight（避免重复造轮子）
- 新增任务前置环节：先检索（a）技能库内同类实现（b）外部已有开源/方案，再动手。
- 借鉴 Advise Project Approach：澄清 → 搜索 → 区分「对当前规模有用」vs「大团队才需要」→ 成本三阶段估算。
- 加中文生态搜索源（Gitee / 阿里云 / 腾讯云 / 掘金 / 知乎），弥补海外偏置。
- 借鉴 NeuroArchive：无现成方案时用子 Agent 并行检索 arXiv/论文（可选、按需触发）。
- 验收：run 一个「加用户认证」类任务，能先给出「已有 X/Y 方案，建议直接接入」而非从零写。

### V23.5 阶段路由强化 Director
- Director 前置需求澄清（grill→PRD→issue 沉淀到 `CONTEXT.md`/PRD），再进入执行。
- `modes`（coding/eval/autonomous/safe-review）增加「clarify」模式或强化 autonomous 的澄清分支。
- 借鉴 ask-matt：不确定下一步时路由到合适子流程，而非直接执行。
- 验收：模糊目标任务先产出 PRD/issue 再实现，返工率下降。

### V23.6 多维质量门禁
- 在 `gate`/`Verifier` 引入多维评分（可运行性 / 定位健壮性类比 / 可维护性 / 稳定性 / 覆盖透明度），低于阈值不交付（呼应 mobile-app-autotest 五维门禁）。
- 复用现有 `bench_public` 覆盖率 + 新增维度。
- 验收：低质量产物被门禁拦截并给出维度化诊断。

## 四、风险与开放问题
- **自创建 skill 的质量控制**：Agent 写出的 SKILL.md 可能劣质，需 `gate` 把关 + V23.3 审计闭环。
- **检索语义化成本**：是否引入 embedding？纯 stdlib 下可用 `rag` 现有 TF-IDF，避免过度工程。
- **技能库合并的破坏性**：去重删除前需备份 / 保留 git 历史，先 `--dry-run`。
- **中文生态搜索的法律/合规**：外部搜索需用户授权，默认关闭、显式开启。

## 五、与既有路线的衔接
- V20 规格（openspec）已立：自主运行时、LLM 客户端、工具注册表、Verifier 硬化 —— V23 在其上叠加「技能自治」。
- V22 组合内核 `component`/`modes` fail-closed —— V23.4/V23.5 的侦察/澄清可作为新组件或模式接入，不破坏 fail-closed。
- 发布节奏：每里程碑先 `openspec/specs` 立规格 → `manifest validate` → 代码+测试 → 交付报告（非 archive，V23 为当前规划版本）。
## 六、V23.0 实现记录（代码已落地，待本机 pytest 验证）

### V23.1 技能库治理
- `baize/skill_index.py`：去重由「先到先得」改为 `_dedup` 按 `_norm_score`（有 description 优先 + 描述更长优先 + 源权威性 user>external>local:assets 优先）选最规范副本，修复「内置缺 desc 副本覆盖外部完整副本」的 V22 bug。
- `build_index` 新增 `audit` 字段：per_source 计数、missing_description 列表、duplicate_groups（保留/丢弃来源）。index version 升为 2。

### V23.2 自主创建技能规范化
- `config.py` 新增 `BAIZE_USER_SKILLS_DIR`（`user_skills/`），与内置 `assets/skills` 收集库分离。
- `skill_index.create_skill(name, description, body, domain, level, origin)`：写入 `user_skills/<slug>/SKILL.md`（标准 frontmatter：name/description/domain/level/origin/created_at）并立即重建索引。
- `tools._tool_save_skill` 改为调用 `create_skill`（不再写 `assets/skills/learned`），`save_skill` 工具 schema 增加可选 domain/level。Agent 自进化产出与内置收集库解耦。
- CLI 新增 `baize skill create <name> --description --domain --level [--body|--body-file]`，人也可直接创建技能。

### V23.3 技能审计
- `skill_index.audit_index()` + CLI `baize skill audit`：输出索引总数、去重数、各库计数、缺失 description 列表、跨库重复组，状态良好提示。中文摘要。

### 版本与测试
- `__init__.__version__` 22.0.0 升 23.0.0。
- 新增 `tests/test_skill_index.py`（safe_name slugify / dedup 取最完整副本 / create_skill 写入并索引 / audit 报告缺失与重复）。
- `tests/test_tools.py`：sandbox fixture 增加 `BAIZE_USER_SKILLS_DIR` 重定向；`test_save_skill_persists_and_indexes` 断言路径改 `user_skills/deploy-checklist`。
- `openspec/specs/baize-tools/spec.md` 第 6 条同步为 user_skills 描述。

### 待本机验证（当前沙箱无真实 Python）
```
cd F:\TC\baize-agent-main
pip install -e .
python -m pytest tests/test_skill_index.py tests/test_tools.py -q
python -m baize skill build
python -m baize skill audit
python -m baize skill create demo-skill --description "示例" --domain dev --body "1. step"
```

### V23.4 方案侦察 pre-flight
- 新增 `baize/recon.py`：`extract_keywords`（停用词/标点清洗）→ `recon_library`（按关键词在技能库 `skill_index.search` 命中同类实现）→ `recon(goal, web=)`（组合库内命中 + 可选外部搜索）。
- 外部搜索默认关闭：仅当 `BAIZE_RECON_WEB=1` 且显式 `--web` 才生成 Gitee/阿里云/腾讯云/掘金/知乎 搜索 URL（纯 urllib、零解析、不抓网页，fail-closed 到本地扫描）。
- `Orchestrator.run` 开头调用 `recon` 并把建议贴入团队黑板（recon 阶段），Director/Executor 规划前即可见已有方案。
- CLI 新增 `baize recon <goal> [--web]`。

### V23.5 阶段路由强化 Director
- `agent.build_system_prompt` 新增 `clarifier` 角色（grill 需求澄清 → 产出 questions/answers/assumptions/prd JSON）。
- `Orchestrator.clarify(goal)`：spawn 澄清 agent → `render_prd` 渲染 PRD → 落盘 `PRD.md`（默认工作区根）→ 写入团队黑板；fail-closed（无 JSON 仍返回有效澄清，不崩溃）。
- `render_prd(goal, qa)` 为纯函数，便于测试。
- `Orchestrator.run` 在 `BAIZE_CLARIFY=1` 时于规划前调用 `clarify`（默认关，需显式开启以免改变既有行为）。
- CLI 新增 `baize clarify <goal>`（直接产出 PRD）。

### V23.6 多维质量门禁
- `gate.check_quality(cfg)`：五维评分 `runnable / coverage_clarity / composition / locatability / maintainability`，加权综合 `score`，低于 `BAIZE_QUALITY_THRESHOLD`（默认 0.7）即 `pass=False`。
  - runnable←manifest 真实证据；coverage_clarity←真实覆盖率；composition←组合内核+模式可装配；locatability←技能库缺失 description 率；maintainability←有 tests/+README（静态）。
- `run_gate` 集成 `quality` 字段并纳入 `status`：质量不达标则整体 FAIL（拦截，不交付）。
- CLI `gate` 输出新增 quality 维度逐条。
- `config` 新增 `BAIZE_QUALITY_THRESHOLD`、`BAIZE_RECON_WEB`、`BAIZE_CLARIFY`。

### 版本与测试
- 新增 `tests/test_recon.py`（extract_keywords / recon_library 命中 / recon 结构 + web 开关）、`tests/test_clarify.py`（render_prd 全量 + 空兜底）、`tests/test_gate.py`（check_quality 维度边界 + run_gate 含 quality，并覆盖 gate 核心函数）。
- `__init__.__version__` 仍为 23.0.0（V23.0 完整里程碑收口）。

### 待本机验证（当前沙箱无真实 Python）
```
cd F:\TC\baize-agent-main
pip install -e .
python -m pytest tests/ -q
python -m baize skill build
python -m baize recon "加一个用户认证"
python -m baize clarify "做一个定时备份工具"
python -m baize gate
python -m baize skill create demo-skill --description "示例" --domain dev --body "1. step"
```
