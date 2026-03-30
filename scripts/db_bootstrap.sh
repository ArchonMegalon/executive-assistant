#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/db_bootstrap.sh

Applies kernel migrations in order:
  - v0_2 execution ledger
  - v0_3 channel runtime
  - v0_4 policy decisions
  - v0_5 artifacts
  - v0_6 execution ledger v2
  - v0_7 approvals
  - v0_8 channel runtime reliability
  - v0_9 tool/connector kernel
  - v0_10 task contracts kernel
  - v0_11 memory kernel
  - v0_12 entities/relationships kernel
  - v0_13 commitments kernel
  - v0_14 authority bindings kernel
  - v0_15 delivery preferences kernel
  - v0_16 follow-ups kernel
  - v0_17 deadline windows kernel
  - v0_18 stakeholders kernel
  - v0_19 decision windows kernel
  - v0_20 communication policies kernel
  - v0_21 follow-up rules kernel
  - v0_22 interruption budgets kernel
  - v0_23 execution queue kernel
  - v0_24 human tasks kernel
  - v0_25 human task resume kernel
  - v0_26 human task assignment-state kernel
  - v0_27 human task review contract kernel
  - v0_28 operator profiles kernel
  - v0_29 human task assignment-source kernel
  - v0_30 human task assignment provenance kernel
  - v0_31 artifact principal scope
  - v0_32 provider bindings kernel
  - v0_33 task contract runtime-policy kernel
  - v0_34 assistant onboarding canonical schema
  - v0_35 execution ledger legacy compatibility
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

SQL_FILES=(
  "ea/schema/20260305_v0_2_execution_ledger_kernel.sql"
  "ea/schema/20260305_v0_3_channel_runtime_kernel.sql"
  "ea/schema/20260305_v0_4_policy_decisions_kernel.sql"
  "ea/schema/20260305_v0_5_artifacts_kernel.sql"
  "ea/schema/20260305_v0_6_execution_ledger_v2.sql"
  "ea/schema/20260305_v0_7_approvals_kernel.sql"
  "ea/schema/20260305_v0_8_channel_runtime_reliability.sql"
  "ea/schema/20260305_v0_9_tool_connector_kernel.sql"
  "ea/schema/20260305_v0_10_task_contracts_kernel.sql"
  "ea/schema/20260305_v0_11_memory_kernel.sql"
  "ea/schema/20260305_v0_12_entities_relationships_kernel.sql"
  "ea/schema/20260305_v0_13_commitments_kernel.sql"
  "ea/schema/20260305_v0_14_authority_bindings_kernel.sql"
  "ea/schema/20260305_v0_15_delivery_preferences_kernel.sql"
  "ea/schema/20260305_v0_16_follow_ups_kernel.sql"
  "ea/schema/20260305_v0_17_deadline_windows_kernel.sql"
  "ea/schema/20260305_v0_18_stakeholders_kernel.sql"
  "ea/schema/20260305_v0_19_decision_windows_kernel.sql"
  "ea/schema/20260305_v0_20_communication_policies_kernel.sql"
  "ea/schema/20260305_v0_21_follow_up_rules_kernel.sql"
  "ea/schema/20260305_v0_22_interruption_budgets_kernel.sql"
  "ea/schema/20260305_v0_23_execution_queue_kernel.sql"
  "ea/schema/20260305_v0_24_human_tasks_kernel.sql"
  "ea/schema/20260305_v0_25_human_task_resume_kernel.sql"
  "ea/schema/20260305_v0_26_human_task_assignment_state.sql"
  "ea/schema/20260305_v0_27_human_task_review_contract.sql"
  "ea/schema/20260305_v0_28_operator_profiles_kernel.sql"
  "ea/schema/20260305_v0_29_human_task_assignment_source.sql"
  "ea/schema/20260305_v0_30_human_task_assignment_provenance.sql"
  "ea/schema/20260305_v0_31_artifact_principal_scope.sql"
  "ea/schema/20260305_v0_32_provider_bindings_kernel.sql"
  "ea/schema/20260305_v0_33_task_contract_runtime_policy.sql"
  "ea/schema/20260305_v0_34_assistant_onboarding_canonical_schema.sql"
  "ea/schema/20260305_v0_35_execution_ledger_legacy_compat.sql"
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
