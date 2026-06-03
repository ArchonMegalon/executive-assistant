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
  bash scripts/hard_exit_gates.sh

Runs the full flagship hard exit bundle:
  - full pytest suite
  - release preflight
  - LTD critical inventory/env verification
  - LTD flagship verified-subset verification
  - postgres contract tests
  - postgres smoke
  - postgres legacy smoke
  - Tibor smoke
  - pocket audio archive verification
EOF
  exit 0
fi

cd "${EA_ROOT}"
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q
make release-preflight
make verify-ltd-critical-entries
make verify-ltd-flagship-subset
make test-postgres-contracts
make smoke-postgres
make smoke-postgres-legacy
make smoke-api-tibor
make verify-pocket-audio-archive
