#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_SMOKE="false"

for arg in "$@"; do
  case "${arg}" in
    --with-smoke)
      WITH_SMOKE="true"
      ;;
    *)
      echo "unknown option: ${arg}"
      echo "usage: ./scripts/run_goal_round.sh [--with-smoke]"
      exit 2
      ;;
  esac
done

echo "[goal-round] entry checks"
"$ROOT_DIR/scripts/check_goal_entry.sh"

echo
echo "[goal-round] full verify"
"$ROOT_DIR/scripts/verify_local.sh"

if [[ "${WITH_SMOKE}" == "true" ]]; then
  echo
  echo "[goal-round] local smoke"
  "$ROOT_DIR/scripts/smoke_local.sh"
fi

echo
echo "run_goal_round: all checks passed"
