from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_schema_readme_lists_latest_migrations() -> None:
    text = (ROOT / "ea/schema/README.md").read_text()
    assert "20260305_v0_5_artifacts_kernel.sql" in text
    assert "20260305_v0_6_execution_ledger_v2.sql" in text
    assert "20260305_v0_7_approvals_kernel.sql" in text
    assert "20260305_v0_8_channel_runtime_reliability.sql" in text
    assert "20260305_v0_9_tool_connector_kernel.sql" in text
    assert "20260305_v0_10_task_contracts_kernel.sql" in text
    assert "20260305_v0_31_artifact_principal_scope.sql" in text
    assert "20260305_v0_32_provider_bindings_kernel.sql" in text
    assert "20260305_v0_33_task_contract_runtime_policy.sql" in text
    assert "20260305_v0_34_assistant_onboarding_canonical_schema.sql" in text
    assert "20260305_v0_35_execution_ledger_legacy_compat.sql" in text


def test_db_bootstrap_includes_latest_migrations() -> None:
    text = (ROOT / "scripts/db_bootstrap.sh").read_text()
    assert "20260305_v0_5_artifacts_kernel.sql" in text
    assert "20260305_v0_6_execution_ledger_v2.sql" in text
    assert "20260305_v0_7_approvals_kernel.sql" in text
    assert "20260305_v0_8_channel_runtime_reliability.sql" in text
    assert "20260305_v0_9_tool_connector_kernel.sql" in text
    assert "20260305_v0_10_task_contracts_kernel.sql" in text
    assert "20260305_v0_31_artifact_principal_scope.sql" in text
    assert "20260305_v0_32_provider_bindings_kernel.sql" in text
    assert "20260305_v0_33_task_contract_runtime_policy.sql" in text
    assert "20260305_v0_34_assistant_onboarding_canonical_schema.sql" in text
    assert "20260305_v0_35_execution_ledger_legacy_compat.sql" in text


def test_latest_kernel_migrations_define_provider_bindings_and_runtime_policy_column() -> None:
    provider_bindings = (ROOT / "ea/schema/20260305_v0_32_provider_bindings_kernel.sql").read_text()
    runtime_policy = (ROOT / "ea/schema/20260305_v0_33_task_contract_runtime_policy.sql").read_text()
    artifact_scope = (ROOT / "ea/schema/20260305_v0_31_artifact_principal_scope.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS provider_bindings" in provider_bindings
    assert "idx_provider_bindings_principal_provider" in provider_bindings
    assert "idx_provider_bindings_principal_updated" in provider_bindings

    assert "ALTER TABLE task_contracts" in runtime_policy
    assert "ADD COLUMN IF NOT EXISTS runtime_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb" in runtime_policy
    assert "WHERE a.session_id = es.session_id::text" in artifact_scope


def test_legacy_migration_regression_smoke_contract_is_wired() -> None:
    smoke = (ROOT / "scripts/smoke_postgres.sh").read_text()
    workflow = (ROOT / ".github/workflows/smoke-runtime.yml").read_text()

    assert "--legacy-fixture" in smoke
    assert "apply_legacy_fixture()" in smoke
    assert "validate_legacy_upgrade()" in smoke
    assert 'POSTGRES_DB="${SMOKE_DB}" bash scripts/db_bootstrap.sh' in smoke
    assert "smoke-postgres legacy fixture complete" in smoke
    assert "execution_events missing runtime columns" in smoke
    assert "execution_events.event_id type mismatch" in smoke
    assert "execution_steps missing runtime columns" in smoke
    assert "approval_requests missing runtime columns" in smoke
    assert "approval_decisions missing runtime columns" in smoke
    assert "bash scripts/smoke_postgres.sh --legacy-fixture" in workflow


def test_legacy_compatibility_migrations_encode_uuid_and_approval_upgrades() -> None:
    ledger = (ROOT / "ea/schema/20260305_v0_6_execution_ledger_v2.sql").read_text()
    ledger_compat = (ROOT / "ea/schema/20260305_v0_35_execution_ledger_legacy_compat.sql").read_text()
    approvals = (ROOT / "ea/schema/20260305_v0_7_approvals_kernel.sql").read_text()
    human_tasks = (ROOT / "ea/schema/20260305_v0_24_human_tasks_kernel.sql").read_text()

    assert "Some older installations use UUID-typed session identifiers" in ledger
    assert "format_type(a.atttypid, a.atttypmod)" in ledger
    assert "session_id %s NOT NULL REFERENCES execution_sessions(session_id)" in ledger

    assert "Older rewrite installations may still expose bigint event IDs" in ledger_compat
    assert "ADD COLUMN IF NOT EXISTS name TEXT" in ledger_compat
    assert "ALTER COLUMN event_id TYPE TEXT USING event_id::text" in ledger_compat
    assert "ALTER COLUMN event_type SET DEFAULT ''event''" in ledger_compat
    assert "ADD COLUMN IF NOT EXISTS step_kind TEXT" in ledger_compat
    assert "ADD COLUMN IF NOT EXISTS state TEXT" in ledger_compat
    assert "ADD COLUMN IF NOT EXISTS error_json JSONB" in ledger_compat

    assert "Older installations may have legacy approval tables" in approvals
    assert "approval_request_id" in approvals
    assert "approval_decision_id" in approvals
    assert "SET approval_id = 'legacy-' || approval_request_id::text" in approvals
    assert "SET decision_id = 'legacy-' || approval_decision_id::text" in approvals

    assert "Some upgraded installations may still use UUID-typed session identifiers" in human_tasks
    assert "format_type(a.atttypid, a.atttypmod)" in human_tasks
    assert "session_id %s NOT NULL REFERENCES execution_sessions(session_id)" in human_tasks
    assert "step_id %s NULL REFERENCES execution_steps(step_id)" in human_tasks


def test_postgres_ledger_runtime_bootstrap_heals_legacy_event_and_step_shapes() -> None:
    ledger_repo = (ROOT / "ea/app/repositories/ledger_postgres.py").read_text()

    assert "format_type(a.atttypid, a.atttypmod)" in ledger_repo
    assert "ADD COLUMN IF NOT EXISTS name TEXT" in ledger_repo
    assert "ALTER COLUMN event_id TYPE TEXT USING event_id::text" in ledger_repo
    assert "ALTER COLUMN event_type SET DEFAULT 'event'" in ledger_repo
    assert "ADD COLUMN IF NOT EXISTS step_kind TEXT" in ledger_repo
    assert "ADD COLUMN IF NOT EXISTS error_json JSONB" in ledger_repo


def test_operator_summary_lists_legacy_postgres_shortcuts() -> None:
    text = (ROOT / "scripts/operator_summary.sh").read_text()
    smoke_help = (ROOT / "scripts/smoke_help.sh").read_text()
    makefile = (ROOT / "Makefile").read_text()

    assert "Usage:" in text
    assert "make smoke-postgres-legacy" in text
    assert "make release-smoke" in text
    assert "make all-local" in text
    assert "make ci-gates-postgres-legacy" in text
    assert "make ci-gates-postgres" in text
    assert "make verify-release-assets" in text
    assert "make release-preflight" in text
    assert "make support-bundle" in text
    assert "make tasks-archive" in text
    assert "make tasks-archive-dry-run" in text
    assert "make tasks-archive-prune" in text
    assert "scripts/operator_summary.sh" in smoke_help
    assert "scripts/operator_summary.sh" in makefile


def test_endpoint_version_openapi_scripts_have_help_contracts_and_wiring() -> None:
    smoke_help = (ROOT / "scripts/smoke_help.sh").read_text()
    makefile = (ROOT / "Makefile").read_text()

    for rel in (
        "scripts/list_endpoints.sh",
        "scripts/version_info.sh",
        "scripts/export_openapi.sh",
        "scripts/diff_openapi.sh",
        "scripts/prune_openapi.sh",
    ):
        text = (ROOT / rel).read_text()
        assert "Usage:" in text
        assert rel in smoke_help
        assert rel in makefile


def test_smoke_help_has_help_contract_and_operator_help_wiring() -> None:
    smoke_help = (ROOT / "scripts/smoke_help.sh").read_text()
    makefile = (ROOT / "Makefile").read_text()

    assert "Usage:" in smoke_help
    assert "scripts/smoke_help.sh" in makefile
