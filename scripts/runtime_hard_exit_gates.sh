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
  - smoke_api
  - verify_pocket_audio_archive

`smoke_api_tibor.sh` stays in the full hard-exit bundle because it mutates
deeper task-contract state and is not a live-deploy-safe probe.
EOF
  exit 0
fi

cd "${EA_ROOT}"
bash scripts/smoke_help.sh
env -u EA_API_TOKEN bash scripts/smoke_api.sh
"${PYTHON_BIN}" scripts/verify_pocket_audio_archive.py
