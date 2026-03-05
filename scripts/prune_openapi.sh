#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ART_DIR="${EA_ROOT}/artifacts"
KEEP="${1:-20}"

if [[ "${KEEP}" == "--help" || "${KEEP}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/prune_openapi.sh [keep_count]

Prune old artifacts/openapi_*.json snapshots, keeping the newest keep_count
files. Default keep_count is 20.
EOF
  exit 0
fi

if ! [[ "${KEEP}" =~ ^[0-9]+$ ]]; then
  echo "keep must be a non-negative integer" >&2
  exit 1
fi

if [[ ! -d "${ART_DIR}" ]]; then
  echo "no artifacts directory; nothing to prune"
  exit 0
fi

mapfile -t snapshots < <(ls -1 "${ART_DIR}"/openapi_*.json 2>/dev/null | sort)
total="${#snapshots[@]}"
if [[ "${total}" -le "${KEEP}" ]]; then
  echo "nothing to prune (total=${total}, keep=${KEEP})"
  exit 0
fi

to_remove=$((total - KEEP))
for ((i=0; i<to_remove; i++)); do
  rm -f "${snapshots[$i]}"
done

echo "pruned ${to_remove} snapshots; kept ${KEEP}"
