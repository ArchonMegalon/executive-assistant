#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${OPENVOICE_VENV_DIR:-$ROOT_DIR/.venv-openvoice}"
CHECKPOINT_ROOT="${OPENVOICE_CHECKPOINT_ROOT:-$ROOT_DIR/.models/openvoice}"
SOURCE_DIR="${OPENVOICE_SOURCE_DIR:-$ROOT_DIR/third_party/OpenVoice}"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "missing virtualenv: $VENV_DIR" >&2
  echo "run scripts/setup_openvoice.sh first" >&2
  exit 1
fi

export OPENVOICE_CHECKPOINT_ROOT="$CHECKPOINT_ROOT"
export OPENVOICE_SOURCE_DIR="$SOURCE_DIR"
export OPENVOICE_BASE_URL="${OPENVOICE_BASE_URL:-http://127.0.0.1:${OPENVOICE_PORT:-8093}}"
export EA_ROLE="${EA_ROLE:-openvoice}"

cd "$ROOT_DIR"
exec "$VENV_DIR/bin/python" -m app.runner
