#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

require_pattern() {
  local description="$1"
  local pattern="$2"
  local file="$3"
  if ! rg -n --fixed-strings "${pattern}" "${file}" >/dev/null; then
    echo "[line-drawing-guard] missing ${description}: ${pattern} (${file})"
    exit 1
  fi
}

echo "[line-drawing-guard] checking manual line drawing integration guards"

require_pattern "line drawing mode prop" "lineDrawingMode: boolean;" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "manual line color prop" "manualLineColor: string;" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "manual line width prop" "manualLineWidth: number;" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "manual line callback prop" "onCreateManualLine?: (start: ChartClickAnchor, end: ChartClickAnchor) => void;" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line series ref" "const previewLineSeriesRef = useRef<ISeriesApi<\"Line\"> | null>(null);" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line series create" "const previewLineSeries = chart.addSeries(LineSeries, {" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line clear helper" "const clearPreviewLine = () => {" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line show helper" "const showPreviewLine = (start: ResolvedAnchor, end: ResolvedAnchor) => {" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line pointer move" "const handlePointerMove = (event: PointerEvent) => {" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line pointer leave" "const handlePointerLeave = () => {" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line move listener" "container.addEventListener(\"pointermove\", handlePointerMove);" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line leave listener" "container.addEventListener(\"pointerleave\", handlePointerLeave);" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line remove listener move" "container.removeEventListener(\"pointermove\", handlePointerMove);" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line remove listener leave" "container.removeEventListener(\"pointerleave\", handlePointerLeave);" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line cleanup on disable" "previewLineSeriesRef.current?.setData([]);" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line series remove on unmount" "chart.removeSeries(previewLineSeries);" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "pointerup drawing anchor path" "const anchor = anchorFromPointerEvent(event, true);" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "drawing suppress click dup" "suppressNextClickRef.current = true;" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "same-bar auto adjustment" "const adjusted = adjustSameBarAnchor(pendingStart, resolved);" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "anchor resolve diagnostics" "[KLineChart] line-anchor-resolve" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "line series update diagnostics" "[KLineChart] line-series-update" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "drawing create callback invoke" "createManualLineHandlerRef.current?.(pendingStart.anchor, finalEnd.anchor);" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "price-pane fallback ratio" "const PRICE_PANE_BOTTOM_RATIO = 0.78;" "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "drawing mode keeps scroll enabled" "handleScroll: true," "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "drawing mode keeps scale enabled" "handleScale: true," "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "manual line color applied" "color: lineColor," "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "manual line width applied" "lineWidth," "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "preview line style from manual style" "color: toPreviewLineColor(manualLineColor)," "${ROOT_DIR}/frontend/src/KLineChart.tsx"
require_pattern "app create line handler" "const handleCreateManualLine = useCallback(" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "app manual line persistence" "safeLocalStorageSetItem(\"manualLines\", JSON.stringify(manualLines));" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "app manual line style state" "const [manualLineStyle, setManualLineStyle] = useState<ManualLineStyle>(() => readManualLineStyle());" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "app manual line style persistence" "safeLocalStorageSetItem(\"manualLineStyle\", JSON.stringify(manualLineStyle));" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "chart gets manual lines" "manualLines={manualLinesForCurrentChart}" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "chart gets manual line color" "manualLineColor={manualLineStyle.color}" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "chart gets manual line width" "manualLineWidth={manualLineStyle.width}" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "chart receives drawing mode" "lineDrawingMode={lineDrawingMode}" "${ROOT_DIR}/frontend/src/App.tsx"
require_pattern "pen cursor class" ".kline-chart.line-drawing-mode {" "${ROOT_DIR}/frontend/src/styles.css"
require_pattern "line style control class" ".line-style-control {" "${ROOT_DIR}/frontend/src/styles.css"

echo "[line-drawing-guard] passed"
