#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/docker/EA}"

echo "[SMOKE][v1.20] Host compile"
python3 -m py_compile \
  "$ROOT/ea/app/execution/session_store.py" \
  "$ROOT/ea/app/planner/task_registry.py" \
  "$ROOT/ea/app/planner/provider_outcomes.py" \
  "$ROOT/ea/app/sim_user/runner.py" \
  "$ROOT/ea/app/intent_runtime.py" \
  "$ROOT/tests/smoke_python_compile_tree.py" \
  "$ROOT/tests/smoke_v1_20_execution_sessions.py" \
  "$ROOT/tests/smoke_v1_20_doc_alignment.py" \
  "$ROOT/tests/smoke_v1_20_typed_action_sessions.py" \
  "$ROOT/tests/smoke_v1_20_browseract_event_sessions.py" \
  "$ROOT/tests/smoke_v1_20_external_event_sessions.py" \
  "$ROOT/tests/smoke_v1_20_external_event_behavior.py" \
  "$ROOT/tests/smoke_v1_20_slash_command_sessions.py" \
  "$ROOT/tests/smoke_v1_20_teable_memory_boundary.py" \
  "$ROOT/tests/smoke_v1_20_slash_command_behavior.py" \
  "$ROOT/tests/smoke_v1_20_typed_action_behavior.py" \
  "$ROOT/tests/smoke_v1_20_typed_action_approval_resume.py" \
  "$ROOT/tests/smoke_v1_20_free_text_approval_gate_behavior.py" \
  "$ROOT/tests/smoke_v1_20_gog_session_id_uniqueness.py" \
  "$ROOT/tests/smoke_v1_20_legacy_button_action_sessions.py" \
  "$ROOT/tests/smoke_v1_20_brief_command_sessions.py" \
  "$ROOT/tests/smoke_v1_21_task_contract_registry.py" \
  "$ROOT/tests/smoke_v1_21_intent_spec_v2_shape.py" \
  "$ROOT/tests/smoke_v1_21_provider_broker.py" \
  "$ROOT/tests/smoke_v1_21_provider_outcomes.py" \
  "$ROOT/tests/smoke_v1_21_provider_registry.py" \
  "$ROOT/tests/smoke_v1_21_approval_gate_store.py" \
  "$ROOT/tests/smoke_v1_21_typed_action_reference_enforcement.py" \
  "$ROOT/tests/smoke_v1_21_step_executor_path.py" \
  "$ROOT/tests/smoke_v1_21_intent_runtime_planner_steps.py" \
  "$ROOT/tests/smoke_v1_21_generic_skill_execution.py" \
  "$ROOT/tests/smoke_v1_21_plan_builder.py" \
  "$ROOT/tests/smoke_v1_21_gate_alias.py" \
  "$ROOT/tests/smoke_v1_21_doc_alignment.py" \
  "$ROOT/tests/smoke_v1_22_world_model_seed.py" \
  "$ROOT/tests/smoke_v1_22_memory_candidates.py" \
  "$ROOT/tests/smoke_v1_22_memory_promotion_pipeline.py" \
  "$ROOT/tests/smoke_v1_22_approval_callback_guard.py" \
  "$ROOT/tests/smoke_v1_22_sim_user_harness.py" \
  "$ROOT/tests/smoke_v1_22_route_signal_router.py" \
  "$ROOT/tests/smoke_v1_22_proactive_role_wiring.py" \
  "$ROOT/tests/smoke_v1_22_proactive_runtime_integration.py" \
  "$ROOT/tests/smoke_v1_22_task_contract_surface.py" \
  "$ROOT/tests/smoke_v1_22_schema_manifest_gate.py" \
  "$ROOT/tests/smoke_v1_22_synthetic_preview_outcomes.py" \
  "$ROOT/tests/smoke_v1_22_task_matcher.py" \
  "$ROOT/tests/smoke_v1_22_step_executor_ledger_seed.py" \
  "$ROOT/tests/smoke_v1_22_plan_store_seed.py" \
  "$ROOT/tests/smoke_v1_22_pre_step_parity.py" \
  "$ROOT/tests/smoke_v1_22_planner_exports.py" \
  "$ROOT/tests/smoke_v1_22_planner_runtime_contracts.py" \
  "$ROOT/tests/smoke_work_tasks_contract.py"

echo "[SMOKE][v1.20] Host smoke"
python3 "$ROOT/tests/smoke_python_compile_tree.py"
python3 "$ROOT/tests/smoke_v1_20_execution_sessions.py"
python3 "$ROOT/tests/smoke_v1_20_doc_alignment.py"
python3 "$ROOT/tests/smoke_v1_20_typed_action_sessions.py"
python3 "$ROOT/tests/smoke_v1_20_browseract_event_sessions.py"
python3 "$ROOT/tests/smoke_v1_20_external_event_sessions.py"
python3 "$ROOT/tests/smoke_v1_20_external_event_behavior.py"
python3 "$ROOT/tests/smoke_v1_20_slash_command_sessions.py"
python3 "$ROOT/tests/smoke_v1_20_teable_memory_boundary.py"
python3 "$ROOT/tests/smoke_v1_20_slash_command_behavior.py"
python3 "$ROOT/tests/smoke_v1_20_typed_action_behavior.py"
python3 "$ROOT/tests/smoke_v1_20_typed_action_approval_resume.py"
python3 "$ROOT/tests/smoke_v1_20_free_text_approval_gate_behavior.py"
python3 "$ROOT/tests/smoke_v1_20_gog_session_id_uniqueness.py"
python3 "$ROOT/tests/smoke_v1_20_legacy_button_action_sessions.py"
python3 "$ROOT/tests/smoke_v1_20_brief_command_sessions.py"
python3 "$ROOT/tests/smoke_v1_21_task_contract_registry.py"
python3 "$ROOT/tests/smoke_v1_21_intent_spec_v2_shape.py"
python3 "$ROOT/tests/smoke_v1_21_provider_broker.py"
python3 "$ROOT/tests/smoke_v1_21_provider_outcomes.py"
python3 "$ROOT/tests/smoke_v1_21_provider_registry.py"
python3 "$ROOT/tests/smoke_v1_21_approval_gate_store.py"
python3 "$ROOT/tests/smoke_v1_21_typed_action_reference_enforcement.py"
python3 "$ROOT/tests/smoke_v1_21_step_executor_path.py"
python3 "$ROOT/tests/smoke_v1_21_intent_runtime_planner_steps.py"
python3 "$ROOT/tests/smoke_v1_21_generic_skill_execution.py"
python3 "$ROOT/tests/smoke_v1_21_plan_builder.py"
python3 "$ROOT/tests/smoke_v1_21_gate_alias.py"
python3 "$ROOT/tests/smoke_v1_21_doc_alignment.py"
python3 "$ROOT/tests/smoke_v1_22_world_model_seed.py"
python3 "$ROOT/tests/smoke_v1_22_memory_candidates.py"
python3 "$ROOT/tests/smoke_v1_22_memory_promotion_pipeline.py"
python3 "$ROOT/tests/smoke_v1_22_approval_callback_guard.py"
python3 "$ROOT/tests/smoke_v1_22_sim_user_harness.py"
python3 "$ROOT/tests/smoke_v1_22_route_signal_router.py"
python3 "$ROOT/tests/smoke_v1_22_proactive_role_wiring.py"
python3 "$ROOT/tests/smoke_v1_22_proactive_runtime_integration.py"
python3 "$ROOT/tests/smoke_v1_22_task_contract_surface.py"
python3 "$ROOT/tests/smoke_v1_22_schema_manifest_gate.py"
python3 "$ROOT/tests/smoke_v1_22_synthetic_preview_outcomes.py"
python3 "$ROOT/tests/smoke_v1_22_task_matcher.py"
python3 "$ROOT/tests/smoke_v1_22_step_executor_ledger_seed.py"
python3 "$ROOT/tests/smoke_v1_22_plan_store_seed.py"
python3 "$ROOT/tests/smoke_v1_22_pre_step_parity.py"
python3 "$ROOT/tests/smoke_v1_22_planner_exports.py"
python3 "$ROOT/tests/smoke_v1_22_planner_runtime_contracts.py"
python3 "$ROOT/tests/smoke_work_tasks_contract.py"

if [[ "${EA_SKIP_FULL_GATES:-0}" != "1" ]]; then
  echo "[SMOKE][v1.20] Running full docker gate suite"
  "$ROOT/scripts/docker_e2e.sh"
else
  echo "[SMOKE][v1.20] Skipping full docker gate suite (EA_SKIP_FULL_GATES=1)"
fi

echo "[SMOKE][v1.20] PASS"
