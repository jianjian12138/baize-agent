# OpenSpec 规格中心

> **范围声明（V24 统一化）**：本目录是白泽引擎运行时的**代表性规格子集**，
> 仅覆盖 `specs/` 下已落地的核心模块（见下方目录），并非全部运行时模块的规格库。
> 各 spec 是对应功能的评审对齐事实源；运行时的真正强制约束由 `baize/gate.py` +
> `baize/manifest.py`（NO FAKE DONE 证据核验）执行，**本目录不被运行时加载**。
> 新增功能仍建议先在此立规格。

白泽引擎遵循"规格先行"原则：功能演进先在 OpenSpec 中建立规格文档，再由执行层基于规格产出代码。

## 目录结构

```
openspec/
  README.md           本文件
  specs/              已落地的功能规格（代表性子集，非全量模块覆盖）
    baize-agent/        自主 Agent 循环规格
    baize-doctor/        环境门禁规格
    baize-llm/           模型无关客户端规格
    baize-manifest/      流水线门禁规格
    baize-memory/        持久记忆规格
    baize-orchestrator/  多 Agent 编排规格
    baize-skill-index/   技能索引规格
    baize-tools/         工具注册表与沙箱规格

> 说明：本目录是白泽引擎运行时的代表性规格子集，仅覆盖上述 8 个核心模块，
> 并非全部运行时模块的规格库。各 spec 是对应功能的评审对齐事实源；
> 运行时真正的强制约束由 `baize/gate.py` + `baize/manifest.py`（NO FAKE DONE 证据核验）
> 执行，本目录不被运行时加载。新增功能仍建议先在此立规格。
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
