#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/smoke_postgres.sh

Runs a Postgres-backed smoke path:
  1) starts ea-db + ea-api with docker compose
  2) applies kernel migrations
  3) verifies /health/ready reason is postgres_ready
  4) runs scripts/smoke_api.sh
  5) verifies DB row growth for core runtime tables

Environment:
  EA_HOST_PORT              Optional host port override (falls back to .env or 8090)
  EA_DB_CONTAINER           Postgres container name (default: ea-db)
  POSTGRES_USER             Postgres user (default: postgres)
  POSTGRES_DB               Postgres database name (default: ea)
EOF
  exit 0
fi

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

created_env=0
if [[ ! -f "${EA_ROOT}/.env" ]]; then
  cp "${EA_ROOT}/.env.example" "${EA_ROOT}/.env"
  chmod 600 "${EA_ROOT}/.env"
  created_env=1
fi

HOST_PORT="${EA_HOST_PORT:-}"
if [[ -z "${HOST_PORT}" ]]; then
  HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
fi
HOST_PORT="${HOST_PORT:-8090}"
BASE="http://localhost:${HOST_PORT}"

cleanup() {
  if [[ "${created_env}" == "1" ]]; then
    rm -f "${EA_ROOT}/.env"
  fi
}
trap cleanup EXIT

cd "${EA_ROOT}"

echo "== smoke-postgres: compose up =="
"${DC[@]}" up -d --build ea-db ea-api

echo "== smoke-postgres: bootstrap migrations =="
bash scripts/db_bootstrap.sh

echo "== smoke-postgres: readiness check =="
ready_json="$(curl -fsS "${BASE}/health/ready")"
ready_reason="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("reason",""))' <<<"${ready_json}")"
if [[ "${ready_reason}" != "postgres_ready" ]]; then
  echo "expected readiness reason postgres_ready, got: ${ready_reason}" >&2
  exit 31
fi

echo "== smoke-postgres: api smoke =="
bash scripts/smoke_api.sh

echo "== smoke-postgres: db status verification =="
status_out="$(bash scripts/db_status.sh)"
echo "${status_out}"

sessions_count="$(awk -F': ' '/^execution_sessions:/ {v=$2} END {print v+0}' <<<"${status_out}")"
events_count="$(awk -F': ' '/^execution_events:/ {v=$2} END {print v+0}' <<<"${status_out}")"
policy_count="$(awk -F': ' '/^policy_decisions:/ {v=$2} END {print v+0}' <<<"${status_out}")"

if [[ "${sessions_count}" -lt 1 || "${events_count}" -lt 1 || "${policy_count}" -lt 1 ]]; then
  echo "postgres smoke failed: expected non-zero execution_sessions/execution_events/policy_decisions counts" >&2
  exit 32
fi

echo "smoke-postgres complete"
