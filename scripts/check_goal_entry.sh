#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[1/3] git status --short"
(
  cd "$ROOT_DIR"
  git status --short
)

echo
echo "[2/3] git diff --stat"
(
  cd "$ROOT_DIR"
  git diff --stat
)

echo
echo "[3/3] rg -n \"limit_pct|limitPct|prev_close_\" backend frontend docs README.md"
(
  cd "$ROOT_DIR"
  rg -n "limit_pct|limitPct|prev_close_" backend frontend docs README.md
)

echo
echo "check_goal_entry: all checks finished"
