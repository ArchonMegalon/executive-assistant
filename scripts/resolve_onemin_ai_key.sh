#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${EA_ROOT}/.env"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/resolve_onemin_ai_key.sh [--all]
  bash scripts/resolve_onemin_ai_key.sh --next CURRENT_KEY

Resolution order:
  1. ONEMIN_AI_API_KEY
  2. ONEMIN_AI_API_KEY_FALLBACK_1
  3. ONEMIN_AI_API_KEY_FALLBACK_2
  4. ONEMIN_AI_API_KEY_FALLBACK_3
  5. ONEMIN_AI_API_KEY_FALLBACK_4
  6. ONEMIN_AI_API_KEY_FALLBACK_5
  7. ONEMIN_AI_API_KEY_FALLBACK_6
  8. ONEMIN_AI_API_KEY_FALLBACK_7
  9. ONEMIN_AI_API_KEY_FALLBACK_8
  10. ONEMIN_AI_API_KEY_FALLBACK_9

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
    "ONEMIN_AI_API_KEY"
    "ONEMIN_AI_API_KEY_FALLBACK_1"
    "ONEMIN_AI_API_KEY_FALLBACK_2"
    "ONEMIN_AI_API_KEY_FALLBACK_3"
    "ONEMIN_AI_API_KEY_FALLBACK_4"
    "ONEMIN_AI_API_KEY_FALLBACK_5"
    "ONEMIN_AI_API_KEY_FALLBACK_6"
    "ONEMIN_AI_API_KEY_FALLBACK_7"
    "ONEMIN_AI_API_KEY_FALLBACK_8"
    "ONEMIN_AI_API_KEY_FALLBACK_9"
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
  echo "no 1min.ai key configured" >&2
  exit 1
fi
printf '%s\n' "${first_key}"
