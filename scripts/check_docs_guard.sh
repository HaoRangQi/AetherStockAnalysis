#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "[docs-guard] missing file: ${path}"
    exit 1
  fi
}

require_pattern() {
  local description="$1"
  local pattern="$2"
  local file="$3"
  if ! rg -n --fixed-strings "${pattern}" "${file}" >/dev/null; then
    echo "[docs-guard] missing ${description}: ${pattern} (${file})"
    exit 1
  fi
}

echo "[docs-guard] checking documentation governance baseline"

require_file "${ROOT_DIR}/README.md"
require_file "${ROOT_DIR}/docs/architecture.md"
require_file "${ROOT_DIR}/docs/api.md"
require_file "${ROOT_DIR}/docs/rules.md"
require_file "${ROOT_DIR}/docs/testing.md"
require_file "${ROOT_DIR}/docs/schema.sql"

require_pattern "readme architecture link" "[docs/architecture.md](docs/architecture.md)" "${ROOT_DIR}/README.md"
require_pattern "readme api link" "[docs/api.md](docs/api.md)" "${ROOT_DIR}/README.md"
require_pattern "readme rules link" "[docs/rules.md](docs/rules.md)" "${ROOT_DIR}/README.md"
require_pattern "readme testing link" "[docs/testing.md](docs/testing.md)" "${ROOT_DIR}/README.md"
require_pattern "readme schema link" "[docs/schema.sql](docs/schema.sql)" "${ROOT_DIR}/README.md"
require_pattern "readme scheme manual line style guard command" "make scheme-manual-lines-guard # 分析方案 manual_lines / manual_line_style 链路守护检查" "${ROOT_DIR}/README.md"
require_pattern "readme scheme manual line style guard explanation" 'manual_lines` / `manual_line_style` 导出' "${ROOT_DIR}/README.md"

require_pattern "api backtest endpoint doc" "GET /backtests/structure" "${ROOT_DIR}/docs/api.md"
require_pattern "api annotations endpoint doc" "GET /annotations" "${ROOT_DIR}/docs/api.md"
require_pattern "api manual line style scheme doc" "workspace.manual_line_style" "${ROOT_DIR}/docs/api.md"
require_pattern "api manual line style invalid tries camel" '继续尝试同义 camelCase 字段 `manualLineStyle`' "${ROOT_DIR}/docs/api.md"
require_pattern "api manual line style double invalid keeps current" "两者都缺失或非法时保持当前样式" "${ROOT_DIR}/docs/api.md"
require_pattern "rules manual wave section" "overlay_type=\"wave\"" "${ROOT_DIR}/docs/rules.md"
require_pattern "rules manual line style scheme doc" "workspace.manual_line_style" "${ROOT_DIR}/docs/rules.md"
require_pattern "architecture annotations section" '### `annotations`' "${ROOT_DIR}/docs/architecture.md"
require_pattern "testing learning page guard" "learning page guard" "${ROOT_DIR}/docs/testing.md"
require_pattern "testing verification summary" "./scripts/verify_local.sh" "${ROOT_DIR}/docs/testing.md"
require_pattern "testing high risk frontend e2e" "前端缺少真正 E2E 测试框架" "${ROOT_DIR}/docs/testing.md"

echo "[docs-guard] passed"
