#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

HOST_PORT="${EA_HOST_PORT:-}"
if [[ -z "${HOST_PORT}" && -f "${EA_ROOT}/.env" ]]; then
  HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
fi
HOST_PORT="${HOST_PORT:-8090}"
BASE="http://localhost:${HOST_PORT}"

OUT_DIR="${EA_ROOT}/artifacts"
mkdir -p "${OUT_DIR}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${OUT_DIR}/openapi_${STAMP}.json"

curl -fsS "${BASE}/openapi.json" -o "${OUT_FILE}"
cp "${OUT_FILE}" "${OUT_DIR}/openapi_latest.json"

echo "openapi exported to: ${OUT_FILE}"
echo "latest snapshot: ${OUT_DIR}/openapi_latest.json"
