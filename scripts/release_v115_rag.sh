#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  scripts/release_v115_rag.sh prune_meta
  scripts/release_v115_rag.sh prune_pycache
  scripts/release_v115_rag.sh clean_rewrite_baseline
  PROPERTYQUARRY_ROOT=/path/to/property scripts/release_v115_rag.sh prune_meta

This is a controlled maintenance wrapper used for rewrite-baseline cleanup.
EOF
}

prune_meta() {
  cd "${EA_ROOT}"
  rm -rf .github
}

prune_pycache() {
  cd "${EA_ROOT}"
  find . -type d -name "__pycache__" -prune -exec rm -rf {} +
  find . -type f -name "*.pyc" -delete
}

clean_rewrite_baseline() {
  cd "${EA_ROOT}"
  rm -rf attachments logs daemon-gogcli-config data-private bin ea/config
  rm -f .env scripts/apply_patch.sh
  prune_pycache
}

main() {
  local cmd="${1:-}"
  case "${cmd}" in
    prune_meta)
      prune_meta
      ;;
    prune_pycache)
      prune_pycache
      ;;
    clean_rewrite_baseline)
      clean_rewrite_baseline
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
