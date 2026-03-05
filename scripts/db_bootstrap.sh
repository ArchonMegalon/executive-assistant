#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

DB_CONTAINER="${EA_DB_CONTAINER:-ea-db}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-ea}"

SQL_FILES=(
  "ea/schema/20260305_v0_2_execution_ledger_kernel.sql"
  "ea/schema/20260305_v0_3_channel_runtime_kernel.sql"
  "ea/schema/20260305_v0_4_policy_decisions_kernel.sql"
)

echo "== EA DB bootstrap =="
"${DC[@]}" up -d ea-db

for _ in $(seq 1 30); do
  if docker exec "${DB_CONTAINER}" pg_isready -U "${DB_USER}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

for rel in "${SQL_FILES[@]}"; do
  sql="${EA_ROOT}/${rel}"
  if [[ ! -f "${sql}" ]]; then
    echo "missing migration: ${sql}" >&2
    exit 1
  fi
  echo "applying ${rel}"
  docker exec -i "${DB_CONTAINER}" psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "${DB_NAME}" < "${sql}"
done

echo "db bootstrap complete"
