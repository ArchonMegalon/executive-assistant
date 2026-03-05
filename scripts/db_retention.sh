#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/db_retention.sh [--apply]

Dry-run by default. Prints candidate row counts for retention pruning on runtime tables.
Use --apply to execute deletion statements.

Environment:
  EA_DB_CONTAINER                          Postgres container name (default: ea-db)
  POSTGRES_USER                            Postgres user (default: postgres)
  POSTGRES_DB                              Postgres database name (default: ea)
  EA_RETENTION_EXECUTION_EVENTS_DAYS       default: 90
  EA_RETENTION_POLICY_DECISIONS_DAYS       default: 90
  EA_RETENTION_OBSERVATIONS_DAYS           default: 60
  EA_RETENTION_DELIVERY_SENT_DAYS          default: 30
  EA_RETENTION_APPROVAL_REQUESTS_DAYS      default: 120
  EA_RETENTION_APPROVAL_DECISIONS_DAYS     default: 120
EOF
  exit 0
fi

APPLY=0
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
elif [[ -n "${1:-}" ]]; then
  echo "unknown argument: ${1}" >&2
  echo "use --help for usage" >&2
  exit 2
fi

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

DB_CONTAINER="${EA_DB_CONTAINER:-ea-db}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-ea}"

EXECUTION_EVENTS_DAYS="${EA_RETENTION_EXECUTION_EVENTS_DAYS:-90}"
POLICY_DECISIONS_DAYS="${EA_RETENTION_POLICY_DECISIONS_DAYS:-90}"
OBSERVATIONS_DAYS="${EA_RETENTION_OBSERVATIONS_DAYS:-60}"
DELIVERY_SENT_DAYS="${EA_RETENTION_DELIVERY_SENT_DAYS:-30}"
APPROVAL_REQUESTS_DAYS="${EA_RETENTION_APPROVAL_REQUESTS_DAYS:-120}"
APPROVAL_DECISIONS_DAYS="${EA_RETENTION_APPROVAL_DECISIONS_DAYS:-120}"

for v in \
  EXECUTION_EVENTS_DAYS \
  POLICY_DECISIONS_DAYS \
  OBSERVATIONS_DAYS \
  DELIVERY_SENT_DAYS \
  APPROVAL_REQUESTS_DAYS \
  APPROVAL_DECISIONS_DAYS
do
  if ! [[ "${!v}" =~ ^[0-9]+$ ]]; then
    echo "${v} must be an integer day count" >&2
    exit 2
  fi
done

sql_scalar() {
  local q="$1"
  docker exec -i "${DB_CONTAINER}" psql -At -U "${DB_USER}" -d "${DB_NAME}" -c "${q}" | tr -d '[:space:]'
}

table_exists() {
  local table_name="$1"
  [[ "$(sql_scalar "SELECT to_regclass('public.${table_name}') IS NOT NULL;")" == "t" ]]
}

predicate_for_table() {
  local table_name="$1"
  case "${table_name}" in
    execution_events)
      echo "created_at < NOW() - INTERVAL '${EXECUTION_EVENTS_DAYS} days'"
      ;;
    policy_decisions)
      echo "created_at < NOW() - INTERVAL '${POLICY_DECISIONS_DAYS} days'"
      ;;
    observation_events)
      echo "created_at < NOW() - INTERVAL '${OBSERVATIONS_DAYS} days'"
      ;;
    delivery_outbox)
      echo "status = 'sent' AND COALESCE(updated_at, created_at) < NOW() - INTERVAL '${DELIVERY_SENT_DAYS} days'"
      ;;
    approval_requests)
      echo "status IN ('approved', 'denied', 'expired', 'cancelled') AND COALESCE(updated_at, created_at) < NOW() - INTERVAL '${APPROVAL_REQUESTS_DAYS} days'"
      ;;
    approval_decisions)
      echo "created_at < NOW() - INTERVAL '${APPROVAL_DECISIONS_DAYS} days'"
      ;;
    *)
      echo "FALSE"
      ;;
  esac
}

TABLES=(
  execution_events
  policy_decisions
  observation_events
  delivery_outbox
  approval_requests
  approval_decisions
)

echo "== EA DB retention =="
if [[ "${APPLY}" == "1" ]]; then
  echo "mode: apply"
else
  echo "mode: dry-run"
fi

"${DC[@]}" up -d ea-db >/dev/null
for _ in $(seq 1 30); do
  if docker exec "${DB_CONTAINER}" pg_isready -U "${DB_USER}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

for table_name in "${TABLES[@]}"; do
  if ! table_exists "${table_name}"; then
    echo "${table_name}: missing"
    continue
  fi
  predicate="$(predicate_for_table "${table_name}")"
  candidates="$(sql_scalar "SELECT COUNT(*) FROM public.${table_name} WHERE ${predicate};")"
  if [[ "${APPLY}" == "1" ]]; then
    deleted="$(sql_scalar "WITH deleted AS (DELETE FROM public.${table_name} WHERE ${predicate} RETURNING 1) SELECT COUNT(*) FROM deleted;")"
    echo "${table_name}: candidates=${candidates} deleted=${deleted}"
  else
    echo "${table_name}: candidates=${candidates}"
  fi
done

if [[ "${APPLY}" == "1" ]]; then
  echo "retention apply complete"
else
  echo "retention dry-run complete"
fi
