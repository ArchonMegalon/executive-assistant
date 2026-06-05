#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose -f docker-compose.property.yml)
else
  DC=(docker-compose -f docker-compose.property.yml)
fi

export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-propertyquarry_ci_postgres}"
TEST_DB="${EA_TEST_POSTGRES_DB:-propertyquarry_test_contracts}"
PYTHON_BIN="${EA_TEST_PYTHON:-python3}"
created_env=0
env_had_file=0
env_backup=""

if [[ ! -f "${ROOT}/.env" ]]; then
  cp "${ROOT}/.env.example" "${ROOT}/.env"
  chmod 600 "${ROOT}/.env"
  created_env=1
else
  env_had_file=1
  env_backup="$(mktemp)"
  cp "${ROOT}/.env" "${env_backup}"
fi

cleanup() {
  "${DC[@]}" down -v >/dev/null 2>&1 || true
  if [[ "${env_had_file}" == "1" && -n "${env_backup}" && -f "${env_backup}" ]]; then
    cp "${env_backup}" "${ROOT}/.env"
    rm -f "${env_backup}"
  fi
  if [[ "${created_env}" == "1" ]]; then
    rm -f "${ROOT}/.env"
  fi
}
trap cleanup EXIT

set_env_value() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "${ROOT}/.env"; then
    sed -i "s|^${key}=.*$|${key}=${value}|" "${ROOT}/.env"
  else
    echo "${key}=${value}" >> "${ROOT}/.env"
  fi
}

set_env_value "POSTGRES_PASSWORD" "${POSTGRES_PASSWORD}"
set_env_value "EA_RUNTIME_MODE" "dev"
set_env_value "DATABASE_URL" ""

echo "== property-postgres-contracts: boot db =="
"${DC[@]}" up -d propertyquarry-db

db_ready=0
for _ in $(seq 1 90); do
  if docker exec propertyquarry-db pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then
    db_ready=1
    break
  fi
  sleep 1
done
if [[ "${db_ready}" != "1" ]]; then
  echo "propertyquarry-db did not become ready" >&2
  docker logs propertyquarry-db >&2 || true
  exit 3
fi

docker exec -i propertyquarry-db psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d postgres \
  -c "DROP DATABASE IF EXISTS \"${TEST_DB}\";" >/dev/null
docker exec -i propertyquarry-db psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d postgres \
  -c "CREATE DATABASE \"${TEST_DB}\";" >/dev/null

db_host="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' propertyquarry-db 2>/dev/null | tr -d '[:space:]')"
if [[ -z "${db_host}" ]]; then
  echo "unable to resolve propertyquarry-db IP address" >&2
  exit 3
fi

db_url="postgresql://postgres:${POSTGRES_PASSWORD}@${db_host}:5432/${TEST_DB}"
echo "db_name=${TEST_DB}"

EA_TEST_PROPERTY_DATABASE_URL="${db_url}" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ea \
  "${PYTHON_BIN}" -m pytest -q tests/test_property_search_runs.py -k "postgres_round_trip" -p no:cacheprovider

echo "property-postgres-contracts complete"
