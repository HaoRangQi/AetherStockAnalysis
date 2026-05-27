#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[1/11] scope guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_scope_guard.sh
)

echo "[2/11] docs guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_docs_guard.sh
)

echo "[3/11] workspace draft guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_workspace_draft_guard.sh
)

echo "[4/11] limit_pct guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_limit_pct_guard.sh
)

echo "[5/11] line drawing guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_line_drawing_guard.sh
)

echo "[6/11] default symbol guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_default_symbol_guard.sh
)

echo "[7/11] scheme manual lines guard"
(
  cd "$ROOT_DIR"
  ./scripts/check_scheme_manual_lines_guard.sh
)

echo "[8/11] backend pytest"
(
  cd "$ROOT_DIR/backend"
  .venv/bin/python -m pytest
)

echo "[9/11] frontend lint"
(
  cd "$ROOT_DIR/frontend"
  npm run lint
)

echo "[10/11] frontend build"
(
  cd "$ROOT_DIR/frontend"
  npm run build
)

echo "[11/11] git diff --check"
(
  cd "$ROOT_DIR"
  git diff --check
)

echo "verify_local: all checks passed"
