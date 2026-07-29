# baize-doctor 环境门禁规格

## 概述
启动前探测运行环境，任何必需检查失败则拒绝继续（exit 1），杜绝"环境不对却继续跑"。

## 接口
- CLI：`python -m baize doctor`
- 函数：`baize.doctor.run_checks(cfg) -> DoctorReport`
- 退出码：0 = 全部必需检查通过；1 = 至少一项必需检查失败

## 行为规约
1. 检查 Python >= 3.10（必需）
2. 检查 .env 存在（非必需，缺失则提示复制 .env.example）
3. 检查核心目录存在：persistence / projects / assets（必需）
4. 检查 persistence 目录可写——真实写临时文件探测（必需）
5. 检查 SKILL_LIBRARY_PATHS 配置的每个技能库路径可达（配置了则必需）
6. 检查可选工具：git / node / go（非必需，缺失仅 WARN）

## 边界与异常
- 技能库路径未配置时：WARN 而非 FAIL（索引降级为仅本地）
- 目录不存在时：FAIL 并打印路径
- 写权限探测失败时：FAIL 并提示检查权限

## 测试映射
- `tests/test_doctor.py::test_all_required_pass_with_valid_dirs`
- `tests/test_doctor.py::test_missing_dir_fails`
- `tests/test_doctor.py::test_configured_but_missing_skill_library_fails`
- `tests/test_doctor.py::test_existing_skill_library_passes`
- `tests/test_doctor.py::test_empty_library_config_is_warning_not_failure`
