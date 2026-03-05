#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/db_size.sh

Prints Postgres runtime size diagnostics:
  - total database size
  - total table/index/relation footprints
  - largest user tables with table/index/total sizes

Environment:
  EA_DB_CONTAINER          Postgres container name (default: ea-db)
  POSTGRES_USER            Postgres user (default: postgres)
  POSTGRES_DB              Postgres database name (default: ea)
  EA_DB_SIZE_LIMIT         Number of largest tables to print (default: 20)
  EA_DB_SIZE_TABLE_PREFIX  Optional table-name prefix filter
  EA_DB_SIZE_MIN_MB        Optional minimum total table size in MB
EOF
  exit 0
fi

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

DB_CONTAINER="${EA_DB_CONTAINER:-ea-db}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-ea}"
SIZE_LIMIT="${EA_DB_SIZE_LIMIT:-20}"
TABLE_PREFIX="${EA_DB_SIZE_TABLE_PREFIX:-}"
MIN_MB="${EA_DB_SIZE_MIN_MB:-0}"

if ! [[ "${SIZE_LIMIT}" =~ ^[0-9]+$ ]]; then
  echo "EA_DB_SIZE_LIMIT must be an integer" >&2
  exit 2
fi

if [[ -n "${TABLE_PREFIX}" && ! "${TABLE_PREFIX}" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "EA_DB_SIZE_TABLE_PREFIX must match [A-Za-z0-9_]+" >&2
  exit 2
fi

if ! [[ "${MIN_MB}" =~ ^[0-9]+$ ]]; then
  echo "EA_DB_SIZE_MIN_MB must be an integer" >&2
  exit 2
fi

FILTER_CLAUSE="TRUE"
if [[ -n "${TABLE_PREFIX}" ]]; then
  FILTER_CLAUSE="${FILTER_CLAUSE} AND relname LIKE '${TABLE_PREFIX}%'"
fi
if [[ "${MIN_MB}" -gt 0 ]]; then
  FILTER_CLAUSE="${FILTER_CLAUSE} AND pg_total_relation_size(relid) >= (${MIN_MB} * 1024 * 1024)"
fi

echo "== EA DB size =="
"${DC[@]}" up -d ea-db >/dev/null

for _ in $(seq 1 30); do
  if docker exec "${DB_CONTAINER}" pg_isready -U "${DB_USER}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "-- database size --"
docker exec -i "${DB_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -c \
  "SELECT current_database() AS db_name, pg_size_pretty(pg_database_size(current_database())) AS db_size;"

echo "-- aggregate relation footprint --"
docker exec -i "${DB_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -c \
  "SELECT \
     pg_size_pretty(COALESCE(SUM(pg_relation_size(relid)),0)) AS table_bytes, \
     pg_size_pretty(COALESCE(SUM(pg_indexes_size(relid)),0)) AS index_bytes, \
     pg_size_pretty(COALESCE(SUM(pg_total_relation_size(relid)),0)) AS relation_total \
   FROM pg_catalog.pg_statio_user_tables \
   WHERE ${FILTER_CLAUSE};"

echo "-- largest user tables (top ${SIZE_LIMIT}) --"
if [[ -n "${TABLE_PREFIX}" ]]; then
  echo "table_prefix_filter=${TABLE_PREFIX}"
fi
if [[ "${MIN_MB}" -gt 0 ]]; then
  echo "table_min_size_mb=${MIN_MB}"
fi
docker exec -i "${DB_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -c \
  "SELECT \
     relname AS table_name, \
     pg_size_pretty(pg_relation_size(relid)) AS table_size, \
     pg_size_pretty(pg_indexes_size(relid)) AS index_size, \
     pg_size_pretty(pg_total_relation_size(relid)) AS total_size \
   FROM pg_catalog.pg_statio_user_tables \
   WHERE ${FILTER_CLAUSE} \
   ORDER BY pg_total_relation_size(relid) DESC \
   LIMIT ${SIZE_LIMIT};"
