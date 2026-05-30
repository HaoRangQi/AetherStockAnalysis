#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

require_pattern() {
  local description="$1"
  local pattern="$2"
  local file="$3"
  if ! rg -n --fixed-strings "${pattern}" "${file}" >/dev/null; then
    echo "[scheme-manual-lines-guard] missing ${description}: ${pattern} (${file})"
    exit 1
  fi
}

echo "[scheme-manual-lines-guard] checking analysis-scheme manual lines integration"

require_pattern "workspace state manual lines field" "manualLines: StoredManualLine[];" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace state manual line style field" "manualLineStyle: ManualLineStyle;" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "parsed workspace manual lines field" "manualLines: StoredManualLine[] | null | undefined;" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "parsed workspace manual line style field" "manualLineStyle: ManualLineStyle | null | undefined;" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace setters manual lines setter" "setManualLines: (value: StoredManualLine[]) => void;" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace setters manual line style setter" "setManualLineStyle: (value: ManualLineStyle) => void;" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace export manual_line_style" "manual_line_style: {" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace export manual_lines" "manual_lines: state.manualLines.map((line) => ({" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace parse manual line style" "workspace.manual_line_style," "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace parse manual line style camel fallback" "workspace.manualLineStyle," "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace parse manual lines" "workspace.manual_lines," "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace parse manual lines camel fallback" "workspace.manualLines," "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace apply manual line style" "setters.setManualLineStyle(parsed.manualLineStyle ?? DEFAULT_MANUAL_LINE_STYLE);" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace apply manual lines" "setters.setManualLines(parsed.manualLines ?? []);" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace snake invalid falls back to camel helper" "function parseSchemeFieldWithCamelFallback<T>(" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace parse style helper exists" "function parseManualLineStyle(value: unknown): ManualLineStyle | null | undefined {" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace invalid style keeps current" "if (typeof colorRaw !== \"string\" || !isManualLineColor(colorRaw)) {" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace invalid style width keeps current" "if (!Number.isFinite(widthValue)) {" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace style color helper exists" "function isManualLineColor(value: string): boolean {" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace parse helper exists" "function parseSchemeManualLines(value: unknown): StoredManualLine[] | null | undefined {" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace parse anchor helper exists" "function parseSchemeLineAnchor(value: unknown): ChartClickAnchor | null {" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "analysis scheme export includes manual line style" "manualLineStyle," "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "analysis scheme export includes manual lines" "manualLines," "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "analysis scheme import includes manual line style setter" "setManualLineStyle," "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "analysis scheme import includes manual lines setter" "setManualLines," "${ROOT_DIR}/frontend/src/App.tsx"

require_pattern "readme mentions manual_lines scheme" "manual_lines" "${ROOT_DIR}/README.md"
require_pattern "readme mentions manual_line_style scheme" "manual_line_style" "${ROOT_DIR}/README.md"
require_pattern "api docs mention manual_lines scheme" "workspace.manual_lines" "${ROOT_DIR}/docs/api.md"
require_pattern "api docs mention manual_line_style scheme" "workspace.manual_line_style" "${ROOT_DIR}/docs/api.md"
require_pattern "rules docs mention manual_lines scheme" "workspace.manual_lines" "${ROOT_DIR}/docs/rules.md"
require_pattern "rules docs mention manual_line_style scheme" "workspace.manual_line_style" "${ROOT_DIR}/docs/rules.md"

echo "[scheme-manual-lines-guard] passed"
