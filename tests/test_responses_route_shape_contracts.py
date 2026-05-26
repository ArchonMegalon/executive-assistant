from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relpath: str) -> str:
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


def test_responses_codex_profile_routes_share_profiled_helper() -> None:
    source = _read("ea/app/api/routes/responses.py")
    background_source = _read("ea/app/api/routes/responses_background_runtime.py")
    background_orchestration_source = _read("ea/app/api/routes/responses_background_orchestration.py")
    background_workers_source = _read("ea/app/api/routes/responses_background_workers.py")
    persistence_source = _read("ea/app/api/routes/responses_persistence_runtime.py")
    planner_source = _read("ea/app/api/routes/responses_planner_runtime.py")
    prompt_source = _read("ea/app/api/routes/responses_prompt_runtime.py")
    prompt_compaction_source = _read("ea/app/api/routes/responses_prompt_compaction_runtime.py")
    operator_scope_source = _read("ea/app/api/routes/responses_operator_scope_runtime.py")
    output_runtime_source = _read("ea/app/api/routes/responses_output_runtime.py")
    probe_final_text_source = _read("ea/app/api/routes/responses_probe_final_text_runtime.py")
    direct_final_runtime_source = _read("ea/app/api/routes/responses_direct_final_runtime.py")
    local_unblock_runtime_source = _read("ea/app/api/routes/responses_local_unblock_runtime.py")
    local_fleet_runtime_source = _read("ea/app/api/routes/responses_local_fleet_runtime.py")
    staged_prompt_runtime_source = _read("ea/app/api/routes/responses_staged_prompt_runtime.py")
    command_history_runtime_source = _read("ea/app/api/routes/responses_command_history_runtime.py")
    staged_git_runtime_source = _read("ea/app/api/routes/responses_staged_git_runtime.py")
    package_scope_runtime_source = _read("ea/app/api/routes/responses_package_scope_runtime.py")
    package_planner_runtime_source = _read("ea/app/api/routes/responses_package_planner_runtime.py")
    repo_followup_runtime_source = _read("ea/app/api/routes/responses_repo_followup_runtime.py")
    telemetry_runtime_source = _read("ea/app/api/routes/responses_telemetry_runtime.py")
    registration_source = _read("ea/app/api/routes/responses_route_registration.py")
    codex_execution_source = _read("ea/app/api/routes/responses_codex_execution.py")
    metadata_source = _read("ea/app/api/routes/responses_codex_metadata.py")
    execution_source = _read("ea/app/api/routes/responses_execution_routes.py")
    read_source = _read("ea/app/api/routes/responses_read_routes.py")
    runtime_source = _read("ea/app/api/routes/responses_route_runtime.py")
    tool_runtime_source = _read("ea/app/api/routes/responses_tool_runtime.py")
    transcript_source = _read("ea/app/api/routes/responses_transcript_runtime.py")

    assert "_CODEX_PROFILE_ROUTE_SPECS = (" in source
    assert "from app.api.routes.responses_route_registration import (" in source
    assert "from app.api.routes.responses_background_runtime import (" in source
    assert "from app.api.routes.responses_background_orchestration import (" in source
    assert "from app.api.routes.responses_background_workers import (" in source
    assert "from app.api.routes.responses_persistence_runtime import (" in source
    assert "from app.api.routes.responses_codex_execution import build_run_profiled_codex_response" in source
    assert "from app.api.routes.responses_codex_metadata import (" in source
    assert "from app.api.routes.responses_execution_routes import (" in source
    assert "from app.api.routes.responses_read_routes import (" in source
    assert "from app.api.routes.responses_route_runtime import (" in source
    assert "from app.api.routes.responses_tool_runtime import (" in source
    assert "from app.api.routes.responses_planner_runtime import (" in source
    assert "from app.api.routes.responses_prompt_runtime import (" in source
    assert "from app.api.routes.responses_prompt_compaction_runtime import (" in source
    assert "from app.api.routes.responses_operator_scope_runtime import (" in source
    assert "from app.api.routes.responses_output_runtime import (" in source
    assert "from app.api.routes.responses_probe_final_text_runtime import (" in source
    assert "from app.api.routes.responses_direct_final_runtime import build_tool_shim_direct_final_text" in source
    assert "from app.api.routes.responses_local_unblock_runtime import (" in source
    assert "from app.api.routes.responses_local_fleet_runtime import (" in source
    assert "from app.api.routes.responses_staged_prompt_runtime import (" in source
    assert "from app.api.routes.responses_command_history_runtime import (" in source
    assert "from app.api.routes.responses_staged_git_runtime import (" in source
    assert "from app.api.routes.responses_package_scope_runtime import (" in source
    assert "from app.api.routes.responses_package_planner_runtime import (" in source
    assert "from app.api.routes.responses_repo_followup_runtime import (" in source
    assert "from app.api.routes.responses_telemetry_runtime import (" in source
    assert "from app.api.routes.responses_transcript_runtime import (" in source
    assert "def background_timeout_seconds_for_response(" in background_source
    assert "def background_response_deadline_unix(" in background_source
    assert "def background_response_has_expired(" in background_source
    assert "def background_replay_payload(" in background_source
    assert "def background_failed_response(" in background_source
    assert "def background_timeout_failure_message(" in background_source
    assert "def build_spawn_background_codex_worker(" in background_orchestration_source
    assert "def build_ensure_background_response_progress(" in background_orchestration_source
    assert "def build_load_response_for_runtime(" in background_orchestration_source
    assert "def cleanup_background_response_workers(" in background_workers_source
    assert "def background_response_has_live_worker(" in background_workers_source
    assert "def claim_background_response_worker_slot(" in background_workers_source
    assert "def register_background_response_worker(" in background_workers_source
    assert "def release_background_response_worker_slot(" in background_workers_source
    assert "def container_database_url(" in persistence_source
    assert "def response_record_repository(" in persistence_source
    assert "def store_response(" in persistence_source
    assert "def load_response(" in persistence_source
    assert "def store_background_terminal_response(" in persistence_source
    assert "def register_model_routes(" in registration_source
    assert "def register_response_item_routes(" in registration_source
    assert "def build_profiled_codex_route(" in registration_source
    assert "def register_profiled_codex_routes(" in registration_source
    assert "def register_codex_metadata_routes(" in registration_source
    assert "def build_run_profiled_codex_response(" in codex_execution_source
    assert "def codex_profiles_response_payload(" in metadata_source
    assert "def codex_status_response_payload(" in metadata_source
    assert "def build_list_codex_profiles_handler(" in metadata_source
    assert "def build_get_codex_status_handler(" in metadata_source
    assert "def provider_health_response_payload(" in execution_source
    assert "def build_get_provider_health_handler(" in execution_source
    assert "def build_create_response_handler(" in execution_source
    assert "def models_response_payload(" in read_source
    assert "def response_read_payload(" in read_source
    assert "def response_input_items_payload(" in read_source
    assert "def build_list_models_handler(" in read_source
    assert "def build_get_response_handler(" in read_source
    assert "def build_get_response_input_items_handler(" in read_source
    assert "def header_codex_profile_from_request(" in runtime_source
    assert "def payload_with_request_trace_metadata(" in runtime_source
    assert "def preferred_onemin_labels_from_request(" in runtime_source
    assert "def build_run_response_in_executor(" in runtime_source
    assert "def generate_upstream_text(" in tool_runtime_source
    assert "def build_tool_shim_generate_upstream_text_with_timeout(" in tool_runtime_source
    assert "def response_tools(" in tool_runtime_source
    assert "def tool_choice_disables_tools(" in tool_runtime_source
    assert "def build_tool_shim_supported_tools(" in tool_runtime_source
    assert "def history_items_for_request(" in planner_source
    assert "def tool_shim_transcript_max_chars(" in planner_source
    assert "def tool_shim_transcript_part_max_chars(" in planner_source
    assert "def build_tool_shim_planner_model(" in planner_source
    assert "def tool_shim_planner_max_output_tokens(" in planner_source
    assert "def build_tool_shim_planner_deadline_monotonic(" in planner_source
    assert "def tool_shim_is_staged_local_orientation_prompt(" in prompt_source
    assert "def tool_shim_is_operator_fleet_unblock_prompt(" in prompt_source
    assert "def tool_shim_is_package_work_prompt(" in prompt_source
    assert "def tool_shim_is_operator_readiness_remedy_prompt(" in prompt_source
    assert "def tool_shim_is_operator_gap_audit_prompt(" in prompt_source
    assert "def tool_shim_is_operator_gap_fix_prompt(" in prompt_source
    assert "def build_tool_shim_transcript_limit_for_prompt(" in prompt_compaction_source
    assert "def build_tool_shim_compact_operator_prompt_for_planner(" in prompt_compaction_source
    assert "def build_tool_shim_compact_readiness_prompt_for_planner(" in prompt_compaction_source
    assert "def build_tool_shim_is_operator_fleet_unblock_context(" in operator_scope_source
    assert "def build_tool_shim_operator_unblock_scope_rejection_reason(" in operator_scope_source
    assert "codexea" in operator_scope_source
    assert "EA endpoint and 1min-manager code only" in operator_scope_source
    assert "This operator fleet-unblock run may read only the codexea shim" in operator_scope_source
    assert "def tool_shim_unwrap_tool_output_envelope(" in output_runtime_source
    assert "def build_tool_shim_latest_function_output(" in output_runtime_source
    assert "def build_tool_shim_requires_immediate_tool(" in output_runtime_source
    assert "def build_tool_shim_local_upstream_result(" in output_runtime_source
    assert "def tool_shim_scalar_text(" in output_runtime_source
    assert "provider_key=\"local\"" in output_runtime_source
    assert "function_call_output" in output_runtime_source
    assert "def tool_shim_gap_audit_final_text(" in probe_final_text_source
    assert "def tool_shim_ui_parity_audit_final_text(" in probe_final_text_source
    assert "def tool_shim_parity_build_final_text(" in probe_final_text_source
    assert "def tool_shim_gap_fix_final_text(" in probe_final_text_source
    assert "Gap audit findings:" in probe_final_text_source
    assert "UI parity audit result:" in probe_final_text_source
    assert "Parity build result:" in probe_final_text_source
    assert "Gap fix result:" in probe_final_text_source
    assert "def build_tool_shim_direct_final_text(" in direct_final_runtime_source
    assert "fleet_local_unblock.py" in direct_final_runtime_source
    assert "codexea_parity_build_workflow.py" in direct_final_runtime_source
    assert "codexea_ui_parity_audit_probe.py" in direct_final_runtime_source
    assert "codexea_gap_fix_workflow.py" in direct_final_runtime_source
    assert "codexea_gap_audit_probe.py" in direct_final_runtime_source
    assert "def tool_shim_local_unblock_command_for_prompt(" in local_unblock_runtime_source
    assert "def build_tool_shim_direct_local_unblock_command(" in local_unblock_runtime_source
    assert "def tool_shim_local_unblock_final_text(" in local_unblock_runtime_source
    assert "\"chummer6-ui\"" in local_unblock_runtime_source
    assert "mirror_sync --repo {repo_id}" in local_unblock_runtime_source
    assert "local_unblock_failed" in local_unblock_runtime_source
    assert "def build_tool_shim_staged_first_command_max_output_tokens(" in local_fleet_runtime_source
    assert "def build_tool_shim_direct_local_fleet_command(" in local_fleet_runtime_source
    assert "remaining_not_started_milestones" in local_fleet_runtime_source
    assert "active_runs_count" in local_fleet_runtime_source
    assert "eta_human" in local_fleet_runtime_source
    assert "def tool_shim_has_tool_history(" in staged_prompt_runtime_source
    assert "def tool_shim_direct_file_read_command(" in staged_prompt_runtime_source
    assert "def tool_shim_looks_like_shell_command(" in staged_prompt_runtime_source
    assert "def build_tool_shim_staged_commands(" in staged_prompt_runtime_source
    assert "Run these exact commands first:" in staged_prompt_runtime_source
    assert "Read these files directly first:" in staged_prompt_runtime_source
    assert "def tool_shim_resolve_equivalent_shard_runtime_path(" in command_history_runtime_source
    assert "def tool_shim_normalize_equivalent_command_paths(" in command_history_runtime_source
    assert "def tool_shim_exec_command_history(" in command_history_runtime_source
    assert "def build_tool_shim_exec_command_identity_history(" in command_history_runtime_source
    assert "def build_tool_shim_command_identity_sequence(" in command_history_runtime_source
    assert "def build_tool_shim_exec_command_expanded_sequence(" in command_history_runtime_source
    assert "def build_tool_shim_command_sequence_executed(" in command_history_runtime_source
    assert "def build_tool_shim_exec_command_output_history(" in command_history_runtime_source
    assert "def build_tool_shim_latest_exec_json_output(" in command_history_runtime_source
    assert "def build_tool_shim_latest_exec_json_output_for_command(" in command_history_runtime_source
    assert "def tool_shim_is_git_command(" in staged_git_runtime_source
    assert "def build_tool_shim_is_staged_git_commit_push_workflow(" in staged_git_runtime_source
    assert "def build_tool_shim_build_staged_git_commit_push_command(" in staged_git_runtime_source
    assert "def tool_shim_extract_git_head_hash(" in staged_git_runtime_source
    assert "def build_tool_shim_direct_staged_git_commit_push_final_text(" in staged_git_runtime_source
    assert "def tool_shim_package_scope_text(" in package_scope_runtime_source
    assert "def tool_shim_bulleted_section_paths(" in package_scope_runtime_source
    assert "def build_tool_shim_active_slice_followup_paths(" in package_scope_runtime_source
    assert "def tool_shim_package_current_slice_text(" in package_scope_runtime_source
    assert "def tool_shim_package_worktree(" in package_scope_runtime_source
    assert "def tool_shim_package_allowed_scope_tokens(" in package_scope_runtime_source
    assert "def build_tool_shim_package_allowed_scope_paths(" in package_scope_runtime_source
    assert "def build_tool_shim_package_scope_pathspecs(" in package_scope_runtime_source
    assert "def build_tool_shim_build_package_scope_repo_diff_command(" in package_scope_runtime_source
    assert "def build_tool_shim_build_package_scope_repo_hunks_command(" in package_scope_runtime_source
    assert "def build_tool_shim_package_scope_search_terms(" in package_scope_runtime_source
    assert "def build_tool_shim_build_package_scope_search_command(" in package_scope_runtime_source
    assert "def build_tool_shim_package_planner_blocked_final_text(" in package_planner_runtime_source
    assert "def build_tool_shim_package_planner_blocked_decision(" in package_planner_runtime_source
    assert "def tool_shim_provider_row_is_ready(" in package_planner_runtime_source
    assert "def build_tool_shim_provider_row_is_dispatchable(" in package_planner_runtime_source
    assert "def build_tool_shim_package_planner_preflight_failure_message(" in package_planner_runtime_source
    assert "def build_tool_shim_build_repo_diff_command_for_paths(" in repo_followup_runtime_source
    assert "def build_tool_shim_build_staged_repo_diff_command(" in repo_followup_runtime_source
    assert "def build_tool_shim_build_repo_hunks_command_for_paths(" in repo_followup_runtime_source
    assert "def build_tool_shim_build_staged_repo_hunks_command(" in repo_followup_runtime_source
    assert "def build_tool_shim_operator_unblock_repo_diff_command(" in repo_followup_runtime_source
    assert "def build_tool_shim_operator_unblock_repo_hunks_command(" in repo_followup_runtime_source
    assert "def tool_shim_direct_compact_provider_health_command(" in telemetry_runtime_source
    assert "def build_tool_shim_operator_unblock_provider_health_command(" in telemetry_runtime_source
    assert "def tool_shim_operator_unblock_live_routing_hotspots_command(" in telemetry_runtime_source
    assert "def build_tool_shim_telemetry_followup_commands(" in telemetry_runtime_source
    assert "def build_tool_shim_recent_nested_telemetry_commands(" in telemetry_runtime_source
    assert "def build_tool_shim_direct_nested_telemetry_first_command(" in telemetry_runtime_source
    assert "def tool_shim_truncate_text(" in transcript_source
    assert "def tool_shim_tool_parameters_summary(" in transcript_source
    assert "def build_history_item_to_transcript(" in transcript_source
    assert "def build_tool_shim_latest_user_text(" in transcript_source
    assert "def build_tool_shim_latest_package_work_prompt(" in transcript_source
    assert "register_model_routes(" in source
    assert "register_response_item_routes(" in source
    assert "register_profiled_codex_routes(" in source
    assert "register_codex_metadata_routes(" in source
    assert "build_list_codex_profiles_handler(" in source
    assert "build_get_codex_status_handler(" in source
    assert "build_get_provider_health_handler(" in source
    assert "build_create_response_handler(" in source
    assert "build_run_profiled_codex_response(" in source
    assert "build_run_response_in_executor(" in source
    assert "build_list_models_handler(" in source
    assert "build_get_response_handler(" in source
    assert "build_get_response_input_items_handler(" in source
    assert "async def _provider_health_route_registry_payload(" in source
    assert '"core"' in source
    assert '"core_batch"' in source
    assert '"core_rescue"' in source
    assert '"easy"' in source
    assert '"repair"' in source
    assert '"groundwork"' in source
    assert '"review_light"' in source
    assert '"survival"' in source
    assert '"audit"' in source

    for route_name in (
        "create_codex_core",
        "create_codex_core_batch",
        "create_codex_core_rescue",
        "create_codex_easy",
        "create_codex_repair",
        "create_codex_groundwork",
        "create_codex_review_light",
        "create_codex_survival",
        "create_codex_audit",
    ):
        assert f'"{route_name}"' in source


def test_responses_provider_health_and_profiles_routes_use_shared_helpers() -> None:
    source = _read("ea/app/api/routes/responses.py")
    background_source = _read("ea/app/api/routes/responses_background_runtime.py")
    background_orchestration_source = _read("ea/app/api/routes/responses_background_orchestration.py")
    background_workers_source = _read("ea/app/api/routes/responses_background_workers.py")
    persistence_source = _read("ea/app/api/routes/responses_persistence_runtime.py")
    planner_source = _read("ea/app/api/routes/responses_planner_runtime.py")
    prompt_source = _read("ea/app/api/routes/responses_prompt_runtime.py")
    prompt_compaction_source = _read("ea/app/api/routes/responses_prompt_compaction_runtime.py")
    operator_scope_source = _read("ea/app/api/routes/responses_operator_scope_runtime.py")
    output_runtime_source = _read("ea/app/api/routes/responses_output_runtime.py")
    probe_final_text_source = _read("ea/app/api/routes/responses_probe_final_text_runtime.py")
    direct_final_runtime_source = _read("ea/app/api/routes/responses_direct_final_runtime.py")
    local_unblock_runtime_source = _read("ea/app/api/routes/responses_local_unblock_runtime.py")
    local_fleet_runtime_source = _read("ea/app/api/routes/responses_local_fleet_runtime.py")
    staged_prompt_runtime_source = _read("ea/app/api/routes/responses_staged_prompt_runtime.py")
    command_history_runtime_source = _read("ea/app/api/routes/responses_command_history_runtime.py")
    staged_git_runtime_source = _read("ea/app/api/routes/responses_staged_git_runtime.py")
    package_scope_runtime_source = _read("ea/app/api/routes/responses_package_scope_runtime.py")
    package_planner_runtime_source = _read("ea/app/api/routes/responses_package_planner_runtime.py")
    repo_followup_runtime_source = _read("ea/app/api/routes/responses_repo_followup_runtime.py")
    telemetry_runtime_source = _read("ea/app/api/routes/responses_telemetry_runtime.py")
    registration_source = _read("ea/app/api/routes/responses_route_registration.py")
    codex_execution_source = _read("ea/app/api/routes/responses_codex_execution.py")
    metadata_source = _read("ea/app/api/routes/responses_codex_metadata.py")
    execution_source = _read("ea/app/api/routes/responses_execution_routes.py")
    read_source = _read("ea/app/api/routes/responses_read_routes.py")
    runtime_source = _read("ea/app/api/routes/responses_route_runtime.py")
    tool_runtime_source = _read("ea/app/api/routes/responses_tool_runtime.py")
    transcript_source = _read("ea/app/api/routes/responses_transcript_runtime.py")

    assert "normalize_payload_for_profile(" in codex_execution_source
    assert "return await run_response_in_executor(" in codex_execution_source
    assert "preferred_onemin_labels=preferred_onemin_labels_from_request(request)" in codex_execution_source
    assert "return current >= deadline_unix" in background_source
    assert "\"background_timeout_seconds\"" in background_source
    assert "visible_text=f\"Error: {failure_message}\"" in background_source
    assert "request_deadline_monotonic = time.monotonic() + background_timeout_seconds_for_response(" in background_orchestration_source
    assert "background_resume_count" in background_orchestration_source
    assert "background_response_replay_unavailable" in background_orchestration_source
    assert "stale_ids = [response_id for response_id, worker in background_response_workers.items() if not worker.is_alive()]" in background_workers_source
    assert "background_response_starting.add(response_id)" in background_workers_source
    assert "background_response_workers[response_id] = worker" in background_workers_source
    assert "postgres_response_repositories.get(database_url)" in persistence_source
    assert "response_record_repository(container=container).store(" in persistence_source
    assert "return response_record_repository(container=container).load(" in persistence_source
    assert "with background_response_transition_lock:" in persistence_source
    assert "def codex_status_response_payload(" in metadata_source
    assert "def provider_health_response_payload(" in execution_source
    assert "def models_response_payload(" in read_source
    assert "def response_read_payload(" in read_source
    assert "def response_input_items_payload(" in read_source
    assert "_STREAMING_ROUTE_RESPONSES = {" in source
    assert "_CORE_BATCH_ROUTE_RESPONSES = {" in source
    assert "_SURVIVAL_ROUTE_RESPONSES = {" in source
    assert "_RESPONSES_CREATE_REQUEST_OPENAPI_EXTRA = {" in source
    assert "_background_timeout_seconds_for_response = background_timeout_seconds_for_response" in source
    assert "_background_replay_payload = background_replay_payload" in source
    assert "_container_database_url = container_database_url" in source
    assert "cleanup_background_response_workers(" in source
    assert "return background_response_has_live_worker(" in source
    assert "return claim_background_response_worker_slot(" in source
    assert "register_background_response_worker(" in source
    assert "release_background_response_worker_slot(" in source
    assert "_spawn_background_codex_worker = build_spawn_background_codex_worker(" in source
    assert "_ensure_background_response_progress = build_ensure_background_response_progress(" in source
    assert "_load_response_for_runtime = build_load_response_for_runtime(" in source
    assert "def _background_failed_response(" in source
    assert "return background_failed_response(" in source
    assert "return response_record_repository(" in source
    assert "store_response(" in source
    assert "return load_response(" in source
    assert "return store_background_terminal_response(" in source
    assert "provider_registry = await provider_health_route_registry_payload(" in execution_source
    assert "return JSONResponse(\n            provider_health_response_payload(" in execution_source
    assert "return JSONResponse(\n            codex_profiles_response_payload(" in metadata_source
    assert "return JSONResponse(\n            codex_status_response_payload(" in metadata_source
    assert "return JSONResponse(\n            models_response_payload(" in read_source
    assert "return JSONResponse(\n            response_read_payload(" in read_source
    assert "return JSONResponse(\n            response_input_items_payload(" in read_source
    assert "normalized_payload = payload_with_request_trace_metadata(payload, request=request)" in execution_source
    assert "header_profile = header_codex_profile_from_request(request)" in execution_source
    assert "return await loop.run_in_executor(" in runtime_source
    assert "trace_metadata[\"ea_correlation_id\"] = correlation_id" in runtime_source
    assert "X-EA-Onemin-Preferred-Accounts" in runtime_source
    assert "upstream_unavailable:tool_shim_planner_timeout" in tool_runtime_source
    assert "tool_choice_type == \"none\"" in tool_runtime_source
    assert "\"read_mcp_resource\"" in tool_runtime_source
    assert "previous_response_in_progress" in planner_source
    assert "previous_response_failed" in planner_source
    assert "EA_TOOL_SHIM_TRANSCRIPT_MAX_CHARS" in planner_source
    assert "EA_TOOL_SHIM_TRANSCRIPT_PART_MAX_CHARS" in planner_source
    assert "EA_TOOL_SHIM_PLANNER_MODEL" in planner_source
    assert "operator-prepared readiness remedy context:" in prompt_source
    assert "operator-prepared gap audit context:" in prompt_source
    assert "operator-prepared gap fix context:" in prompt_source
    assert "Prepared repo context summary:" in prompt_compaction_source
    assert "Bootstrap context was already captured" in prompt_compaction_source
    assert "Live fleet snapshot:" in prompt_compaction_source
    assert "Do not inspect shard content, backlog artifacts" in operator_scope_source
    assert "Use `/docker/fleet` or `/docker/EA` targets only" in operator_scope_source
    assert "upstream_model=\"tool_shim_local\"" in output_runtime_source
    assert "\"right now\"" in output_runtime_source
    assert "\"how many \"" in output_runtime_source
    assert "def _finding_lines(" in probe_final_text_source
    assert "coverage_gap_keys" in probe_final_text_source
    assert "flagship_readiness" in probe_final_text_source
    assert "Published readiness proof is already materialized." in direct_final_runtime_source
    assert "Published the user-journey tester trace and reran the readiness audit." in direct_final_runtime_source
    assert "tool_shim_direct_staged_git_commit_push_final_text(" in direct_final_runtime_source
    assert "review_template_parity" in local_unblock_runtime_source
    assert "verify_ui_campaign_memory" in local_unblock_runtime_source
    assert "Completed local unblock task" in local_unblock_runtime_source
    assert "status --state-root /docker/fleet/state/chummer_design_supervisor --json" in local_fleet_runtime_source
    assert "eta --state-root /docker/fleet/state/chummer_design_supervisor --json" in local_fleet_runtime_source
    assert "\"fleet eta\"" in local_fleet_runtime_source
    assert "tool_shim_direct_file_read_command(" in staged_prompt_runtime_source
    assert "build_package_scope_search_command(text)" in staged_prompt_runtime_source
    assert "function_call_output" in staged_prompt_runtime_source
    assert "/__fleet_shard_runtime__/chummer_design_supervisor/" in command_history_runtime_source
    assert "if str(item.get(\"name\") or \"\").strip() != \"exec_command\":" in command_history_runtime_source
    assert "\"call_id\": call_id" in command_history_runtime_source
    assert "expected_probe" in command_history_runtime_source
    assert "git diff --cached --quiet" in staged_git_runtime_source
    assert "git rev-parse HEAD" in staged_git_runtime_source
    assert "Pushed commit {head_hash}" in staged_git_runtime_source
    assert "Package scope:" in package_scope_runtime_source
    assert "Allowed paths:" in package_scope_runtime_source
    assert "Edit these files first for this pass" in package_scope_runtime_source
    assert "house rule" in package_scope_runtime_source
    assert "git -C {quoted_worktree} status --short -- {quoted_paths}" in package_scope_runtime_source
    assert "rg -n -i -F -m 80" in package_scope_runtime_source
    assert "completed staged repo reads" in package_planner_runtime_source
    assert "tool_shim_package_planner_blocked" in package_planner_runtime_source
    assert "upstream_unavailable:planner_capacity_preflight:" in package_planner_runtime_source
    assert "gemini_vortex" in package_planner_runtime_source
    assert "git -C {quoted_root} status --short -- {quoted_paths}" in repo_followup_runtime_source
    assert "git -C {quoted_root} diff --unified=0 -- {quoted_paths} | sed -n '1,200p'" in repo_followup_runtime_source
    assert "/docker/fleet/scripts/codex-shims/codexea" in repo_followup_runtime_source
    assert "/docker/EA/ea/app/services/responses_upstream.py" in repo_followup_runtime_source
    assert "/docker/fleet/state/chummer_design_supervisor/ea_provider_health_cache.json" in telemetry_runtime_source
    assert "\"TASK_LOCAL_TELEMETRY.generated.json\"" in telemetry_runtime_source
    assert "\"source_paths\"" in telemetry_runtime_source
    assert "sed -n '293,355p;680,780p'" in telemetry_runtime_source
    assert "[... omitted for compact audit transport ...]" in transcript_source
    assert "Assistant tool call" in transcript_source
    assert "Tool output (" in transcript_source
    assert "streaming_route_responses=_STREAMING_ROUTE_RESPONSES" in source
    assert "route_specs=_CODEX_PROFILE_ROUTE_SPECS" in source
    assert "request_openapi_extra=_RESPONSES_CREATE_REQUEST_OPENAPI_EXTRA" in source
    assert "_run_profiled_codex_response = build_run_profiled_codex_response(" in source
    assert "_run_response_in_executor = build_run_response_in_executor(" in source
    assert "_generate_upstream_text = lambda **kwargs: generate_upstream_text(" in source
    assert "_tool_shim_generate_upstream_text_with_timeout = build_tool_shim_generate_upstream_text_with_timeout(" in source
    assert "_response_tools = response_tools" in source
    assert "_tool_choice_disables_tools = tool_choice_disables_tools" in source
    assert "_tool_shim_supported_tools = build_tool_shim_supported_tools(" in source
    assert "_history_items_for_request = lambda **kwargs: history_items_for_request(" in source
    assert "_tool_shim_transcript_max_chars = tool_shim_transcript_max_chars" in source
    assert "_tool_shim_transcript_part_max_chars = tool_shim_transcript_part_max_chars" in source
    assert "_tool_shim_planner_model = build_tool_shim_planner_model(" in source
    assert "_tool_shim_planner_max_output_tokens = tool_shim_planner_max_output_tokens" in source
    assert "_tool_shim_planner_deadline_monotonic = build_tool_shim_planner_deadline_monotonic(" in source
    assert "_tool_shim_is_staged_local_orientation_prompt = tool_shim_is_staged_local_orientation_prompt" in source
    assert "_tool_shim_is_operator_fleet_unblock_prompt = tool_shim_is_operator_fleet_unblock_prompt" in source
    assert "_tool_shim_is_package_work_prompt = tool_shim_is_package_work_prompt" in source
    assert "_tool_shim_is_operator_readiness_remedy_prompt = tool_shim_is_operator_readiness_remedy_prompt" in source
    assert "_tool_shim_is_operator_gap_audit_prompt = tool_shim_is_operator_gap_audit_prompt" in source
    assert "_tool_shim_is_operator_gap_fix_prompt = tool_shim_is_operator_gap_fix_prompt" in source
    assert "_tool_shim_transcript_limit_for_prompt = build_tool_shim_transcript_limit_for_prompt(" in source
    assert "_tool_shim_compact_operator_prompt_for_planner = build_tool_shim_compact_operator_prompt_for_planner(" in source
    assert "_tool_shim_compact_readiness_prompt_for_planner = build_tool_shim_compact_readiness_prompt_for_planner(" in source
    assert "_tool_shim_is_operator_fleet_unblock_context = build_tool_shim_is_operator_fleet_unblock_context(" in source
    assert (
        "_tool_shim_operator_unblock_scope_rejection_reason = build_tool_shim_operator_unblock_scope_rejection_reason("
        in source
    )
    assert "_tool_shim_unwrap_tool_output_envelope = tool_shim_unwrap_tool_output_envelope" in source
    assert "_tool_shim_latest_function_output = build_tool_shim_latest_function_output(" in source
    assert "_tool_shim_requires_immediate_tool = build_tool_shim_requires_immediate_tool(" in source
    assert "_tool_shim_local_upstream_result = build_tool_shim_local_upstream_result(" in source
    assert "_tool_shim_scalar_text = tool_shim_scalar_text" in source
    assert "_tool_shim_gap_audit_final_text = tool_shim_gap_audit_final_text" in source
    assert "_tool_shim_ui_parity_audit_final_text = tool_shim_ui_parity_audit_final_text" in source
    assert "_tool_shim_parity_build_final_text = tool_shim_parity_build_final_text" in source
    assert "_tool_shim_gap_fix_final_text = tool_shim_gap_fix_final_text" in source
    assert "_tool_shim_direct_final_text = build_tool_shim_direct_final_text(" in source
    assert "_tool_shim_local_unblock_command_for_prompt = tool_shim_local_unblock_command_for_prompt" in source
    assert "_tool_shim_direct_local_unblock_command = build_tool_shim_direct_local_unblock_command(" in source
    assert "_tool_shim_local_unblock_final_text = tool_shim_local_unblock_final_text" in source
    assert "_tool_shim_staged_first_command_max_output_tokens = build_tool_shim_staged_first_command_max_output_tokens(" in source
    assert "_tool_shim_direct_local_fleet_command = build_tool_shim_direct_local_fleet_command(" in source
    assert "_tool_shim_has_tool_history = tool_shim_has_tool_history" in source
    assert "_tool_shim_staged_commands = build_tool_shim_staged_commands(" in source
    assert "_tool_shim_direct_file_read_command = tool_shim_direct_file_read_command" in source
    assert "_tool_shim_looks_like_shell_command = tool_shim_looks_like_shell_command" in source
    assert "_tool_shim_resolve_equivalent_shard_runtime_path = tool_shim_resolve_equivalent_shard_runtime_path" in source
    assert "_tool_shim_normalize_equivalent_command_paths = tool_shim_normalize_equivalent_command_paths" in source
    assert "_tool_shim_exec_command_history = tool_shim_exec_command_history" in source
    assert "_tool_shim_exec_command_identity_history = build_tool_shim_exec_command_identity_history(" in source
    assert "_tool_shim_command_identity_sequence = build_tool_shim_command_identity_sequence(" in source
    assert "_tool_shim_exec_command_expanded_sequence = build_tool_shim_exec_command_expanded_sequence(" in source
    assert "_tool_shim_command_sequence_executed = build_tool_shim_command_sequence_executed(" in source
    assert "_tool_shim_exec_command_output_history = build_tool_shim_exec_command_output_history(" in source
    assert "_tool_shim_latest_exec_json_output = build_tool_shim_latest_exec_json_output(" in source
    assert "_tool_shim_latest_exec_json_output_for_command = build_tool_shim_latest_exec_json_output_for_command(" in source
    assert "_tool_shim_is_git_command = tool_shim_is_git_command" in source
    assert "_tool_shim_is_staged_git_commit_push_workflow = build_tool_shim_is_staged_git_commit_push_workflow(" in source
    assert "_tool_shim_build_staged_git_commit_push_command = build_tool_shim_build_staged_git_commit_push_command(" in source
    assert "_tool_shim_extract_git_head_hash = tool_shim_extract_git_head_hash" in source
    assert "_tool_shim_direct_staged_git_commit_push_final_text = build_tool_shim_direct_staged_git_commit_push_final_text(" in source
    assert "_tool_shim_package_scope_text = tool_shim_package_scope_text" in source
    assert "_tool_shim_bulleted_section_paths = tool_shim_bulleted_section_paths" in source
    assert "_tool_shim_active_slice_followup_paths = build_tool_shim_active_slice_followup_paths(" in source
    assert "_tool_shim_package_current_slice_text = tool_shim_package_current_slice_text" in source
    assert "_tool_shim_package_worktree = tool_shim_package_worktree" in source
    assert "_tool_shim_package_allowed_scope_tokens = tool_shim_package_allowed_scope_tokens" in source
    assert "_tool_shim_package_allowed_scope_paths = build_tool_shim_package_allowed_scope_paths(" in source
    assert "_tool_shim_package_scope_pathspecs = build_tool_shim_package_scope_pathspecs(" in source
    assert "_tool_shim_build_package_scope_repo_diff_command = build_tool_shim_build_package_scope_repo_diff_command(" in source
    assert "_tool_shim_build_package_scope_repo_hunks_command = build_tool_shim_build_package_scope_repo_hunks_command(" in source
    assert "_tool_shim_package_scope_search_terms = build_tool_shim_package_scope_search_terms(" in source
    assert "_tool_shim_build_package_scope_search_command = build_tool_shim_build_package_scope_search_command(" in source
    assert "_tool_shim_package_planner_blocked_final_text = build_tool_shim_package_planner_blocked_final_text(" in source
    assert "_tool_shim_package_planner_blocked_decision = build_tool_shim_package_planner_blocked_decision(" in source
    assert "_tool_shim_provider_row_is_ready = tool_shim_provider_row_is_ready" in source
    assert "_tool_shim_provider_row_is_dispatchable = build_tool_shim_provider_row_is_dispatchable(" in source
    assert "_tool_shim_package_planner_preflight_failure_message = build_tool_shim_package_planner_preflight_failure_message(" in source
    assert "_tool_shim_build_repo_diff_command_for_paths = build_tool_shim_build_repo_diff_command_for_paths(" in source
    assert "_tool_shim_build_staged_repo_diff_command = build_tool_shim_build_staged_repo_diff_command(" in source
    assert "_tool_shim_build_repo_hunks_command_for_paths = build_tool_shim_build_repo_hunks_command_for_paths(" in source
    assert "_tool_shim_build_staged_repo_hunks_command = build_tool_shim_build_staged_repo_hunks_command(" in source
    assert "_tool_shim_operator_unblock_repo_diff_command = build_tool_shim_operator_unblock_repo_diff_command(" in source
    assert "_tool_shim_operator_unblock_repo_hunks_command = build_tool_shim_operator_unblock_repo_hunks_command(" in source
    assert "_tool_shim_direct_compact_provider_health_command = tool_shim_direct_compact_provider_health_command" in source
    assert "_tool_shim_operator_unblock_provider_health_command = build_tool_shim_operator_unblock_provider_health_command(" in source
    assert "_tool_shim_operator_unblock_live_routing_hotspots_command = tool_shim_operator_unblock_live_routing_hotspots_command" in source
    assert "_tool_shim_telemetry_followup_commands = build_tool_shim_telemetry_followup_commands(" in source
    assert "_tool_shim_recent_nested_telemetry_commands = build_tool_shim_recent_nested_telemetry_commands(" in source
    assert "_tool_shim_direct_nested_telemetry_first_command = build_tool_shim_direct_nested_telemetry_first_command(" in source
    assert "_tool_shim_truncate_text = tool_shim_truncate_text" in source
    assert "_tool_shim_tool_parameters_summary = tool_shim_tool_parameters_summary" in source
    assert "_history_item_to_transcript = build_history_item_to_transcript(" in source
    assert "_tool_shim_latest_user_text = build_tool_shim_latest_user_text(" in source
    assert "_tool_shim_latest_package_work_prompt = build_tool_shim_latest_package_work_prompt(" in source
    assert 'models_router.add_api_route(\n        "",' in registration_source
    assert 'responses_item_router.add_api_route(\n        "/_provider_health",' in registration_source
    assert 'responses_item_router.add_api_route(\n        "/{response_id}",' in registration_source
    assert 'responses_item_router.add_api_route(\n        "/{response_id}/input_items",' in registration_source
    assert 'responses_item_router.add_api_route(\n        "",' in registration_source
    assert "module_globals[route_name] = route" in registration_source
    assert "codex_router.add_api_route(" in registration_source
    assert "list_codex_profiles.__name__ = \"list_codex_profiles\"" in metadata_source
    assert "get_codex_status.__name__ = \"get_codex_status\"" in metadata_source
    assert "get_provider_health.__name__ = \"get_provider_health\"" in execution_source
    assert "create_response.__name__ = \"create_response\"" in execution_source
    assert "list_models.__name__ = \"list_models\"" in read_source
    assert "get_response.__name__ = \"get_response\"" in read_source
    assert "get_response_input_items.__name__ = \"get_response_input_items\"" in read_source
