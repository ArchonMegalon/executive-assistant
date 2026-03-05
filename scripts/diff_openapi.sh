#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ART_DIR="${EA_ROOT}/artifacts"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/diff_openapi.sh [left_snapshot right_snapshot]

Pretty-print and diff two OpenAPI snapshots. If paths are omitted, the script
diffs the two most recent artifacts/openapi_*.json snapshots.
EOF
  exit 0
fi

LEFT="${1:-}"
RIGHT="${2:-}"

if [[ -z "${LEFT}" || -z "${RIGHT}" ]]; then
  if [[ ! -d "${ART_DIR}" ]]; then
    echo "missing artifacts directory: ${ART_DIR}" >&2
    exit 1
  fi
  mapfile -t snapshots < <(ls -1 "${ART_DIR}"/openapi_*.json 2>/dev/null | sort)
  if [[ "${#snapshots[@]}" -lt 2 ]]; then
    echo "need at least two snapshots in ${ART_DIR} (openapi_*.json)" >&2
    exit 1
  fi
  LEFT="${snapshots[-2]}"
  RIGHT="${snapshots[-1]}"
fi

if [[ ! -f "${LEFT}" ]]; then
  echo "missing left snapshot: ${LEFT}" >&2
  exit 1
fi
if [[ ! -f "${RIGHT}" ]]; then
  echo "missing right snapshot: ${RIGHT}" >&2
  exit 1
fi

tmp_left="$(mktemp)"
tmp_right="$(mktemp)"
trap 'rm -f "${tmp_left}" "${tmp_right}"' EXIT

python3 -m json.tool "${LEFT}" > "${tmp_left}"
python3 -m json.tool "${RIGHT}" > "${tmp_right}"

echo "diffing:"
echo "  left:  ${LEFT}"
echo "  right: ${RIGHT}"
diff -u "${tmp_left}" "${tmp_right}" || true
