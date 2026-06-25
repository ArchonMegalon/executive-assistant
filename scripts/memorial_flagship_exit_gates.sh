#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPDIR="${TMPDIR:-/tmp}"
PYTHON_BIN="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi
export TMPDIR

cd "$ROOT"
export MEMORIAL_FLAGSHIP_EXIT_GATES_RUNNING=1
pytest -q \
  tests/test_memorial_archive_registry_public.py \
  tests/test_memorial_audio_probe_contracts.py \
  tests/test_memorial_demo_rehearsal_contracts.py \
  tests/test_memorial_flagship_preflight.py \
  tests/test_memorial_room_ready_contracts.py \
  tests/test_memorial_security_contracts.py \
  tests/test_validate_memorial_voice_loop.py \
  tests/test_providers_api_contracts.py \
  tests/test_memorial_showtime_contracts.py \
  -k 'memorial'

if [[ -n "${PYTEST_CURRENT_TEST:-}" ]]; then
  "$PYTHON_BIN" -m pytest -q \
    tests/e2e/test_memorial_showtime_cli.py
else
  "$PYTHON_BIN" -m pytest -q \
    tests/e2e/test_memorial_browser.py \
    tests/e2e/test_memorial_flagship_exit_gates.py \
    tests/e2e/test_memorial_flagship_operator_tools.py \
    tests/e2e/test_memorial_showtime_cli.py
fi

cd "$ROOT/ea"
preflight_args=("manfred")
if [[ -n "${MEMORIAL_FLAGSHIP_BASE_URL:-}" ]]; then
  preflight_args+=("--base-url" "$MEMORIAL_FLAGSHIP_BASE_URL")
fi
python3 scripts/memorial_flagship_preflight.py "${preflight_args[@]}"

if [[ -n "${MEMORIAL_FLAGSHIP_BASE_URL:-}" ]]; then
  avatar_mode="--avatar-optional"
  if [[ "${MEMORIAL_FLAGSHIP_AVATAR_REQUIRED:-0}" == "1" ]]; then
    avatar_mode="--avatar-required"
  fi
  python3 scripts/memorial_room_ready.py \
    --slug manfred \
    --base-url "$MEMORIAL_FLAGSHIP_BASE_URL" \
    --questions ../examples/demo_questions.manfred.json \
    --output-dir "$TMPDIR/manfred_room_ready_exit_gate" \
    --launch-mode \
    "$avatar_mode" \
    --skip-exit-gates

  python3 - <<'PY'
import json
import os
from pathlib import Path

report_path = Path(os.environ["TMPDIR"]) / "manfred_room_ready_exit_gate" / "showtime_report.json"
if not report_path.is_file():
    raise SystemExit(f"missing_showtime_report:{report_path}")
payload = json.loads(report_path.read_text(encoding="utf-8"))
results = payload.get("results") or []
voice_step = next((item for item in results if item.get("name") == "voice_roundtrip_validation"), None)
if not voice_step:
    raise SystemExit("missing_voice_roundtrip_validation_step")
effective = str(voice_step.get("effective_status") or "")
if effective != "pass":
    raise SystemExit(f"voice_roundtrip_validation_not_pass:{effective}")
PY

  "$PYTHON_BIN" "$ROOT/scripts/measure_memorial_live_browser.py" \
    --base-url "$MEMORIAL_FLAGSHIP_BASE_URL" \
    --slug manfred \
    --output "$TMPDIR/manfred_room_ready_exit_gate/memorial_live_turn_gate.json" \
    --exit-gate
fi
