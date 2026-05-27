#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 当前交付口径：不做社区分享/外部发布，只保留本地复用/迁移/离线复盘。
PATTERN="社区分享|社区方案|社区友好|只分享参数|社区 ZigZag|公开分享|外部发布|community sharing|share parameters"

echo "[scope-guard] scanning for out-of-scope publish wording"
if rg -n "${PATTERN}" \
  "${ROOT_DIR}/README.md" \
  "${ROOT_DIR}/docs" \
  "${ROOT_DIR}/backend" \
  "${ROOT_DIR}/frontend/src"; then
  echo "scope-guard: found out-of-scope publish wording, please align to local-only scope"
  exit 1
fi

echo "scope-guard: passed"
