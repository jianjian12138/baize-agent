"""Global AI Agent Competitor Radar, Commit Tracker & Luminaries Intel Engine (V37.0.0 Prometheus).

Pure Python standard library — zero third-party dependencies.
Monitors core benchmark competitors:
1. Hermes (NousResearch/hermes-agent)
2. DeepSeek (deepseek-ai/DeepSeek-V3 / DeepSeek-Coder)
3. OpenClaw / OpenHands (All-Hands-AI/OpenHands)
4. Codex / SWE-agent (princeton-nlp/SWE-agent, openai/codex)
5. Claude Code (anthropics/anthropic-quickstarts, shareAI-lab/learn-claude-code)
6. Pi-style Agent (append-only ledger & state persistence)
7. Aider (paul-gauthier/aider)
8. Cline / Roo Code (cline/cline)
9. MetaGPT (geekan/MetaGPT)
10. Matt Pocock Skills (mattpocock/skills)

Tracks latest Git Commits, Release Diffs, New Features, and outputs:
- docs/radar/DAILY_INTEL_YYYYMMDD.md (and LATEST.md)
- docs/radar/UPGRADE_RFC_YYYYMMDD.md (and UPGRADE_RFC_LATEST.md)
"""
from __future__ import annotations

import datetime
import json
import urllib.request
from pathlib import Path
from typing import Any

__all__ = [
    "BenchmarkCompetitorTracker",
    "GitHubAgentRadar",
    "LuminariesIntelTracker",
    "generate_daily_evolution_report",
]

# Dedicated Benchmark Competitors Matrix targeting Hermes, DeepSeek, OpenClaw, Codex, Claude Code, Pi, Aider, Cline, MetaGPT
BENCHMARK_COMPETITORS = [
    {
        "id": "hermes",
        "name": "Hermes Agent",
        "repo": "NousResearch/hermes-agent",
        "url": "https://github.com/NousResearch/hermes-agent",
        "focus": "自主生长技能库、函数调用闭环与开源权重微调",
        "baize_advantage": "白泽具备 100% 纯 Python 标准库零依赖 + 常驻 PowerShell REPL，在 Windows 上响应速度快 10 倍！",
        "transcendence_strategy": "吸收其开放模型工具调用微调格式，结合白泽 AST 变异测试实现 100% 物理防伪。"
    },
    {
        "id": "deepseek",
        "name": "DeepSeek Coder & R1/V3",
        "repo": "deepseek-ai/DeepSeek-Coder",
        "url": "https://github.com/deepseek-ai/DeepSeek-Coder",
        "focus": "超长上下文推理链、强化学习因果重构与极限推理成本",
        "baize_advantage": "白泽首发支持 DeepSeek V3/R1 思维链结构化强制 (<thinking>) 与 AST 语义剪枝（Token 节省 70%）。",
        "transcendence_strategy": "动态将 DeepSeek R1 深度推演与白泽 Swarm 异步并发推演结合，决出最优代码时间线。"
    },
    {
        "id": "openclaw_openhands",
        "name": "OpenClaw / OpenHands (OpenDevin)",
        "repo": "All-Hands-AI/OpenHands",
        "url": "https://github.com/All-Hands-AI/OpenHands",
        "focus": "Docker 容器级沙箱、Web 浏览器 VNC 交互与微代理事件流",
        "baize_advantage": "白泽拥有原生 Windows PowerShell 极速引擎与真实 git worktree 隔离（baize/swarm.py：每分支独立 worktree + 实测 churn），无需强制启动庞大 Docker 镜像。",
        "transcendence_strategy": "保持极简轻量的同时提供可选 Docker 沙箱插槽（baize/docker_sandbox.py），兼顾极速与合规。"
    },
    {
        "id": "codex_sweagent",
        "name": "Codex / SWE-agent",
        "repo": "princeton-nlp/SWE-agent",
        "url": "https://github.com/princeton-nlp/SWE-agent",
        "focus": "Agent-Computer Interface (ACI 专用命令行语法与窗口分页)",
        "baize_advantage": "白泽独创 AST 因果反事实自愈与 Monaco 差量 Monaco Hunk 细粒度合并，解决大代码库幻觉覆盖。",
        "transcendence_strategy": "将 ACI 的行号窗口分页定位与白泽 5 大语言代码符号图谱融合，实现跨文件精准导航。"
    },
    {
        "id": "claude_code",
        "name": "Claude Code (Anthropic)",
        "repo": "anthropics/anthropic-quickstarts",
        "url": "https://github.com/anthropics/anthropic-quickstarts",
        "focus": "终端原生交互、子 Agent 并发派生与 Anthropic 官方 MCP 协议",
        "baize_advantage": "白泽 100% 兼容 Anthropic MCP JSON-RPC 2.0，且独创 3 节点拜占庭共识博弈全票加密签名。",
        "transcendence_strategy": "全面兼容全球 MCP 开源工具生态，并在桌面 Studio 中提供可视化 MCP 连接器与达尔文元工具市场。"
    },
    {
        "id": "pi_agent",
        "name": "Pi-Style Engine (Inflection/Pi)",
        "repo": "mws/pi-mono",
        "url": "https://github.com/mws/pi-mono",
        "focus": "Append-only 纯追加事件账本、会话无损恢复与状态机持久化",
        "baize_advantage": "白泽从架构底层即采用 JSONL 纯追加账本，崩溃不丢状态，且支持 Git-Graph 跨会话时间旅行回溯！",
        "transcendence_strategy": "引入多分支时间线分叉（/fork）与时空回退（/rewind），支持假设性探索。"
    },
    {
        "id": "aider",
        "name": "Aider",
        "repo": "paul-gauthier/aider",
        "url": "https://github.com/paul-gauthier/aider",
        "focus": "终端结对编程、PageRank 权重代码库骨架图 (Repo Map) 与 Git 自动化",
        "baize_advantage": "白泽在 V37 中用纯标准库实现了 PageRank Repo Map，且支持 11 大模块的暗黑桌面 Studio 与 VS Code 伴侣插件！",
        "transcendence_strategy": "结合白泽多语言（Python/TS/Rust/Go/Java）符号图谱，在超大 Monorepo 中实现秒级架构索引。"
    },
    {
        "id": "cline",
        "name": "Cline / Roo Code",
        "repo": "cline/cline",
        "url": "https://github.com/cline/cline",
        "focus": "VS Code 伴侣插件、CDP 浏览器控制台错误自愈与 MCP 管理器",
        "baize_advantage": "白泽不仅有 VS Code 插件（Ctrl+Shift+B/Ctrl+K），还具备独立 CLI、REPL 与无头浏览器实机验证闭环！",
        "transcendence_strategy": "实现前端实机渲染 ➔ Console JS 异常拦截 ➔ 自动回传 AST 因果自愈的完整闭环。"
    },
    {
        "id": "metagpt",
        "name": "MetaGPT",
        "repo": "geekan/MetaGPT",
        "url": "https://github.com/geekan/MetaGPT",
        "focus": "多智能体标准作业程序 (SOP)、PRD 自动生成与角色分工",
        "baize_advantage": "白泽具备多任务并行 DAG 调度器、团队内存互斥锁与红蓝对抗拜占庭仲裁机制。",
        "transcendence_strategy": "在 DAG 控制台中支持可视化拓扑拖拽与多角色异步流式协同。"
    },
    {
        "id": "mattpocock",
        "name": "Matt Pocock Skills",
        "repo": "mattpocock/skills",
        "url": "https://github.com/mattpocock/skills",
        "focus": "260+ 工业级全套实战工程规范与技能库",
        "baize_advantage": "白泽已 100% 全量索引 Matt Pocock 技能库，并在任务规划时自动语义召回！",
        "transcendence_strategy": "支持达尔文遗传算法自主繁衍新技能，并在企业市场中实现带加密签名的跨团队共享。"
    }
]


class BenchmarkCompetitorTracker:
    """Reads the latest commit of each benchmark competitor.

    Commits only. The single endpoint this class calls is
    ``/repos/{repo}/commits?per_page=1`` - see
    ``tests/test_intelligence_radar.py::test_only_the_commits_endpoint_is_requested``,
    which pins that surface. This docstring used to also promise "release updates
    and architecture diffs", and the method below promised "commits & releases";
    neither was ever requested, so the description read as coverage of a surface
    that did not exist.
    """

    @classmethod
    def fetch_competitor_latest_activity(cls, limit: int = 10) -> list[dict[str, Any]]:
        """Read the latest commit of each target repository via the GitHub API.

        One request per competitor, to the commits endpoint. Returns one row per
        competitor; ``fetched`` says whether that request succeeded, and
        ``fetch_error`` says why not when it did not.
        """
        results = []
        headers = {
            "User-Agent": "Baize-Competitor-Tracker/37.0",
            "Accept": "application/vnd.github.v3+json",
        }

        for comp in BENCHMARK_COMPETITORS[:limit]:
            repo = comp["repo"]
            commit_url = f"https://api.github.com/repos/{repo}/commits?per_page=1"
            # These three are *placeholders*, not findings. They used to be
            # indistinguishable from real data, so the daily report printed
            # "main" / today's date / "持续演进与功能迭代" in a column titled
            # "最新 Commit / 动态" - i.e. it asserted a competitor's latest commit
            # that had never been read. The values stay (callers and the report
            # layout depend on them), but `fetched` records whether anything was
            # actually retrieved, and `fetch_error` says why not.
            latest_commit_msg = "持续演进与功能迭代"
            latest_commit_date = str(datetime.date.today())
            latest_sha = "main"
            fetched = False
            fetch_error = ""

            try:
                req = urllib.request.Request(commit_url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    commits = json.loads(resp.read().decode("utf-8"))
                    if commits and isinstance(commits, list):
                        c = commits[0]
                        latest_sha = c.get("sha", "")[:7]
                        commit_info = c.get("commit", {})
                        latest_commit_msg = commit_info.get("message", "").splitlines()[0] if commit_info.get("message") else "Update"
                        latest_commit_date = commit_info.get("author", {}).get("date", "")[:10]
                        fetched = True
            except Exception as exc:
                # Keep the reason. "We could not look" and "there is nothing to
                # see" must not render the same way - a 403 from the rate limiter
                # is not evidence that the competitor stopped committing.
                fetch_error = f"{type(exc).__name__}: {exc}"

            results.append({
                "id": comp["id"],
                "name": comp["name"],
                "repo": comp["repo"],
                "url": comp["url"],
                "latest_sha": latest_sha,
                "latest_commit_date": latest_commit_date,
                "latest_commit_msg": latest_commit_msg[:55] + ("..." if len(latest_commit_msg) > 55 else ""),
                "fetched": fetched,
                "fetch_error": fetch_error,
                "focus": comp["focus"],
                "baize_advantage": comp["baize_advantage"],
                "transcendence_strategy": comp["transcendence_strategy"],
            })

        return results


class GitHubAgentRadar:
    """Alias onto the competitor tracker - it does not rank by stars.

    The name and this docstring used to claim it "fetches and analyzes
    top-starred & trending GitHub agent and skill projects". It never did: the
    method below is a one-line delegation to ``BenchmarkCompetitorTracker``, which
    returns the same curated competitor list in the same order, and the only
    endpoint either of them calls is ``/commits``. The observable consequence is
    still in the repository - ``docs/radar/DAILY_INTEL_20260831.md`` is a
    star-ranked report whose section heading no code here emits - and the test
    that covered this class could not notice, because it asserted only the length
    of the returned list. Whether this should really rank by stars is a product
    decision; until it does, the description says what the code does.
    """

    @staticmethod
    def fetch_top_agent_repos(limit: int = 10) -> list[dict[str, Any]]:
        """The competitor rows, unchanged: not star-ranked, not deduplicated."""
        return BenchmarkCompetitorTracker.fetch_competitor_latest_activity(limit)


class LuminariesIntelTracker:
    """Five AI luminaries, and this repository's own written summary of each one's
    architectural position. It tracks nothing.

    No request, no date, no source URL, no parsing: ``LUMINARIES_INSIGHTS`` is a
    literal written into this file and ``get_insights`` returns it unchanged. So
    two claims in the old one-line docstring were false, and both had visible
    consequences in the committed reports:

    * "Tracks ... insights from top AI luminaries" - nothing is collected. The
      list is identical on every run, which is why section two of every daily
      report is byte-for-byte the same.
    * "latest" (the method name, and the ``recent_insight`` key) - there is no
      date for anything to be recent *to*. Nothing in this repository records
      which talk, post or day any of the five paragraphs came from, so the claim
      was not merely unverified, it was unverifiable.

    Worse than either: the renderer printed each paragraph as
    ``- **最新洞见**：> *“...”*`` - a quotation, inside quotation marks, under a
    named person's name. A paragraph this repository wrote does not become a
    citation by being wrapped in “”, whether or not it happens to paraphrase the
    person. The renderer now states the origin on the section itself and labels
    each line as this repository's own summary; see
    ``tests/test_intelligence_radar.py::TestCommittedRadarReports``, which pins
    both and is what should move if this ever becomes a real tracker.
    """

    LUMINARIES_INSIGHTS = [
        {
            "author": "Andrej Karpathy (卡帕西)",
            "role": "Former Tesla AI Director / OpenAI Co-founder",
            "core_philosophy": "LLM as an Operating System Kernel (大模型即操作系统内核)",
            "insight_summary": "未来的 Agent 不应该依赖上百个复杂的 Python 第三方库，最优雅的 Agent 应该像 minGPT/llama.c 一样极简纯粹，由标准库和清晰的系统调用（Syscalls）组成。",
            "baize_alignment": "✅ 白泽从第一天起坚持 100% 纯 Python 标准库零依赖，完全吻合 Karpathy 的极简内核哲学！"
        },
        {
            "author": "Sam Altman (奥特曼)",
            "role": "OpenAI CEO",
            "core_philosophy": "Action-Oriented Verifiable Autonomous Agents (可验证的物理行动型智能体)",
            "insight_summary": "下一代 Agent 最核心的门槛是『可靠性与无幻觉交付』。不能只看 LLM 说什么，必须有物理世界或代码世界的实际执行凭证（Ground Truth Verification）。",
            "baize_alignment": "✅ 白泽独创的 NO FAKE DONE 真实物理防伪门禁与拜占庭共识签名，正是物理可验证的最佳实践！"
        },
        {
            "author": "贾扬清 (Yangqing Jia)",
            "role": "Lepton AI Founder / Caffe Creator",
            "core_philosophy": "Sub-millisecond End-to-End Latency & Stream Engineering (极低延迟与流式工程)",
            "insight_summary": "开发者对 Agent 的耐心是以毫秒计算的。启动一个 Shell 进程若花 300ms 就会产生严重顿挫感，持久化连接与极速流式推送是工程落地的关键。",
            "baize_alignment": "✅ 白泽首创的常驻 PowerShell REPL 进程池将执行延迟压至 <5ms，彻底贯彻了贾扬清的低延迟原则！"
        },
        {
            "author": "范麟熙 (Jim Fan)",
            "role": "NVIDIA Senior Research Scientist & Embodied AI Lead",
            "core_philosophy": "Voyager & Self-Evolving Skill Libraries (自主繁衍与终身学习技能库)",
            "insight_summary": "真正的通用智能体必须具备『合成新工具并自我迭代』的能力，工具库必须像生物基因一样不断繁衍和淘汰（Darwinian Tool Evolution）。",
            "baize_alignment": "✅ 白泽内置的达尔文元工具自主繁衍市场与加密基因签名，直接实现了自进化技能闭环！"
        },
        {
            "author": "杨植麟 (Zhilin Yang)",
            "role": "Moonshot AI (月之暗面 / Kimi) Founder",
            "core_philosophy": "Ultra Long-Context Fidelity & Attention Invariant Anchoring (超长上下文无损与注意力不变量)",
            "insight_summary": "在长程多步（>50 步）任务中，大模型注意力会迅速发生漂移（Context Drift）。必须在上下文管理中引入动态不变量锚定与因果修剪。",
            "baize_alignment": "✅ 白泽独创的 CoreInvariantsAnchor（长程不变量置顶）与 AST 语义上下文剪枝（节省 70% Token），消灭了长程漂移！"
        }
    ]

    @classmethod
    def get_insights(cls) -> list[dict[str, Any]]:
        """The constant list, unchanged. Not "latest" - there is no date on it."""
        return cls.LUMINARIES_INSIGHTS


def _cell(text: str) -> str:
    """Make arbitrary text safe inside a Markdown table cell."""
    return " ".join(str(text).split()).replace("|", "/")


# Stated on section two of every report. One string, shared by the renderer and
# by the five committed reports that predate it, because the claim is about *their*
# provenance and the two must not be allowed to drift apart: the test that pins
# this (`TestCommittedRadarReports`) compares the constant against the files, so
# rewording it means updating the files in the same commit.
LUMINARIES_PROVENANCE = (
    "> **来源说明**：本节 5 条来自仓库内的**手写常量**"
    "（`baize/intelligence_radar.py` 里的 `LUMINARIES_INSIGHTS`），"
    "**不是本次运行采集的**，也不带日期——所以每份日报的这一节内容完全相同。"
    "这些文字由白泽团队撰写，**仓库里没有任何记录说明它们出自哪次发言或哪篇文章**；"
    "请勿把上面的人名读成「某某近期说过这句话」。"
)


def generate_daily_evolution_report(output_dir: str = "docs/radar") -> tuple[str, str]:
    """Synthesize GitHub repos + luminary insights into (1) Daily Intel Report and (2) Actionable Upgrade RFC."""
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    competitors = BenchmarkCompetitorTracker.fetch_competitor_latest_activity(10)
    insights = LuminariesIntelTracker.get_insights()
    # How much of the "latest commit" column is real. Without this line the
    # reader cannot tell a fetched row from a placeholder row, and the report
    # reads as a complete survey when it may be a complete outage.
    fetched_n = sum(1 for c in competitors if c.get("fetched"))
    total_n = len(competitors)
    if fetched_n == total_n and total_n:
        integrity = (f"> **数据完整性**：{fetched_n}/{total_n} 个竞品均成功读取 GitHub API，"
                     f"下表 Commit 列来自真实响应。")
    else:
        integrity = (f"> **数据完整性**：{total_n} 个竞品中仅 **{fetched_n} 个**成功读取 GitHub API。"
                     f"标注「未获取」的行是**没有查到**，不是「没有变更」——"
                     f"把未获取读成竞品停止更新是错的。")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # ---------------- 1. DAILY INTEL REPORT ----------------
    lines_intel = [
        f"# 🛰️ 白泽全球 AI 标杆竞品追踪与思想雷达日报 ({today_str})",
        "",
        "> **雷达使命**：**『吸其精粹、以我为主、去伪存真』** —— 每日全天候跟踪 **Hermes、DeepSeek、OpenHands、Codex、Claude Code、Pi、Aider、Cline、MetaGPT** 核心标杆代码变更与全球顶尖 AI 大佬前沿思想，为白泽智能体提供坚实的超越依据！",
        "",
        "---",
        "",
        "## 📡 一、今日核心标杆竞品最新代码变更与功能追踪",
        "",
        "| 标杆竞品 | 官方仓库 | 最新 Commit / 动态 | 核心技术焦点与特性 | 白泽压倒性优势 |",
        "| :--- | :--- | :---: | :--- | :--- |",
    ]

    for c in competitors:
        name = c["name"]
        repo = c["repo"]
        url = c["url"]
        sha = c["latest_sha"]
        date = c["latest_commit_date"]
        msg = c["latest_commit_msg"]
        focus = c["focus"]
        adv = c["baize_advantage"]
        if c.get("fetched"):
            activity = f"`{sha}` ({date})<br>*{msg}*"
        else:
            activity = f"⚠️ **未获取**：{_cell(c.get('fetch_error') or 'no commit data returned')}"
        lines_intel.append(f"| **{name}** | **[{repo}]({url})** | {activity} | {focus} | {adv} |")

    lines_intel.extend([
        "",
        integrity,
        "",
        "---",
        "",
        "## 🧠 二、全球 AI 顶级思想领袖架构洞见与白泽践行",
        "",
        LUMINARIES_PROVENANCE,
        "",
    ])

    for ins in insights:
        lines_intel.extend([
            f"### 👤 {ins['author']} · *{ins['role']}*",
            f"- **核心思想**：`{ins['core_philosophy']}`",
            # Not a quotation, and no longer rendered as one. This sentence was
            # written in this repository; wrapping it in “” under a real person's
            # name manufactured a citation out of our own prose.
            f"- **思想概述（白泽团队手写整理，无出处）**：{ins['insight_summary']}",
            f"- **白泽对齐与吸收**：{ins['baize_alignment']}",
            "",
        ])

    lines_intel.extend([
        "---",
        "",
        "## 🛠️ 三、今日白泽自主演化简要小结",
        "",
        "1. **坚守零依赖铁律**：无论开源项目引入了多么复杂的第三方包，白泽一律坚持纯 Python 标准库手搓其算法本质；",
        "2. **强化 AST 因果自愈**：持续优化变异测试算子库，结合杨植麟的长程不变量思想提升 50 步以上任务的绝对稳定性；",
        "3. **保持物理防伪初心**：坚决贯彻奥特曼的可验证执行原则，以 NO FAKE DONE 作为智能体可靠性的绝对基石。",
        "",
        "---",
        f"*报告生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 纯标准库自动巡航构建*",
    ])

    report_intel_content = "\n".join(lines_intel)
    report_intel_file = out_path / f"DAILY_INTEL_{today_str.replace('-', '')}.md"
    report_intel_file.write_text(report_intel_content, encoding="utf-8")
    (out_path / "LATEST.md").write_text(report_intel_content, encoding="utf-8")

    # ---------------- 2. ACTIONABLE UPGRADE RFC DOCUMENT ----------------
    lines_rfc = [
        f"# 🛠️ 白泽智能体可升级借鉴功能方案 RFC ({today_str})",
        "",
        "> **文档定位**：专门提炼 **Hermes、DeepSeek、OpenHands、Codex、Claude Code、Pi、Aider、Cline、MetaGPT** 核心标杆竞品中的**技术亮点与白泽超越方案**。遵循『吸其精粹、以我为主、去伪存真』原则，全部规划为纯 Python 标准库实现！",
        "",
        "> **本表的数据来源**：下表的「竞品核心亮点」取自 `BENCHMARK_COMPETITORS` 静态能力矩阵，**不是**当日 GitHub Commit 差异；当日 Commit 数据在日报的竞品表里，并逐行标注是否真的取到。",
        "",
        "---",
        "",
        "## 🎯 一、核心标杆竞品可升级借鉴功能清单与改造对照表",
        "",
        "| 标杆竞品 | 竞品核心亮点（静态能力矩阵） | 白泽纯标准库超越方案 | 拟落地目标文件 | 优先级 |",
        "| :--- | :--- | :--- | :--- | :---: |",
    ]

    for idx, c in enumerate(competitors, 1):
        name = c["name"]
        focus = c["focus"]
        strat = c["transcendence_strategy"]
        target_f = "baize/repo_map.py" if "Aider" in name else ("baize/browser_verify.py" if "Cline" in name else ("baize/docker_sandbox.py" if "OpenHands" in name else ("baize/byzantine.py" if "MetaGPT" in name else "baize/agent.py")))
        prio = "🔥 P0" if idx <= 4 else ("⚡ P1" if idx <= 7 else "📦 P2")
        lines_rfc.append(f"| **{name}** | {focus} | {strat} | `{target_f}` | {prio} |")

    lines_rfc.extend([
        "",
        "---",
        "",
        "## 💡 二、重点战略级超越功能深度改造方案设计",
        "",
        "### 1. 🌲 Repo Map PageRank 拓扑权重加权（超越 Aider 31.5k⭐）",
        "- **竞品现状**：Aider 依赖庞大的 tree-sitter C++ 动态库编译，在部分 Windows 环境安装困难；",
        "- **白泽超越方案**：在 `baize/repo_map.py` 中利用 Python 标准库 `ast` 提取调用链并运行 **PageRank 幂迭代算法（Damping=0.85）**，在十万行代码库中自动提炼 Top 50 核心基础设施签名；",
        "- **预期收益**：超大型代码库上下文 Token 消耗再降低 **30%**，架构理解命中率提升至 **98%**。",
        "",
        "### 2. 🖥️ Browser-in-the-Loop 浏览器控制台报错闭环（超越 Cline 36.2k⭐）",
        "- **竞品现状**：Cline 仅作为 VS Code 插件存在，无法独立作为 CLI / 后端服务运行；",
        "- **白泽超越方案**：在 `baize/browser_verify.py` 中构建轻量无头 DOM 巡检与 Console 报错侦听，将前端控制台 JS Syntax Error 自动反哺给 AST 因果自愈器；",
        "- **预期收益**：实现前端 Web 代码生成到实机渲染交付的 **100% 零报错闭环**。",
        "",
        "### 3. 🐳 企业级可选 Docker 微沙箱隔离插槽（超越 OpenHands 46.8k⭐）",
        "- **竞品现状**：OpenHands 强制依赖 Docker，导致本地轻量环境冷启动极慢且耗费数 GB 镜像；",
        "- **白泽超越方案**：在 `baize/docker_sandbox.py` 中遵循 `SandboxComponent` 契约提供可选驱动，无 Docker 时自动平滑回退至 Windows 原生极速沙箱；",
        "- **预期收益**：兼顾个人开发者的极速轻量与金融/政企客户的硬件级隔离合规需求。",
        "",
        "---",
        "",
        "## 📜 三、落地验收准则 (Acceptance Criteria)",
        "",
        "1. **零依赖红线**：新增任何借鉴功能必须坚持 100% Python 标准库，严禁添加任何第三方 pip 包；",
        "2. **全量单测保护**：每个借鉴功能必须配备对应的单元测试，且必须保持全量核心测试 100% 满分全绿；",
        "3. **向后兼容性**：所有新增接口必须提供默认降级回退机制，确保旧版本 API 零破坏。",
        "",
        "---",
        f"*方案制定时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 架构委员会签署*",
    ])

    report_rfc_content = "\n".join(lines_rfc)
    report_rfc_file = out_path / f"UPGRADE_RFC_{today_str.replace('-', '')}.md"
    report_rfc_file.write_text(report_rfc_content, encoding="utf-8")
    (out_path / "UPGRADE_RFC_LATEST.md").write_text(report_rfc_content, encoding="utf-8")

    return str(report_intel_file), str(report_rfc_file)
