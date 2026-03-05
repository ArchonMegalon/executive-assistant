#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA_FILES=(
  "${EA_ROOT}/ea/schema/20260303_v1_18_1_runtime_alignment.sql"
  "${EA_ROOT}/ea/schema/20260304_v1_20_execution_sessions.sql"
)
HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
HOST_PORT="${HOST_PORT:-8090}"
REPORT_DIR="${EA_ROOT}/logs/gates"
REPORT_TS="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_FILE="${REPORT_DIR}/docker_e2e_${REPORT_TS}.json"
REPORT_TMP="/tmp/ea_gate_steps_${REPORT_TS}_$$.tsv"

cd "${EA_ROOT}"
mkdir -p "${REPORT_DIR}"

record_step() {
  local name="$1"
  local status="$2"
  local duration_ms="$3"
  printf "%s\t%s\t%s\n" "${name}" "${status}" "${duration_ms}" >> "${REPORT_TMP}"
}

run_step() {
  local name="$1"
  shift
  local start_ms end_ms duration
  start_ms="$(date +%s%3N)"
  "$@"
  end_ms="$(date +%s%3N)"
  duration="$((end_ms - start_ms))"
  record_step "${name}" "pass" "${duration}"
}

write_report() {
  local rc="$1"
  python3 - <<PY
import json
from pathlib import Path

report_tmp = Path("${REPORT_TMP}")
steps = []
if report_tmp.exists():
    for line in report_tmp.read_text(encoding="utf-8").splitlines():
        parts = line.split("\\t")
        if len(parts) == 3:
            steps.append({
                "name": parts[0],
                "status": parts[1],
                "duration_ms": int(parts[2]),
            })

payload = {
    "generated_at_utc": "${REPORT_TS}",
    "overall_status": "pass" if int("${rc}") == 0 else "fail",
    "exit_code": int("${rc}"),
    "steps": steps,
}

Path("${REPORT_FILE}").write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(f"[gate-report] wrote ${REPORT_FILE}")
PY
  rm -f "${REPORT_TMP}" || true
}

on_exit() {
  local rc="$?"
  write_report "${rc}"
}
trap on_exit EXIT

echo "== Docker E2E: bring up EA stack =="
run_step "compose_up" docker compose up -d --build ea-db ea-api ea-poller ea-worker ea-outbox ea-event-worker ea-teable-sync

echo "== Docker E2E: apply runtime alignment schema =="
start_ms="$(date +%s%3N)"
for schema_file in "${SCHEMA_FILES[@]}"; do
  docker exec -i ea-db psql -U postgres -d ea -v ON_ERROR_STOP=1 < "${schema_file}"
done
end_ms="$(date +%s%3N)"
record_step "apply_schema" "pass" "$((end_ms - start_ms))"

echo "== Docker E2E: restart app services to pick up latest code =="
run_step "compose_restart" docker compose restart ea-api ea-poller ea-worker ea-outbox ea-event-worker ea-teable-sync
LOG_CHECK_SINCE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "== Docker E2E: wait for API health =="
start_ms="$(date +%s%3N)"
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:${HOST_PORT}/health" >/tmp/ea_e2e_health.json 2>/dev/null; then
    break
  fi
  sleep 2
done
curl -fsS "http://localhost:${HOST_PORT}/health" >/tmp/ea_e2e_health.json
cat /tmp/ea_e2e_health.json
echo
end_ms="$(date +%s%3N)"
record_step "health_check" "pass" "$((end_ms - start_ms))"

echo "== Docker E2E: runtime alignment smoke =="
run_step "smoke_runtime_alignment" python3 tests/smoke_v1_18_1_runtime_alignment.py
run_step "smoke_v1_12_6_avomap" python3 tests/smoke_v1_12_6.py
run_step "smoke_v1_12_7_contract_freeze" python3 tests/smoke_v1_12_7_contract_freeze.py
run_step "smoke_sentinel_user_message" python3 tests/smoke_sentinel_user_message.py
run_step "smoke_brief_dedupe_guard" python3 tests/smoke_brief_dedupe_guard.py
run_step "smoke_calendar_import_result" python3 tests/smoke_calendar_import_result.py
run_step "smoke_calendar_event_normalization" python3 tests/smoke_calendar_event_normalization.py
run_step "smoke_calendar_preview_html_safety" python3 tests/smoke_calendar_preview_html_safety.py
run_step "smoke_open_loops_store" python3 tests/smoke_open_loops_store.py
run_step "smoke_v1_13" python3 tests/smoke_v1_13.py
run_step "smoke_v1_13_future_intelligence_pack" python3 tests/smoke_v1_13_future_intelligence_pack.py
run_step "smoke_v1_14" python3 tests/smoke_v1_14.py
run_step "smoke_v1_15" python3 tests/smoke_v1_15.py
run_step "smoke_v1_16" python3 tests/smoke_v1_16.py
run_step "smoke_v1_17" python3 tests/smoke_v1_17.py
run_step "smoke_v1_18" python3 tests/smoke_v1_18.py
run_step "smoke_v1_19_future_intelligence_pack" python3 tests/smoke_v1_19_future_intelligence_pack.py
run_step "smoke_v1_19_1_future_intelligence_expansion" python3 tests/smoke_v1_19_1_future_intelligence_expansion.py
run_step "smoke_v1_19_1_profile_persistence" python3 tests/smoke_v1_19_1_profile_persistence.py
run_step "smoke_v1_19_1_llm_gateway_boundary" python3 tests/smoke_v1_19_1_llm_gateway_boundary.py
run_step "smoke_v1_19_2_human_assistant_mode" python3 tests/smoke_v1_19_2_human_assistant_mode.py
run_step "smoke_v1_19_2_health_dossier" python3 tests/smoke_v1_19_2_health_dossier.py
run_step "smoke_v1_19_2_household_dossier" python3 tests/smoke_v1_19_2_household_dossier.py
run_step "smoke_v1_19_2_snapshot_persistence" python3 tests/smoke_v1_19_2_snapshot_persistence.py
run_step "smoke_v1_19_2_llm_egress_policy" python3 tests/smoke_v1_19_2_llm_egress_policy.py
run_step "smoke_v1_19_2_missingness" python3 tests/smoke_v1_19_2_missingness.py
run_step "smoke_v1_19_3_human_compose_behavior" python3 tests/smoke_v1_19_3_human_compose_behavior.py
run_step "smoke_v1_19_3_skill_router" python3 tests/smoke_v1_19_3_skill_router.py
run_step "smoke_v1_19_4_capability_registry" python3 tests/smoke_v1_19_4_capability_registry.py
run_step "smoke_v1_19_4_skill_inventory" python3 tests/smoke_v1_19_4_skill_inventory.py
run_step "smoke_v1_19_4_capability_router" python3 tests/smoke_v1_19_4_capability_router.py
run_step "smoke_v1_19_4_doc_alignment" python3 tests/smoke_v1_19_4_doc_alignment.py
run_step "smoke_v1_19_4_backlog_contract" python3 tests/smoke_v1_19_4_backlog_contract.py
run_step "smoke_v1_19_4_skill_runtime_path" python3 tests/smoke_v1_19_4_skill_runtime_path.py
run_step "smoke_v1_19_4_sidecar_skill_orchestration" python3 tests/smoke_v1_19_4_sidecar_skill_orchestration.py
run_step "smoke_v1_19_4_llm_gateway_convergence" python3 tests/smoke_v1_19_4_llm_gateway_convergence.py
run_step "smoke_v1_19_4_briefing_diagnostics_log_gate" python3 tests/smoke_v1_19_4_briefing_diagnostics_log_gate.py
run_step "smoke_v1_19_4_ltd_inventory_doc" python3 tests/smoke_v1_19_4_ltd_inventory_doc.py
run_step "smoke_v1_19_4_event_worker_role_alignment" python3 tests/smoke_v1_19_4_event_worker_role_alignment.py
run_step "smoke_v1_20_execution_sessions" python3 tests/smoke_v1_20_execution_sessions.py
run_step "smoke_v1_20_doc_alignment" python3 tests/smoke_v1_20_doc_alignment.py
run_step "smoke_v1_20_typed_action_sessions" python3 tests/smoke_v1_20_typed_action_sessions.py
run_step "smoke_v1_20_browseract_event_sessions" python3 tests/smoke_v1_20_browseract_event_sessions.py
run_step "smoke_v1_20_external_event_sessions" python3 tests/smoke_v1_20_external_event_sessions.py
run_step "smoke_v1_20_external_event_behavior" python3 tests/smoke_v1_20_external_event_behavior.py
run_step "smoke_v1_20_slash_command_sessions" python3 tests/smoke_v1_20_slash_command_sessions.py
run_step "smoke_v1_20_teable_memory_boundary" python3 tests/smoke_v1_20_teable_memory_boundary.py
run_step "smoke_v1_20_slash_command_behavior" python3 tests/smoke_v1_20_slash_command_behavior.py
run_step "smoke_v1_20_typed_action_behavior" python3 tests/smoke_v1_20_typed_action_behavior.py
run_step "smoke_v1_20_gog_session_id_uniqueness" python3 tests/smoke_v1_20_gog_session_id_uniqueness.py
run_step "smoke_v1_20_legacy_button_action_sessions" python3 tests/smoke_v1_20_legacy_button_action_sessions.py
run_step "smoke_v1_19_3_control_plane_decomposition" python3 tests/smoke_v1_19_3_control_plane_decomposition.py
run_step "smoke_v1_19_3_source_acquisition_split" python3 tests/smoke_v1_19_3_source_acquisition_split.py
run_step "smoke_v1_19_3_briefing_runtime_behavior" python3 tests/smoke_v1_19_3_briefing_runtime_behavior.py

echo "== Docker E2E: newspaper integration smokes =="
run_step "smoke_newspaper_issue_pipeline" python3 tests/smoke_newspaper_issue_pipeline.py
run_step "smoke_newspaper_brief_wiring" python3 tests/smoke_newspaper_brief_wiring.py
run_step "smoke_newspaper_pdf_gate_wiring" python3 tests/smoke_newspaper_pdf_gate_wiring.py
run_step "smoke_telegram_payload_sanitized" python3 tests/smoke_telegram_payload_sanitized.py

echo "== Docker E2E: design workflow suite (onboarding/surveys/...) =="
run_step "design_workflows_e2e" bash scripts/docker_e2e_design_workflows.sh

echo "== Docker E2E: logs must not show known runtime-regression errors =="
start_ms="$(date +%s%3N)"
sleep 8
DB_ERRS="$(docker logs ea-db --since "${LOG_CHECK_SINCE}" 2>&1 | grep -E 'column \"id\" does not exist|relation \"location_cursors\" does not exist' || true)"
API_ERRS="$(docker logs ea-api --since "${LOG_CHECK_SINCE}" 2>&1 | grep -E 'location watcher error|relation \"location_cursors\" does not exist' || true)"
if [[ -n "${DB_ERRS}" || -n "${API_ERRS}" ]]; then
  echo "FAIL: found regression errors in recent logs"
  [[ -n "${DB_ERRS}" ]] && echo "--- ea-db ---" && echo "${DB_ERRS}"
  [[ -n "${API_ERRS}" ]] && echo "--- ea-api ---" && echo "${API_ERRS}"
  exit 1
fi
end_ms="$(date +%s%3N)"
record_step "log_regression_gate" "pass" "$((end_ms - start_ms))"

echo "PASS: Docker E2E checks passed"
