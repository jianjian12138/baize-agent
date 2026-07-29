# baize-memory 持久记忆规格

## 概述
跨会话持久记忆：JSONL 每日事件日志 + notes.md 长期笔记 + 关键词检索。每次读写都是真实文件操作。

## 接口
- CLI：
  - `python -m baize memory log "<文本>" [--tags a,b]`
  - `python -m baize memory remember "<文本>"`
  - `python -m baize memory recall <关键词> [--tags x] [--limit N]`
  - `python -m baize memory stats`
- 函数：
  - `baize.memory.log_event(text, tags, cfg) -> Path`
  - `baize.memory.remember(text, cfg) -> Path`
  - `baize.memory.recall(keyword, cfg, limit, tags) -> list[dict]`
  - `baize.memory.stats(cfg) -> dict`

## 行为规约
1. log_event：追加一条 JSON 记录到 `logs/YYYY-MM-DD.jsonl`，含 ts / text / tags
2. remember：追加一行到 `notes.md`，格式 `- [YYYY-MM-DD] 文本`
3. recall：搜索 notes.md + 所有 logs/*.jsonl，按关键词匹配（大小写不敏感）
4. recall 支持多关键词（空格分隔，AND 语义——全部命中才返回）
5. recall 支持 tags 过滤（--tags，记录的 tags 包含任一指定 tag 即命中）
6. recall 按相关性排序（命中关键词越多越靠前），受 limit 限制
7. stats：统计日志文件数、事件总数、笔记数

## 边界与异常
- persistence 目录不存在时自动创建（含 logs/ 子目录）
- JSONL 行解析失败时跳过该行
- notes.md 不存在时 recall 返回空
- 空关键词时返回全部记录（受 limit 限制）

## 测试映射
- `tests/test_memory.py::test_log_event_appends_jsonl`
- `tests/test_memory.py::test_remember_and_recall`
- `tests/test_memory.py::test_stats_counts_real_content`
- `tests/test_memory.py::test_recall_multi_keyword_and`
- `tests/test_memory.py::test_recall_tags_filter`
