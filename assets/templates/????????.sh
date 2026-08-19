#!/usr/bin/env bash

# {{REQUEST_TITLE}} 冒烟测试脚本模板
# 默认能力：
# 1. 自动 source picasso runtime-lib
# 2. 按 .env / manifest 约定自动启动后端、前端、本地联调
# 3. 可选自动登录获取 Token
# 4. 脚本结束后自动收尾

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

find_runtime_lib() {
  local current="$SCRIPT_DIR"
  while [ "$current" != "/" ]; do
    if [ -f "$current/shared/scripts/runtime-lib.sh" ]; then
      echo "$current/shared/scripts/runtime-lib.sh"
      return 0
    fi
    current="$(dirname "$current")"
  done
  return 1
}

RUNTIME_LIB_PATH="${PICASSO_RUNTIME_LIB_PATH:-$(find_runtime_lib)}"
if [ -z "$RUNTIME_LIB_PATH" ] || [ ! -f "$RUNTIME_LIB_PATH" ]; then
  echo "[SMOKE][ERROR] 未找到 runtime-lib.sh，请检查 skill 包结构" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$RUNTIME_LIB_PATH"

export PICASSO_RUNTIME_SESSION_NAME="${PICASSO_RUNTIME_SESSION_NAME:-{{REQUEST_KEY}}}"
picasso_runtime_bootstrap

BASE_URL="${BASE_URL:-${PICASSO_BACKEND_BASE_URL:-http://127.0.0.1:8080}}"
API_PREFIX="${API_PREFIX:-${PICASSO_API_PREFIX:-/admin-api}}"
TENANT_ID="${TENANT_ID:-${PICASSO_LOGIN_TENANT_ID:-1}}"
TOKEN="${TOKEN:-${ACCESS_TOKEN:-}}"

FRONT_REPO_DIR="${FRONT_REPO_DIR:-${PICASSO_FRONT_CODE_DIR:-}}"
MINIAPP_REPO_DIR="${MINIAPP_REPO_DIR:-${PICASSO_MINIAPP_CODE_DIR:-}}"
MOBILE_APP_REPO_DIR="${MOBILE_APP_REPO_DIR:-${PICASSO_MOBILE_APP_CODE_DIR:-}}"

FRONTEND_READY_URL="${FRONTEND_READY_URL:-${PICASSO_FRONTEND_READY_URL:-}}"
FRONTEND_EXPECT_TEXT="${FRONTEND_EXPECT_TEXT:-${PICASSO_FRONTEND_EXPECT_TEXT:-}}"

PC_PAGE_FILE="${PC_PAGE_FILE:-}"
PC_API_FILE="${PC_API_FILE:-}"
PC_ROUTE_FILE="${PC_ROUTE_FILE:-}"
PC_ROUTE_KEYWORD="${PC_ROUTE_KEYWORD:-}"

MINIAPP_ROUTE_FILE="${MINIAPP_ROUTE_FILE:-}"
MINIAPP_ROUTE_KEYWORD="${MINIAPP_ROUTE_KEYWORD:-}"

MOBILE_NAMES_FILE="${MOBILE_NAMES_FILE:-}"
MOBILE_PAGES_FILE="${MOBILE_PAGES_FILE:-}"
MOBILE_NAVIGATION_FILE="${MOBILE_NAVIGATION_FILE:-}"
MOBILE_ROUTE_KEYWORD="${MOBILE_ROUTE_KEYWORD:-}"

CONTROLLER_FILE="${CONTROLLER_FILE:-}"
CONTROLLER_ROUTE_KEYWORD="${CONTROLLER_ROUTE_KEYWORD:-}"

PASS_COUNT=0
FAIL_COUNT=0
GATE1_PASS=0
GATE1_FAIL=0
GATE2_PASS=0
GATE2_FAIL=0

pass() {
  local gate="$1"
  local name="$2"
  echo "[PASS] $name"
  PASS_COUNT=$((PASS_COUNT + 1))
  if [ "$gate" = "gate1" ]; then
    GATE1_PASS=$((GATE1_PASS + 1))
  else
    GATE2_PASS=$((GATE2_PASS + 1))
  fi
}

fail() {
  local gate="$1"
  local name="$2"
  echo "[FAIL] $name"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  if [ "$gate" = "gate1" ]; then
    GATE1_FAIL=$((GATE1_FAIL + 1))
  else
    GATE2_FAIL=$((GATE2_FAIL + 1))
  fi
}

skip() {
  local gate="$1"
  local name="$2"
  echo "[SKIP] $name"
  if [ "$gate" = "gate1" ]; then
    GATE1_PASS=$((GATE1_PASS + 1))
  else
    GATE2_PASS=$((GATE2_PASS + 1))
  fi
}

check_http() {
  local gate="$1"
  local name="$2"
  local path="$3"
  local method="${4:-GET}"
  local code

  code="$(
    curl -s -o /dev/null -w "%{http_code}" \
      -X "$method" \
      "$BASE_URL$path" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Tenant-Id: $TENANT_ID" || echo "000"
  )"
  if [ "$code" = "200" ] || [ "$code" = "201" ]; then
    pass "$gate" "$name"
  else
    fail "$gate" "$name (HTTP $code)"
  fi
}

check_url_contains() {
  local gate="$1"
  local name="$2"
  local url="$3"
  local expect_text="${4:-}"
  if [ -z "$url" ]; then
    skip "$gate" "$name（未配置）"
    return
  fi
  if picasso_runtime_probe_http "$url" "$expect_text"; then
    pass "$gate" "$name"
  else
    fail "$gate" "$name（URL 不可访问或未包含期望内容）"
  fi
}

check_file() {
  local gate="$1"
  local name="$2"
  local path="$3"
  if [ -z "$path" ]; then
    skip "$gate" "$name（未配置）"
    return
  fi
  if [ -f "$path" ]; then
    pass "$gate" "$name"
  else
    fail "$gate" "$name（文件不存在: $path）"
  fi
}

check_contains() {
  local gate="$1"
  local name="$2"
  local path="$3"
  local keyword="$4"
  if [ -z "$path" ] || [ -z "$keyword" ]; then
    skip "$gate" "$name（未配置）"
    return
  fi
  if [ ! -f "$path" ]; then
    fail "$gate" "$name（文件不存在: $path）"
    return
  fi
  if grep -q "$keyword" "$path"; then
    pass "$gate" "$name"
  else
    fail "$gate" "$name（未找到关键字: $keyword）"
  fi
}

echo "[SMOKE] 冒烟测试 - {{REQUEST_TITLE}}"
echo "[SMOKE] 运行会话目录: $PICASSO_RUNTIME_SESSION_DIR"
echo
echo "--- 第1关：API 接口验证 ---"
check_http "gate1" "1.1 健康检查" "/actuator/health"

if [ -z "$TOKEN" ]; then
  fail "gate1" "1.2 登录获取 Token（TOKEN 未配置且未自动获取成功）"
else
  pass "gate1" "1.2 登录获取 Token"
fi

# 使用前请替换为真实接口
# check_http "gate1" "1.3 列表接口" "$API_PREFIX/xxx/page?pageNo=1&pageSize=10"
# check_http "gate1" "1.4 详情接口" "$API_PREFIX/xxx/get?id=1"
# check_http "gate1" "1.5 新增接口" "$API_PREFIX/xxx/create" "POST"
# check_http "gate1" "1.6 字典 / 菜单 / 权限依赖接口" "$API_PREFIX/system/dict-data/page?dictType=xxx"

echo "--- 第1关结果: ✅ $GATE1_PASS 通过, ❌ $GATE1_FAIL 失败 ---"
echo

echo "--- 第2关：页面集成验证 ---"
check_file "gate2" "2.1 PC 页面文件存在" "$PC_PAGE_FILE"
check_file "gate2" "2.2 PC API 文件存在" "$PC_API_FILE"
check_contains "gate2" "2.3 PC 路由已注册" "$PC_ROUTE_FILE" "$PC_ROUTE_KEYWORD"
check_contains "gate2" "2.4 小程序路由已注册" "$MINIAPP_ROUTE_FILE" "$MINIAPP_ROUTE_KEYWORD"
check_contains "gate2" "2.5 Flutter names.dart 已注册" "$MOBILE_NAMES_FILE" "$MOBILE_ROUTE_KEYWORD"
check_contains "gate2" "2.6 Flutter pages.dart 已注册" "$MOBILE_PAGES_FILE" "$MOBILE_ROUTE_KEYWORD"
check_contains "gate2" "2.7 Flutter Navigation.to 已映射" "$MOBILE_NAVIGATION_FILE" "$MOBILE_ROUTE_KEYWORD"
check_contains "gate2" "2.8 Controller 路径 / 前缀正确" "$CONTROLLER_FILE" "$CONTROLLER_ROUTE_KEYWORD"
check_url_contains "gate2" "2.9 前端页面可访问" "$FRONTEND_READY_URL" "$FRONTEND_EXPECT_TEXT"

if [ -n "$FRONT_REPO_DIR" ] && [ -d "$FRONT_REPO_DIR" ]; then
  pass "gate2" "2.10 前端仓库路径可访问"
else
  skip "gate2" "2.10 前端仓库路径可访问（未配置）"
fi

if [ -n "$MINIAPP_REPO_DIR" ] && [ -d "$MINIAPP_REPO_DIR" ]; then
  pass "gate2" "2.11 小程序仓库路径可访问"
else
  skip "gate2" "2.11 小程序仓库路径可访问（未配置）"
fi

if [ -n "$MOBILE_APP_REPO_DIR" ] && [ -d "$MOBILE_APP_REPO_DIR" ]; then
  pass "gate2" "2.12 移动端仓库路径可访问"
else
  skip "gate2" "2.12 移动端仓库路径可访问（未配置）"
fi

echo "--- 第2关结果: ✅ $GATE2_PASS 通过, ❌ $GATE2_FAIL 失败 ---"
echo

echo "--- 汇总 ---"
echo "[SMOKE] 总计: ✅ $PASS_COUNT 通过, ❌ $FAIL_COUNT 失败"
echo "[SMOKE] 运行日志目录: $PICASSO_RUNTIME_SESSION_DIR/logs"

if [ "$FAIL_COUNT" -gt 0 ]; then
  echo "[SMOKE] ❌ 存在失败项，请修复后重新运行"
  exit 1
fi

echo "[SMOKE] ✅ 两关全部通过"
