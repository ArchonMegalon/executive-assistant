#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/docker/EA}"

echo "[SMOKE][v1.19] Host compile"
python3 -m py_compile \
  "$ROOT/ea/app/intelligence/profile.py" \
  "$ROOT/ea/app/intelligence/dossiers.py" \
  "$ROOT/ea/app/intelligence/future_situations.py" \
  "$ROOT/ea/app/intelligence/readiness.py" \
  "$ROOT/ea/app/intelligence/critical_lane.py" \
  "$ROOT/ea/app/intelligence/modes.py" \
  "$ROOT/ea/app/intelligence/preparation_planner.py" \
  "$ROOT/tests/run_incoming_v119_pack.py" \
  "$ROOT/tests/smoke_v1_19_future_intelligence_pack.py" \
  "$ROOT/tests/smoke_v1_19_1_future_intelligence_expansion.py" \
  "$ROOT/tests/smoke_v1_19_1_profile_persistence.py" \
  "$ROOT/tests/smoke_v1_19_1_llm_gateway_boundary.py" \
  "$ROOT/tests/smoke_v1_19_2_human_assistant_mode.py" \
  "$ROOT/tests/smoke_v1_19_2_health_dossier.py" \
  "$ROOT/tests/smoke_v1_19_2_household_dossier.py" \
  "$ROOT/tests/smoke_v1_19_2_snapshot_persistence.py" \
  "$ROOT/tests/smoke_v1_19_2_llm_egress_policy.py" \
  "$ROOT/tests/smoke_v1_19_2_missingness.py" \
  "$ROOT/tests/smoke_v1_19_3_human_compose_behavior.py" \
  "$ROOT/tests/smoke_v1_19_3_skill_router.py" \
  "$ROOT/tests/smoke_v1_19_4_capability_registry.py" \
  "$ROOT/tests/smoke_v1_19_4_skill_inventory.py" \
  "$ROOT/tests/smoke_v1_19_4_capability_router.py" \
  "$ROOT/tests/smoke_v1_19_4_doc_alignment.py" \
  "$ROOT/tests/smoke_v1_19_4_backlog_contract.py" \
  "$ROOT/tests/smoke_v1_19_4_skill_runtime_path.py" \
  "$ROOT/tests/smoke_v1_19_4_sidecar_skill_orchestration.py" \
  "$ROOT/tests/smoke_v1_19_4_llm_gateway_convergence.py" \
  "$ROOT/tests/smoke_v1_19_4_briefing_diagnostics_log_gate.py" \
  "$ROOT/tests/smoke_v1_19_4_ltd_inventory_doc.py" \
  "$ROOT/tests/smoke_v1_19_4_event_worker_role_alignment.py" \
  "$ROOT/tests/smoke_v1_20_execution_sessions.py" \
  "$ROOT/tests/smoke_v1_20_doc_alignment.py" \
  "$ROOT/tests/smoke_v1_20_typed_action_sessions.py" \
  "$ROOT/tests/smoke_v1_20_browseract_event_sessions.py" \
  "$ROOT/tests/smoke_v1_20_external_event_sessions.py" \
  "$ROOT/tests/smoke_v1_19_3_control_plane_decomposition.py" \
  "$ROOT/tests/smoke_v1_19_3_source_acquisition_split.py" \
  "$ROOT/tests/smoke_v1_19_3_briefing_runtime_behavior.py"

echo "[SMOKE][v1.19] Incoming contract-pack smoke"
python3 "$ROOT/tests/smoke_v1_19_future_intelligence_pack.py"
python3 "$ROOT/tests/smoke_v1_19_1_future_intelligence_expansion.py"
python3 "$ROOT/tests/smoke_v1_19_1_profile_persistence.py"
python3 "$ROOT/tests/smoke_v1_19_1_llm_gateway_boundary.py"
python3 "$ROOT/tests/smoke_v1_19_2_human_assistant_mode.py"
python3 "$ROOT/tests/smoke_v1_19_2_health_dossier.py"
python3 "$ROOT/tests/smoke_v1_19_2_household_dossier.py"
python3 "$ROOT/tests/smoke_v1_19_2_snapshot_persistence.py"
python3 "$ROOT/tests/smoke_v1_19_2_llm_egress_policy.py"
python3 "$ROOT/tests/smoke_v1_19_2_missingness.py"
python3 "$ROOT/tests/smoke_v1_19_3_human_compose_behavior.py"
python3 "$ROOT/tests/smoke_v1_19_3_skill_router.py"
python3 "$ROOT/tests/smoke_v1_19_4_capability_registry.py"
python3 "$ROOT/tests/smoke_v1_19_4_skill_inventory.py"
python3 "$ROOT/tests/smoke_v1_19_4_capability_router.py"
python3 "$ROOT/tests/smoke_v1_19_4_doc_alignment.py"
python3 "$ROOT/tests/smoke_v1_19_4_backlog_contract.py"
python3 "$ROOT/tests/smoke_v1_19_4_skill_runtime_path.py"
python3 "$ROOT/tests/smoke_v1_19_4_sidecar_skill_orchestration.py"
python3 "$ROOT/tests/smoke_v1_19_4_llm_gateway_convergence.py"
python3 "$ROOT/tests/smoke_v1_19_4_briefing_diagnostics_log_gate.py"
python3 "$ROOT/tests/smoke_v1_19_4_ltd_inventory_doc.py"
python3 "$ROOT/tests/smoke_v1_19_4_event_worker_role_alignment.py"
python3 "$ROOT/tests/smoke_v1_20_execution_sessions.py"
python3 "$ROOT/tests/smoke_v1_20_doc_alignment.py"
python3 "$ROOT/tests/smoke_v1_20_typed_action_sessions.py"
python3 "$ROOT/tests/smoke_v1_20_browseract_event_sessions.py"
python3 "$ROOT/tests/smoke_v1_20_external_event_sessions.py"
python3 "$ROOT/tests/smoke_v1_19_3_control_plane_decomposition.py"
python3 "$ROOT/tests/smoke_v1_19_3_source_acquisition_split.py"
python3 "$ROOT/tests/smoke_v1_19_3_briefing_runtime_behavior.py"

if [[ "${EA_SKIP_FULL_GATES:-0}" != "1" ]]; then
  echo "[SMOKE][v1.19] Running full docker gate suite"
  "$ROOT/scripts/docker_e2e.sh"
else
  echo "[SMOKE][v1.19] Skipping full docker gate suite (EA_SKIP_FULL_GATES=1)"
fi

echo "[SMOKE][v1.19] PASS"
