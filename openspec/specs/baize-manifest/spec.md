# baize-manifest 流水线门禁规格

## 概述
校验项目的 12 阶段 manifest.json：phase 标记 done 时，列出的证据文件必须全部物理存在。这是 NO FAKE DONE 原则的执行器。

## 接口
- CLI：`python -m baize manifest validate <manifest路径>`
- 函数：`baize.manifest.validate_manifest(manifest_path) -> ValidationResult`
- 退出码：0 = VALID；1 = INVALID

## 行为规约
1. manifest 文件不存在 → ERROR
2. JSON 解析失败 → ERROR
3. 缺少必需字段（project / version / phases）→ ERROR
4. phases 非列表或空列表 → ERROR
5. 重复 phase id → ERROR
6. 非标准 phase id（非 P1-P12）→ WARN
7. status 不在 {pending, in_progress, done, skipped} → ERROR
8. **核心门禁**：status=done 时，evidence 列表不能为空，且每个 evidence 文件必须物理存在（相对路径基于 manifest 所在目录）→ 缺失则 ERROR
9. done 出现在 pending/in_progress 之后 → WARN（流水线顺序异常）

## 边界与异常
- evidence 路径为绝对路径时直接检查；相对路径时基于 manifest 父目录解析
- ValidationResult.errors 非空则 ok=False
- warnings 不影响 ok 判定

## 测试映射
- `tests/test_manifest.py::test_missing_file_is_error`
- `tests/test_manifest.py::test_invalid_json_is_error`
- `tests/test_manifest.py::test_done_without_evidence_is_rejected`
- `tests/test_manifest.py::test_done_with_missing_evidence_file_is_rejected`
- `tests/test_manifest.py::test_done_with_real_evidence_passes`
- `tests/test_manifest.py::test_invalid_status_rejected`
- `tests/test_manifest.py::test_done_after_pending_warns`
