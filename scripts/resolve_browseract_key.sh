#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${EA_ROOT}/.env"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/resolve_browseract_key.sh [--all]
  bash scripts/resolve_browseract_key.sh --next CURRENT_KEY

Resolution order:
  1. BROWSERACT_API_KEY
  2. BROWSERACT_API_KEY_FALLBACK_1
  3. BROWSERACT_API_KEY_FALLBACK_2
  4. BROWSERACT_API_KEY_FALLBACK_3

The script loads values from the current shell first and then from .env when present.
Default output is the first non-empty key.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

read_env_value() {
  local key="$1"
  if [[ -n "${!key:-}" ]]; then
    printf '%s\n' "${!key}"
    return 0
  fi
  if [[ -f "${ENV_FILE}" ]]; then
    local line
    line="$(grep -E "^${key}=" "${ENV_FILE}" | tail -n1 || true)"
    if [[ -n "${line}" ]]; then
      printf '%s\n' "${line#*=}"
      return 0
    fi
  fi
  printf '\n'
}

ordered_keys() {
  local key_names=(
    "BROWSERACT_API_KEY"
    "BROWSERACT_API_KEY_FALLBACK_1"
    "BROWSERACT_API_KEY_FALLBACK_2"
    "BROWSERACT_API_KEY_FALLBACK_3"
  )
  local value
  for key_name in "${key_names[@]}"; do
    value="$(read_env_value "${key_name}")"
    if [[ -n "${value}" ]]; then
      printf '%s\n' "${value}"
    fi
  done
}

if [[ "${1:-}" == "--all" ]]; then
  ordered_keys
  exit 0
fi

if [[ "${1:-}" == "--next" ]]; then
  if [[ -z "${2:-}" ]]; then
    echo "missing current key for --next" >&2
    exit 2
  fi
  current="${2}"
  found_current=0
  while IFS= read -r candidate; do
    if [[ "${found_current}" -eq 1 ]]; then
      printf '%s\n' "${candidate}"
      exit 0
    fi
    if [[ "${candidate}" == "${current}" ]]; then
      found_current=1
    fi
  done < <(ordered_keys)
  exit 1
fi

first_key="$(ordered_keys | head -n1 || true)"
if [[ -z "${first_key}" ]]; then
  echo "no browseract key configured" >&2
  exit 1
fi
printf '%s\n' "${first_key}"
