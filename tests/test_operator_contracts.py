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


def test_planner_human_task_auto_preselection_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    planner_test = (ROOT / "tests/test_planner.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "human_review_auto_assign_if_unique" in readme
    assert "human_review_auto_assign_if_unique" in runbook
    assert "human_review_auto_assign_if_unique" in smoke_api
    assert "assigned|operator-specialist" in smoke_api
    assert "human_review_auto_assign_if_unique" in smoke_runtime
    assert 'review_task["assignment_state"] == "assigned"' in smoke_runtime
    assert 'review_task["assigned_operator_id"] == "operator-specialist"' in smoke_runtime
    assert "human_review_auto_assign_if_unique" in planner_test
    assert "auto_assign_if_unique is True" in planner_test

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "planner_human_task_auto_preselection")
    assert capability["status"] == "tested"
    assert "plan_step_auto_assign_projection" in capability["scope"]
    assert "runtime_human_task_auto_assignment" in capability["scope"]


def test_human_task_assignment_source_visibility_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    postgres_matrix = (ROOT / "tests/test_postgres_contract_matrix_integration.py").read_text(encoding="utf-8")
    db_bootstrap = (ROOT / "scripts/db_bootstrap.sh").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "assignment_source" in readme
    assert "assignment_source" in runbook
    assert "assignment_source" in smoke_api
    assert "operator-specialist|recommended" in smoke_api
    assert "operator-junior|manual" in smoke_api
    assert "auto_preselected" in smoke_api
    assert 'task["assignment_source"] == ""' in smoke_runtime
    assert 'assigned.json()["assignment_source"] == "recommended"' in smoke_runtime
    assert 'review_task["assignment_source"] == "auto_preselected"' in smoke_runtime
    assert 'assignment_source="manual"' in postgres_matrix
    assert "v0_29 human task assignment-source kernel" in db_bootstrap

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_assignment_source_visibility"
    )
    assert capability["status"] == "tested"
    assert "manual_recommended_auto_preselected_labels" in capability["scope"]
    assert "ea/schema/20260305_v0_29_human_task_assignment_source.sql" in milestone["migrations"]


def test_human_task_assignment_provenance_fields_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    postgres_matrix = (ROOT / "tests/test_postgres_contract_matrix_integration.py").read_text(encoding="utf-8")
    db_bootstrap = (ROOT / "scripts/db_bootstrap.sh").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "assigned_at" in readme
    assert "assigned_by_actor_id" in readme
    assert "assigned_at" in runbook
    assert "assigned_by_actor_id" in runbook
    assert "assigned_by_actor_id" in smoke_api
    assert "orchestrator:auto_preselected" in smoke_api
    assert 'task["assigned_by_actor_id"] == ""' in smoke_runtime
    assert 'assigned.json()["assigned_by_actor_id"] == "exec-1"' in smoke_runtime
    assert 'review_task["assigned_by_actor_id"] == "orchestrator:auto_preselected"' in smoke_runtime
    assert 'assigned_by_actor_id="principal-1"' in postgres_matrix
    assert 'assigned_by_actor_id == "operator-1"' in postgres_matrix
    assert "v0_30 human task assignment provenance kernel" in db_bootstrap

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_assignment_provenance_fields"
    )
    assert capability["status"] == "tested"
    assert "assignment_provenance_event_payloads" in capability["scope"]
    assert "ea/schema/20260305_v0_30_human_task_assignment_provenance.sql" in milestone["migrations"]


def test_human_task_assignment_history_api_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "/v1/human/tasks/{human_task_id}/assignment-history" in readme
    assert "/v1/human/tasks/{human_task_id}/assignment-history" in runbook
    assert "assignment history (includes originating task_key and deliverable_type)" in http_examples
    assert "/v1/human/tasks/${HUMAN_TASK_ID}/assignment-history" in smoke_api
    assert "human_task_created,human_task_assigned,human_task_assigned,human_task_claimed,human_task_returned" in smoke_api
    assert '/assignment-history", params={"limit": 10}' in smoke_runtime
    assert 'all(row["task_key"] == "rewrite_text" for row in history_rows)' in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_assignment_history_api")
    assert capability["status"] == "tested"
    assert "ledger_backed_reassignment_audit" in capability["scope"]


def test_human_task_assignment_history_task_identity_projection_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "assignment-history` exposes task-scoped ownership transitions, now carries originating task identity too" in readme
    assert "those direct history rows now also carry originating `task_key`/`deliverable_type`" in runbook
    assert "assignment history (includes originating task_key and deliverable_type)" in http_examples
    assert "GENERIC_HUMAN_HISTORY_FIELDS" in smoke_api
    assert 'review_history.json()[0]["task_key"] == "stakeholder_briefing_review"' in smoke_runtime

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_assignment_history_task_identity_projection"
    )
    assert capability["status"] == "tested"


def test_session_human_task_assignment_history_projection_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "human_task_assignment_history" in readme
    assert "human_task_assignment_history" in runbook
    assert "human_task_assignment_history" in smoke_api
    assert 'body["human_task_assignment_history"] == []' in smoke_runtime
    assert 'session_body["human_task_assignment_history"]' in smoke_runtime
    assert 'body["human_task_assignment_history"][1]["assignment_source"] == "auto_preselected"' in smoke_runtime

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "session_human_task_assignment_history_projection"
    )
    assert capability["status"] == "tested"


def test_session_human_task_assignment_history_task_identity_projection_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "inline human-task assignment-history rows now carry originating task identity" in readme
    assert "assignment-history rows now also carry originating `task_key`/`deliverable_type`" in runbook
    assert "human-task assignment-history rows include originating task_key and deliverable_type" in http_examples
    assert "GENERIC_HUMAN_SESSION_HISTORY_FIELDS" in smoke_api
    assert 'review_session_body["human_task_assignment_history"][0]["task_key"] == "stakeholder_briefing_review"' in smoke_runtime

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "session_human_task_assignment_history_task_identity_projection"
    )
    assert capability["status"] == "tested"


def test_session_human_task_packet_task_identity_projection_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "inline human-task packet rows now carry originating task identity" in readme
    assert "inline `human_tasks` rows now also carry originating `task_key`/`deliverable_type`" in runbook
    assert "human-task packet, and human-task assignment-history rows include originating task_key and deliverable_type" in http_examples
    assert "GENERIC_HUMAN_SESSION_TASK_FIELDS" in smoke_api
    assert 'review_session_body["human_tasks"][0]["task_key"] == "stakeholder_briefing_review"' in smoke_runtime

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "session_human_task_packet_task_identity_projection"
    )
    assert capability["status"] == "tested"
    assert "generic_session_human_task_identity" in capability["scope"]


def test_human_task_assignment_history_filters_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "assigned_operator_id" in readme
    assert "assigned_by_actor_id" in readme
    assert "assigned_operator_id" in runbook
    assert "assigned_by_actor_id" in runbook
    assert "event_name=human_task_assigned&assigned_by_actor_id=exec-1" in smoke_api
    assert "event_name=human_task_returned&assigned_operator_id=operator-junior" in smoke_api
    assert 'params={"limit": 10, "event_name": "human_task_assigned", "assigned_by_actor_id": "exec-1"}' in smoke_runtime
    assert 'params={"limit": 10, "event_name": "human_task_returned", "assigned_operator_id": "operator-junior"}' in smoke_runtime
    assert "/v1/human/tasks/{{human_task_id}}/assignment-history?limit=20&event_name=human_task_assigned&assigned_by_actor_id={{principal_id}}" in http_examples

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_assignment_history_filters")
    assert capability["status"] == "tested"
    assert "assigned_by_actor_history_filter" in capability["scope"]


def test_human_task_last_transition_summary_projection_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    human_route = (ROOT / "ea/app/api/routes/human.py").read_text(encoding="utf-8")
    rewrite_route = (ROOT / "ea/app/api/routes/rewrite.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "last_transition_event_name" in readme
    assert "last_transition_operator_id" in readme
    assert "last_transition_by_actor_id" in readme
    assert "last_transition_event_name" in runbook
    assert "last_transition_operator_id" in runbook
    assert "last_transition_by_actor_id" in runbook
    assert "HUMAN_CREATE_SUMMARY_FIELDS" in smoke_api
    assert "HUMAN_REWRITE_SUMMARY_FIELDS" in smoke_api
    assert "human_task_returned|True|returned|operator-junior|manual|operator-junior" in smoke_api
    assert 'task["last_transition_event_name"] == "human_task_created"' in smoke_runtime
    assert 'assigned.json()["last_transition_event_name"] == "human_task_assigned"' in smoke_runtime
    assert 'returned.json()["last_transition_event_name"] == "human_task_returned"' in smoke_runtime
    assert 'review_task["last_transition_event_name"] == "human_task_assigned"' in smoke_runtime
    assert 'last_transition_event_name: str' in human_route
    assert 'last_transition_event_name: str' in rewrite_route

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_last_transition_summary_projection"
    )
    assert capability["status"] == "tested"
    assert "session_and_queue_row_summary" in capability["scope"]


def test_human_task_last_transition_sorting_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    human_route = (ROOT / "ea/app/api/routes/human.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "sort=last_transition_desc" in readme
    assert "sort=created_asc|created_desc|last_transition_desc|priority_desc_created_asc|sla_due_at_asc|sla_due_at_asc_last_transition_desc" in runbook
    assert "human task last-transition sort ok" in smoke_api
    assert "SORT_LIST_JSON" in smoke_api
    assert "SORT_BACKLOG_JSON" in smoke_api
    assert 'params={"status": "pending", "sort": "last_transition_desc", "limit": 10}' in smoke_runtime
    assert 'params={"sort": "last_transition_desc", "limit": 10}' in smoke_runtime
    assert "/v1/human/tasks/backlog?sort=last_transition_desc&limit=20" in http_examples
    assert 'sla_due_at_asc_last_transition_desc' in human_route

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_last_transition_sorting")
    assert capability["status"] == "tested"
    assert "last_transition_desc_runtime_ordering" in capability["scope"]


def test_human_task_sla_sorting_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    human_route = (ROOT / "ea/app/api/routes/human.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "sort=sla_due_at_asc" in readme
    assert "sort=created_asc|created_desc|last_transition_desc|priority_desc_created_asc|sla_due_at_asc|sla_due_at_asc_last_transition_desc" in runbook
    assert "human task SLA sort ok" in smoke_api
    assert "SLA_LIST_JSON" in smoke_api
    assert "SLA_BACKLOG_JSON" in smoke_api
    assert 'params={"status": "pending", "sort": "sla_due_at_asc", "limit": 10}' in smoke_runtime
    assert 'params={"sort": "sla_due_at_asc", "limit": 10}' in smoke_runtime
    assert "/v1/human/tasks/backlog?sort=sla_due_at_asc&limit=20" in http_examples
    assert 'sla_due_at_asc_last_transition_desc' in human_route

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_sla_sorting")
    assert capability["status"] == "tested"
    assert "sla_due_at_asc_runtime_ordering" in capability["scope"]


def test_human_task_combined_sla_transition_sorting_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    human_route = (ROOT / "ea/app/api/routes/human.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "sort=sla_due_at_asc_last_transition_desc" in readme
    assert "sort=created_asc|created_desc|last_transition_desc|priority_desc_created_asc|sla_due_at_asc|sla_due_at_asc_last_transition_desc" in runbook
    assert "human task combined sort ok" in smoke_api
    assert "COMBINED_LIST_JSON" in smoke_api
    assert "COMBINED_BACKLOG_JSON" in smoke_api
    assert 'params={"status": "pending", "sort": "sla_due_at_asc_last_transition_desc", "limit": 10}' in smoke_runtime
    assert 'params={"sort": "sla_due_at_asc_last_transition_desc", "limit": 10}' in smoke_runtime
    assert "/v1/human/tasks/backlog?sort=sla_due_at_asc_last_transition_desc&limit=20" in http_examples
    assert 'sla_due_at_asc_last_transition_desc' in human_route

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_sla_transition_combined_sorting"
    )
    assert capability["status"] == "tested"
    assert "sla_due_at_asc_last_transition_desc_runtime_ordering" in capability["scope"]


def test_human_task_unscheduled_fallback_sorting_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "fall back to oldest-created ordering for tasks without `sla_due_at`" in readme
    assert "fall back to oldest-created ordering for tasks without `sla_due_at`" in runbook
    assert "human task unscheduled fallback sort ok" in smoke_api
    assert "UNSCHED_SLA_LIST_JSON" in smoke_api
    assert "UNSCHED_COMBINED_BACKLOG_JSON" in smoke_api
    assert 'params={"status": "pending", "sort": "sla_due_at_asc", "limit": 10}' in smoke_runtime
    assert 'params={"status": "pending", "sort": "sla_due_at_asc_last_transition_desc", "limit": 10}' in smoke_runtime
    assert "/v1/human/tasks?principal_id={{principal_id}}&status=pending&sort=sla_due_at_asc&limit=20" in http_examples

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_unscheduled_fallback_sorting"
    )
    assert capability["status"] == "tested"
    assert "unscheduled_backlog_stability" in capability["scope"]


def test_human_task_created_asc_sorting_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    human_route = (ROOT / "ea/app/api/routes/human.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "sort=created_asc" in readme
    assert "sort=created_asc|created_desc|last_transition_desc|priority_desc_created_asc|sla_due_at_asc|sla_due_at_asc_last_transition_desc" in runbook
    assert "human task created-asc sort ok" in smoke_api
    assert "CREATED_ASC_LIST_JSON" in smoke_api
    assert "CREATED_ASC_MINE_JSON" in smoke_api
    assert 'params={"status": "pending", "sort": "created_asc", "limit": 10}' in smoke_runtime
    assert 'params={"sort": "created_asc", "limit": 10}' in smoke_runtime
    assert 'params={"operator_id": "operator-sorter", "status": "pending", "sort": "created_asc", "limit": 10}' in smoke_runtime
    assert "/v1/human/tasks/backlog?sort=created_asc&limit=20" in http_examples
    assert "created_asc" in human_route

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_created_asc_sorting")
    assert capability["status"] == "tested"
    assert "human_task_operator_fifo_queue_ordering" in capability["scope"]


def test_human_task_priority_created_sorting_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    human_route = (ROOT / "ea/app/api/routes/human.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "sort=priority_desc_created_asc" in readme
    assert "sort=created_asc|created_desc|last_transition_desc|priority_desc_created_asc|sla_due_at_asc|sla_due_at_asc_last_transition_desc" in runbook
    assert "human task priority-desc-created-asc sort ok" in smoke_api
    assert "PRIORITY_SORT_LIST_JSON" in smoke_api
    assert "PRIORITY_SORT_MINE_JSON" in smoke_api
    assert 'params={"status": "pending", "sort": "priority_desc_created_asc", "limit": 10}' in smoke_runtime
    assert 'params={"sort": "priority_desc_created_asc", "limit": 10}' in smoke_runtime
    assert 'params={"operator_id": "operator-sorter", "status": "pending", "sort": "priority_desc_created_asc", "limit": 10}' in smoke_runtime
    assert "/v1/human/tasks/backlog?sort=priority_desc_created_asc&limit=20" in http_examples
    assert "priority_desc_created_asc" in human_route

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_priority_created_sorting"
    )
    assert capability["status"] == "tested"
    assert "priority_band_fifo_queue_ordering" in capability["scope"]


def test_human_task_priority_filters_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "accept `priority=<level>` filters" in readme
    assert "supports `priority`" in runbook
    assert "priority=urgent|high|normal|low" in runbook
    assert "human task priority filter ok" in smoke_api
    assert "PRIORITY_FILTER_LIST_JSON" in smoke_api
    assert "PRIORITY_FILTER_MINE_JSON" in smoke_api
    assert 'params={"status": "pending", "priority": "high", "sort": "created_asc", "limit": 10}' in smoke_runtime
    assert 'params={"priority": "high", "sort": "created_asc", "limit": 10}' in smoke_runtime
    assert 'params={"operator_id": "operator-sorter", "status": "pending", "priority": "urgent", "sort": "created_asc", "limit": 10}' in smoke_runtime
    assert "/v1/human/tasks/backlog?priority=high&sort=created_asc&limit=20" in http_examples

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_priority_filters")
    assert capability["status"] == "tested"
    assert "human_task_operator_priority_band_views" in capability["scope"]


def test_human_task_multi_priority_filters_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "comma-separated values like `priority=urgent,high`" in readme
    assert "priority=urgent,high" in runbook
    assert "human task multi-priority filter ok" in smoke_api
    assert "MULTI_PRIORITY_LIST_JSON" in smoke_api
    assert "MULTI_PRIORITY_MINE_JSON" in smoke_api
    assert 'params={"status": "pending", "priority": "urgent,high", "sort": "priority_desc_created_asc", "limit": 10}' in smoke_runtime
    assert 'params={"priority": "urgent,high", "sort": "priority_desc_created_asc", "limit": 10}' in smoke_runtime
    assert 'params={"operator_id": "operator-sorter", "status": "pending", "priority": "urgent,high", "sort": "priority_desc_created_asc", "limit": 10}' in smoke_runtime
    assert "/v1/human/tasks/backlog?priority=urgent,high&sort=priority_desc_created_asc&limit=20" in http_examples

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_multi_priority_filters")
    assert capability["status"] == "tested"
    assert "combined_priority_band_queue_views" in capability["scope"]


def test_human_task_priority_summary_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    human_route = (ROOT / "ea/app/api/routes/human.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "GET /v1/human/tasks/priority-summary" in readme
    assert "/v1/human/tasks/priority-summary" in runbook
    assert "human task priority summary ok" in smoke_api
    assert "PRIORITY_SUMMARY_JSON" in smoke_api
    assert "PRIORITY_SUMMARY_UNASSIGNED_JSON" in smoke_api
    assert 'params={"status": "pending", "role_required": role_required}' in smoke_runtime
    assert 'params={"status": "pending", "role_required": role_required, "assignment_state": "unassigned"}' in smoke_runtime
    assert "/v1/human/tasks/priority-summary?status=pending&role_required=communications_reviewer" in http_examples
    assert '@router.get("/priority-summary")' in human_route

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_priority_summary")
    assert capability["status"] == "tested"
    assert "priority_band_count_projection" in capability["scope"]


def test_human_task_assigned_priority_summary_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "also accepts `assigned_operator_id`" in readme
    assert "assigned_operator_id" in runbook
    assert "PRIORITY_SUMMARY_ASSIGNED_JSON" in smoke_api
    assert "PRIORITY_SUMMARY_ASSIGNED_FIELDS" in smoke_api
    assert 'params={"status": "pending", "role_required": role_required, "assigned_operator_id": operator_id}' in smoke_runtime
    assert "/v1/human/tasks/priority-summary?status=pending&role_required=communications_reviewer&assigned_operator_id=operator" in http_examples

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_assigned_priority_summary")
    assert capability["status"] == "tested"
    assert "mine_queue_priority_band_projection" in capability["scope"]


def test_human_task_operator_matched_priority_summary_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    human_route = (ROOT / "ea/app/api/routes/human.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "also accepts `operator_id`" in readme
    assert "operator_id" in runbook
    assert "PRIORITY_SUMMARY_MATCHED_JSON" in smoke_api
    assert "PRIORITY_SUMMARY_MATCHED_FIELDS" in smoke_api
    assert 'params={' in smoke_runtime
    assert '"operator_id": "operator-specialist-summary"' in smoke_runtime
    assert "/v1/human/tasks/priority-summary?status=pending&assignment_state=unassigned&operator_id=operator-specialist" in http_examples
    assert "operator_id: str" in human_route

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_operator_matched_priority_summary"
    )
    assert capability["status"] == "tested"
    assert "role_skill_trust_filtered_backlog_counts" in capability["scope"]


def test_human_task_assignment_source_priority_summary_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    human_route = (ROOT / "ea/app/api/routes/human.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "also accepts `assignment_source`" in readme
    assert "assignment_source" in runbook
    assert "PRIORITY_SUMMARY_MANUAL_JSON" in smoke_api
    assert "HUMAN_REWRITE_AUTO_SUMMARY_JSON" in smoke_api
    assert '"assignment_source": "auto_preselected"' in smoke_runtime
    assert "/v1/human/tasks/priority-summary?status=pending&assignment_source=manual" in http_examples
    assert "assignment_source: str" in human_route

    capability = next(
        entry for entry in milestone["capabilities"]
        if entry["name"] == "human_task_priority_summary_assignment_source_filter"
    )
    assert capability["status"] == "tested"
    assert "manual_vs_auto_preselected_pending_projection" in capability["scope"]


def test_human_task_priority_summary_mixed_source_non_ownerless_isolation_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "rechecked after extra ownerless rows are added" in readme
    assert "rechecked after extra ownerless rows are added" in runbook
    assert "PRIORITY_SUMMARY_MANUAL_MIXED_FIELDS" in smoke_api
    assert "HUMAN_REWRITE_AUTO_SUMMARY_MIXED_FIELDS" in smoke_api

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_priority_summary_mixed_source_non_ownerless_isolation"
    )
    assert capability["status"] == "tested"
    assert "manual_summary_after_ownerless_churn" in capability["scope"]
    assert "auto_preselected_summary_after_ownerless_churn" in capability["scope"]


def test_human_task_assignment_source_queue_filters_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "queue views now also accept `assignment_source=<source>`" in readme
    assert "assignment_source=manual|recommended|auto_preselected" in runbook
    assert "PRIORITY_SUMMARY_MANUAL_LIST_JSON" in smoke_api
    assert "HUMAN_REWRITE_AUTO_BACKLOG_JSON" in smoke_api
    assert 'params={"status": "pending", "assignment_source": "manual"}' in smoke_runtime
    assert 'params={"operator_id": "operator-auto-summary", "assignment_source": "auto_preselected"}' in smoke_runtime
    assert "/v1/human/tasks/backlog?assignment_source=auto_preselected&limit=20" in http_examples

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_assignment_source_queue_filters"
    )
    assert capability["status"] == "tested"
    assert "human_task_backlog_assignment_source_filter" in capability["scope"]


def test_human_task_ownerless_assignment_source_alias_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    postgres_matrix = (ROOT / "tests/test_postgres_contract_matrix_integration.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "assignment_source=none" in readme
    assert "assignment_source=none" in runbook
    assert "HUMAN_UNASSIGNED_NONE_JSON" in smoke_api
    assert "PRIORITY_SUMMARY_NONE_JSON" in smoke_api
    assert 'params={"status": "pending", "assignment_state": "unassigned", "assignment_source": "none"}' in smoke_runtime
    assert 'params={"assignment_source": "none"}' in smoke_runtime
    assert 'assignment_source="none"' in postgres_matrix
    assert "/v1/human/tasks/unassigned?assignment_source=none&limit=20" in http_examples

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_ownerless_assignment_source_alias"
    )
    assert capability["status"] == "tested"
    assert "human_task_unassigned_ownerless_source_alias" in capability["scope"]


def test_human_task_ownerless_session_history_alias_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "human_task_assignment_source=none" in readme
    assert "human_task_assignment_source=none" in runbook
    assert "SESSION_HUMAN_NONE_JSON" in smoke_api
    assert "HUMAN_HISTORY_NONE_JSON" in smoke_api
    assert 'params={"limit": 10, "assignment_source": "none"}' in smoke_runtime
    assert 'params={"human_task_assignment_source": "none"}' in smoke_runtime
    assert "/v1/rewrite/sessions/{{session_id}}?human_task_assignment_source=none" in http_examples
    assert "/v1/human/tasks/{{human_task_id}}/assignment-history?limit=20&assignment_source=none" in http_examples

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_ownerless_session_history_alias"
    )
    assert capability["status"] == "tested"
    assert "session_human_task_ownerless_source_alias" in capability["scope"]


def test_human_task_ownerless_backlog_alias_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "assignment_state=unassigned&assignment_source=none" in readme
    assert "assignment_state=unassigned&assignment_source=none" in runbook
    assert "HUMAN_OWNERLESS_BACKLOG_JSON" in smoke_api
    assert 'params={"assignment_state": "unassigned", "assignment_source": "none"}' in smoke_runtime
    assert "/v1/human/tasks/backlog?assignment_state=unassigned&assignment_source=none&limit=20" in http_examples

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_ownerless_backlog_alias"
    )
    assert capability["status"] == "tested"
    assert "human_task_backlog_ownerless_source_alias" in capability["scope"]


def test_human_task_ownerless_backlog_created_sort_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "assignment_state=unassigned&assignment_source=none&sort=created_asc" in readme
    assert "assignment_state=unassigned&assignment_source=none&sort=created_asc" in runbook
    assert "HUMAN_OWNERLESS_BACKLOG_CREATED_JSON" in smoke_api
    assert 'params={\n            "assignment_state": "unassigned",\n            "assignment_source": "none",\n            "sort": "created_asc",' in smoke_runtime
    assert "/v1/human/tasks/backlog?assignment_state=unassigned&assignment_source=none&sort=created_asc&limit=20" in http_examples

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_ownerless_backlog_created_sort"
    )
    assert capability["status"] == "tested"
    assert "ownerless_backlog_created_asc_fifo" in capability["scope"]


def test_human_task_ownerless_backlog_last_transition_sort_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "assignment_state=unassigned&assignment_source=none&sort=last_transition_desc" in readme
    assert "assignment_state=unassigned&assignment_source=none&sort=last_transition_desc" in runbook
    assert "HUMAN_OWNERLESS_BACKLOG_TRANSITION_JSON" in smoke_api
    assert 'params={\n            "assignment_state": "unassigned",\n            "assignment_source": "none",\n            "sort": "last_transition_desc",' in smoke_runtime
    assert "/v1/human/tasks/backlog?assignment_state=unassigned&assignment_source=none&sort=last_transition_desc&limit=20" in http_examples

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_ownerless_backlog_last_transition_sort"
    )
    assert capability["status"] == "tested"
    assert "ownerless_backlog_last_transition_desc_ordering" in capability["scope"]


def test_human_task_ownerless_unassigned_last_transition_sort_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "assignment_source=none&sort=last_transition_desc" in readme
    assert "assignment_source=none&sort=last_transition_desc" in runbook
    assert "HUMAN_OWNERLESS_UNASSIGNED_TRANSITION_JSON" in smoke_api
    assert 'params={"assignment_source": "none", "sort": "last_transition_desc"}' in smoke_runtime
    assert "/v1/human/tasks/unassigned?assignment_source=none&sort=last_transition_desc&limit=20" in http_examples

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_ownerless_unassigned_last_transition_sort"
    )
    assert capability["status"] == "tested"
    assert "ownerless_unassigned_last_transition_desc_ordering" in capability["scope"]


def test_human_task_ownerless_unassigned_created_sort_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "assignment_source=none&sort=created_asc" in readme
    assert "assignment_source=none&sort=created_asc" in runbook
    assert "HUMAN_OWNERLESS_UNASSIGNED_CREATED_JSON" in smoke_api
    assert 'params={"assignment_source": "none", "sort": "created_asc"}' in smoke_runtime
    assert "/v1/human/tasks/unassigned?assignment_source=none&sort=created_asc&limit=20" in http_examples

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_ownerless_unassigned_created_sort"
    )
    assert capability["status"] == "tested"
    assert "ownerless_unassigned_created_asc_fifo" in capability["scope"]


def test_human_task_ownerless_list_created_sort_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "status=pending&assignment_state=unassigned&assignment_source=none&sort=created_asc" in readme
    assert "status=pending&assignment_state=unassigned&assignment_source=none&sort=created_asc" in runbook
    assert "HUMAN_OWNERLESS_LIST_CREATED_JSON" in smoke_api
    assert 'params={\n            "status": "pending",\n            "assignment_state": "unassigned",\n            "assignment_source": "none",\n            "sort": "created_asc",' in smoke_runtime
    assert "/v1/human/tasks?status=pending&assignment_state=unassigned&assignment_source=none&sort=created_asc&limit=20" in http_examples

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_ownerless_list_created_sort"
    )
    assert capability["status"] == "tested"
    assert "ownerless_list_created_asc_fifo" in capability["scope"]


def test_human_task_ownerless_list_last_transition_sort_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "status=pending&assignment_state=unassigned&assignment_source=none&sort=last_transition_desc" in readme
    assert "status=pending&assignment_state=unassigned&assignment_source=none&sort=last_transition_desc" in runbook
    assert "HUMAN_OWNERLESS_LIST_TRANSITION_JSON" in smoke_api
    assert 'params={\n            "status": "pending",\n            "assignment_state": "unassigned",\n            "assignment_source": "none",\n            "sort": "last_transition_desc",' in smoke_runtime
    assert "/v1/human/tasks?status=pending&assignment_state=unassigned&assignment_source=none&sort=last_transition_desc&limit=20" in http_examples

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_ownerless_list_last_transition_sort"
    )
    assert capability["status"] == "tested"
    assert "ownerless_list_last_transition_desc_ordering" in capability["scope"]


def test_human_task_session_ownerless_created_sort_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "session_id=<id>&assignment_source=none&sort=created_asc" in readme
    assert "session_id=<id>&assignment_source=none&sort=created_asc" in runbook
    assert "SESSION_HUMAN_NONE_CREATED_JSON" in smoke_api
    assert 'params={"session_id": session_id, "assignment_source": "none", "sort": "created_asc"}' in smoke_runtime
    assert "/v1/human/tasks?session_id={{session_id}}&assignment_source=none&sort=created_asc&limit=20" in http_examples

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_session_ownerless_created_sort"
    )
    assert capability["status"] == "tested"
    assert "session_ownerless_created_asc_fifo" in capability["scope"]


def test_human_task_session_ownerless_last_transition_sort_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "session_id=<id>&assignment_source=none&sort=last_transition_desc" in readme
    assert "session_id=<id>&assignment_source=none&sort=last_transition_desc" in runbook
    assert "SESSION_HUMAN_NONE_TRANSITION_JSON" in smoke_api
    assert 'params={"session_id": session_id, "assignment_source": "none", "sort": "last_transition_desc"}' in smoke_runtime
    assert "/v1/human/tasks?session_id={{session_id}}&assignment_source=none&sort=last_transition_desc&limit=20" in http_examples

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_session_ownerless_last_transition_sort"
    )
    assert capability["status"] == "tested"
    assert "session_ownerless_last_transition_desc_ordering" in capability["scope"]


def test_human_task_session_ownerless_mixed_source_isolation_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "manual and auto-preselected neighbors too" in readme
    assert "manual and auto-preselected neighbors present" in runbook
    assert "SESSION_HUMAN_NONE_CREATED_JSON" in smoke_api
    assert "SESSION_HUMAN_NONE_TRANSITION_JSON" in smoke_api
    assert "keeping mixed-source neighbors out" in smoke_api
    assert "ownerless_session_created_all_ids ==" in smoke_runtime
    assert "ownerless_session_transition_all_ids ==" in smoke_runtime

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_session_ownerless_mixed_source_isolation"
    )
    assert capability["status"] == "tested"
    assert "session_ownerless_created_asc_excludes_non_ownerless" in capability["scope"]


def test_human_task_ownerless_sorted_queue_mixed_source_isolation_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "manual and auto-preselected neighbors" in readme
    assert "manual and auto-preselected neighbors present" in runbook
    assert "HUMAN_OWNERLESS_BACKLOG_CREATED_JSON" in smoke_api
    assert "HUMAN_OWNERLESS_UNASSIGNED_CREATED_JSON" in smoke_api
    assert "HUMAN_OWNERLESS_LIST_CREATED_JSON" in smoke_api
    assert "keeping mixed-source neighbors out" in smoke_api
    assert "ownerless_backlog_created_all_ids ==" in smoke_runtime
    assert "ownerless_unassigned_created_all_ids ==" in smoke_runtime
    assert "ownerless_list_created_all_ids ==" in smoke_runtime
    assert "ownerless_backlog_transition_all_ids ==" in smoke_runtime
    assert "ownerless_unassigned_transition_all_ids ==" in smoke_runtime
    assert "ownerless_list_transition_all_ids ==" in smoke_runtime

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_ownerless_sorted_queue_mixed_source_isolation"
    )
    assert capability["status"] == "tested"
    assert "ownerless_backlog_sorted_excludes_non_ownerless" in capability["scope"]


def test_human_task_ownerless_priority_summary_mixed_source_counts_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "ownerless `priority-summary?assignment_state=unassigned&assignment_source=none` slice is now explicitly covered after mixed-source churn" in readme
    assert "ownerless `priority-summary?status=pending&assignment_state=unassigned&assignment_source=none` slice is now also covered after mixed-source churn" in runbook
    assert "PRIORITY_SUMMARY_NONE_MIXED_JSON" in smoke_api
    assert "stay ownerless-only after mixed-source churn" in smoke_api
    assert "ownerless_summary_after_churn" in smoke_runtime
    assert 'ownerless_summary_after_churn_body["total"] == 2' in smoke_runtime
    assert 'ownerless_summary_after_churn_body["counts_json"]["low"] == 2' in smoke_runtime

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_ownerless_priority_summary_mixed_source_counts"
    )
    assert capability["status"] == "tested"
    assert "ownerless_priority_summary_total_excludes_non_ownerless_after_churn" in capability["scope"]


def test_human_task_ownerless_unsorted_queue_mixed_source_isolation_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "unsorted ownerless `assignment_source=none` list, backlog, and unassigned slices are now also explicitly covered after mixed-source churn" in readme
    assert "unsorted ownerless `assignment_source=none` list, backlog, and unassigned slices are now also covered after mixed-source churn" in runbook
    assert "HUMAN_OWNERLESS_LIST_MIXED_JSON" in smoke_api
    assert "HUMAN_UNASSIGNED_NONE_MIXED_JSON" in smoke_api
    assert "HUMAN_OWNERLESS_BACKLOG_MIXED_JSON" in smoke_api
    assert "stay ownerless-only after mixed-source churn" in smoke_api
    assert "ownerless_list_after_churn_ids ==" in smoke_runtime
    assert "ownerless_unassigned_after_churn_ids ==" in smoke_runtime
    assert "ownerless_backlog_after_churn_ids ==" in smoke_runtime

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_ownerless_unsorted_queue_mixed_source_isolation"
    )
    assert capability["status"] == "tested"
    assert "ownerless_list_unsorted_excludes_non_ownerless_after_churn" in capability["scope"]


def test_human_task_session_ownerless_unsorted_mixed_source_isolation_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "unsorted session-scoped `session_id=<id>&assignment_source=none` slice is now also explicitly covered after mixed-source churn" in readme
    assert "unsorted session-scoped `session_id=<id>&assignment_source=none` slice is now also covered after mixed-source churn" in runbook
    assert "SESSION_HUMAN_NONE_MIXED_JSON" in smoke_api
    assert "stay ownerless-only after mixed-source churn" in smoke_api
    assert "ownerless_session_list_after_churn_ids ==" in smoke_runtime

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "human_task_session_ownerless_unsorted_mixed_source_isolation"
    )
    assert capability["status"] == "tested"
    assert "session_ownerless_unsorted_excludes_non_ownerless_after_churn" in capability["scope"]


def test_session_ownerless_projection_mixed_source_counts_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "mixed-source session-detail ownerless slice is now also explicitly count-checked" in readme
    assert "mixed-source session-detail ownerless projection is now also count-checked" in runbook
    assert "SESSION_HUMAN_NONE_PROJECTION_JSON" in smoke_api
    assert "longer empty-source history trail" in smoke_api
    assert 'len(ownerless_session_projection_body["human_tasks"]) == 2' in smoke_runtime
    assert 'len(ownerless_session_projection_body["human_task_assignment_history"]) > len(' in smoke_runtime

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "session_ownerless_projection_mixed_source_counts"
    )
    assert capability["status"] == "tested"
    assert "session_ownerless_projection_current_count_after_churn" in capability["scope"]


def test_session_ownerless_projection_created_order_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "human_task_assignment_source=none" in readme
    assert "human_task_assignment_source=none" in runbook
    assert "SESSION_HUMAN_NONE_PROJECTION_JSON" in smoke_api
    assert 'params={"human_task_assignment_source": "none"}' in smoke_runtime
    assert "ownerless_session_projection_ids == [ownerless_task_id, ownerless_newer_task_id]" in smoke_runtime
    assert "ownerless_session_history_ids == [ownerless_task_id, ownerless_newer_task_id]" in smoke_runtime
    assert "/v1/rewrite/sessions/{{session_id}}?human_task_assignment_source=none" in http_examples

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "session_ownerless_projection_created_order"
    )
    assert capability["status"] == "tested"
    assert "session_ownerless_projection_human_tasks_created_asc" in capability["scope"]


def test_session_ownerless_projection_mixed_source_isolation_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "manual and auto-preselected work" in readme
    assert "manual and auto-preselected neighbors" in runbook
    assert "SESSION_HUMAN_NONE_PROJECTION_JSON" in smoke_api
    assert "two-row current ownerless slice" in smoke_api
    assert 'row["human_task_id"] not in {manual_task_id, auto_task_id}' in smoke_runtime
    assert "ownerless_session_projection_history_all_ids[:4]" in smoke_runtime

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "session_ownerless_projection_mixed_source_isolation"
    )
    assert capability["status"] == "tested"
    assert "session_ownerless_projection_current_rows_exclude_non_ownerless" in capability["scope"]


def test_human_task_assignment_history_source_filter_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "assignment-history` also accepts `event_name`, `assigned_operator_id`, `assigned_by_actor_id`, and `assignment_source`" in readme
    assert "assignment_source" in runbook
    assert "HUMAN_HISTORY_RECOMMENDED_JSON" in smoke_api
    assert 'params={"limit": 10, "assignment_source": "recommended"}' in smoke_runtime
    assert "/v1/human/tasks/{{human_task_id}}/assignment-history?limit=20&assignment_source=recommended" in http_examples

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "human_task_assignment_history_source_filter"
    )
    assert capability["status"] == "tested"
    assert "recommended_transition_isolation" in capability["scope"]


def test_session_human_task_assignment_source_filter_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "also accepts `human_task_assignment_source`" in readme
    assert "human_task_assignment_source" in runbook
    assert "SESSION_HUMAN_MANUAL_JSON" in smoke_api
    assert "HUMAN_REWRITE_AUTO_SESSION_JSON" in smoke_api
    assert 'params={"human_task_assignment_source": "manual"}' in smoke_runtime
    assert "/v1/rewrite/sessions/{{session_id}}?human_task_assignment_source=manual" in http_examples

    capability = next(
        entry for entry in milestone["capabilities"] if entry["name"] == "session_human_task_assignment_source_filter"
    )
    assert capability["status"] == "tested"
    assert "manual_session_task_slice" in capability["scope"]


def test_session_scoped_human_task_assignment_source_queue_filters_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "session_id=<id>&assignment_source=<source>" in readme
    assert "session_id=<id>&assignment_source=<source>" in runbook
    assert "PRIORITY_SUMMARY_MANUAL_SESSION_JSON" in smoke_api
    assert "HUMAN_REWRITE_AUTO_LIST_JSON" in smoke_api
    assert 'params={"session_id": session_id, "assignment_source": "manual"}' in smoke_runtime
    assert "/v1/human/tasks?principal_id={{principal_id}}&session_id={{session_id}}&assignment_source=manual&limit=20" in http_examples

    capability = next(
        entry
        for entry in milestone["capabilities"]
        if entry["name"] == "session_scoped_human_task_assignment_source_filters"
    )
    assert capability["status"] == "tested"
    assert "session_scoped_manual_queue_slice" in capability["scope"]


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


def test_principal_scoped_rewrite_and_plan_routes_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "rewrite/session/artifact/receipt/run-cost, plan-compile/execute" in readme
    assert "/v1/rewrite/sessions/{session_id}" in runbook
    assert "/v1/plans/compile" in runbook
    assert "/v1/plans/execute" in runbook
    assert "403 principal_scope_mismatch" in runbook
    assert '"principal_id": "exec-2"' in http_examples
    assert "REWRITE_SESSION_MISMATCH_CODE" in smoke_api
    assert "PLAN_MISMATCH_CODE" in smoke_api
    assert "test_rewrite_routes_enforce_principal_scope" in smoke_runtime
    assert "test_plan_compile_derives_request_principal_and_rejects_mismatch" in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "principal_scoped_rewrite_and_plan_routes")
    assert capability["status"] == "tested"


def test_session_principal_scoped_human_task_routes_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "session-bound human task create/list requests now also enforce the linked execution session principal" in readme
    assert "GET /v1/human/tasks?session_id=..." in runbook
    assert "HUMAN_CREATE_MISMATCH_CODE" in smoke_api
    assert "HUMAN_SESSION_LIST_MISMATCH_CODE" in smoke_api
    assert "test_human_task_session_routes_enforce_session_principal_scope" in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "session_principal_scoped_human_task_routes")
    assert capability["status"] == "tested"


def test_generic_task_execution_runtime_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    postgres_contracts = (ROOT / "tests/test_postgres_contract_matrix_integration.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "/v1/plans/execute" in readme
    assert "non-`rewrite_text` artifact flows" in readme
    assert "/v1/plans/execute" in runbook
    assert "stakeholder briefings" in runbook
    assert "POST {{host}}/v1/plans/execute" in http_examples
    assert "TASK_EXECUTE_JSON" in smoke_api
    assert "generic task execution ok" in smoke_api
    assert "test_generic_task_execution_uses_compiled_contract_runtime" in smoke_runtime
    assert "test_postgres_orchestrator_executes_non_rewrite_task_contract" in postgres_contracts

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "generic_task_execution_runtime")
    assert capability["status"] == "tested"


def test_generic_task_execution_async_contracts_are_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "same first-class `202 awaiting_approval` and `202 awaiting_human` async contract" in readme
    assert "same first-class `202 awaiting_approval` and `202 awaiting_human` workflow contract" in runbook
    assert '"task_key": "decision_brief_approval"' in http_examples
    assert '"task_key": "stakeholder_briefing_review"' in http_examples
    assert "GENERIC_APPROVAL_JSON" in smoke_api
    assert "GENERIC_HUMAN_JSON" in smoke_api
    assert "generic task async contracts ok" in smoke_api
    assert "test_generic_task_execution_supports_async_approval_and_human_contracts" in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "generic_task_execution_async_contracts")
    assert capability["status"] == "tested"


def test_artifact_lookup_task_identity_projection_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "originating task key and deliverable type" in readme
    assert "originating `task_key`/`deliverable_type`" in runbook
    assert "includes originating task_key and deliverable_type" in http_examples
    assert "TASK_EXECUTE_ARTIFACT_JSON" in smoke_api
    assert "TASK_EXECUTE_ARTIFACT_FIELDS" in smoke_api
    assert 'fetched_artifact.json()["task_key"] == "stakeholder_briefing"' in smoke_runtime
    assert 'fetched_artifact.json()["deliverable_type"] == "stakeholder_briefing"' in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "artifact_lookup_task_identity_projection")
    assert capability["status"] == "tested"


def test_proof_lookup_task_identity_projection_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "direct execution proof records" in readme
    assert "originating `task_key`/`deliverable_type`" in runbook
    assert "fetch receipt (includes originating task_key and deliverable_type)" in http_examples
    assert "fetch run cost (includes originating task_key and deliverable_type)" in http_examples
    assert "TASK_EXECUTE_RECEIPT_JSON" in smoke_api
    assert "TASK_EXECUTE_COST_JSON" in smoke_api
    assert 'fetched_receipt.json()["task_key"] == "stakeholder_briefing"' in smoke_runtime
    assert 'fetched_cost.json()["task_key"] == "stakeholder_briefing"' in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "proof_lookup_task_identity_projection")
    assert capability["status"] == "tested"


def test_session_artifact_task_identity_projection_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "inline artifact/proof rows now carry originating task identity" in readme
    assert "self-describing artifact/proof task identity" in runbook
    assert "TASK_EXECUTE_SESSION_FIELDS" in smoke_api
    assert "stakeholder_briefing|stakeholder_briefing|stakeholder_briefing" in smoke_api
    assert 'session_body["artifacts"][0]["task_key"] == "stakeholder_briefing"' in smoke_runtime
    assert 'session_body["artifacts"][0]["deliverable_type"] == "stakeholder_briefing"' in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "session_artifact_task_identity_projection")
    assert capability["status"] == "tested"


def test_async_queue_projection_task_identity_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    http_examples = (ROOT / "HTTP_EXAMPLES.http").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "approval projections now carry the originating task identity" in readme
    assert "queue/detail payloads now also carry the originating task identity" in readme
    assert "Approval and human-task queue/detail payloads now stay self-describing" in runbook
    assert "Approvals -> pending (includes originating task_key and deliverable_type)" in http_examples
    assert "Human tasks -> direct detail (includes originating task_key and deliverable_type)" in http_examples
    assert "GENERIC_APPROVAL_PENDING_FIELDS" in smoke_api
    assert "GENERIC_APPROVAL_HISTORY_FIELDS" in smoke_api
    assert "GENERIC_HUMAN_LIST_FIELDS" in smoke_api
    assert 'pending_row["task_key"] == "decision_brief_approval"' in smoke_runtime
    assert 'review_detail.json()["task_key"] == "stakeholder_briefing_review"' in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "async_queue_projection_task_identity")
    assert capability["status"] == "tested"


def test_dependency_aware_execution_scheduler_is_documented_and_tested() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    postgres_contracts = (ROOT / "tests/test_postgres_contract_matrix_integration.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "queue advancement now selects the next ready step from satisfied dependency edges" in readme
    assert "queue advancement now chooses the next ready step from satisfied dependency edges" in runbook
    assert "Queue advancement now resolves the next ready step from satisfied `depends_on` edges" in changelog
    assert "test_postgres_orchestrator_dependency_scheduler_waits_for_all_dependencies" in postgres_contracts

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "dependency_aware_execution_scheduler")
    assert capability["status"] == "tested"


def test_queued_policy_step_audit_truthfulness_is_documented_and_smoked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    smoke_api = (ROOT / "scripts/smoke_api.sh").read_text(encoding="utf-8")
    smoke_runtime = (ROOT / "tests/smoke_runtime_api.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "policy_decision` is now recorded by the queued `step_policy_evaluate` handler after `input_prepared`" in readme
    assert "policy_decision` is now emitted from the queued `step_policy_evaluate` handler after `input_prepared`" in runbook
    assert "Policy decisions are now recorded from the queued `step_policy_evaluate` handler after `input_prepared`" in changelog
    assert "policy_decision" in smoke_api
    assert "order_ok" in smoke_api
    assert 'event_names.index("input_prepared") < event_names.index("policy_decision")' in smoke_runtime

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "queued_policy_step_audit_truthfulness")
    assert capability["status"] == "tested"


def test_human_task_dependency_input_merge_is_documented_and_tested() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    postgres_contracts = (ROOT / "tests/test_postgres_contract_matrix_integration.py").read_text(encoding="utf-8")
    milestone = json.loads((ROOT / "MILESTONE.json").read_text(encoding="utf-8"))

    assert "compiled human-review steps now merge dependency outputs into the created packet input" in readme
    assert "queued human-review step now also merges dependency outputs into the packet input" in runbook
    assert "Human-review step execution now merges dependency outputs into the created packet input" in changelog
    assert "test_postgres_human_task_step_merges_dependency_outputs" in postgres_contracts

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "human_task_dependency_input_merge")
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
    assert "high|45|True|manager_review" in smoke_api
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
