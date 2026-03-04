#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/docker/EA}"

echo "[SMOKE][v1.20] Host compile"
python3 -m py_compile \
  "$ROOT/ea/app/execution/session_store.py" \
  "$ROOT/ea/app/intent_runtime.py" \
  "$ROOT/tests/smoke_v1_20_execution_sessions.py" \
  "$ROOT/tests/smoke_v1_20_doc_alignment.py" \
  "$ROOT/tests/smoke_v1_20_typed_action_sessions.py" \
  "$ROOT/tests/smoke_v1_20_browseract_event_sessions.py" \
  "$ROOT/tests/smoke_v1_20_external_event_sessions.py"

echo "[SMOKE][v1.20] Host smoke"
python3 "$ROOT/tests/smoke_v1_20_execution_sessions.py"
python3 "$ROOT/tests/smoke_v1_20_doc_alignment.py"
python3 "$ROOT/tests/smoke_v1_20_typed_action_sessions.py"
python3 "$ROOT/tests/smoke_v1_20_browseract_event_sessions.py"
python3 "$ROOT/tests/smoke_v1_20_external_event_sessions.py"

if [[ "${EA_SKIP_FULL_GATES:-0}" != "1" ]]; then
  echo "[SMOKE][v1.20] Running full docker gate suite"
  "$ROOT/scripts/docker_e2e.sh"
else
  echo "[SMOKE][v1.20] Skipping full docker gate suite (EA_SKIP_FULL_GATES=1)"
fi

echo "[SMOKE][v1.20] PASS"
