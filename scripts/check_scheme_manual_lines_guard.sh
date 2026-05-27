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
require_pattern "parsed workspace manual lines field" "manualLines: StoredManualLine[] | null | undefined;" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace setters manual lines setter" "setManualLines: (value: StoredManualLine[]) => void;" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace export manual_lines" "manual_lines: state.manualLines.map((line) => ({" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace parse manual lines" "const manualLines = parseSchemeManualLines(workspace.manual_lines ?? workspace.manualLines);" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace apply manual lines" "setters.setManualLines(parsed.manualLines ?? []);" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace parse helper exists" "function parseSchemeManualLines(value: unknown): StoredManualLine[] | null | undefined {" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "workspace parse anchor helper exists" "function parseSchemeLineAnchor(value: unknown): ChartClickAnchor | null {" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "analysis scheme export includes manual lines" "manualLines," "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "analysis scheme import includes manual lines setter" "setManualLines," "${ROOT_DIR}/frontend/src/App.tsx"

require_pattern "readme mentions manual_lines scheme" "manual_lines" "${ROOT_DIR}/README.md"
require_pattern "api docs mention manual_lines scheme" "workspace.manual_lines" "${ROOT_DIR}/docs/api.md"
require_pattern "rules docs mention manual_lines scheme" "workspace.manual_lines" "${ROOT_DIR}/docs/rules.md"

echo "[scheme-manual-lines-guard] passed"
