from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_schema_readme_lists_latest_migrations() -> None:
    text = (ROOT / "ea/schema/README.md").read_text()
    assert "20260305_v0_5_artifacts_kernel.sql" in text
    assert "20260305_v0_6_execution_ledger_v2.sql" in text
    assert "20260305_v0_7_approvals_kernel.sql" in text


def test_db_bootstrap_includes_latest_migrations() -> None:
    text = (ROOT / "scripts/db_bootstrap.sh").read_text()
    assert "20260305_v0_5_artifacts_kernel.sql" in text
    assert "20260305_v0_6_execution_ledger_v2.sql" in text
    assert "20260305_v0_7_approvals_kernel.sql" in text
