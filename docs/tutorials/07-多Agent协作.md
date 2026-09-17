# 07 · 让多个白泽协作

> 单个 Agent 的问题是：**没人检查它的工作**。它说自己做完了，你就只能信。
> 多 Agent 协作要解决的就是这件事。

---

## 1. 先跑一次

```bash
python -m baize team "创建一个配置模块并写测试"
```

**真实输出：**

```
   0.0s => phase    recon
   0.0s => phase    planning
   0.1s -> tool     write_file({"path": "hello_baize.txt", "content": "Hello from Baize!\n"})
   0.1s -> tool     read_file({"path": "hello_baize.txt"})
   0.1s .. skill_harvested distilled skill to SKILL.md
   0.1s => phase    executing #1: 创建一个配置模块并写测试
   0.1s => phase    verifying #1
   0.1s => phase    retry #1 (1)
==============================================================
[##############################] 1/1 [FAIL] (retried) #1 创建一个配置模块并写测试
--------------------------------------------------------------
  run finished in 0.1s
  events: phase=5  skill_harvested=1  tool=2
  overall: FAILED
--------------------------------------------------------------
run-id: run-1789614323  (use 'baize status run-1789614323' to inspect)
sessions: 5
```

注意最后是 **`overall: FAILED`**。

这次运行用的是第 03 篇那个"只会写 hello 文件"的桩模型。它交出的产出和"创建配置模块并写测试"这个目标**完全不匹配**，于是 Verifier 拒绝通过，任务被标记为失败。

**这正是我们要的行为。** 如果这里显示 PASS，那才是灾难——说明验证环节形同虚设。

---

## 2. 五个阶段

从真实输出里可以看到完整的阶段序列：

| 阶段 | 做什么 | 对应角色 |
| :--- | :--- | :--- |
| `recon` | 动手前的侦察：有没有现成的轮子？ | `recon` |
| `planning` | 把目标拆成可独立验证的子任务 | `director` |
| `executing #N` | 执行第 N 个子任务 | `executor` |
| `verifying #N` | 验证第 N 个子任务的产出 | `verifier` |
| `retry #N (M)` | 第 N 个任务第 M 次重试 | — |

另外还有一个 `clarifier` 角色（当目标模糊时先澄清需求），由 `baize clarify` 单独触发。

### 2.1 为什么要有 `recon`

`baize recon` 是一个独立的子命令：

```bash
python -m baize recon "实现一个 JSON 解析器"
python -m baize recon "..." --web     # 额外搜索外部生态（需 BAIZE_RECON_WEB=1）
```

**先侦察再动手**是专业工程师和业余选手最大的差别之一。recon 阶段的结果会作为建议注入到后续规划中。

---

## 3. 为什么 Verifier 必须独立

这是整个多 Agent 设计的**核心理由**：

```
❌ 一个 Agent 干活 + 自己说自己干完了     → 你只能信它
✅ 一个 Agent 干活 + 另一个 Agent 验证   → 有独立的判断
```

在编排器里，执行者和验证者是**两次独立的 Agent 运行**：

```python
self._team_post("executor", res.final_text, ["finding", "executed"])   # 执行者提交
...
self._team_post("verifier", "; ".join(issues), ["blocker"])            # 验证者发现问题
self._team_post("verifier", ..., ...)                                  # 验证者放行
```

**验证者看不到执行者的"自信"，只能看到产出物。** 这就是它能拒绝上面那次运行的原因。

### 3.1 验证不通过会怎样

1. 任务标记为 `failed`；
2. 问题写进共享黑板（带 `blocker` 标签）；
3. 触发 `retry`；
4. 重试仍失败 → 整个 run 标记 `overall: FAILED`。

失败信息是**结构化落盘的**，可以查：

```bash
$ python -m baize status run-1789614323
=== Run Status: run-1789614323 ===
  goal       : 创建一个配置模块并写测试
  verified   : []
  failed     : ['1']
  in_progress: []
  unfinished : []
  candidates : 0 skill candidate(s)
  completed  : False
  events     : 9 total in ledger

  next: review failed tasks and fix issues, then re-run
```

注意最后一行 **`next:`**——它不是一句空话，而是根据当前状态推导出来的下一步建议。

---

## 4. 共享黑板（TeamMemory）

多个角色之间怎么交换信息？通过一块**共享黑板**。

```bash
python -m baize team-memory show       # 看黑板内容
python -m baize team-memory stats      # 看统计
python -m baize team-memory clear      # 清空
```

```json
{
  "team_id": "default",
  "notes": 0,
  "claims": 0,
  "roles": []
}
```

写入的每条记录都带**角色和标签**：

```python
self._team_post("recon", recon_report["advice"], ["recon"])
self._team_post("director", ..., ...)
self._team_post("executor", res.final_text, ["finding", "executed"])
self._team_post("verifier", "; ".join(issues), ["blocker"])
```

**标签体系是关键**：`finding` / `executed` / `blocker` / `recon`。当验证者写下 `blocker` 时，其他角色能立刻识别出"这里卡住了"。

### 4.1 任务认领与竞态（一个真实的 bug）

黑板支持**任务认领**——多个执行者并发时，谁先认领谁负责：

```python
def claim(self, task_id: str, role: str) -> bool:
    ...
```

**这里曾经有一个真实的竞态 bug。**

旧实现分成了两个独立临界区：

```python
# ❌ 旧代码：读和写各加一次锁
def claim(self, task_id, role):
    owner = self.owner_of(task_id)      # 加锁 → 读 → 解锁
    if owner is not None:
        return owner == role
    self._append({...})                 # 再次加锁 → 写 → 解锁
    return True
```

问题在于：**锁在"读"和"写"之间被释放了**。两个线程可能同时读到"没人认领"，然后都认为自己认领成功——**双方都赢**。

修复方式是把读和写放进**同一个临界区**：

```python
# ✅ 新代码：读-改-写是一个原子操作
def claim(self, task_id, role):
    with self._lock:
        owner = self.owner_of(task_id)
        if owner is not None:
            obs.inc("team_memory_claim_conflicts")
            return owner == role      # 同一角色重复认领是幂等的
        self._append({"kind": "claim", ...})
        obs.inc("team_memory_claims")
        return True
```

**实测证据**（40 轮 × 10 线程）：

| 版本 | 出现"双方都赢"的轮数 |
| :--- | :--- |
| 旧实现 | **8 / 40** |
| 新实现 | **0 / 40** |

> 这类 bug 的特点是：**单线程测试永远发现不了**，而且在生产环境表现为"偶发的重复执行"，极难复现。所以修完之后特意做了 40 轮对照实验，而不是跑一次通过就算数。

---

## 5. 按需授权：子代理只能拿到该拿的工具

基准测试里的一项：

```
[PASS] subagent_isolation  4.6 ms  scoped tools=['read_file', 'list_dir'], registry size=2
```

一个只负责"侦察代码库"的子代理，注册表里**只有 2 个只读工具**。

同理，编排器支持给子任务限定角色：

```python
allowed_roles = sub.get("allowed_roles")
if allowed_roles and "executor" not in allowed_roles:
    err_msg = f"ERROR: subtask #{task_id} restricted to roles {allowed_roles}, ..."
```

**一个只需要读的任务，不该拥有 `write_file` 和 `bash`。** 这是最小权限原则在 Agent 系统里的落地。

---

## 6. 恢复：不要重复已完成的工作

```bash
python -m baize team "..." --resume run-1789614323
```

`--resume` 会**跳过已经验证通过的任务**，只重做失败和未完成的。

前提是 run ledger 记录了每个任务的状态——所以 `baize status` 才能准确告诉你 `verified: []` / `failed: ['1']`。

**长任务被中断时，这个机制能省下大量重复劳动和 token。**

---

## 7. 自定义团队

```bash
python -m baize team "..." --roles roles.json
```

`roles.json` 里定义你自己的角色集合、各自的系统提示和权限。适合特定领域的流水线（比如"安全审计员"角色）。

---

## 8. 更重的武器（了解即可）

### 8.1 Swarm：真实 git worktree 隔离推演

`baize/swarm.py` 会并发探索 3 条策略路线——极简修补（minimal_patch）、模块化重构（modular_refactor）、强契约设计（contract_driven）——每条路线跑在自己的 **git worktree** 里。

**哪些是真的（实测，不是断言）：**

- 每个分支用 `git worktree add --detach <dir> HEAD` 创建一个真实的第二检出；跑完用 `git worktree remove --force` 删除，并执行 `git worktree prune`，所以不会在 `.git/worktrees/` 留下悬挂注册。
- 分支的候选代码会**真的写进**那个 worktree（默认文件名 `baize_swarm_candidate.py`，由 `BAIZE_SWARM_ARTIFACT` 配置）。
- `churn_lines` 由 worktree 内的 `git diff --cached --numstat` **实测**得出，不是预设常量。
- 如果配置了 `BAIZE_SWARM_VERIFY_CMD`，该命令会在 worktree 内真实执行，`verified` / `verify_exit_code` 如实报告结果。

**哪些是输入（不是测量）：**

- 三条策略的标题、策略描述和 `risk_score` 是调用方给出的**假设权重**，结果里用 `risk_score_is_input: true` 标明。
- **没配置验证命令时 `verified` 是 `null`（未检查），不是 `true`。** 选举顺序为：`verified is True` → `null` → `false`，同档再按 `risk_score`、`churn_lines` 排序。

**降级也是诚实的：** 如果当前路径不是含提交的 git 仓库，无法创建 worktree，此时会退化为普通临时目录，并在结果的 `isolation` 字段里写明 `scratch-dir-degraded`，不会声称拥有并未实现的 worktree 隔离。

### 8.2 评审票数门槛仲裁

```
调用方提供的评审意见 → 票数统计 → 门槛判定 + 可复现内容摘要
```

`baize/byzantine.py` **只做票数统计**：把调用方传入的 `verdicts` 按 `APPROVE` 计数，
与 `quorum`（默认 2）比较，并对 `goal + 目标代码摘要 + 票型` 计算 sha256 得到
`BFT-DIGEST-***`。

**⚠️ 诚实说明：它不启动任何 Agent、不分析代码、不做任何签名。**

- **不传 `verdicts` 时返回 `status="awaiting_verdicts"`，不返回任何裁决。**
  旧版本会在这里返回两条硬编码的 `APPROVE`，于是**任何输入（包括空字符串）都会"达成共识"**，
  而 `quorum >= 2` 对两条固定票永远成立——那个"全票"是 `2 >= 2` 算出来的，不是评审出来的。
- `target_code` 只被测量（字符数、行数、sha256 前缀），结果里的 `analysed: false`
  明确写出**它没有被分析**。
- `BFT-DIGEST-***` 是**内容摘要，不是签名**：没有密钥，也没有任何东西验证它。
  旧版本叫 `BFT-SIG-***`，并把 `time.time()` 混进哈希，所以每次调用结果都不同——
  连"内容摘要"都算不上。

### 8.3 假设性时间线分叉（当前为硬编码演示）

```bash
python -m baize speculative "这个重构方案能行吗"
```

对同一个目标并列展示多条候选时间线。

**⚠️ 诚实说明：`cmd_speculative` 是硬编码的演示 fixture。** 三条时间线的 `churn_lines`、`duration_ms`、`checks_passed/total_checks = 3/3`、以及 `status="verified"` 全部写在 `baize/cli.py` 里，没有生成任何代码、没有执行任何检查，"verified" 不代表任何东西被验证过。命令启动时会打印同样的提示。注意它和 8.1 的 `swarm.py` 是两条不同的代码路径——后者是真的。

### 8.4 Ralph 长程交付

```bash
python -m baize ralph "构建一个完整的博客系统" --max-iterations 10
python -m baize ralph --status      # 看 PRD 完成度看板
python -m baize ralph --resume      # 从已有 prd.json 继续
```

把大目标分解成 `prd.json`，然后按 PRD 迭代交付。

### 8.5 变异测试网与因果实验台

`baize/mutation.py` 的 `run_ast_mutation_arena(code, fn)` 是**真的跑**：

1. 用 `ast` 找出源码里可翻转的比较/算术运算符（`< <= > >= == != + -`）；
2. 对每个位点生成一个变异体源码（`ast.unparse`）；
3. 把**原始函数和每个变异体**都加载进 `baize/safe_exec.py` 的受限命名空间，
   用一组固定探针调用，比较返回值（异常按类型名比较）；
4. **至少一个探针结果不同 = killed；全都相同 = survived**；
   `mutation_score = killed / (killed + survived)`。

实测两个方向都有：

```
def f(x):                 return x + 0          -> 击杀率 0.0%   （+→- 无法被任何探针区分）
def check_score(s):       return True if s > 60 else False  -> 击杀率 100.0%（-1 探针即击杀）
```

**⚠️ 诚实说明：**

- 探针语料是**固定**的，不是从被测代码推导出来的，所以变异体可能仅仅因为"没有探针跨过它的边界"而存活。
  **击杀率只说明这些探针能否区分这些变异体，不代表代码正确。**
- 只翻转 8 个运算符；`*` `/` 被有意排除（在数值语料上它们多半死于 `ZeroDivisionError`，抬分不增信息）。
- 探针在**进程内**执行且没有墙钟上限，永不返回的目标函数会阻塞调用线程（`baize/tools.py` 的 `run_python` 才是子进程 + 超时）。
- 每次最多执行 25 个变异体，超出部分计入 `total_mutants_generated` 但不执行，并在 `limitations` 里写明。
- 没有任何可翻转位点时返回 `status="no_mutation_sites"` 且 `mutation_score=None`。
  **旧版本会在这里凭空造两个变异体并报 100%**，因为它算的是 `killed_count = len(mutants)`——
  一个 `n / n`，从未执行过任何变异体。

返回里的 `synthesized_guardrail_test` 是一个**可独立运行**的测试模块：它把被测源码原样嵌入，
断言来自**实测的探针输入/输出对**。它不是文本而已——生成时会把它分别对原始函数和每个被击杀的变异体
执行一遍（结果见 `guardrail_verification`），并且被 pytest 收集后能通过。

因果实验台 `/v30/causal` 是另一件事：它只做 **AST 切片**（函数行范围、节点类型、可疑参数）
并生成 4 条变异**用例描述符**，结果里 `mutations_executed: false` 明确写出**它们没有被执行**。
`/v30/causal/persist_test` 要求同时传入 `code`，写入的是上面那个 arena 的真实产物
（不是"把函数名替换进一个写死的 divide 模板"）；`target_function` 必须是合法 Python 标识符，
因为这个名字既进文件名也进写盘的源码；输出目录 `tests/generated/` 已加入 `.gitignore`。

---

## 9. 配置速查

| 配置键 | 默认值 | 作用 |
| :--- | :--- | :--- |
| `BAIZE_TEAM_MEMORY_BACKEND` | `local` | 共享黑板后端 |
| `BAIZE_CLARIFY` | `0` | 是否启用需求澄清 |
| `BAIZE_RECON_WEB` | `0` | recon 是否搜索外部生态 |
| `BAIZE_COMPONENTS` | 空 | 组件装配（composition kernel） |

---

## 本篇小结

- `baize team` 走五个阶段：**recon → planning → executing → verifying → retry**。
- **Verifier 是独立的一次 Agent 运行**，它看不到执行者的"自信"，只能看产出物——这是多 Agent 的核心价值。
- 验证失败会结构化落盘，`baize status <run-id>` 能查出 `failed`/`verified` 并给出 `next:` 建议。
- 角色间通过**带标签的共享黑板**交换信息（`finding`/`executed`/`blocker`/`recon`）。
- 任务认领曾有**真实竞态**（读-写分成两个临界区），修复后 40 轮对照实验从 8/40 降到 0/40。
- 子代理**按需授权**：只读任务拿不到写工具。
- `--resume` 跳过已验证任务，避免重复劳动。

## 下一篇预告

[08 · 看得见的工作](./08-看得见的工作.md) —— 桌面 Studio、REST 服务、指标端口、会话回放，以及怎么让运行过程"看得见"。
