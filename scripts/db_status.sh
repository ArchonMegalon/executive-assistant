#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/db_status.sh

Checks kernel table presence and row counts for:
  execution_sessions, execution_events, observation_events,
  delivery_outbox, policy_decisions, artifacts,
  execution_steps, tool_receipts, run_costs,
  approval_requests, approval_decisions,
  memory_candidates, memory_items,
  entities, relationships, commitments, authority_bindings, delivery_preferences,
  follow_ups, deadline_windows, stakeholders, decision_windows, communication_policies, follow_up_rules,
  interruption_budgets
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

TABLES=(
  execution_sessions
  execution_events
  observation_events
  delivery_outbox
  policy_decisions
  artifacts
  execution_steps
  tool_receipts
  run_costs
  approval_requests
  approval_decisions
  memory_candidates
  memory_items
  entities
  relationships
  commitments
  authority_bindings
  delivery_preferences
  follow_ups
  deadline_windows
  stakeholders
  decision_windows
  communication_policies
  follow_up_rules
  interruption_budgets
)

echo "== EA DB status =="
"${DC[@]}" up -d ea-db >/dev/null

for _ in $(seq 1 30); do
  if docker exec "${DB_CONTAINER}" pg_isready -U "${DB_USER}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "-- table presence --"
for t in "${TABLES[@]}"; do
  exists="$(docker exec -i "${DB_CONTAINER}" psql -At -U "${DB_USER}" -d "${DB_NAME}" -c "SELECT to_regclass('public.${t}') IS NOT NULL;" | tr -d '[:space:]')"
  echo "${t}: ${exists}"
done

echo "-- row counts --"
for t in "${TABLES[@]}"; do
  exists="$(docker exec -i "${DB_CONTAINER}" psql -At -U "${DB_USER}" -d "${DB_NAME}" -c "SELECT to_regclass('public.${t}') IS NOT NULL;" | tr -d '[:space:]')"
  if [[ "${exists}" == "t" ]]; then
    count="$(docker exec -i "${DB_CONTAINER}" psql -At -U "${DB_USER}" -d "${DB_NAME}" -c "SELECT COUNT(*) FROM public.${t};" | tr -d '[:space:]')"
    echo "${t}: ${count}"
  else
    echo "${t}: missing"
  fi
done
