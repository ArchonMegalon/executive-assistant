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
  bash scripts/runtime_hard_exit_gates.sh

Runs the runtime-only hard exit bundle that a live deploy must pass:
  - smoke_help
  - smoke_api_runtime
  - spawned CodexEA worker-lane e2e smoke gate
  - verify_release_authority_runtime --require-authoritative
  - verify_memorial_runtime_overlay when MEMORIAL mode is enabled
  - verify_project_mode_runtime --mode memorial when MEMORIAL mode is enabled
  - verify_pocket_audio_archive

`smoke_api.sh` and `smoke_api_principal.sh` stay in the full hard-exit bundle
because they mutate deeper task-contract state and rely on caller principal
headers that production deploys intentionally do not trust.
EOF
  exit 0
fi

if [[ "$#" -gt 0 ]]; then
  echo "Unknown arguments: $*" >&2
  exit 2
fi

mode_enabled() {
  local needle="${1:-}"
  local raw="${EA_DEPLOY_ENABLED_MODES:-${EA_DEPLOY_PRIMARY_MODE:-}}"
  local item=""
  needle="$(printf '%s' "${needle}" | tr '[:lower:]-' '[:upper:]_')"
  [[ -n "${needle}" ]] || return 1
  raw="${raw//;/,}"
  for item in ${raw//,/ }; do
    item="$(printf '%s' "${item}" | tr '[:lower:]-' '[:upper:]_')"
    if [[ "${item}" == "${needle}" ]]; then
      return 0
    fi
  done
  return 1
}

cd "${EA_ROOT}"
bash scripts/smoke_help.sh
bash scripts/smoke_api_runtime.sh
bash scripts/verify_codexea_e2e_exit_gate.sh
if [[ -n "${EA_DEPLOYMENT_ID:-${DEPLOYMENT_ID:-${RENDER_GIT_COMMIT:-}}}" ]]; then
  make -s refresh-release-authority-status
fi
"${PYTHON_BIN}" scripts/verify_release_authority_runtime.py --pretty --require-authoritative
if mode_enabled "MEMORIAL"; then
  "${PYTHON_BIN}" scripts/verify_memorial_runtime_overlay.py --pretty
  PYTHONPATH=ea "${PYTHON_BIN}" scripts/verify_project_mode_runtime.py --mode memorial
fi
"${PYTHON_BIN}" scripts/verify_pocket_audio_archive.py
