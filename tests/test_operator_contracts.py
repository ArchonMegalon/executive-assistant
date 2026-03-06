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
    assert "step_artifact_save" in readme
    assert "step_input_prepare" in runbook
    assert "step_artifact_save" in runbook
    assert "step_input_prepare" in smoke_api
    assert "input_prepared" in smoke_api
    assert "step_input_prepare" in smoke_runtime
    assert "input_prepared" in smoke_runtime
    assert "step_input_prepare" in planner_test

    capability = next(entry for entry in milestone["capabilities"] if entry["name"] == "typed_step_handler_gateway")
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
