#!/usr/bin/env bash
set -euo pipefail

SCRIPTS=(
  scripts/deploy.sh
  scripts/db_bootstrap.sh
  scripts/db_status.sh
  scripts/db_size.sh
  scripts/db_retention.sh
  scripts/smoke_api.sh
  scripts/support_bundle.sh
  scripts/archive_tasks.sh
  scripts/verify_release_assets.sh
)

for s in "${SCRIPTS[@]}"; do
  echo "== help smoke: ${s} =="
  out="$(bash "${s}" --help)"
  if [[ "${out}" != *"Usage:"* ]]; then
    echo "missing Usage header in ${s} --help output" >&2
    exit 21
  fi
done

echo "help smoke complete"
