#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_FILE="${ROOT_DIR}/frontend/src/App.tsx"
STYLE_FILE="${ROOT_DIR}/frontend/src/styles.css"
RULES_FILE="${ROOT_DIR}/docs/rules.md"

require_pattern() {
  local description="$1"
  local pattern="$2"
  local file="$3"
  if ! rg -n --fixed-strings "${pattern}" "${file}" >/dev/null; then
    echo "[learning-page-guard] missing ${description}: ${pattern} (${file})"
    exit 1
  fi
}

echo "[learning-page-guard] checking standalone learning tutorial page"

require_pattern "learning panel type" 'type Panel = "workbench" | "data" | "layers" | "review" | "learning" | "settings";' "${APP_FILE}"
require_pattern "learning tutorial data" "const learningTutorials: LearningTutorial[] = [" "${APP_FILE}"
require_pattern "learning nav item" '{ panel: "learning" as const, label: "学习教程", icon: FileText },' "${APP_FILE}"
require_pattern "learning active flag" 'const learningPageActive = activePanel === "learning";' "${APP_FILE}"
require_pattern "learning shell class" 'className={learningPageActive ? "app-shell learning-page-active" : "app-shell"}' "${APP_FILE}"
require_pattern "learning hides left pane" '{!learningPageActive && <section className="left-pane">' "${APP_FILE}"
require_pattern "learning workspace class" 'className={learningPageActive ? "workspace learning-workspace" : "workspace"}' "${APP_FILE}"
require_pattern "learning page branch" "{learningPageActive ? (" "${APP_FILE}"
require_pattern "learning page renderer call" "renderLearningPage()" "${APP_FILE}"
require_pattern "chart remains workbench branch" "<KLineChart" "${APP_FILE}"
require_pattern "learning renderer function" "function renderLearningPage() {" "${APP_FILE}"
require_pattern "education disclaimer" "不构成交易建议" "${APP_FILE}"
require_pattern "candidate wording" "形态未完成确认前只按候选处理" "${APP_FILE}"

for title in "顶背离" "底背离" "顶分型" "底分型" "M 头" "头肩顶" "头肩底"; do
  require_pattern "tutorial title ${title}" "title: \"${title}\"" "${APP_FILE}"
done

require_pattern "learning shell css" ".app-shell.learning-page-active" "${STYLE_FILE}"
require_pattern "learning workspace css" ".learning-workspace" "${STYLE_FILE}"
require_pattern "learning page css" ".learning-page" "${STYLE_FILE}"
require_pattern "learning card css" ".learning-page-card" "${STYLE_FILE}"
require_pattern "mobile shell scroll" "overflow: visible;" "${STYLE_FILE}"
require_pattern "mobile chart row height" "grid-template-rows: auto minmax(420px, 58vh) auto;" "${STYLE_FILE}"
require_pattern "learning docs section" "## 学习教程说明" "${RULES_FILE}"
require_pattern "learning docs static scope" "不新增背离或形态自动识别算法" "${RULES_FILE}"

echo "[learning-page-guard] passed"
