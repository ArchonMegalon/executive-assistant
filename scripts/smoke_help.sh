#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${EA_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${EA_ROOT}/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/smoke_help.sh

Run the script-help smoke contract by checking that key operator scripts return
a Usage header for their --help output.
EOF
  exit 0
fi

SCRIPTS=(
  scripts/deploy.sh
  scripts/db_bootstrap.sh
  scripts/db_status.sh
  scripts/db_size.sh
  scripts/db_retention.sh
  scripts/smoke_api.sh
  scripts/smoke_help.sh
  scripts/smoke_postgres.sh
  scripts/test_postgres_contracts.sh
  scripts/hard_exit_gates.sh
  scripts/runtime_hard_exit_gates.sh
  scripts/verify_ltd_critical_entries.py
  scripts/verify_ltd_flagship_subset.py
  scripts/list_endpoints.sh
  scripts/version_info.sh
  scripts/export_openapi.sh
  scripts/diff_openapi.sh
  scripts/prune_openapi.sh
  scripts/operator_summary.sh
  scripts/support_bundle.sh
  scripts/archive_tasks.sh
  scripts/bootstrap_payfunnels_propertyquarry.py
  scripts/bootstrap_emailit_propertyquarry.py
  scripts/verify_release_assets.sh
)

for s in "${SCRIPTS[@]}"; do
  echo "== help smoke: ${s} =="
  case "${s}" in
    *.py)
      out="$("${PYTHON_BIN}" "${EA_ROOT}/${s}" --help)"
      ;;
    *)
      out="$(bash "${EA_ROOT}/${s}" --help)"
      ;;
  esac
  if [[ "${out}" != *"Usage:"* ]]; then
    echo "missing Usage header in ${s} --help output" >&2
    exit 21
  fi
done

echo "help smoke complete"
