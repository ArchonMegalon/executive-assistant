#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/repair_design_mirror_bundle.sh

Repairs the bounded EA design-mirror bundle audited for recurring drift by
copying only the approved local mirror files from their canonical sources.
EOF
  exit 0
fi

python3 scripts/verify_design_mirror_bundle.py --repair "$@"
