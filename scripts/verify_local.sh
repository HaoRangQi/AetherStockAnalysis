#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[1/12] scope guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_scope_guard.sh
)

echo "[2/12] docs guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_docs_guard.sh
)

echo "[3/12] workspace draft guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_workspace_draft_guard.sh
)

echo "[4/12] limit_pct guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_limit_pct_guard.sh
)

echo "[5/12] line drawing guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_line_drawing_guard.sh
)

echo "[6/12] default symbol guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_default_symbol_guard.sh
)

echo "[7/12] scheme manual lines guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_scheme_manual_lines_guard.sh
)

echo "[8/12] learning page guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_learning_page_guard.sh
)

echo "[9/12] backend pytest"
(
  cd "$ROOT_DIR/backend"
  .venv/bin/python -m pytest
)

echo "[10/12] frontend lint"
(
  cd "$ROOT_DIR/frontend"
  npm run lint
)

echo "[11/12] frontend build"
(
  cd "$ROOT_DIR/frontend"
  npm run build
)

echo "[12/12] git diff --check"
(
  cd "$ROOT_DIR"
  git diff --check
)

echo "verify_local: all checks passed"
