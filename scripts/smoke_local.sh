#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="5173"

BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
FRONTEND_URL="http://${FRONTEND_HOST}:${FRONTEND_PORT}"

BACKEND_PID=""
FRONTEND_PID=""
BACKEND_LOG=""
FRONTEND_LOG=""
BACKEND_STARTED_BY_SCRIPT="false"
FRONTEND_STARTED_BY_SCRIPT="false"
WAIT_RETRIES=60
WAIT_INTERVAL=0.5

cleanup() {
  if [[ "${BACKEND_STARTED_BY_SCRIPT}" == "true" && -n "${BACKEND_PID}" ]]; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
  if [[ "${FRONTEND_STARTED_BY_SCRIPT}" == "true" && -n "${FRONTEND_PID}" ]]; then
    kill "${FRONTEND_PID}" >/dev/null 2>&1 || true
    wait "${FRONTEND_PID}" 2>/dev/null || true
  fi
  if [[ -n "${BACKEND_LOG}" && -f "${BACKEND_LOG}" ]]; then
    rm -f "${BACKEND_LOG}"
  fi
  if [[ -n "${FRONTEND_LOG}" && -f "${FRONTEND_LOG}" ]]; then
    rm -f "${FRONTEND_LOG}"
  fi
}

wait_http_ok() {
  local url="$1"
  local retries="$2"
  local sleep_seconds="$3"
  local i=0
  while [[ "${i}" -lt "${retries}" ]]; do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${sleep_seconds}"
    i=$((i + 1))
  done
  return 1
}

print_service_log_tail() {
  local label="$1"
  local log_file="$2"
  if [[ -n "${log_file}" && -f "${log_file}" ]]; then
    echo "[smoke] ${label} log tail"
    tail -n 80 "${log_file}" || true
  fi
}

is_restricted_bind_error() {
  local log_file="$1"
  if [[ -z "${log_file}" || ! -f "${log_file}" ]]; then
    return 1
  fi
  rg -qi "operation not permitted|permission denied|error while attempting to bind" "${log_file}"
}

print_port_listener() {
  local port="$1"
  echo "[smoke] port ${port} listener"
  lsof -nP -iTCP:"${port}" -sTCP:LISTEN || true
}

trap cleanup EXIT

echo "[smoke] backend service"
if lsof -iTCP:${BACKEND_PORT} -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  echo "reuse backend ${BACKEND_URL}"
  if ! wait_http_ok "${BACKEND_URL}/api/health" 6 0.5; then
    echo "backend port ${BACKEND_PORT} is occupied but not reusable at ${BACKEND_URL}/api/health"
    print_port_listener "${BACKEND_PORT}"
    exit 1
  fi
else
  BACKEND_LOG="$(mktemp)"
  (
    cd "${ROOT_DIR}/backend"
    .venv/bin/python -m uvicorn app.main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" >"${BACKEND_LOG}" 2>&1
  ) &
  BACKEND_PID="$!"
  BACKEND_STARTED_BY_SCRIPT="true"
  if ! wait_http_ok "${BACKEND_URL}/api/health" "${WAIT_RETRIES}" "${WAIT_INTERVAL}"; then
    if is_restricted_bind_error "${BACKEND_LOG}"; then
      echo "smoke_local: skipped (sandbox blocks local bind for backend ${BACKEND_HOST}:${BACKEND_PORT})"
      print_service_log_tail "backend" "${BACKEND_LOG}"
      exit 0
    fi
    echo "backend health check timeout: ${BACKEND_URL}/api/health"
    print_service_log_tail "backend" "${BACKEND_LOG}"
    exit 1
  fi
fi

echo "[smoke] frontend service"
if lsof -iTCP:${FRONTEND_PORT} -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  echo "reuse frontend ${FRONTEND_URL}"
  if ! wait_http_ok "${FRONTEND_URL}/" 6 0.5; then
    echo "frontend port ${FRONTEND_PORT} is occupied but not reusable at ${FRONTEND_URL}/"
    print_port_listener "${FRONTEND_PORT}"
    exit 1
  fi
else
  FRONTEND_LOG="$(mktemp)"
  (
    cd "${ROOT_DIR}/frontend"
    npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" >"${FRONTEND_LOG}" 2>&1
  ) &
  FRONTEND_PID="$!"
  FRONTEND_STARTED_BY_SCRIPT="true"
  if ! wait_http_ok "${FRONTEND_URL}/" "${WAIT_RETRIES}" "${WAIT_INTERVAL}"; then
    if is_restricted_bind_error "${FRONTEND_LOG}"; then
      echo "smoke_local: skipped (sandbox blocks local bind for frontend ${FRONTEND_HOST}:${FRONTEND_PORT})"
      print_service_log_tail "frontend" "${FRONTEND_LOG}"
      exit 0
    fi
    echo "frontend readiness timeout: ${FRONTEND_URL}/"
    print_service_log_tail "frontend" "${FRONTEND_LOG}"
    exit 1
  fi
fi

echo "[smoke] backend health"
HEALTH_PAYLOAD="$(curl -fsS "${BACKEND_URL}/api/health")"
if [[ "${HEALTH_PAYLOAD}" != *"\"status\":\"ok\""* ]]; then
  echo "unexpected backend payload: ${HEALTH_PAYLOAD}"
  exit 1
fi

echo "[smoke] backend openapi"
OPENAPI_PAYLOAD="$(curl -fsS "${BACKEND_URL}/openapi.json")"
if [[ "${OPENAPI_PAYLOAD}" != *"\"/api/backtests/structure\""* ]]; then
  echo "missing /api/backtests/structure in openapi"
  exit 1
fi

echo "[smoke] frontend index"
HTTP_HEADER="$(curl -fsSI "${FRONTEND_URL}/" | tr -d '\r')"
if [[ "${HTTP_HEADER}" != *"200 OK"* ]]; then
  echo "unexpected frontend header: ${HTTP_HEADER}"
  exit 1
fi

echo "[smoke] frontend title"
INDEX_PAYLOAD="$(curl -fsS "${FRONTEND_URL}/")"
if [[ "${INDEX_PAYLOAD}" != *"<title>AetherStockAnalysis</title>"* ]]; then
  echo "missing frontend title marker"
  exit 1
fi

echo "smoke_local: passed"
