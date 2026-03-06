from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_db_size_help_explains_pgdata_volume() -> None:
    result = subprocess.run(
        ["bash", "scripts/db_size.sh", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "ea_pgdata" in result.stdout
    assert "/var/lib/postgresql/data" in result.stdout
    assert "not RAM" in result.stdout


def test_docs_explain_pgdata_volume_usage() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")

    assert "ea_pgdata" in readme
    assert "/var/lib/postgresql/data" in readme
    assert "not RAM" in readme

    assert "ea_pgdata" in runbook
    assert "/var/lib/postgresql/data" in runbook
    assert "not RAM" in runbook


def test_milestone_uses_status_model_and_release_tags() -> None:
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert set(milestone["status_model"]) == {"planned", "coded", "wired", "tested", "released"}
    assert "ci_gate_bundle" in milestone["release_tags"]
    assert "release_preflight_bundle" in milestone["release_tags"]
    assert "docs_verify_alias" in milestone["release_tags"]


def test_support_bundle_help_mentions_db_volume_attribution() -> None:
    result = subprocess.run(
        ["bash", "scripts/support_bundle.sh", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "SUPPORT_INCLUDE_DB_VOLUME=0|1" in result.stdout


def test_version_info_reports_milestone_status_counts() -> None:
    result = subprocess.run(
        ["bash", "scripts/version_info.sh"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "milestone_status_counts=planned:" in result.stdout
    assert "milestone_release_tags=ci_gate_bundle" in result.stdout


def test_postgres_contract_script_help_and_wiring() -> None:
    result = subprocess.run(
        ["bash", "scripts/test_postgres_contracts.sh", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    workflow = (ROOT / ".github/workflows/smoke-runtime.yml").read_text(encoding="utf-8")
    smoke_help = (ROOT / "scripts/smoke_help.sh").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    script = (ROOT / "scripts/test_postgres_contracts.sh").read_text(encoding="utf-8")

    assert "EA_TEST_POSTGRES_DB" in result.stdout
    assert "scripts/test_postgres_contracts.sh" in smoke_help
    assert "test-postgres-contracts:" in makefile
    assert "bash scripts/test_postgres_contracts.sh" in workflow
    assert "tests/test_postgres_contract_matrix_integration.py" in script


def test_policy_docs_and_milestone_cover_external_action_evaluation() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "/v1/policy/evaluate" in readme
    assert "/v1/policy/evaluate" in runbook
    assert "/v1/policy/evaluate" in http_examples

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "external_action_policy_api_exposure")
    assert capability["status"] == "tested"


def test_artifact_lookup_docs_and_milestone_cover_direct_fetch() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "/v1/rewrite/artifacts/{artifact_id}" in readme
    assert "/v1/rewrite/artifacts/{artifact_id}" in runbook
    assert "/v1/rewrite/artifacts/{{artifact_id}}" in http_examples
    assert "/v1/rewrite/artifacts/${ARTIFACT_ID}" in smoke_api

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "artifact_lookup_api_exposure")
    assert capability["status"] == "tested"


def test_receipt_and_run_cost_lookup_docs_and_milestone_cover_direct_fetch() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "/v1/rewrite/receipts/{receipt_id}" in readme
    assert "/v1/rewrite/run-costs/{cost_id}" in readme
    assert "/v1/rewrite/receipts/{receipt_id}" in runbook
    assert "/v1/rewrite/run-costs/{cost_id}" in runbook
    assert "/v1/rewrite/receipts/{{receipt_id}}" in http_examples
    assert "/v1/rewrite/run-costs/{{cost_id}}" in http_examples
    assert "/v1/rewrite/receipts/${RECEIPT_ID}" in smoke_api
    assert "/v1/rewrite/run-costs/${COST_ID}" in smoke_api

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "receipt_and_run_cost_lookup_api_exposure"
    )
    assert capability["status"] == "tested"


def test_approval_resume_docs_and_milestone_cover_inline_completion() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "resumes execution inline" in readme
    assert "resumes execution immediately" in runbook
    assert "approve and resume execution" in http_examples
    assert "approval resume path ok" in smoke_api

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "approval_resume_execution")
    assert capability["status"] == "tested"


def test_execution_queue_docs_and_milestone_cover_runtime_path() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    db_bootstrap = (ROOT / "scripts/db_bootstrap.sh").read_text(encoding="utf-8")
    db_status = (ROOT / "scripts/db_status.sh").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_postgres = (ROOT / "scripts/smoke_postgres.sh").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "execution_queue" in readme
    assert "execution_queue" in runbook
    assert "v0_23 execution queue kernel" in db_bootstrap
    assert "execution_queue" in db_status
    assert "queue_items" in smoke_api
    assert "execution_queue" in smoke_postgres

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "execution_queue_inline_worker")
    assert capability["status"] == "tested"
    assert "ea/schema/20260305_v0_23_execution_queue_kernel.sql" in milestone["migrations"]


def test_runtime_mode_docs_and_smoke_cover_prod_fail_fast_storage() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    env_matrix = (ROOT / "ENVIRONMENT_MATRIX.md").read_text(encoding="utf-8")
    smoke_postgres = (ROOT / "scripts/smoke_postgres.sh").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "EA_RUNTIME_MODE=dev|test|prod" in readme
    assert "EA_RUNTIME_MODE=prod" in readme
    assert "EA_RUNTIME_MODE=prod" in runbook
    assert "EA_RUNTIME_MODE" in env_matrix
    assert "prod fail-fast path ok" in smoke_postgres

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "runtime_mode_fail_fast_storage")
    assert capability["status"] == "tested"


def test_human_task_docs_and_milestone_cover_session_linked_packets() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    db_bootstrap = (ROOT / "scripts/db_bootstrap.sh").read_text(encoding="utf-8")
    db_status = (ROOT / "scripts/db_status.sh").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "/v1/human/tasks" in readme
    assert "human task packets" in readme
    assert "human_task_returned" in readme
    assert "resume_session_on_return=true" in readme

    assert "/v1/human/tasks" in runbook
    assert "human_task_created" in runbook
    assert "human_task_returned" in runbook
    assert "awaiting_human" in runbook

    assert "/v1/human/tasks/{{human_task_id}}/return" in http_examples
    assert "role_required=communications_reviewer&overdue_only=true" in http_examples
    assert "assigned_operator_id=operator&status=claimed" in http_examples
    assert "/v1/human/tasks/backlog?role_required=communications_reviewer&overdue_only=true&limit=20" in http_examples
    assert "/v1/human/tasks/unassigned?role_required=communications_reviewer&overdue_only=true&limit=20" in http_examples
    assert "/v1/human/tasks/mine?operator_id=operator&limit=20" in http_examples
    assert "/v1/human/tasks/{{human_task_id}}/assign" in http_examples
    assert "assignment_state=assigned&limit=20" in http_examples
    assert "\"resume_session_on_return\": true" in http_examples

    assert "v0_24 human tasks kernel" in db_bootstrap
    assert "v0_25 human task resume kernel" in db_bootstrap
    assert "v0_26 human task assignment-state kernel" in db_bootstrap
    assert "human_tasks" in db_status

    assert "human tasks ok" in smoke_api
    assert "awaiting_human|True|True" in smoke_api
    assert "role/overdue human task queue filter" in smoke_api
    assert "assigned-operator human task queue filter" in smoke_api
    assert "human task backlog endpoint" in smoke_api
    assert "human task mine endpoint" in smoke_api
    assert "pre-assigned task" in smoke_api
    assert "human task unassigned endpoint" in smoke_api
    assert "assigned-only backlog endpoint" in smoke_api
    assert "/v1/human/tasks" in smoke_api
    assert "test_human_task_flow_and_session_projection" in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_packets_kernel")
    assert capability["status"] == "tested"


def test_human_task_review_contract_metadata_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    planner_test = (ROOT / "tests/test_planner.py").read_text(encoding="utf-8")
    postgres_matrix = (ROOT / "tests/test_postgres_contract_matrix_integration.py").read_text(encoding="utf-8")
    db_bootstrap = (ROOT / "scripts/db_bootstrap.sh").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "human_review_authority_required" in readme
    assert "human_review_why_human" in readme
    assert "human_review_quality_rubric_json" in readme
    assert "human_review_authority_required" in runbook
    assert "human_review_why_human" in runbook
    assert "human_review_quality_rubric_json" in runbook
    assert "send_on_behalf_review" in smoke_api
    assert "External executive communication needs human tone review." in smoke_api
    assert 'review_task["authority_required"] == "send_on_behalf_review"' in smoke_runtime
    assert "quality_rubric_json" in smoke_runtime
    assert "human_review_authority_required" in planner_test
    assert "human_review_quality_rubric_json" in planner_test
    assert 'authority_required="send_on_behalf_review"' in postgres_matrix
    assert "v0_27 human task review contract kernel" in db_bootstrap

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_review_contract_metadata")
    assert capability["status"] == "tested"


def test_operator_profile_specialized_backlog_routing_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    postgres_matrix = (ROOT / "tests/test_postgres_contract_matrix_integration.py").read_text(encoding="utf-8")
    db_bootstrap = (ROOT / "scripts/db_bootstrap.sh").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "/v1/human/tasks/operators" in readme
    assert "skill-tag" in readme
    assert "/v1/human/tasks/operators" in runbook
    assert "operator_id=<id>" in runbook
    assert "operator-specialist" in smoke_api
    assert "operator-specialized backlog endpoint" in smoke_api
    assert "operator-specialized backlog endpoint to exclude" in smoke_api
    assert '"/v1/human/tasks/operators"' in smoke_runtime
    assert "operator-specialist" in smoke_runtime
    assert "test_postgres_operator_profiles_upsert_get_and_list" in postgres_matrix
    assert "v0_28 operator profiles kernel" in db_bootstrap

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "operator_profile_specialized_backlog_routing"
    )
    assert capability["status"] == "tested"
    resume_capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_pause_resume_session_flow"
    )
    assert resume_capability["status"] == "tested"
    filter_capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_operator_queue_filters"
    )
    assert filter_capability["status"] == "tested"
    backlog_capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_operator_backlog_endpoints"
    )
    assert backlog_capability["status"] == "tested"
    assignment_capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_operator_assignment"
    )
    assert assignment_capability["status"] == "tested"
    visibility_capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_assignment_state_visibility"
    )
    assert visibility_capability["status"] == "tested"
    assert "human_task_assignment_state_field" in visibility_capability["scope"]
    assert "claimed_and_returned_assignment_projection" in visibility_capability["scope"]
    assert "ea/schema/20260305_v0_26_human_task_assignment_state.sql" in milestone["migrations"]


def test_human_task_operator_assignment_hints_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    rewrite_route = (ROOT / "ea/app/api/routes/rewrite.py").read_text(encoding="utf-8")
    human_route = (ROOT / "ea/app/api/routes/human.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "routing_hints_json" in readme
    assert "auto_assign_operator_id" in readme
    assert "routing_hints_json" in runbook
    assert "auto_assign_operator_id" in runbook
    assert "operator auto-assignment hint" in smoke_api
    assert "routing_hints_json" in smoke_runtime
    assert "auto_assign_operator_id" in smoke_runtime
    assert "routing_hints_json: dict[str, object]" in rewrite_route
    assert "routing_hints_json: dict[str, object]" in human_route

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_operator_assignment_hints")
    assert capability["status"] == "tested"
    assert "suggested_operator_ids" in capability["scope"]
    assert "auto_assign_operator_id" in capability["scope"]


def test_human_task_recommended_assignment_action_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    human_route = (ROOT / "ea/app/api/routes/human.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "/v1/human/tasks/{human_task_id}/assign" in readme
    assert "omits `operator_id`" in readme
    assert "auto_assign_operator_id" in runbook
    assert "omits `operator_id`" in runbook
    assert "-d '{}'" in smoke_api
    assert "pending|assigned|operator-specialist" in smoke_api
    assert 'json={}' in smoke_runtime
    assert 'assigned.json()["assigned_operator_id"] == "operator-specialist"' in smoke_runtime
    assert "human_task_no_auto_assign_candidate" in human_route

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_recommended_assignment_action"
    )
    assert capability["status"] == "tested"
    assert "auto_assign_operator_id_consumption" in capability["scope"]


def test_milestone_marks_postgres_contract_matrix_tested() -> None:
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))
    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "postgres_contract_matrix")

    assert capability["status"] == "tested"


def test_principal_scoped_memory_seed_surface_is_tested_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "/v1/memory/candidates" in readme
    assert "/v1/memory/stakeholders" in readme
    assert "/v1/memory/interruption-budgets" in readme

    assert "/v1/memory/candidates" in runbook
    assert "/v1/memory/stakeholders" in runbook
    assert "/v1/memory/interruption-budgets" in runbook

    assert "/v1/memory/candidates" in smoke_api
    assert "/v1/memory/stakeholders" in smoke_api
    assert "/v1/memory/interruption-budgets" in smoke_api

    assert "test_memory_candidate_promotion_flow" in smoke_runtime
    assert "test_memory_stakeholders_principal_scope_flow" in smoke_runtime
    assert "test_memory_interruption_budgets_principal_scope_flow" in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "principal_scoped_memory_seed_apis")
    assert capability["status"] == "tested"


def test_principal_request_context_guardrails_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    env_matrix = (ROOT / "ENVIRONMENT_MATRIX.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "X-EA-Principal-ID" in readme
    assert "EA_DEFAULT_PRINCIPAL_ID" in readme
    assert "principal_scope_mismatch" in readme

    assert "X-EA-Principal-ID" in runbook
    assert "EA_DEFAULT_PRINCIPAL_ID" in runbook
    assert "principal_scope_mismatch" in runbook

    assert "EA_DEFAULT_PRINCIPAL_ID" in env_matrix

    assert "X-EA-Principal-ID" in http_examples
    assert "principal_scope_mismatch" in http_examples

    assert "X-EA-Principal-ID" in smoke_api
    assert "principal_scope_mismatch" in smoke_api

    assert "test_tool_registry_and_connector_bindings_flow" in smoke_runtime
    assert "test_memory_routes_use_default_principal_when_header_and_body_are_omitted" in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "principal_request_context_guardrails")
    assert capability["status"] == "tested"


def test_typed_step_handler_gateway_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    planner_test = (ROOT / "tests/test_planner.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "step_input_prepare" in readme
    assert "step_policy_evaluate" in readme
    assert "step_artifact_save" in readme
    assert "step_input_prepare" in runbook
    assert "step_policy_evaluate" in runbook
    assert "step_artifact_save" in runbook
    assert "step_input_prepare" in smoke_api
    assert "step_policy_evaluate" in smoke_api
    assert "input_prepared" in smoke_api
    assert "policy_step_completed" in smoke_api
    assert "step_input_prepare" in smoke_runtime
    assert "step_policy_evaluate" in smoke_runtime
    assert "input_prepared" in smoke_runtime
    assert "policy_step_completed" in smoke_runtime
    assert "step_input_prepare" in planner_test
    assert "step_policy_evaluate" in planner_test

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "typed_step_handler_gateway")
    assert capability["status"] == "tested"
    planner_capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "planner_dependency_graph_projection"
    )
    assert planner_capability["status"] == "tested"


def test_planner_human_task_branch_projection_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    planner_test = (ROOT / "tests/test_planner.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "human_review_role" in readme
    assert "step_human_review" in readme
    assert "human_review_role" in runbook
    assert "step_human_review" in runbook
    assert "rewrite_review" in smoke_api
    assert "communications_reviewer" in smoke_api
    assert "step_human_review" in smoke_runtime
    assert "communications_review" in smoke_runtime
    assert "human_review_role" in planner_test
    assert "step_human_review" in planner_test

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "planner_human_task_branch_projection"
    )
    assert capability["status"] == "tested"


def test_runtime_human_task_step_execution_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "202 awaiting_human" in runbook
    assert "awaiting_human" in readme
    assert "compiled human review runtime ok" in smoke_api
    assert "awaiting_human|poll_or_subscribe|True|" in smoke_api
    assert "test_rewrite_compiled_human_review_branch_pauses_and_resumes" in smoke_runtime
    assert "human_task_step_started" in smoke_runtime

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "runtime_human_task_step_execution"
    )
    assert capability["status"] == "tested"


def test_human_review_payload_artifact_override_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "returned_payload_json.final_text" in readme
    assert "final_text" in runbook
    assert "edited by reviewer" in smoke_api
    assert 'body_after["artifacts"][0]["content"]' in smoke_runtime

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_review_payload_artifact_override"
    )
    assert capability["status"] == "tested"


def test_planner_human_review_operational_metadata_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    planner_test = (ROOT / "tests/test_planner.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "human_review_priority" in readme
    assert "human_review_sla_minutes" in readme
    assert "human_review_desired_output_json" in readme
    assert "human_review_priority" in runbook
    assert "human_review_sla_minutes" in runbook
    assert "human_review_desired_output_json" in runbook
    assert "manager_review" in smoke_api
    assert "high|45|manager_review" in smoke_api
    assert 'review_task["priority"] == "high"' in smoke_runtime
    assert 'review_task["desired_output_json"]["escalation_policy"] == "manager_review"' in smoke_runtime
    assert "human_review_sla_minutes" in planner_test
    assert 'desired_output_json["escalation_policy"] == "manager_review"' in planner_test

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "planner_human_review_operational_metadata"
    )
    assert capability["status"] == "tested"


def test_registry_backed_tool_execution_service_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "ToolExecutionService" in readme
    assert "tool.v1" in readme
    assert "ToolExecutionService" in runbook
    assert "tool.v1" in runbook
    assert "artifact_repository|tool.v1" in smoke_api
    assert "tool_execution_completed" in smoke_api
    assert "artifact_repository" in smoke_runtime
    assert "tool_execution_completed" in smoke_runtime
    assert "invocation_contract" in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "registry_backed_tool_execution_service")
    assert capability["status"] == "tested"


def test_connector_dispatch_tool_execution_slice_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    tool_execution_tests = (ROOT / "tests/test_tool_execution.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "/v1/tools/execute" in readme
    assert "connector.dispatch" in readme
    assert "/v1/tools/execute" in runbook
    assert "connector.dispatch" in runbook
    assert "/v1/tools/execute" in http_examples
    assert "connector.dispatch" in http_examples
    assert "connector.dispatch|queued|" in smoke_api
    assert "connector.dispatch|tool.v1" in smoke_api
    assert "connector.dispatch" in smoke_runtime
    assert "/v1/tools/execute" in smoke_runtime
    assert "test_tool_execution_service_executes_builtin_connector_dispatch_handler" in tool_execution_tests

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "connector_dispatch_tool_execution_slice")
    assert capability["status"] == "tested"


def test_connector_dispatch_binding_scope_guardrails_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    tool_execution_tests = (ROOT / "tests/test_tool_execution.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "enabled connector binding" in readme
    assert "principal scope" in runbook
    assert "\"binding_id\"" in http_examples
    assert "principal_scope_mismatch" in smoke_api
    assert "binding_id" in smoke_api
    assert "execute_mismatch" in smoke_runtime
    assert "binding_id" in smoke_runtime
    assert "test_tool_execution_service_rejects_foreign_connector_binding_scope" in tool_execution_tests

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "connector_dispatch_binding_scope_guardrails")
    assert capability["status"] == "tested"


def test_approval_async_acceptance_contract_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "202 Accepted" in readme
    assert "awaiting_approval" in readme
    assert "202 awaiting_approval" in runbook
    assert "poll_or_subscribe" in runbook
    assert "expected 202 for approval-required path" in smoke_api
    assert "awaiting_approval|poll_or_subscribe" in smoke_api
    assert "assert create.status_code == 202" in smoke_runtime
    assert "next_action" in smoke_runtime
    assert "approval-required acceptance contract" in http_examples

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "approval_async_acceptance_contract")
    assert capability["status"] == "tested"
