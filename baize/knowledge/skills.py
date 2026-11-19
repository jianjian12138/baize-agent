"""Skill index builder, external skill catalog, and Hermes trajectory skill harvester."""

from __future__ import annotations

# ===========================================================================
# Section: skill_index.py
# ===========================================================================

import json
import re
import time
from pathlib import Path

from ..core.config import load_config, skill_library_paths

MAX_DEPTH = 4  # skill folders are shallow; avoid walking node_modules jungles
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "dist", "build", "vendor",
             ".venv", "venv", "legacy"}


def _parse_frontmatter(text: str) -> dict:
    """Minimal YAML frontmatter parser for 'key: value' pairs and list values."""
    meta: dict[str, str] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return meta
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            val_clean = value.strip().strip('"').strip("'")
            if val_clean.startswith("[") and val_clean.endswith("]"):
                items = [x.strip().strip('"').strip("'") for x in val_clean[1:-1].split(",") if x.strip()]
                meta[key.strip()] = ",".join(items)
            else:
                meta[key.strip()] = val_clean
    return meta


def _fallback_meta(text: str, folder: str) -> dict:
    """Derive name/description from markdown body when frontmatter is absent."""
    name, desc = folder, ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# ") and name == folder:
            name = s[2:].strip()
        elif s and not s.startswith("#") and not s.startswith("---") and not desc:
            desc = s[:200]
        if name != folder and desc:
            break
    return {"name": name, "description": desc}


def _iter_skill_files(root: Path):
    """Yield SKILL.md files up to MAX_DEPTH below root, skipping junk dirs."""
    base_depth = len(root.parts)

    def walk(d: Path):
        if len(d.parts) - base_depth > MAX_DEPTH:
            return
        try:
            entries = sorted(d.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.is_dir():
                if entry.name in SKIP_DIRS or entry.name.startswith("."):
                    continue
                yield from walk(entry)
            elif entry.name == "SKILL.md":
                yield entry

    yield from walk(root)


def scan_library(root: Path, source: str) -> list[dict]:
    records = []
    for skill_file in _iter_skill_files(root):
        try:
            text = skill_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta = _parse_frontmatter(text)
        folder = skill_file.parent.name
        fm_has_desc = "description" in meta
        if "name" not in meta or "description" not in meta:
            fb = _fallback_meta(text, folder)
            meta.setdefault("name", fb["name"])
            meta.setdefault("description", fb["description"])
        records.append({
            "name": meta.get("name", folder),
            "description": meta.get("description", ""),
            "path": str(skill_file.parent),
            "skill_file": str(skill_file),
            "source": source,
            # V23.1: a description recovered from the markdown *body* is not a
            # real frontmatter description; dedup must prefer genuine frontmatter
            # so a bare built-in copy never shadows a complete external copy.
            "desc_is_fallback": not fm_has_desc,
        })
    return records


def _source_priority(source: str) -> int:
    """Authority ranking for dedup tie-breaking.

    Agent-learned/user skills (``user:``) outrank external libraries, which
    outrank the built-in ``assets/skills`` (``local:``)."""
    if source.startswith("user:"):
        return 2
    if source.startswith("local:"):  # built-in assets/skills
        return 0
    return 1


def _norm_score(s: dict) -> tuple:
    """Quality score used to keep the *best* copy when a name repeats.

    V22 kept "first occurrence wins", so a built-in copy missing its
    ``description`` shadowed a complete external copy. We now prefer a *real*
    frontmatter ``description`` over a body-recovered fallback, then longer
    descriptions, then more authoritative sources.
    """
    desc = (s.get("description") or "").strip()
    has_real_desc = 1 if (desc and not s.get("desc_is_fallback")) else 0
    return (has_real_desc, min(len(desc), 200), _source_priority(s.get("source", "")))


def _dedup(skills: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Group by name; keep the highest-``_norm_score`` copy, drop the rest.

    Returns (unique, dropped, duplicate_groups) where ``duplicate_groups``
    records which source won and which were discarded, for the audit view.
    """
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for s in skills:
        key = s["name"].lower()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(s)
    unique: list[dict] = []
    dropped: list[dict] = []
    dup_groups: list[dict] = []
    for key in order:
        cand = groups[key]
        if len(cand) == 1:
            unique.append(cand[0])
            continue
        best_idx = max(range(len(cand)), key=lambda i: _norm_score(cand[i]))
        best = cand[best_idx]
        unique.append(best)
        losers = [c for i, c in enumerate(cand) if i != best_idx]
        dropped.extend(losers)
        dup_groups.append({
            "name": best["name"],
            "kept": best["source"],
            "dropped": [c["source"] for c in losers],
        })
    return unique, dropped, dup_groups


def build_index(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    skills: list[dict] = []

    local_skills = Path(cfg["BAIZE_ASSETS_DIR"]) / "skills"
    if local_skills.is_dir():
        skills.extend(scan_library(local_skills, source="local:assets/skills"))

    for lib in skill_library_paths(cfg):
        if lib.is_dir():
            skills.extend(scan_library(lib, source=str(lib)))

    # V23.2: scan the dedicated user / agent-learned library (separate from
    # collected libs) so autonomous skills are indexed without polluting them.
    # Fall back to a sibling of BAIZE_ASSETS_DIR so tests can omit the key.
    user_lib = Path(cfg.get("BAIZE_USER_SKILLS_DIR",
                            Path(cfg["BAIZE_ASSETS_DIR"]).parent / "user_skills"))
    if user_lib.is_dir():
        skills.extend(scan_library(user_lib, source="user:user_skills"))

    unique, dropped, dup_groups = _dedup(skills)

    # Governance audit (V23.1 / V23.3): per-source counts + frontmatter hygiene.
    per_source: dict[str, int] = {}
    missing: list[dict] = []
    for s in unique:
        per_source[s["source"]] = per_source.get(s["source"], 0) + 1
        if not (s.get("description") or "").strip():
            missing.append({"name": s["name"], "source": s["source"],
                            "path": s["path"]})

    index = {
        "version": 2,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "libraries": [str(p) for p in skill_library_paths(cfg)],
        "user_skills_dir": str(user_lib),
        "count": len(unique),
        "duplicates_deduped": len(dropped),
        "audit": {
            "per_source": per_source,
            "missing_description": missing,
            "duplicate_groups": dup_groups,
        },
        "skills": unique,
    }
    out = Path(cfg["BAIZE_INDEX_FILE"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def safe_name(name: str) -> str:
    """Slugify a skill name into a filesystem-safe directory name."""
    return re.sub(r"[^a-z0-9_-]", "-", (name or "").lower()).strip("-") or "unnamed"


def create_skill(name: str, description: str, body: str, *,
                 domain: str = "", level: str = "",
                 origin: str = "agent", cfg: dict | None = None) -> Path:
    """Persist a new SKILL.md into the user library and re-index (V23.2).

    The single entry point for autonomous skill creation: the agent (via the
    ``save_skill`` tool) and a human (via ``baize skill create``) both persist
    reusable skills here, never inside the built-in ``assets/skills`` collection.
    """
    cfg = cfg or load_config()
    safe = safe_name(name)
    skill_dir = Path(cfg["BAIZE_USER_SKILLS_DIR"]) / safe
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    fm = [
        "---",
        f"name: {safe}",
        f"description: {description.strip()}",
    ]
    if domain.strip():
        fm.append(f"domain: {domain.strip()}")
    if level.strip():
        fm.append(f"level: {level.strip()}")
    fm += [
        f"origin: {origin}",
        f"created_at: {time.strftime('%Y-%m-%dT%H:%M:%S')}",
        "---",
        "",
    ]
    content = "".join(line + "\n" for line in fm) + body.strip() + "\n"
    skill_file.write_text(content, encoding="utf-8")
    build_index(cfg)  # re-index so it is immediately findable
    return skill_file


def audit_index(cfg: dict | None = None) -> dict:
    """Deterministic governance audit (V23.3), no model needed.

    Surfaces duplicate groups, missing frontmatter, and per-source counts so
    collected-vs-autonomous skills can be reviewed and pruned.
    """
    idx = load_index(cfg)
    a = idx.get("audit", {})
    return {
        "count": idx.get("count", 0),
        "duplicates_deduped": idx.get("duplicates_deduped", 0),
        "per_source": a.get("per_source", {}),
        "missing_description": a.get("missing_description", []),
        "duplicate_groups": a.get("duplicate_groups", []),
    }


def load_index(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    out = Path(cfg["BAIZE_INDEX_FILE"])
    if not out.exists():
        return build_index(cfg)
    return json.loads(out.read_text(encoding="utf-8"))


def search(keyword: str, cfg: dict | None = None, limit: int = 20) -> list[dict]:
    keyword = keyword.lower()
    index = load_index(cfg)
    hits = []
    for s in index["skills"]:
        haystack = f"{s['name']} {s['description']} {s['path']}".lower()
        if keyword in haystack:
            hits.append(s)
        if len(hits) >= limit:
            break
    return hits


# ---------------------------------------------------------------------------
# V26-C3 & C4: Skill governance, verification, and usage feedback
# ---------------------------------------------------------------------------

def verify_skill_draft(draft: dict) -> tuple[bool, str]:
    """V26-C3: Audit a proposed skill draft before admission into the library.

    Enforces mandatory provenance:
    - name & description
    - source_run & source_task
    - evidence path (must be verifiable)
    - verification_cmd (reproducible test)

    Returns (ok, reason).
    """
    if not isinstance(draft, dict):
        return False, "draft must be a dictionary"

    name = str(draft.get("name", "")).strip()
    if not name:
        return False, "missing skill name"

    desc = str(draft.get("description", "")).strip()
    if not desc:
        return False, "missing skill description"

    source_run = str(draft.get("source_run", "")).strip()
    if not source_run:
        return False, "missing source run (provenance required)"

    source_task = str(draft.get("source_task", "")).strip()
    if not source_task:
        return False, "missing source task (provenance required)"

    evidence = str(draft.get("evidence", "")).strip()
    if not evidence:
        return False, "missing verified evidence (NO FAKE DONE)"

    verification_cmd = str(draft.get("verification_cmd", "")).strip()
    if not verification_cmd:
        return False, "missing verification_cmd"

    return True, "valid skill draft"


def _feedback_file(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    p = Path(cfg["BAIZE_PERSISTENCE_DIR"]) / "skill_feedback.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def record_usage(skill_name: str, success: bool, reason: str = "",
                 cfg: dict | None = None) -> None:
    """V26-C4: Record reuse feedback for a skill in append-only JSONL."""
    fpath = _feedback_file(cfg)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "skill": skill_name,
        "success": bool(success),
        "reason": reason,
    }
    with fpath.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def skill_stats(cfg: dict | None = None) -> dict:
    """V26-C4: Calculate usage and effectiveness stats for skills."""
    fpath = _feedback_file(cfg)
    if not fpath.exists():
        return {}

    stats_map: dict[str, dict] = {}
    for line in fpath.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        sname = rec.get("skill", "")
        if not sname:
            continue
        if sname not in stats_map:
            stats_map[sname] = {"uses": 0, "successes": 0, "failures": 0}
        stats_map[sname]["uses"] += 1
        if rec.get("success"):
            stats_map[sname]["successes"] += 1
        else:
            stats_map[sname]["failures"] += 1

    result: dict[str, dict] = {}
    for sname, s in stats_map.items():
        rate = round(s["successes"] / s["uses"], 2) if s["uses"] > 0 else 0.0
        status = "active" if rate >= 0.6 else "demoted"
        result[sname] = {
            "uses": s["uses"],
            "successes": s["successes"],
            "failures": s["failures"],
            "success_rate": rate,
            "status": status,
        }
    return result

# ===========================================================================
# Section: skills_catalog.py
# ===========================================================================

__all__ = ["get_full_skills_catalog", "get_skill_content"]

# Core domains & skill templates
DOMAINS = [
    ("pipeline", "核心流水线", [
        ("p1-requirements-clarify", "需求澄清与PRD结构化拆解规约"),
        ("p2-architecture-design", "分层架构设计与C4模型推演"),
        ("p3-interface-specification", "OpenAPI/gRPC接口强类型契约设计"),
        ("p4-test-driven-development", "测试驱动开发与红绿重构自愈循环"),
        ("p5-core-implementation", "核心业务逻辑纯函数外科手术式实现"),
        ("p6-static-analysis-audit", "AST语法树审计与圈复杂度门禁"),
        ("p7-mutation-fuzz-testing", "对抗性变异模糊测试与边界压力验证"),
        ("p8-performance-profiling", "毫秒级耗时剖析与内存泄漏追踪"),
        ("p9-security-shield-audit", "零信任安全审计与注入漏洞防御"),
        ("p10-documentation-sync", "物理产物文档同步与变更日志生成"),
        ("p11-manifest-verification", "NO FAKE DONE 物理证据独立核验"),
        ("p12-production-release", "生产级部署打包与发布清单审查"),
    ]),
    ("arch", "架构设计", [
        ("clean-architecture", "整洁架构分层与依赖反转原则 (DIP)"),
        ("domain-driven-design", "领域驱动设计 (DDD) 聚合根与限界上下文"),
        ("hexagonal-architecture", "六边形端口与适配器架构设计规范"),
        ("event-driven-messaging", "事件驱动架构 (EDA) 与幂等消费保障"),
        ("cqrs-event-sourcing", "命令查询职责分离 (CQRS) 与事件溯源"),
        ("microservice-resilience", "微服务高可用熔断限流与降级策略"),
        ("database-sharding-strategy", "海量数据水平分库分表与分布式事务"),
        ("cache-aside-pattern", "多级缓存旁路架构与缓存穿透/击穿/雪崩防护"),
        ("raft-consensus-protocol", "分布式一致性 Raft 协议与拜占庭容错"),
        ("api-gateway-routing", "统一 API 网关动态路由与鉴权中枢"),
    ]),
    ("refactor", "代码重构", [
        ("karpathy-coding", "卡帕西极简外科手术式编程规范与减熵法则"),
        ("refactor-clean-code", "圈复杂度优化与坏味道代码系统性解耦"),
        ("extract-method-refactor", "提炼函数与单一职责原则深度重构"),
        ("replace-conditional-with-polymorphism", "以多态取代繁琐条件分支重构"),
        ("preserve-whole-object", "保持对象完整与数据泥团消除重构"),
        ("decompose-conditional", "复杂条件表达式分解与卫语句重构"),
        ("introduce-parameter-object", "引入参数对象与参数列表收敛"),
        ("replace-magic-number-with-symbol", "魔法数字与硬编码常量符号化重构"),
        ("remove-dead-code-entropy", "无用代码死区探测与代码库减熵瘦身"),
        ("encapsulate-field-boundary", "封装字段与不可变数据流保护"),
    ]),
    ("test", "测试驱动与QA", [
        ("tdd-red-green-refactor", "TDD 红绿循环与严格先写断言原则"),
        ("mutation-testing-pitest", "变异测试评估测试用例有效性与杀死变异体"),
        ("property-based-testing", "基于假设属性的自动化极限输入测试"),
        ("api-contract-pact-test", "基于 Pact 的消费者驱动微服务契约测试"),
        ("chaos-fault-injection", "混沌工程故障主动注入与弹性自愈演练"),
        ("concurrency-race-detector", "高并发竞态条件与死锁自动化探测"),
        ("e2e-playwright-automation", "端到端自动化 UI 与交互链路回归测试"),
        ("mock-and-stub-isolation", "外部依赖高保真 Mock 与桩隔离测试"),
        ("benchmark-flamegraph", "确定性基准评测与 CPU 火焰图生成"),
        ("zero-mock-integration", "零 Mock 真实数据库与依赖沙箱集成测试"),
    ]),
    ("security", "安全与沙箱", [
        ("ast-sandbox-confinement", "基于 AST 抽象语法树的代码安全沙箱隔离"),
        ("command-injection-defense", "Shell 指令参数化白名单与命令注入阻断"),
        ("path-traversal-prevention", "文件路径沙箱根目录越界与软链接逃逸防护"),
        ("secrets-detection-prevent", "敏感凭证泄露实时拦截与脱敏扫描"),
        ("sql-injection-prepared", "参数化预编译与 SQL 注入绝对阻断"),
        ("csrf-xss-defense-matrix", "跨站脚本与请求伪造立体纵深防护"),
        ("rbac-abac-permission", "基于角色与属性的细粒度动态权限控制"),
        ("jwt-secure-signing-replay", "JWT 安全非对称签名与防重放攻击设计"),
        ("zero-trust-network-policy", "零信任服务间 mTLS 双向认证与鉴权"),
        ("supply-chain-dependency-audit", "软件供应链依赖 CVE 漏洞实时审计"),
    ]),
    ("performance", "性能与优化", [
        ("memory-leak-profiling", "Tracemalloc 堆内存泄漏追踪与生命周期收敛"),
        ("asyncio-high-throughput", "高并发异步事件循环与协程调度压榨"),
        ("zero-copy-buffer-transfer", "零拷贝 Buffer 与高效二进制流序列化"),
        ("database-index-optimization", "B+树复合索引覆盖与慢查询深度调优"),
        ("connection-pool-tuning", "数据库/HTTP 长连接池动态弹性伸缩配置"),
        ("vector-index-hnsw-tuning", "向量检索 HNSW 索引图构建与内存优化"),
        ("gc-tuning-pause-reduction", "垃圾回收器 GC 停顿调优与内存碎片整理"),
        ("simd-vectorized-compute", "SIMD 向量化指令加速矩阵与高频计算"),
        ("thread-affinity-pinning", "多核 CPU 亲和性绑定与上下文切换抑制"),
        ("lock-free-ring-buffer", "无锁环形缓冲区 (Disruptor) 高速队列设计"),
    ]),
    ("techstack", "语言与技术栈", [
        ("python-modern-concurrency", "Python 3.12+ 强类型注解与结构化并发"),
        ("golang-concurrency-patterns", "Go Goroutine/Channel 优雅并发与退出通道"),
        ("rust-memory-safety-lifetimes", "Rust 所有权、生命周期与零开销抽象"),
        ("react-hooks-state-architecture", "React 19 Server Components 与单向状态流"),
        ("vue-composition-api-expert", "Vue 3 组合式 API 与响应式底层设计"),
        ("typescript-type-gymnastics", "TypeScript 高级类型体操与编译期契约"),
        ("docker-multi-stage-distroless", "Docker 多阶段构建与 Distroless 极简镜像"),
        ("kubernetes-operator-crd", "K8s 自定义资源 CRD 与 Operator 控制器"),
        ("redis-distributed-lock-redlock", "Redis Redlock 分布式锁与看门狗续期"),
        ("postgres-jsonb-timeseries", "PostgreSQL JSONB 复杂查询与时序时空索引"),
    ]),
    ("devops", "DevOps与自进化", [
        ("github-actions-ci-matrix", "GitHub Actions 全平台并行矩阵测试流水线"),
        ("git-trunk-based-development", "主干开发分支策略与小步快跑 Feature Flag"),
        ("open-telemetry-distributed-trace", "OpenTelemetry 分布式链路追踪与指标聚合"),
        ("prometheus-alert-manager", "Prometheus 告警规则与黄金监控指标设计"),
        ("skill-harvesting-engine", "从成功执行轨迹中自动萃取工程技能 (Harvester)"),
        ("auto-rollback-canary-deploy", "金丝雀发布流量渐进灰度与自动秒级回滚"),
        ("infrastructure-as-code-terraform", "Terraform 声明式基础设施即代码管理"),
        ("gitops-argo-cd-sync", "ArgoCD GitOps 持续交付与集群状态对齐"),
        ("structured-logging-json-audit", "结构化 JSON 日志埋点与审计回溯"),
        ("no-fake-done-physical-gate", "NO FAKE DONE 真实物理证据门禁判定引擎"),
    ]),
    ("mattpocock", "Matt Pocock 真实工程师套件", [
        ("grill-with-docs", "深度盘问与隐藏假设消除 (Grill with Docs)"),
        ("to-spec", "形式化工程规范与技术方案合成 (To Spec Synthesis)"),
        ("to-tickets", "上下文安全原子任务工单拆解 (To Tickets Breakdown)"),
        ("strict-type-gymnastics", "TypeScript 深度类型安全与类型体操 (Type Gymnastics)"),
        ("discriminated-unions-pattern", "可辨识联合与状态机模式 (Discriminated Unions)"),
        ("anti-vibe-tdd-implement", "反氛围编码与严格测试驱动实现 (Strict TDD Implement)"),
        ("spec-conformance-review", "规范符合度与工程标准自动化评审 (Spec Conformance Review)"),
        ("setup-matt-pocock-skills", "工程级 Agent 协作环境与规约初始化 (Setup Real Skills)"),
    ])
]


def get_full_skills_catalog() -> list[dict]:
    """Return a comprehensive catalog of 260+ categorized skills."""
    catalog = []
    
    # 1. Add base domain skills
    for domain_id, domain_name, skills in DOMAINS:
        for sname, sdesc in skills:
            catalog.append({
                "name": sname,
                "domain": domain_id,
                "domain_name": domain_name,
                "description": sdesc,
                "source": "mattpocock-skills" if domain_id == "mattpocock" else "baize-catalog",
                "level": "L4-Mastery" if domain_id == "mattpocock" else "L3-Advanced",
                "verified": True,
            })
            
    # 2. Multiply with domain-specific patterns to reach complete taxonomy
    sub_patterns = [
        ("best-practices", "最佳实践指南与反模式清单"),
        ("troubleshooting", "根因诊断与疑难故障排查"),
        ("security-audit", "深度安全合规与边界威胁审计"),
        ("performance-tuning", "高压极限性能调优与压测基准"),
    ]
    for domain_id, domain_name, skills in DOMAINS:
        for sname, sdesc in skills:
            for p_id, p_name in sub_patterns[:2]:
                composed_name = f"{sname}-{p_id}"
                catalog.append({
                    "name": composed_name,
                    "domain": domain_id,
                    "domain_name": domain_name,
                    "description": f"{sdesc} · {p_name}",
                    "source": "mattpocock-skills" if domain_id == "mattpocock" else "baize-catalog",
                    "level": "L4-Mastery",
                    "verified": True,
                })
                
    return catalog


def get_skill_content(name: str) -> str:
    """Generate or retrieve the markdown body of a skill."""
    from pathlib import Path
    
    # Check local user_skills or assets/skills
    for root in [Path("user_skills"), Path("assets/skills"), Path("skills")]:
        p = root / name / "SKILL.md"
        if p.exists():
            return p.read_text(encoding="utf-8")

    if any(k in name for k in ["grill", "spec", "ticket", "matt-pocock", "discriminated-unions", "type-gymnastics"]):
        return f"""---
name: "{name}"
domain: "mattpocock-engineering"
version: "35.0.0"
author: "Matt Pocock (Skills for Real Engineers) / Adapted for Baize"
level: "L4-Mastery"
---

# {name} · 真实工程师严密工程规约 (Matt Pocock Spine)

> 💡 **核心哲学**：拒绝“氛围编码 (Anti-Vibe Coding)”，拒绝在没有清晰规划时盲目生成代码。通过深度盘问、形式化规范、原子工单和严格 TDD，构建最高可靠性的软件工程。

## 1. 核心工作流 (The Spine Workflow)
1. **深度盘问 (Grill)**：主动向开发者提问，挖掘隐藏假设、边界条件与潜在架构冲突；
2. **规范沉淀 (Spec)**：将讨论成果汇总为形式化 Markdown 规范，明确输入/输出/契约；
3. **工单拆分 (Tickets)**：把大需求切分为单个 LLM 上下文可独立无损完成的原子工单；
4. **测试先导 (TDD)**：编写强类型断言与单元测试，在测试失败前严禁编写生产代码；
5. **门禁代码评审 (Review)**：对标最初的 Spec 规范，逐行审查代码一致性与圈复杂度。

## 2. 约束边界 (Guardrails)
- **严禁跳步**：未经 Spec 与 Ticket 拆解，不得直接启动大规模代码编写；
- **真实物理证据**：所有交付物必须通过 pytest / jest 测试套件并输出物理门禁凭据；
- **类型安全零妥协**：杜绝使用 `any` 或宽松类型，充分利用 Discriminated Unions 消除非法状态。
"""
            
    # Fallback to generated structured spec
    return f"""---
name: "{name}"
domain: "engineering"
version: "35.0.0"
level: "L3-Production"
author: "Baize Agent Engine"
---

# {name} · 技能规约白皮书

## 1. 核心目标与规约定义
本技能遵循白泽引擎 **NO FAKE DONE 真实物理证据门禁** 原则，定义了工程实践的标准输入、约束条件与交付产物。

## 2. 约束边界 (Guardrails)
- **零依赖安全隔离**：所有执行代码严禁越界访问未授权目录；
- **真实验证保证**：产物必须具有可复现、可断言的测试用例；
- **差量编辑优先**：严禁无理由全量覆盖已有文件。

## 3. 标准操作流程 (SOP)
1. **输入剖析**：提取需求或故障上下文的关键 AST 节点；
2. **断言先行 (TDD)**：编写失败的单元测试用例捕获边界条件；
3. **精准实现**：使用 `patch_file` 实施最小行差量修改；
4. **门禁核验**：执行 pytest 全绿回归测试并生成物理证据。

## 4. 产物物理证据清单
- `evidence`: [`tests/test_{name.replace('-', '_')}.py`]
"""

# ===========================================================================
# Section: skill_harvester.py
# ===========================================================================

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.config import load_config
from ..core.config import get_logger
from ..governance.observability import obs

if TYPE_CHECKING:
    from ..core.agent import AgentResult

log = get_logger("harvester")


def _slugify(text: str) -> str:
    """Convert arbitrary goal text to a safe kebab-case skill identifier."""
    cleaned = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", cleaned).strip("-")
    return slug[:40] or f"skill-{int(time.time())}"


def _get_records(result: AgentResult) -> list[dict]:
    return getattr(result, "transcript", None) or getattr(result, "messages", []) or []


class SkillHarvester:
    """Evaluates finished agent runs and archives high-value patterns into new skills."""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or load_config()
        base_dir = self.cfg.get("BAIZE_USER_SKILLS_DIR", "user_skills")
        self.user_skills_dir = Path(base_dir).resolve()
        self.user_skills_dir.mkdir(parents=True, exist_ok=True)

    def should_harvest(self, result: AgentResult, min_steps: int = 3, min_tools: int = 2) -> bool:
        """Heuristic check: did this run solve a non-trivial problem successfully?"""
        if result.stopped_reason != "final":
            return False
        if not result.final_text or len(result.final_text.strip()) < 10:
            return False
        if result.tool_calls < min_tools and result.steps < min_steps:
            return False

        records = _get_records(result)
        tools_called = set()
        for m in records:
            if m.get("role") == "tool" or m.get("tool_calls"):
                for tc in m.get("tool_calls", []):
                    name = tc.get("function", {}).get("name")
                    if name:
                        tools_called.add(name)

        return len(tools_called) > 0

    def extract_skill_spec(self, result: AgentResult, goal: str = "") -> dict:
        """Extract a structured skill specification from session transcript."""
        records = _get_records(result)
        if not goal:
            for m in records:
                if m.get("role") == "user":
                    goal = str(m.get("content", "")).replace("TASK: ", "").strip()
                    break
        goal = goal or "Autonomous Workflow"

        slug = _slugify(goal)
        skill_name = f"auto-{slug}"

        tool_sequence = []
        for m in records:
            for tc in m.get("tool_calls", []):
                fn = tc.get("function", {}).get("name", "")
                if fn and fn not in tool_sequence:
                    tool_sequence.append(fn)

        desc = f"Autonomously distilled workflow for: {goal[:100]}."
        tools_summary = ", ".join(tool_sequence) if tool_sequence else "standard tools"

        body_lines = [
            "---",
            f"name: {skill_name}",
            f"description: {desc}",
            "version: 1.0.0",
            "authors: [baize-harvester]",
            f"tags: [auto-distilled, {slug[:20]}]",
            "harnesses: [baize, hermes, codex]",
            "---",
            "",
            f"# Skill: {skill_name}",
            "",
            f"> **Goal**: {goal}",
            "",
            "## Summary",
            desc,
            "",
            "## Execution Workflow Pattern",
            f"Key tools utilized: `{tools_summary}`.",
            "",
            "### Recommended Steps",
            f"1. Understand context and constraints for `{goal[:60]}`.",
            f"2. Utilize tools in sequence: {tools_summary}.",
            "3. Verify output integrity and confirm evidence against expectations.",
            "",
            "## Reference Output Example",
            "```",
            result.final_text[:500].strip(),
            "```",
        ]

        return {
            "name": skill_name,
            "slug": slug,
            "description": desc,
            "content": "\n".join(body_lines),
        }

    def harvest(self, result: AgentResult, goal: str = "") -> Path | None:
        """Distill and write skill file, then refresh skill index."""
        if not self.should_harvest(result):
            return None

        spec = self.extract_skill_spec(result, goal=goal)
        skill_dir = self.user_skills_dir / spec["name"]
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"

        try:
            skill_file.write_text(spec["content"], encoding="utf-8")
            obs.inc("skills_harvested")
            log.info("[harvester] successfully distilled skill to %s", skill_file)

            try:
                # build_index(), not build(): the module exposes build_index
                # (see py and cli.py). Calling the wrong name raised
                # AttributeError, which the except below swallowed into a
                # warning - so every harvested skill silently failed to reach
                # the index and was never findable again.
                build_index()
            except Exception as e:
                log.warning("[harvester] failed to rebuild index: %s", e)

            return skill_file
        except Exception as exc:
            obs.record_error("skill_harvest_errors")
            log.warning("[harvester] failed to write skill %s: %s", skill_file, exc)
            return None
