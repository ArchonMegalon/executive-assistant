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
