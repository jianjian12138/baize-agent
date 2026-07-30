# OpenSpec 规格中心

白泽引擎遵循"规格先行"原则：功能演进先在 OpenSpec 中建立规格文档，再由执行层基于规格产出代码。

## 目录结构

```
openspec/
  README.md           本文件
  specs/              已落地的功能规格
    baize-doctor/       环境门禁规格
    baize-skill-index/  技能索引规格
    baize-manifest/     流水线门禁规格
    baize-memory/       持久记忆规格（V20：新增长程压缩）
    baize-agent/        自主 Agent 循环规格（V20：反思规划 + 长程压缩）
    baize-llm/          模型无关客户端规格（V20：速率限制/退避 + 异常全捕获）
    baize-tools/        工具注册表与沙箱规格（V20：SDK 单例注册表）
    baize-orchestrator/ 多 Agent 编排规格（V20：Verifier 硬化）
    # V20 新增规格
    baize-vector/       向量检索规格（TF-IDF 默认，embedding 预留）
    baize-rag/          RAG 检索增强 + 技能评分规格
    baize-graph/        知识图谱三元组规格
    baize-bench/        确定性基准套件规格
    baize-ui/           TUI 进度规格
    baize-dashboard/    Web 仪表盘 + REST 规格
    baize-team-memory/  协作记忆白板规格
    baize-observability/ 可观测性 + Prometheus 规格
    baize-logging/      结构化日志 + 脱敏规格
    baize-chaos/        混沌工程韧性规格
    baize-config-schema/ 配置强类型校验规格
    baize-plugin/       可插拔插件（验证钩子/指标）规格
```

## 工作流程

1. **Propose**：在 `specs/` 下创建规格文档，定义字段、逻辑与边界。
2. **Review**：通过 `python -m baize manifest validate` 确保规格与实现一致。
3. **Apply**：执行层基于规格产出代码与测试。
4. **Archive**：规格与实现一致后，规格成为该功能的唯一事实源。

## 规格格式

每个 spec 目录包含一个 `spec.md`，结构：

```markdown
# <功能名> 规格说明

## 概述
一句话描述功能用途。

## 接口
CLI 命令、函数签名、输入输出。

## 行为规约
编号列表，每条可测试的行为。

## 边界与异常
无效输入、错误处理、降级策略。

## 测试映射
每个行为规约对应的测试文件与用例。
```
