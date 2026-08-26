---
name: Verification-Expert-Nitpicking
level: Advanced
domain: Proof-by-Contradiction
---

# 🔱 技能：证伪专家与恶意审计 (Verification Expert)

本技能借鉴 Claude Code 的 Nitpicking (挑剔) 模式，以“破坏性证明”为核心，全方位拦截逻辑缺陷。

## 🪐 1. 证伪逻辑 (Proof by Contradiction)
- **攻击型测试 (Negative Testing)**：不尝试证明“代码能跑”，而是尝试证明“代码在此场景下一定会死”。
- **极端路径探测 (Corner-Case Audit)**：
    - Go：高并发竞争（Race Condition）、连接池溢出（Pool Leak）、协程不归路（G-Leak）。
    - Vue 3：非闭环状态转移、不必要的响应式开销、异步竞争。
    - Postgres：慢查询预判、非索引字段扫描、锁升级风险。

## 🛡️ 2. 物理证伪规约 (Auditor Mantra)
- **拒绝假设**：在代码评审环节，强制提出 3 个“可能的崩坏路径”。
- **深度挑剔**：审查每一个 `if err != nil` 的覆盖范围，确证无“吞掉错误”的行为。
- **内存主权**：强制分析 Go 的 `escape analysis`，确证关键数据未分配在堆上导致 GC 抖动。

## 🧪 3. 驱动工具
- `go test -race`
- `pg_stat_statements` (Postgres 性能监控)
- `Vue Devtools` (状态一致性审计)

---
*“Stability is not the absence of errors, but the containment of their proof.”*
