#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${EA_ROOT}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/verify_release_assets.sh

Validates presence of required runtime docs, scripts, and schema files.
Exits non-zero when any required asset is missing.
EOF
  exit 0
fi

missing=0

required_files=(
  "README.md"
  "RUNBOOK.md"
  "ARCHITECTURE_MAP.md"
  "HTTP_EXAMPLES.http"
  "CHANGELOG.md"
  "ENVIRONMENT_MATRIX.md"
  "MILESTONE.json"
  "RELEASE_CHECKLIST.md"
  "TASKS_WORK_LOG.md"
  "scripts/deploy.sh"
  "scripts/db_bootstrap.sh"
  "scripts/db_status.sh"
  "scripts/db_size.sh"
  "scripts/db_retention.sh"
  "scripts/smoke_api.sh"
  "scripts/smoke_postgres.sh"
  "scripts/test_postgres_contracts.sh"
  "scripts/smoke_help.sh"
  "scripts/export_openapi.sh"
  "scripts/diff_openapi.sh"
  "scripts/prune_openapi.sh"
  "scripts/list_endpoints.sh"
  "scripts/version_info.sh"
  "scripts/operator_summary.sh"
  "scripts/support_bundle.sh"
  "scripts/archive_tasks.sh"
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
)

echo "== verify release assets =="
for f in "${required_files[@]}"; do
  if [[ -f "${f}" ]]; then
    echo "ok: ${f}"
  else
    echo "missing: ${f}" >&2
    missing=1
  fi
done

echo "== verify release docs linkage =="
if grep -Fq "make operator-help" "README.md"; then
  echo "ok: README operator-help reference"
else
  echo "missing: README operator-help reference" >&2
  missing=1
fi

if grep -Fq "scripts/smoke_help.sh --help" "README.md"; then
  echo "ok: README smoke-help help note"
else
  echo "missing: README smoke-help help note" >&2
  missing=1
fi

if grep -Fq "make release-smoke" "README.md"; then
  echo "ok: README release-smoke reference"
else
  echo "missing: README release-smoke reference" >&2
  missing=1
fi

if grep -Fq "make smoke-postgres-legacy" "README.md"; then
  echo "ok: README legacy postgres smoke reference"
else
  echo "missing: README legacy postgres smoke reference" >&2
  missing=1
fi

if grep -Fq "make test-postgres-contracts" "README.md"; then
  echo "ok: README postgres contract test reference"
else
  echo "missing: README postgres contract test reference" >&2
  missing=1
fi

if grep -Fq "make ci-gates-postgres-legacy" "README.md"; then
  echo "ok: README legacy postgres parity reference"
else
  echo "missing: README legacy postgres parity reference" >&2
  missing=1
fi

if grep -Fq "make release-preflight" "README.md"; then
  echo "ok: README release-preflight reference"
else
  echo "missing: README release-preflight reference" >&2
  missing=1
fi

if grep -Fq "lighter local readiness pass" "README.md"; then
  echo "ok: README all-local vs release-preflight note"
else
  echo "missing: README all-local vs release-preflight note" >&2
  missing=1
fi

if grep -Fq "make docs-verify" "README.md"; then
  echo "ok: README docs-verify alias reference"
else
  echo "missing: README docs-verify alias reference" >&2
  missing=1
fi

if grep -Fq "make release-docs" "README.md"; then
  echo "ok: README release-docs reference"
else
  echo "missing: README release-docs reference" >&2
  missing=1
fi

if grep -Fq "temporary backward-compatible alias" "README.md"; then
  echo "ok: README backend alias deprecation note"
else
  echo "missing: README backend alias deprecation note" >&2
  missing=1
fi

if grep -Fq "ea_pgdata" "README.md" && \
   grep -Fq "/var/lib/postgresql/data" "README.md" && \
   grep -Fq "not RAM" "README.md"; then
  echo "ok: README pgdata note"
else
  echo "missing: README pgdata note" >&2
  missing=1
fi

if grep -Fq "policy_denied:tool_not_allowed" "README.md"; then
  echo "ok: README policy tool contract note"
else
  echo "missing: README policy tool contract note" >&2
  missing=1
fi

if grep -Fq "/v1/policy/evaluate" "README.md" && \
   grep -Fq "/v1/policy/evaluate" "RUNBOOK.md" && \
   grep -Fq "/v1/policy/evaluate" "HTTP_EXAMPLES.http" && \
   grep -Fq "/v1/policy/evaluate" "scripts/smoke_api.sh"; then
  echo "ok: external-action policy evaluation route docs"
else
  echo "missing: external-action policy evaluation route docs" >&2
  missing=1
fi

if python3 - <<'PY'
import json
from pathlib import Path

milestone = json.loads(Path("MILESTONE.json").read_text(encoding="utf-8"))
capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "artifact_lookup_api_exposure")
assert capability["status"] == "tested"
PY
then
  if grep -Fq "/v1/rewrite/artifacts/{artifact_id}" "README.md" && \
     grep -Fq "/v1/rewrite/artifacts/{artifact_id}" "RUNBOOK.md" && \
     grep -Fq "/v1/rewrite/artifacts/{{artifact_id}}" "HTTP_EXAMPLES.http" && \
     grep -Fq '/v1/rewrite/artifacts/${ARTIFACT_ID}' "scripts/smoke_api.sh"; then
    echo "ok: artifact lookup route docs"
  else
    echo "missing: artifact lookup route docs" >&2
    missing=1
  fi
else
  echo "missing: artifact lookup milestone status" >&2
  missing=1
fi

if python3 - <<'PY'
import json
from pathlib import Path

milestone = json.loads(Path("MILESTONE.json").read_text(encoding="utf-8"))
capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "receipt_and_run_cost_lookup_api_exposure")
assert capability["status"] == "tested"
PY
then
  if grep -Fq "/v1/rewrite/receipts/{receipt_id}" "README.md" && \
     grep -Fq "/v1/rewrite/run-costs/{cost_id}" "README.md" && \
     grep -Fq "/v1/rewrite/receipts/{receipt_id}" "RUNBOOK.md" && \
     grep -Fq "/v1/rewrite/run-costs/{cost_id}" "RUNBOOK.md" && \
     grep -Fq "/v1/rewrite/receipts/{{receipt_id}}" "HTTP_EXAMPLES.http" && \
     grep -Fq "/v1/rewrite/run-costs/{{cost_id}}" "HTTP_EXAMPLES.http" && \
     grep -Fq '/v1/rewrite/receipts/${RECEIPT_ID}' "scripts/smoke_api.sh" && \
     grep -Fq '/v1/rewrite/run-costs/${COST_ID}' "scripts/smoke_api.sh"; then
    echo "ok: receipt and run-cost lookup route docs"
  else
    echo "missing: receipt and run-cost lookup route docs" >&2
    missing=1
  fi
else
  echo "missing: receipt and run-cost lookup milestone status" >&2
  missing=1
fi

if python3 - <<'PY'
import json
from pathlib import Path

milestone = json.loads(Path("MILESTONE.json").read_text(encoding="utf-8"))
capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "approval_resume_execution")
assert capability["status"] == "tested"
PY
then
  if grep -Fq "resumes execution inline" "README.md" && \
     grep -Fq "resumes execution immediately" "RUNBOOK.md" && \
     grep -Fq "approve and resume execution" "HTTP_EXAMPLES.http" && \
     grep -Fq "approval resume path ok" "scripts/smoke_api.sh"; then
    echo "ok: approval resume execution docs"
  else
    echo "missing: approval resume execution docs" >&2
    missing=1
  fi
else
  echo "missing: approval resume execution milestone status" >&2
  missing=1
fi

if python3 - <<'PY'
import json
from pathlib import Path

milestone = json.loads(Path("MILESTONE.json").read_text(encoding="utf-8"))
capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "execution_queue_inline_worker")
assert capability["status"] == "tested"
assert "ea/schema/20260305_v0_23_execution_queue_kernel.sql" in milestone["migrations"]
PY
then
  if grep -Fq "execution_queue" "README.md" && \
     grep -Fq "execution_queue" "RUNBOOK.md" && \
     grep -Fq "v0_23 execution queue kernel" "scripts/db_bootstrap.sh" && \
     grep -Fq "execution_queue" "scripts/db_status.sh" && \
     grep -Fq "queue_items" "scripts/smoke_api.sh" && \
     grep -Fq "execution_queue" "scripts/smoke_postgres.sh"; then
    echo "ok: execution queue runtime docs"
  else
    echo "missing: execution queue runtime docs" >&2
    missing=1
  fi
else
  echo "missing: execution queue milestone status" >&2
  missing=1
fi

if grep -Fq 'Gate-bundle hardening flags are tracked in `MILESTONE.json` release tags' "README.md"; then
  echo "ok: README milestone gate-tag pointer"
else
  echo "missing: README milestone gate-tag pointer" >&2
  missing=1
fi

if grep -Fq 'Release preflight checklist includes milestone release-tag parity verification in `RELEASE_CHECKLIST.md`.' "README.md"; then
  echo "ok: README checklist milestone parity note"
else
  echo "missing: README checklist milestone parity note" >&2
  missing=1
fi

if grep -Fq 'Recommended sequencing: run `make release-docs` before `make release-preflight`.' "README.md"; then
  echo "ok: README release-docs sequencing note"
else
  echo "missing: README release-docs sequencing note" >&2
  missing=1
fi

if grep -Fq "smoke, readiness, CI parity, release/support, and task-archive shortcuts" "README.md"; then
  echo "ok: README operator summary shortcut note"
else
  echo "missing: README operator summary shortcut note" >&2
  missing=1
fi

if grep -Fq "operator_summary.sh --help" "README.md"; then
  echo "ok: README operator-summary help note"
else
  echo "missing: README operator-summary help note" >&2
  missing=1
fi

if grep -Fq 'Endpoint/version/OpenAPI helper scripts also expose `--help`' "README.md"; then
  echo "ok: README endpoint/version/openapi help note"
else
  echo "missing: README endpoint/version/openapi help note" >&2
  missing=1
fi

if grep -Fq '`scripts/version_info.sh` now also prints milestone capability-status counts and release tags' "README.md"; then
  echo "ok: README version-info milestone summary note"
else
  echo "missing: README version-info milestone summary note" >&2
  missing=1
fi

if grep -Fq "SUPPORT_INCLUDE_DB_VOLUME=0" "README.md" && \
   grep -Fq "live \`ea-db\` mount inspection output" "README.md"; then
  echo "ok: README support bundle volume note"
else
  echo "missing: README support bundle volume note" >&2
  missing=1
fi

if grep -Fq "Operator Script Help Index" "RUNBOOK.md"; then
  echo "ok: RUNBOOK script help index"
else
  echo "missing: RUNBOOK script help index" >&2
  missing=1
fi

if grep -Fq "EA_STORAGE_BACKEND" "ENVIRONMENT_MATRIX.md" && \
   grep -Fq "deprecated compatibility alias" "ENVIRONMENT_MATRIX.md"; then
  echo "ok: ENVIRONMENT_MATRIX canonical backend env note"
else
  echo "missing: ENVIRONMENT_MATRIX canonical backend env note" >&2
  missing=1
fi

if grep -Fq "scripts/operator_summary.sh" "RUNBOOK.md"; then
  echo "ok: RUNBOOK operator-summary help reference"
else
  echo "missing: RUNBOOK operator-summary help reference" >&2
  missing=1
fi

if grep -Fq "ea_pgdata" "RUNBOOK.md" && \
   grep -Fq "/var/lib/postgresql/data" "RUNBOOK.md" && \
   grep -Fq "not RAM" "RUNBOOK.md"; then
  echo "ok: RUNBOOK pgdata note"
else
  echo "missing: RUNBOOK pgdata note" >&2
  missing=1
fi

if grep -Fq "tool_not_allowed" "RUNBOOK.md" && \
   grep -Fq "high-risk/high-budget or external-send actions" "RUNBOOK.md"; then
  echo "ok: RUNBOOK policy metadata note"
else
  echo "missing: RUNBOOK policy metadata note" >&2
  missing=1
fi

if grep -Fq '"artifact_repository"' "HTTP_EXAMPLES.http" && \
   grep -Fq '"allowed_tools":["artifact_repository"]' "scripts/smoke_api.sh"; then
  echo "ok: task-contract examples align on artifact_repository"
else
  echo "missing: task-contract examples align on artifact_repository" >&2
  missing=1
fi

if grep -Fq "scripts/list_endpoints.sh" "RUNBOOK.md" && \
   grep -Fq "scripts/version_info.sh" "RUNBOOK.md" && \
   grep -Fq "scripts/export_openapi.sh" "RUNBOOK.md" && \
   grep -Fq "scripts/diff_openapi.sh" "RUNBOOK.md" && \
   grep -Fq "scripts/prune_openapi.sh" "RUNBOOK.md"; then
  echo "ok: RUNBOOK endpoint/version/openapi help references"
else
  echo "missing: RUNBOOK endpoint/version/openapi help references" >&2
  missing=1
fi

if grep -Fq "scripts/test_postgres_contracts.sh" "RUNBOOK.md" && \
   grep -Fq "make test-postgres-contracts" "RUNBOOK.md"; then
  echo "ok: RUNBOOK postgres contract test reference"
else
  echo "missing: RUNBOOK postgres contract test reference" >&2
  missing=1
fi

if grep -Fq '`bash scripts/version_info.sh` now prints milestone capability-status counts and release tags' "RUNBOOK.md"; then
  echo "ok: RUNBOOK version-info milestone summary note"
else
  echo "missing: RUNBOOK version-info milestone summary note" >&2
  missing=1
fi

if grep -Fq "scripts/smoke_help.sh" "RUNBOOK.md"; then
  echo "ok: RUNBOOK smoke-help reference"
else
  echo "missing: RUNBOOK smoke-help reference" >&2
  missing=1
fi

if grep -Fq "SUPPORT_INCLUDE_DB_VOLUME=0 bash scripts/support_bundle.sh" "RUNBOOK.md" && \
   grep -Fq "live \`ea-db\` mount inspection" "RUNBOOK.md"; then
  echo "ok: RUNBOOK support bundle volume note"
else
  echo "missing: RUNBOOK support bundle volume note" >&2
  missing=1
fi

if grep -Fq "Release ops linkage" "RUNBOOK.md"; then
  echo "ok: RUNBOOK release ops linkage note"
else
  echo "missing: RUNBOOK release ops linkage note" >&2
  missing=1
fi

if grep -Fq "make release-preflight" "RUNBOOK.md"; then
  echo "ok: RUNBOOK release-preflight reference"
else
  echo "missing: RUNBOOK release-preflight reference" >&2
  missing=1
fi

if grep -Fq "lightweight readiness pass" "RUNBOOK.md"; then
  echo "ok: RUNBOOK all-local vs release-preflight note"
else
  echo "missing: RUNBOOK all-local vs release-preflight note" >&2
  missing=1
fi

if grep -Fq "make docs-verify" "RUNBOOK.md"; then
  echo "ok: RUNBOOK docs-verify alias reference"
else
  echo "missing: RUNBOOK docs-verify alias reference" >&2
  missing=1
fi

if grep -Fq "make release-docs" "RUNBOOK.md"; then
  echo "ok: RUNBOOK release-docs reference"
else
  echo "missing: RUNBOOK release-docs reference" >&2
  missing=1
fi

if grep -Fq "make smoke-postgres-legacy" "RUNBOOK.md"; then
  echo "ok: RUNBOOK legacy postgres smoke reference"
else
  echo "missing: RUNBOOK legacy postgres smoke reference" >&2
  missing=1
fi

if grep -Fq "make ci-gates-postgres-legacy" "RUNBOOK.md"; then
  echo "ok: RUNBOOK legacy postgres parity reference"
else
  echo "missing: RUNBOOK legacy postgres parity reference" >&2
  missing=1
fi

if grep -Fq 'operator summary includes release smoke/readiness commands plus legacy smoke/parity shortcuts, release/support commands' "RUNBOOK.md"; then
  echo "ok: RUNBOOK operator summary shortcut note"
else
  echo "missing: RUNBOOK operator summary shortcut note" >&2
  missing=1
fi

if grep -Fq "pre-smoke documentation/usage pass" "RUNBOOK.md"; then
  echo "ok: RUNBOOK release-docs sequencing note"
else
  echo "missing: RUNBOOK release-docs sequencing note" >&2
  missing=1
fi

if grep -Fq 'Milestone tracking linkage: `MILESTONE.json` maps capabilities to `planned|coded|wired|tested|released`' "RUNBOOK.md"; then
  echo "ok: RUNBOOK milestone gate-tag linkage note"
else
  echo "missing: RUNBOOK milestone gate-tag linkage note" >&2
  missing=1
fi

if grep -Fq 'RELEASE_CHECKLIST.md` now includes an explicit milestone release-tag parity preflight line' "RUNBOOK.md"; then
  echo "ok: RUNBOOK checklist milestone parity linkage note"
else
  echo "missing: RUNBOOK checklist milestone parity linkage note" >&2
  missing=1
fi

if grep -Fq "CI gate bundle" "RELEASE_CHECKLIST.md"; then
  echo "ok: RELEASE_CHECKLIST CI gate bundle line"
else
  echo "missing: RELEASE_CHECKLIST CI gate bundle line" >&2
  missing=1
fi

if grep -Fq "make release-preflight" "RELEASE_CHECKLIST.md"; then
  echo "ok: RELEASE_CHECKLIST release-preflight line"
else
  echo "missing: RELEASE_CHECKLIST release-preflight line" >&2
  missing=1
fi

if grep -Fq "make ci-gates" "RELEASE_CHECKLIST.md"; then
  echo "ok: RELEASE_CHECKLIST ci-gates line"
else
  echo "missing: RELEASE_CHECKLIST ci-gates line" >&2
  missing=1
fi

if grep -Fq "make ci-gates-postgres" "RELEASE_CHECKLIST.md"; then
  echo "ok: RELEASE_CHECKLIST ci-gates-postgres line"
else
  echo "missing: RELEASE_CHECKLIST ci-gates-postgres line" >&2
  missing=1
fi

if grep -Fq "make ci-gates-postgres-legacy" "RELEASE_CHECKLIST.md"; then
  echo "ok: RELEASE_CHECKLIST ci-gates-postgres-legacy line"
else
  echo "missing: RELEASE_CHECKLIST ci-gates-postgres-legacy line" >&2
  missing=1
fi

if grep -Fq "make docs-verify" "RELEASE_CHECKLIST.md"; then
  echo "ok: RELEASE_CHECKLIST docs-verify line"
else
  echo "missing: RELEASE_CHECKLIST docs-verify line" >&2
  missing=1
fi

if grep -Fq "make release-docs" "RELEASE_CHECKLIST.md"; then
  echo "ok: RELEASE_CHECKLIST release-docs line"
else
  echo "missing: RELEASE_CHECKLIST release-docs line" >&2
  missing=1
fi

if grep -Fq 'Docs parity confirms milestone release tags in `MILESTONE.json`' "RELEASE_CHECKLIST.md"; then
  echo "ok: RELEASE_CHECKLIST milestone gate-tag line"
else
  echo "missing: RELEASE_CHECKLIST milestone gate-tag line" >&2
  missing=1
fi

if grep -Fq "make ci-gates" "CHANGELOG.md"; then
  echo "ok: CHANGELOG ci-gates note"
else
  echo "missing: CHANGELOG ci-gates note" >&2
  missing=1
fi

if grep -Fq "make release-preflight" "CHANGELOG.md"; then
  echo "ok: CHANGELOG release-preflight note"
else
  echo "missing: CHANGELOG release-preflight note" >&2
  missing=1
fi

if grep -Fq "make docs-verify" "CHANGELOG.md"; then
  echo "ok: CHANGELOG docs-verify note"
else
  echo "missing: CHANGELOG docs-verify note" >&2
  missing=1
fi

if grep -Fq "make release-docs" "CHANGELOG.md"; then
  echo "ok: CHANGELOG release-docs note"
else
  echo "missing: CHANGELOG release-docs note" >&2
  missing=1
fi

if grep -Fq "make ci-gates-postgres-legacy" "CHANGELOG.md"; then
  echo "ok: CHANGELOG legacy postgres parity note"
else
  echo "missing: CHANGELOG legacy postgres parity note" >&2
  missing=1
fi

if grep -Fq "Operator summary output now includes legacy Postgres smoke and CI parity shortcuts." "CHANGELOG.md"; then
  echo "ok: CHANGELOG operator summary parity note"
else
  echo "missing: CHANGELOG operator summary parity note" >&2
  missing=1
fi

if grep -Fq "Operator summary output now also surfaces release/support commands" "CHANGELOG.md"; then
  echo "ok: CHANGELOG operator summary release/support note"
else
  echo "missing: CHANGELOG operator summary release/support note" >&2
  missing=1
fi

if grep -Fq "Operator summary output now also includes task-archive shortcuts" "CHANGELOG.md"; then
  echo "ok: CHANGELOG operator summary task-archive note"
else
  echo "missing: CHANGELOG operator summary task-archive note" >&2
  missing=1
fi

if grep -Fq "EA_STORAGE_BACKEND" "CHANGELOG.md" && \
   grep -Fq "deprecated compatibility alias" "CHANGELOG.md"; then
  echo "ok: CHANGELOG backend env deprecation note"
else
  echo "missing: CHANGELOG backend env deprecation note" >&2
  missing=1
fi

if grep -Fq 'Operator summary output now also includes `make release-smoke` and `make all-local`' "CHANGELOG.md"; then
  echo "ok: CHANGELOG operator summary readiness note"
else
  echo "missing: CHANGELOG operator summary readiness note" >&2
  missing=1
fi

if grep -Fq 'Operator summary now exposes a `--help` contract' "CHANGELOG.md"; then
  echo "ok: CHANGELOG operator-summary help-contract note"
else
  echo "missing: CHANGELOG operator-summary help-contract note" >&2
  missing=1
fi

if grep -Fq 'Endpoint, version, and OpenAPI helper scripts now expose `--help` contracts' "CHANGELOG.md"; then
  echo "ok: CHANGELOG endpoint/version/openapi help-contract note"
else
  echo "missing: CHANGELOG endpoint/version/openapi help-contract note" >&2
  missing=1
fi

if grep -Fq '`version_info.sh` now prints milestone capability-status counts and release tags' "CHANGELOG.md"; then
  echo "ok: CHANGELOG version-info milestone summary note"
else
  echo "missing: CHANGELOG version-info milestone summary note" >&2
  missing=1
fi

if grep -Fq 'scripts/smoke_help.sh` now exposes its own `--help` contract' "CHANGELOG.md"; then
  echo "ok: CHANGELOG smoke-help help-contract note"
else
  echo "missing: CHANGELOG smoke-help help-contract note" >&2
  missing=1
fi

if grep -Fq "Milestone metadata now uses \`planned|coded|wired|tested|released\` capability statuses plus CI/docs/release gate tags." "CHANGELOG.md"; then
  echo "ok: CHANGELOG milestone gate-tag note"
else
  echo "missing: CHANGELOG milestone gate-tag note" >&2
  missing=1
fi

if grep -Fq "Release checklist now includes explicit milestone release-tag parity verification." "CHANGELOG.md"; then
  echo "ok: CHANGELOG checklist milestone-tag note"
else
  echo "missing: CHANGELOG checklist milestone-tag note" >&2
  missing=1
fi

if grep -Fq "SUPPORT_INCLUDE_DB_VOLUME" "CHANGELOG.md"; then
  echo "ok: CHANGELOG support bundle volume note"
else
  echo "missing: CHANGELOG support bundle volume note" >&2
  missing=1
fi

if grep -Fq "make ci-gates" ".github/workflows/smoke-runtime.yml"; then
  echo "ok: smoke-runtime workflow uses ci-gates"
else
  echo "missing: smoke-runtime workflow ci-gates usage" >&2
  missing=1
fi

if grep -Fq "scripts/smoke_postgres.sh" ".github/workflows/smoke-runtime.yml"; then
  echo "ok: smoke-runtime workflow includes postgres smoke job"
else
  echo "missing: smoke-runtime workflow postgres smoke job" >&2
  missing=1
fi

if grep -Fq "scripts/test_postgres_contracts.sh" ".github/workflows/smoke-runtime.yml"; then
  echo "ok: smoke-runtime workflow includes postgres contract job"
else
  echo "missing: smoke-runtime workflow postgres contract job" >&2
  missing=1
fi

if grep -Fq -- "--legacy-fixture" ".github/workflows/smoke-runtime.yml"; then
  echo "ok: smoke-runtime workflow includes legacy migration smoke job"
else
  echo "missing: smoke-runtime workflow legacy migration smoke job" >&2
  missing=1
fi

if grep -Fq "make smoke-postgres-legacy" "scripts/operator_summary.sh" && \
   grep -Fq "Usage:" "scripts/operator_summary.sh" && \
   grep -Fq "make release-smoke" "scripts/operator_summary.sh" && \
   grep -Fq "make test-postgres-contracts" "scripts/operator_summary.sh" && \
   grep -Fq "make all-local" "scripts/operator_summary.sh" && \
   grep -Fq "make ci-gates-postgres-legacy" "scripts/operator_summary.sh" && \
   grep -Fq "make release-preflight" "scripts/operator_summary.sh" && \
   grep -Fq "make support-bundle" "scripts/operator_summary.sh" && \
   grep -Fq "make tasks-archive" "scripts/operator_summary.sh" && \
   grep -Fq "make tasks-archive-dry-run" "scripts/operator_summary.sh" && \
   grep -Fq "make tasks-archive-prune" "scripts/operator_summary.sh"; then
  echo "ok: operator-summary includes help, readiness, legacy postgres, release/support, and task-archive shortcuts"
else
  echo "missing: operator-summary help, readiness, legacy postgres, release/support, and task-archive shortcuts" >&2
  missing=1
fi

if grep -Fq "scripts/operator_summary.sh" "scripts/smoke_help.sh" && \
   grep -Fq "scripts/operator_summary.sh" "Makefile"; then
  echo "ok: operator-summary included in help-smoke and operator-help surfaces"
else
  echo "missing: operator-summary help-smoke/operator-help wiring" >&2
  missing=1
fi

if grep -Fq "Usage:" "scripts/smoke_help.sh" && \
   grep -Fq "scripts/smoke_help.sh" "Makefile"; then
  echo "ok: smoke-help includes help contract and operator-help wiring"
else
  echo "missing: smoke-help help contract/operator-help wiring" >&2
  missing=1
fi

if grep -Fq "scripts/list_endpoints.sh" "scripts/smoke_help.sh" && \
   grep -Fq "scripts/version_info.sh" "scripts/smoke_help.sh" && \
   grep -Fq "scripts/test_postgres_contracts.sh" "scripts/smoke_help.sh" && \
   grep -Fq "scripts/export_openapi.sh" "scripts/smoke_help.sh" && \
   grep -Fq "scripts/diff_openapi.sh" "scripts/smoke_help.sh" && \
   grep -Fq "scripts/prune_openapi.sh" "scripts/smoke_help.sh" && \
   grep -Fq "scripts/list_endpoints.sh" "Makefile" && \
   grep -Fq "scripts/version_info.sh" "Makefile" && \
   grep -Fq "scripts/test_postgres_contracts.sh" "Makefile" && \
   grep -Fq "scripts/export_openapi.sh" "Makefile" && \
   grep -Fq "scripts/diff_openapi.sh" "Makefile" && \
   grep -Fq "scripts/prune_openapi.sh" "Makefile"; then
  echo "ok: endpoint/version/openapi scripts included in help-smoke and operator-help surfaces"
else
  echo "missing: endpoint/version/openapi help-smoke/operator-help wiring" >&2
  missing=1
fi

if grep -Fq '"status_model"' "MILESTONE.json" && \
   grep -Fq '"release_tags"' "MILESTONE.json" && \
   grep -Fq '"planned"' "MILESTONE.json" && \
   grep -Fq '"coded"' "MILESTONE.json" && \
   grep -Fq '"wired"' "MILESTONE.json" && \
   grep -Fq '"tested"' "MILESTONE.json" && \
   grep -Fq '"released"' "MILESTONE.json" && \
   grep -Fq '"ci_gate_bundle"' "MILESTONE.json" && \
   grep -Fq '"release_preflight_bundle"' "MILESTONE.json" && \
   grep -Fq '"docs_verify_alias"' "MILESTONE.json" && \
   grep -Fq '"postgres_legacy_fixture_smoke"' "MILESTONE.json" && \
   grep -Fq '"ci_postgres_legacy_smoke_job"' "MILESTONE.json" && \
   grep -Fq '"ci_gates_postgres_legacy_local_target"' "MILESTONE.json"; then
  echo "ok: MILESTONE status model and release tags"
else
  echo "missing: MILESTONE status model and release tags" >&2
  missing=1
fi

if python3 - <<'PY'
import json
from pathlib import Path

milestone = json.loads(Path("MILESTONE.json").read_text(encoding="utf-8"))
capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "principal_scoped_memory_seed_apis")
assert capability["status"] == "tested"
PY
then
  if grep -Fq "/v1/memory/candidates" "README.md" && \
     grep -Fq "/v1/memory/stakeholders" "README.md" && \
     grep -Fq "/v1/memory/interruption-budgets" "README.md" && \
     grep -Fq "/v1/memory/candidates" "RUNBOOK.md" && \
     grep -Fq "/v1/memory/stakeholders" "RUNBOOK.md" && \
     grep -Fq "/v1/memory/interruption-budgets" "RUNBOOK.md" && \
     grep -Fq "/v1/memory/candidates" "scripts/smoke_api.sh" && \
     grep -Fq "/v1/memory/stakeholders" "scripts/smoke_api.sh" && \
     grep -Fq "/v1/memory/interruption-budgets" "scripts/smoke_api.sh"; then
    echo "ok: principal-scoped memory seed API coverage"
  else
    echo "missing: principal-scoped memory seed API coverage" >&2
    missing=1
  fi
else
  echo "missing: principal-scoped memory seed API milestone status" >&2
  missing=1
fi

if [[ "${missing}" -ne 0 ]]; then
  echo "release asset verification failed" >&2
  exit 1
fi

echo "all required release assets present"
