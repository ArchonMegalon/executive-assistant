from __future__ import annotations

from pathlib import Path

from app.repositories.preference_profiles import InMemoryPreferenceProfileRepository
from app.services.preference_profile_service import PreferenceProfileService
from app.services.teable_projection_adapter import build_teable_projection_records, build_teable_projection_summary
from app.services import teable_projection_adapter


def test_teable_projection_adapter_keeps_static_fallback_without_principal() -> None:
    records = build_teable_projection_records()

    assert "product_signals" in records
    assert "preference_review_queue" in records
    assert records["preference_review_queue"][0]["display_name"] == "Principal"


def test_teable_projection_adapter_can_project_live_preference_rows() -> None:
    service = PreferenceProfileService(repo=InMemoryPreferenceProfileRepository())
    service.ensure_profile(
        principal_id="pref-principal",
        person_id="self",
        display_name="Tibor",
        consent_mode="behavioral_learning",
        learning_enabled=True,
    )
    service.upsert_preference_node(
        principal_id="pref-principal",
        person_id="self",
        domain="willhaben",
        category="soft_preference",
        key="preferred_districts",
        value_json=["Waehring"],
        confidence=0.8,
    )

    records = build_teable_projection_records(
        preference_profile_service=service,
        principal_id="pref-principal",
        person_id="self",
    )
    summary = build_teable_projection_summary(
        preference_profile_service=service,
        principal_id="pref-principal",
        person_id="self",
    )

    assert records["preference_review_queue"][0]["display_name"] == "Tibor"
    assert records["preference_review_queue"][0]["key"] == "preferred_districts"
    table = next(item for item in summary["tables"] if item["table_name"] == "preference_review_queue")
    assert table["record_count"] >= 1


def test_teable_projection_adapter_project_backup_tables_from_markdown_and_env(
    tmp_path,
    monkeypatch,
) -> None:
    env_file = tmp_path / "env.backup"
    env_file.write_text(
        "\n".join(
            [
                "export EXPLICIT_KEY=explicit-value",
                "QUOTED_KEY=\"quoted-value\"",
                "EMPTY_KEY=",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ltd_file = tmp_path / "LTDs.md"
    ltd_file.write_text(
        "\n".join(
            [
                "## Non-AppSumo / Other LTDs",
                "| Service | Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
                "| `1min.ai` | Tier 4 | Archon | Activated | 2026-06-26 | Tier 2 | local | local workspace key |",
                "## AppSumo LTDs",
                "| Service | Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
                "## Discovery Tracking",
                "| service | account / email | status | verification source | last verified | notes |",
                "| --- | --- | --- | --- | --- | --- |",
                "| `1min.ai` | `archon.megalon@gmail.com` | verified | browseract | 2026-06-24 | recovery row |",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(teable_projection_adapter, "_env_source_candidates", lambda: (env_file,))
    monkeypatch.setattr(teable_projection_adapter, "_ltd_markdown_path", lambda: ltd_file)
    records = build_teable_projection_records()

    env_rows = records["environment_secret_backup"]
    inventory_rows = records["ltd_inventory_snapshot"]
    discovery_rows = records["ltd_discovery_snapshot"]

    assert any(row["env_key"] == "EXPLICIT_KEY" for row in env_rows)
    assert any(row["env_key"] == "QUOTED_KEY" for row in env_rows)
    assert any(row["env_key"] == "EMPTY_KEY" for row in env_rows)
    assert inventory_rows
    assert discovery_rows
    assert any(row["value_origin"] == str(env_file) for row in env_rows)
    assert inventory_rows[0]["service_name"] == "1min.ai"
    assert any(row["account_email"] == "`archon.megalon@gmail.com`" for row in discovery_rows)


def test_teable_projection_adapter_defaults_are_repo_local() -> None:
    source = (Path(__file__).resolve().parents[1] / "ea" / "app" / "services" / "teable_projection_adapter.py").read_text(
        encoding="utf-8"
    )

    assert "/docker/" + "EA/.env" not in source
    assert "/docker/" + "EA/LTDs.md" not in source
    assert "_repo_root() / \".env\"" in source
    assert "_repo_root() / \"LTDs.md\"" in source
