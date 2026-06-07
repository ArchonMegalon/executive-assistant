#!/usr/bin/env bash
set -euo pipefail

ROOT="/docker/EA"
TMPDIR="${TMPDIR:-/tmp}"
export TMPDIR

cd "$ROOT"
pytest -q \
  tests/test_memorial_archive_registry_public.py \
  tests/test_memorial_demo_rehearsal_contracts.py \
  tests/test_memorial_flagship_preflight.py \
  tests/test_memorial_security_contracts.py \
  tests/test_providers_api_contracts.py \
  tests/test_memorial_showtime_contracts.py \
  -k 'memorial'

"$ROOT/.venv/bin/pytest" -q \
  tests/e2e/test_memorial_browser.py \
  tests/e2e/test_memorial_flagship_exit_gates.py \
  tests/e2e/test_memorial_flagship_operator_tools.py \
  tests/e2e/test_memorial_showtime_cli.py

cd "$ROOT/ea"
preflight_args=("manfred")
if [[ -n "${MEMORIAL_FLAGSHIP_BASE_URL:-}" ]]; then
  preflight_args+=("--base-url" "$MEMORIAL_FLAGSHIP_BASE_URL")
fi
python3 scripts/memorial_flagship_preflight.py "${preflight_args[@]}"
