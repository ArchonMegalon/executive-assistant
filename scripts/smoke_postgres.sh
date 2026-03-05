#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
legacy_fixture=0

for arg in "$@"; do
  case "${arg}" in
    --legacy-fixture)
      legacy_fixture=1
      ;;
    --help|-h)
      cat <<'USAGE'
Usage:
  bash scripts/smoke_postgres.sh [--legacy-fixture]

Runs a Postgres-backed smoke path against an isolated smoke database:
  1) starts ea-db with docker compose
  2) resets isolated smoke DB
  3) starts ea-api pinned to isolated DB
  4) applies kernel migrations
  5) verifies /health/ready reason is postgres_ready
  6) runs scripts/smoke_api.sh
  7) verifies DB row growth for core runtime tables

Options:
  --legacy-fixture          Seed a legacy UUID/approval schema fixture before
                            bootstrap and validate migration-upgrade behavior.
                            In this mode, API smoke is skipped.

Environment:
  EA_HOST_PORT              Optional host port override (falls back to .env or 8090)
  EA_DB_CONTAINER           Postgres container name (default: ea-db)
  POSTGRES_USER             Postgres user (default: postgres)
  POSTGRES_PASSWORD         Postgres password (falls back to .env)
  EA_SMOKE_DB               Isolated smoke database name (default: ea_smoke_runtime)
USAGE
      exit 0
      ;;
    *)
      echo "unknown argument: ${arg}" >&2
      exit 2
      ;;
  esac
done

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

env_template=""
if [[ -f "${EA_ROOT}/.env.example" ]]; then
  env_template="${EA_ROOT}/.env.example"
elif [[ -f "${EA_ROOT}/.env.local.example" ]]; then
  env_template="${EA_ROOT}/.env.local.example"
else
  echo "missing env template (.env.example or .env.local.example)" >&2
  exit 34
fi

created_env=0
env_had_file=0
env_backup=""
restore_api_env=0
if [[ ! -f "${EA_ROOT}/.env" ]]; then
  cp "${env_template}" "${EA_ROOT}/.env"
  chmod 600 "${EA_ROOT}/.env"
  created_env=1
else
  env_had_file=1
  env_backup="$(mktemp)"
  cp "${EA_ROOT}/.env" "${env_backup}"
fi

HOST_PORT="${EA_HOST_PORT:-}"
if [[ -z "${HOST_PORT}" ]]; then
  HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
fi
HOST_PORT="${HOST_PORT:-8090}"
BASE="http://localhost:${HOST_PORT}"

DB_CONTAINER="${EA_DB_CONTAINER:-ea-db}"
DB_USER="${POSTGRES_USER:-$(grep -E '^POSTGRES_USER=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${POSTGRES_PASSWORD:-$(grep -E '^POSTGRES_PASSWORD=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)}"
DB_PASSWORD="${DB_PASSWORD:-CHANGE_ME_STRONG}"
SMOKE_DB="${EA_SMOKE_DB:-ea_smoke_runtime}"

if [[ ! "${SMOKE_DB}" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "EA_SMOKE_DB must match ^[a-zA-Z0-9_]+$" >&2
  exit 33
fi

cleanup() {
  if [[ "${restore_api_env}" == "1" && "${env_had_file}" == "1" && -n "${env_backup}" && -f "${env_backup}" ]]; then
    cp "${env_backup}" "${EA_ROOT}/.env"
    "${DC[@]}" up -d ea-api >/dev/null 2>&1 || true
  fi
  if [[ -n "${env_backup}" && -f "${env_backup}" ]]; then
    rm -f "${env_backup}"
  fi
  if [[ "${created_env}" == "1" ]]; then
    rm -f "${EA_ROOT}/.env"
  fi
}
trap cleanup EXIT

apply_legacy_fixture() {
  echo "== smoke-postgres: apply legacy fixture =="
  docker exec -i "${DB_CONTAINER}" psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "${SMOKE_DB}" <<'SQL'
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS execution_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS execution_events (
    event_id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
    level TEXT NOT NULL DEFAULT 'info',
    event_type TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS execution_steps (
    step_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
    step_order INT NOT NULL DEFAULT 0,
    step_key TEXT NOT NULL DEFAULT '',
    step_title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    preconditions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_text TEXT,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS approval_requests (
    approval_request_id SERIAL PRIMARY KEY,
    draft_id UUID NOT NULL DEFAULT gen_random_uuid(),
    tenant_key TEXT NOT NULL DEFAULT 'default',
    principal_id TEXT NOT NULL DEFAULT 'local-user',
    request_status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS approval_decisions (
    approval_decision_id SERIAL PRIMARY KEY,
    approval_request_id BIGINT NOT NULL REFERENCES approval_requests(approval_request_id),
    decided_by TEXT NOT NULL DEFAULT 'system',
    decision TEXT NOT NULL DEFAULT 'pending',
    decision_payload_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SQL
}

validate_legacy_upgrade() {
  echo "== smoke-postgres: validate legacy migration upgrade =="

  type_match="$(docker exec -i "${DB_CONTAINER}" psql -At -U "${DB_USER}" -d "${SMOKE_DB}" -c "SELECT (SELECT data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='execution_sessions' AND column_name='session_id') = (SELECT data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='execution_steps' AND column_name='session_id');" | tr -d '[:space:]')"
  if [[ "${type_match}" != "t" ]]; then
    echo "legacy upgrade check failed: execution_steps.session_id type mismatch" >&2
    exit 41
  fi

  req_cols="$(docker exec -i "${DB_CONTAINER}" psql -At -U "${DB_USER}" -d "${SMOKE_DB}" -c "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='approval_requests' AND column_name IN ('approval_id','session_id','step_id','reason','requested_action_json','status','created_at','updated_at');" | tr -d '[:space:]')"
  if [[ "${req_cols}" -lt 8 ]]; then
    echo "legacy upgrade check failed: approval_requests missing runtime columns" >&2
    exit 42
  fi

  dec_cols="$(docker exec -i "${DB_CONTAINER}" psql -At -U "${DB_USER}" -d "${SMOKE_DB}" -c "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='approval_decisions' AND column_name IN ('decision_id','approval_id','session_id','step_id','decision','decided_by','reason','created_at');" | tr -d '[:space:]')"
  if [[ "${dec_cols}" -lt 8 ]]; then
    echo "legacy upgrade check failed: approval_decisions missing runtime columns" >&2
    exit 43
  fi
}

cd "${EA_ROOT}"

echo "== smoke-postgres: compose up (db only) =="
"${DC[@]}" up -d --build ea-db

for _ in $(seq 1 30); do
  if docker exec "${DB_CONTAINER}" pg_isready -U "${DB_USER}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "== smoke-postgres: reset isolated db ${SMOKE_DB} =="
db_password_sql="${DB_PASSWORD//\'/\'\'}"
docker exec -i "${DB_CONTAINER}" psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d postgres \
  -c "ALTER ROLE \"${DB_USER}\" WITH PASSWORD '${db_password_sql}';" >/dev/null

docker exec -i "${DB_CONTAINER}" psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d postgres \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${SMOKE_DB}' AND pid <> pg_backend_pid();" >/dev/null
docker exec -i "${DB_CONTAINER}" psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d postgres \
  -c "DROP DATABASE IF EXISTS \"${SMOKE_DB}\";" >/dev/null
docker exec -i "${DB_CONTAINER}" psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d postgres \
  -c "CREATE DATABASE \"${SMOKE_DB}\";" >/dev/null

if [[ "${legacy_fixture}" == "1" ]]; then
  apply_legacy_fixture
fi

if grep -q '^DATABASE_URL=' "${EA_ROOT}/.env"; then
  sed -i "s|^DATABASE_URL=.*$|DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@ea-db:5432/${SMOKE_DB}|" "${EA_ROOT}/.env"
else
  echo "DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@ea-db:5432/${SMOKE_DB}" >> "${EA_ROOT}/.env"
fi
if grep -q '^EA_STORAGE_BACKEND=' "${EA_ROOT}/.env"; then
  sed -i 's|^EA_STORAGE_BACKEND=.*$|EA_STORAGE_BACKEND=postgres|' "${EA_ROOT}/.env"
elif grep -q '^EA_LEDGER_BACKEND=' "${EA_ROOT}/.env"; then
  sed -i 's|^EA_LEDGER_BACKEND=.*$|EA_LEDGER_BACKEND=postgres|' "${EA_ROOT}/.env"
else
  echo 'EA_STORAGE_BACKEND=postgres' >> "${EA_ROOT}/.env"
fi

if [[ "${env_had_file}" == "1" ]]; then
  restore_api_env=1
fi

echo "== smoke-postgres: compose up (api) =="
"${DC[@]}" up -d --build ea-api

echo "== smoke-postgres: bootstrap migrations =="
POSTGRES_DB="${SMOKE_DB}" bash scripts/db_bootstrap.sh

if [[ "${legacy_fixture}" == "1" ]]; then
  validate_legacy_upgrade
  echo "smoke-postgres legacy fixture complete (${SMOKE_DB})"
  exit 0
fi

echo "== smoke-postgres: readiness check =="
ready_json=""
ready_reason=""
for _ in $(seq 1 40); do
  ready_json="$(curl -sS "${BASE}/health/ready" || true)"
  ready_reason="$(python3 -c 'import json,sys
raw = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
if not raw:
    print("")
    raise SystemExit(0)
try:
    payload = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
    print("")
else:
    print(str(payload.get("reason") or ""))' "${ready_json}")"
  if [[ "${ready_reason}" == "postgres_ready" ]]; then
    break
  fi
  sleep 1
done
if [[ "${ready_reason}" != "postgres_ready" ]]; then
  echo "expected readiness reason postgres_ready, got: ${ready_reason}" >&2
  echo "readiness payload: ${ready_json}" >&2
  exit 31
fi

echo "== smoke-postgres: api smoke =="
bash scripts/smoke_api.sh

echo "== smoke-postgres: db status verification =="
status_out="$(POSTGRES_DB="${SMOKE_DB}" bash scripts/db_status.sh)"
echo "${status_out}"

sessions_count="$(awk -F': ' '/^execution_sessions:/ {v=$2} END {print v+0}' <<<"${status_out}")"
events_count="$(awk -F': ' '/^execution_events:/ {v=$2} END {print v+0}' <<<"${status_out}")"
policy_count="$(awk -F': ' '/^policy_decisions:/ {v=$2} END {print v+0}' <<<"${status_out}")"

if [[ "${sessions_count}" -lt 1 || "${events_count}" -lt 1 || "${policy_count}" -lt 1 ]]; then
  echo "postgres smoke failed: expected non-zero execution_sessions/execution_events/policy_decisions counts" >&2
  exit 32
fi

echo "smoke-postgres complete (${SMOKE_DB})"
