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
  "scripts/smoke_api.sh"
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

if grep -Fq "make release-smoke" "README.md"; then
  echo "ok: README release-smoke reference"
else
  echo "missing: README release-smoke reference" >&2
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

if grep -Fq 'Gate-bundle hardening flags are tracked in `MILESTONE.json` feature tags' "README.md"; then
  echo "ok: README milestone gate-tag pointer"
else
  echo "missing: README milestone gate-tag pointer" >&2
  missing=1
fi

if grep -Fq 'Release preflight checklist includes milestone gate-tag parity verification in `RELEASE_CHECKLIST.md`.' "README.md"; then
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

if grep -Fq "Operator Script Help Index" "RUNBOOK.md"; then
  echo "ok: RUNBOOK script help index"
else
  echo "missing: RUNBOOK script help index" >&2
  missing=1
fi

if grep -Fq "scripts/smoke_help.sh" "RUNBOOK.md"; then
  echo "ok: RUNBOOK smoke-help reference"
else
  echo "missing: RUNBOOK smoke-help reference" >&2
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

if grep -Fq "pre-smoke documentation/usage pass" "RUNBOOK.md"; then
  echo "ok: RUNBOOK release-docs sequencing note"
else
  echo "missing: RUNBOOK release-docs sequencing note" >&2
  missing=1
fi

if grep -Fq 'Milestone tracking linkage: `MILESTONE.json` feature tags include `ci_gate_bundle`' "RUNBOOK.md"; then
  echo "ok: RUNBOOK milestone gate-tag linkage note"
else
  echo "missing: RUNBOOK milestone gate-tag linkage note" >&2
  missing=1
fi

if grep -Fq 'RELEASE_CHECKLIST.md` now includes an explicit milestone gate-tag parity preflight line' "RUNBOOK.md"; then
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

if grep -Fq 'Docs parity confirms milestone gate tags in `MILESTONE.json`' "RELEASE_CHECKLIST.md"; then
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

if grep -Fq "Milestone metadata now includes CI/docs/release gate-bundle feature tags." "CHANGELOG.md"; then
  echo "ok: CHANGELOG milestone gate-tag note"
else
  echo "missing: CHANGELOG milestone gate-tag note" >&2
  missing=1
fi

if grep -Fq "Release checklist now includes explicit milestone gate-tag parity verification." "CHANGELOG.md"; then
  echo "ok: CHANGELOG checklist milestone-tag note"
else
  echo "missing: CHANGELOG checklist milestone-tag note" >&2
  missing=1
fi

if grep -Fq "make ci-gates" ".github/workflows/smoke-runtime.yml"; then
  echo "ok: smoke-runtime workflow uses ci-gates"
else
  echo "missing: smoke-runtime workflow ci-gates usage" >&2
  missing=1
fi

if grep -Fq '"ci_gate_bundle"' "MILESTONE.json" && \
   grep -Fq '"release_preflight_bundle"' "MILESTONE.json" && \
   grep -Fq '"docs_verify_alias"' "MILESTONE.json"; then
  echo "ok: MILESTONE gate-bundle feature tags"
else
  echo "missing: MILESTONE gate-bundle feature tags" >&2
  missing=1
fi

if [[ "${missing}" -ne 0 ]]; then
  echo "release asset verification failed" >&2
  exit 1
fi

echo "all required release assets present"
