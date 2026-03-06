#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${EA_ROOT}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/test_postgres_contracts.sh

Boot an isolated Postgres test database, apply kernel migrations, and run the
Postgres-backed repository contract tests from the host Python environment.

Environment:
  EA_DB_CONTAINER           Postgres container name (default: ea-db)
  POSTGRES_USER             Postgres user (default: postgres; falls back to .env or env template)
  POSTGRES_PASSWORD         Postgres password (falls back to .env or env template)
  EA_TEST_POSTGRES_DB       Isolated test database name (default: ea_test_contracts)
  EA_TEST_PYTHON            Python executable with pytest installed (default: .venv/bin/python if present, otherwise python3)
  EA_TEST_FILES             Space-separated pytest file list override
EOF
  exit 0
fi

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
fi

created_env=0
if [[ ! -f "${EA_ROOT}/.env" ]]; then
  if [[ -z "${env_template}" ]]; then
    echo "missing env template (.env.example or .env.local.example)" >&2
    exit 2
  fi
  cp "${env_template}" "${EA_ROOT}/.env"
  chmod 600 "${EA_ROOT}/.env"
  created_env=1
fi
env_file="${EA_ROOT}/.env"

cleanup() {
  if [[ "${created_env}" == "1" ]]; then
    rm -f "${EA_ROOT}/.env"
  fi
}
trap cleanup EXIT

DB_CONTAINER="${EA_DB_CONTAINER:-ea-db}"
DB_USER="${POSTGRES_USER:-}"
if [[ -z "${DB_USER}" && -n "${env_file}" ]]; then
  DB_USER="$(grep -E '^POSTGRES_USER=' "${env_file}" | tail -n1 | cut -d= -f2- || true)"
fi
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${POSTGRES_PASSWORD:-}"
if [[ -z "${DB_PASSWORD}" && -n "${env_file}" ]]; then
  DB_PASSWORD="$(grep -E '^POSTGRES_PASSWORD=' "${env_file}" | tail -n1 | cut -d= -f2- || true)"
fi
TEST_DB="${EA_TEST_POSTGRES_DB:-ea_test_contracts}"
PYTHON_BIN="${EA_TEST_PYTHON:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${EA_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${EA_ROOT}/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi
TEST_FILES="${EA_TEST_FILES:-tests/test_artifacts_postgres_integration.py tests/test_channel_runtime_postgres_integration.py tests/test_memory_router_contracts.py tests/test_postgres_contract_matrix_integration.py tests/test_rewrite_scope_contracts.py tests/test_rewrite_api_scope_contracts.py tests/test_rewrite_dependency_projection_contracts.py}"

if [[ -z "${DB_PASSWORD}" ]]; then
  echo "POSTGRES_PASSWORD is required (or set it in .env)" >&2
  exit 2
fi

echo "== postgres contract tests =="
"${DC[@]}" up -d ea-db >/dev/null

for _ in $(seq 1 30); do
  if docker exec "${DB_CONTAINER}" pg_isready -U "${DB_USER}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

docker exec -i "${DB_CONTAINER}" psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d postgres \
  -c "DROP DATABASE IF EXISTS \"${TEST_DB}\";" >/dev/null
docker exec -i "${DB_CONTAINER}" psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d postgres \
  -c "CREATE DATABASE \"${TEST_DB}\";" >/dev/null

POSTGRES_DB="${TEST_DB}" bash scripts/db_bootstrap.sh >/dev/null

DB_HOST="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "${DB_CONTAINER}" 2>/dev/null | tr -d '[:space:]')"
if [[ -z "${DB_HOST}" ]]; then
  echo "unable to resolve ${DB_CONTAINER} IP address" >&2
  exit 3
fi

DB_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:5432/${TEST_DB}"

echo "db_container=${DB_CONTAINER}"
echo "db_host=${DB_HOST}"
echo "db_name=${TEST_DB}"

# shellcheck disable=SC2086
EA_TEST_DATABASE_URL="${DB_URL}" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ea \
  "${PYTHON_BIN}" -m pytest -q ${TEST_FILES} -p no:cacheprovider
