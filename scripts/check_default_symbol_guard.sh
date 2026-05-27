#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

require_pattern() {
  local description="$1"
  local pattern="$2"
  local file="$3"
  if ! rg -n --fixed-strings "${pattern}" "${file}" >/dev/null; then
    echo "[default-symbol-guard] missing ${description}: ${pattern} (${file})"
    exit 1
  fi
}

echo "[default-symbol-guard] checking default symbol and initial window guards"

require_pattern "default symbol fallback query by index" "const byIndex = await pickByQuery(\"sh000001\");" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "default symbol fallback query by code" "const byCode = byIndex ?? await pickByQuery(\"000001\");" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "default symbol fallback any symbol" "fallback = byCode ?? await pickByQuery(\"\");" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "dateEnd init with selected symbol and touched flag" "const [dateEnd, setDateEnd] = useState(() => readCurrentDateEnd(selectedSymbol, dateRangeTouched));" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "dateStart init with selected symbol and touched flag" "const [dateStart, setDateStart] = useState(() => readCurrentDateStart(timeframe, defaultRangeMonths, dateEnd, selectedSymbol, dateRangeTouched));" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "dateEnd init guard signature" "function readCurrentDateEnd(selectedSymbol: SymbolRecord | null, dateRangeTouched: boolean): string {" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "dateEnd follows symbol when untouched" "if (selectedSymbol && !dateRangeTouched) {" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "dateStart init guard signature" "function readCurrentDateStart(" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "dateStart follows symbol when untouched" "const defaultEnd = normalizeDateInputValue(selectedSymbol.last_date) ?? dateEnd;" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "dateStart fallback from default end" "return initialDateStart(timeframe, defaultRangeMonths, defaultEnd);" "${ROOT_DIR}/frontend/src/App.tsx"

echo "[default-symbol-guard] passed"
