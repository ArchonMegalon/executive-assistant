#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/smoke_api_runtime.sh

Runs deploy-safe HTTP smoke checks only. This script does not mutate runtime
state and does not rely on trusted caller principal headers, so it is safe for
prod deploy gates.
EOF
  exit 0
fi

curl() {
  command curl \
    --retry 20 \
    --retry-delay 1 \
    --retry-max-time 120 \
    --retry-all-errors \
    --retry-connrefused \
    --connect-timeout 5 \
    --max-time 30 \
    "$@"
}

HOST_PORT="${EA_HOST_PORT:-}"
if [[ -z "${HOST_PORT}" && -f "${EA_ROOT}/.env" ]]; then
  HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
fi
HOST_PORT="${HOST_PORT:-8090}"
BASE="http://localhost:${HOST_PORT}"

env_file_value() {
  local key="$1"
  local line=""
  if [[ -f "${EA_ROOT}/.env" ]]; then
    line="$(grep -E "^${key}=" "${EA_ROOT}/.env" | tail -n1 || true)"
  fi
  printf '%s' "${line#*=}"
}

effective_value() {
  local key="$1"
  if [[ -n "${!key+x}" ]]; then
    printf '%s' "${!key}"
    return 0
  fi
  env_file_value "${key}"
}

truthy() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

wait_for_health_stable() {
  local attempts="${1:-60}"
  local consecutive_required="${2:-3}"
  local sleep_seconds="${3:-1}"
  local consecutive=0
  local i
  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS "${BASE}/health" >/dev/null \
      && curl -fsS "${BASE}/healthz" >/dev/null \
      && curl -fsS "${BASE}/health/ready" >/dev/null \
      && curl -fsS "${BASE}/version" >/dev/null; then
      consecutive=$((consecutive + 1))
      if [[ "${consecutive}" -ge "${consecutive_required}" ]]; then
        return 0
      fi
    else
      consecutive=0
    fi
    sleep "${sleep_seconds}"
  done
  echo "runtime smoke timed out waiting for stable health/version responses from ${BASE}" >&2
  return 1
}

wait_for_health_stable 60 3 1

tmp_dir="${EA_SMOKE_TMP_DIR:-${EA_ROOT}/.smoke_tmp}"
mkdir -p "${tmp_dir}"
version_path="$(mktemp "${tmp_dir}/runtime-version.XXXXXX.json")"
openapi_path="$(mktemp "${tmp_dir}/runtime-openapi.XXXXXX.json")"
trap 'rm -f "${version_path:-}" "${openapi_path:-}"' EXIT

curl -fsS "${BASE}/version" -o "${version_path}"

runtime_mode="$(effective_value EA_RUNTIME_MODE)"
runtime_mode="${runtime_mode,,}"
runtime_mode="${runtime_mode:-dev}"
api_docs_value="$(effective_value EA_ENABLE_API_DOCS)"
api_docs_expected=0
if [[ -n "${api_docs_value}" ]]; then
  if truthy "${api_docs_value}"; then
    api_docs_expected=1
  fi
elif [[ "${runtime_mode}" != "prod" ]]; then
  api_docs_expected=1
fi

if [[ "${api_docs_expected}" == "1" ]]; then
  curl -fsS "${BASE}/openapi.json" -o "${openapi_path}"
else
  for disabled_path in /openapi.json /api/docs /api/redoc; do
    status_code="$(
      command curl \
        --silent \
        --show-error \
        --output /dev/null \
        --write-out '%{http_code}' \
        --connect-timeout 5 \
        --max-time 30 \
        "${BASE}${disabled_path}"
    )"
    if [[ "${status_code}" != "404" ]]; then
      echo "expected disabled API docs path ${disabled_path} to return 404, got ${status_code}" >&2
      exit 1
    fi
  done
fi

python3 - <<'PY' "${version_path}" "${openapi_path}" "${api_docs_expected}"
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    version = json.load(handle)
if version.get("app_name") != "ea-rewrite":
    raise SystemExit(f"unexpected app_name: {version.get('app_name')!r}")
if sys.argv[3] == "1":
    with open(sys.argv[2], "r", encoding="utf-8") as handle:
        openapi = json.load(handle)
    paths = openapi.get("paths") or {}
    for path in ("/health", "/health/live", "/health/ready", "/version"):
        if path not in paths:
            raise SystemExit(f"missing required OpenAPI path: {path}")
PY

echo "runtime smoke ok: ${BASE} (api_docs_expected=${api_docs_expected})"
