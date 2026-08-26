# baize-skill-index 技能索引规格

## 概述
扫描本地 assets/skills + SKILL_LIBRARY_PATHS 配置的外部技能库，构建 JSON 索引，供任何 Agent 客户端按需检索加载。

## 接口
- CLI：`python -m baize index build` / `python -m baize index search <关键词>`
- 函数：
  - `baize.skill_index.build_index(cfg) -> dict`
  - `baize.skill_index.search(keyword, cfg, limit) -> list[dict]`
  - `baize.skill_index.load_index(cfg) -> dict`（不存在则自动构建）

## 行为规约
1. 扫描深度上限 4 层，跳过 node_modules / .git / __pycache__ / dist / build / vendor / .venv / legacy
2. 识别 SKILL.md 文件，解析 YAML frontmatter 提取 name / description
3. frontmatter 缺失时，从首个 `# 标题` 和首段文本降级提取
4. 按 name 小写去重：同名技能只保留首次出现（local 优先 > 外部库按配置顺序）
5. 索引 JSON 结构：version / generated_at / libraries / count / duplicates_deduped / skills[]
6. 每条技能记录：name / description / path / skill_file / source
7. search 支持关键词模糊匹配（name + description + path），默认返回前 20 条

## 边界与异常
- 目录不可读时：跳过该目录（OSError 防护）
- SKILL.md 读取失败时：跳过该文件
- 索引文件不存在时：自动调用 build_index
- 索引文件 JSON 损坏时：由 load_index 抛出 JSONDecodeError（调用方应 catch 后重建）

## 测试映射
- `tests/test_skill_index.py::test_frontmatter_parse`
- `tests/test_skill_index.py::test_scan_finds_skills_with_and_without_frontmatter`
- `tests/test_skill_index.py::test_scan_skips_node_modules`
- `tests/test_skill_index.py::test_build_index_writes_json_and_search_hits`
- `tests/test_skill_index.py::test_build_index_deduplicates_same_name_across_libraries`
