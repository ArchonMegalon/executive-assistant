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
  EA_RETENTION_PROFILE                     aggressive|standard|conservative (default: standard)
  EA_RETENTION_EXECUTION_EVENTS_DAYS       default: 90
  EA_RETENTION_POLICY_DECISIONS_DAYS       default: 90
  EA_RETENTION_OBSERVATIONS_DAYS           default: 60
  EA_RETENTION_DELIVERY_SENT_DAYS          default: 30
  EA_RETENTION_APPROVAL_REQUESTS_DAYS      default: 120
  EA_RETENTION_APPROVAL_DECISIONS_DAYS     default: 120
  EA_RETENTION_TABLES                      Optional CSV table allowlist
  EA_RETENTION_SKIP_TABLES                 Optional CSV table skip list
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

DB_SERVICE="${PROPERTYQUARRY_DB_SERVICE:-${EA_DB_SERVICE:-ea-db}}"
DB_CONTAINER="${EA_DB_CONTAINER:-${DB_SERVICE}}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-ea}"

RETENTION_PROFILE="$(echo "${EA_RETENTION_PROFILE:-standard}" | tr '[:upper:]' '[:lower:]')"
case "${RETENTION_PROFILE}" in
  aggressive)
    DEFAULT_EXECUTION_EVENTS_DAYS=30
    DEFAULT_POLICY_DECISIONS_DAYS=30
    DEFAULT_OBSERVATIONS_DAYS=30
    DEFAULT_DELIVERY_SENT_DAYS=7
    DEFAULT_APPROVAL_REQUESTS_DAYS=60
    DEFAULT_APPROVAL_DECISIONS_DAYS=60
    ;;
  conservative)
    DEFAULT_EXECUTION_EVENTS_DAYS=180
    DEFAULT_POLICY_DECISIONS_DAYS=180
    DEFAULT_OBSERVATIONS_DAYS=120
    DEFAULT_DELIVERY_SENT_DAYS=60
    DEFAULT_APPROVAL_REQUESTS_DAYS=180
    DEFAULT_APPROVAL_DECISIONS_DAYS=180
    ;;
  standard)
    DEFAULT_EXECUTION_EVENTS_DAYS=90
    DEFAULT_POLICY_DECISIONS_DAYS=90
    DEFAULT_OBSERVATIONS_DAYS=60
    DEFAULT_DELIVERY_SENT_DAYS=30
    DEFAULT_APPROVAL_REQUESTS_DAYS=120
    DEFAULT_APPROVAL_DECISIONS_DAYS=120
    ;;
  *)
    echo "EA_RETENTION_PROFILE must be aggressive|standard|conservative" >&2
    exit 2
    ;;
esac

EXECUTION_EVENTS_DAYS="${EA_RETENTION_EXECUTION_EVENTS_DAYS:-${DEFAULT_EXECUTION_EVENTS_DAYS}}"
POLICY_DECISIONS_DAYS="${EA_RETENTION_POLICY_DECISIONS_DAYS:-${DEFAULT_POLICY_DECISIONS_DAYS}}"
OBSERVATIONS_DAYS="${EA_RETENTION_OBSERVATIONS_DAYS:-${DEFAULT_OBSERVATIONS_DAYS}}"
DELIVERY_SENT_DAYS="${EA_RETENTION_DELIVERY_SENT_DAYS:-${DEFAULT_DELIVERY_SENT_DAYS}}"
APPROVAL_REQUESTS_DAYS="${EA_RETENTION_APPROVAL_REQUESTS_DAYS:-${DEFAULT_APPROVAL_REQUESTS_DAYS}}"
APPROVAL_DECISIONS_DAYS="${EA_RETENTION_APPROVAL_DECISIONS_DAYS:-${DEFAULT_APPROVAL_DECISIONS_DAYS}}"

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

DEFAULT_TABLES=(
  execution_events
  policy_decisions
  observation_events
  delivery_outbox
  approval_requests
  approval_decisions
)
TABLES=("${DEFAULT_TABLES[@]}")

if [[ -n "${EA_RETENTION_TABLES:-}" ]]; then
  TABLES=()
  IFS=',' read -r -a requested_tables <<<"${EA_RETENTION_TABLES}"
  for raw_table in "${requested_tables[@]}"; do
    t="$(echo "${raw_table}" | xargs)"
    if [[ -n "${t}" ]]; then
      TABLES+=("${t}")
    fi
  done
fi

if [[ -n "${EA_RETENTION_SKIP_TABLES:-}" ]]; then
  declare -A skip_table_map=()
  IFS=',' read -r -a skip_tables <<<"${EA_RETENTION_SKIP_TABLES}"
  for raw_skip in "${skip_tables[@]}"; do
    t="$(echo "${raw_skip}" | xargs)"
    if [[ -n "${t}" ]]; then
      skip_table_map["${t}"]=1
    fi
  done
  filtered_tables=()
  for t in "${TABLES[@]}"; do
    if [[ -z "${skip_table_map[${t}]+x}" ]]; then
      filtered_tables+=("${t}")
    fi
  done
  TABLES=("${filtered_tables[@]}")
fi

echo "== EA DB retention =="
if [[ "${APPLY}" == "1" ]]; then
  echo "mode: apply"
else
  echo "mode: dry-run"
fi
echo "profile: ${RETENTION_PROFILE}"
echo "windows: execution_events=${EXECUTION_EVENTS_DAYS}d policy_decisions=${POLICY_DECISIONS_DAYS}d observations=${OBSERVATIONS_DAYS}d delivery_sent=${DELIVERY_SENT_DAYS}d approval_requests=${APPROVAL_REQUESTS_DAYS}d approval_decisions=${APPROVAL_DECISIONS_DAYS}d"
if [[ "${#TABLES[@]}" == "0" ]]; then
  echo "no retention tables selected after allowlist/skip filtering" >&2
  exit 2
fi
echo "tables: $(IFS=, ; echo "${TABLES[*]}")"

"${DC[@]}" up -d "${DB_SERVICE}" >/dev/null
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
