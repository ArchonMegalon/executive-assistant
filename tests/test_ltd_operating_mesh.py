from __future__ import annotations

from pathlib import Path

import yaml

from scripts.materialize_ltd_capacity_status import build_payload as build_capacity
from scripts.materialize_ltd_proof_debt import build_payload as build_proof_debt
from scripts.query_ltd_opportunity_index import QUERIES, build_payload as build_opportunities


ROOT = Path(__file__).resolve().parents[1]


def test_operating_mesh_configs_are_fail_closed_and_truth_bounded() -> None:
    scheduler = yaml.safe_load((ROOT / "config/ltd_capacity_scheduler.yaml").read_text(encoding="utf-8"))
    blast = yaml.safe_load((ROOT / "config/ltd_blast_radius.yaml").read_text(encoding="utf-8"))
    router = yaml.safe_load((ROOT / "config/ltd_capability_router.yaml").read_text(encoding="utf-8"))

    assert scheduler["default_policy"] == "fail_closed"
    assert scheduler["providers"]["AI Magicx"]["empty_credential_action"] == "omit_from_effective_order"
    assert blast["default_class"] == "regulated_or_high_risk"
    assert all(policy.get("may_own_truth") is False for policy in blast["provider_policies"].values())
    assert router["hard_rules"]["can_publish_directly"] is False
    assert router["hard_rules"]["can_own_truth"] is False
    assert router["catalog_only"]["VocalLab.ai"]["executable"] is False


def test_capacity_projection_omits_empty_magicx_without_leaking_secrets() -> None:
    payload = build_capacity(
        env={"ONEMIN_AI_API_KEY": "onemin-private", "AI_MAGICX_API_KEY": ""},
        generated_at="2026-08-13T00:00:00Z",
    )
    rows = {row["provider"]: row for row in payload["providers"]}

    assert rows["1min.AI"]["route_state"] == "eligible_for_health_probe"
    assert rows["AI Magicx"]["route_state"] == "omitted_empty_credential"
    assert payload["secret_material_exposed"] is False
    assert "onemin-private" not in str(payload)
    for row in rows.values():
        assert row["task_class"]
        assert len(row["slot_ref_sha256"]) == 64
        assert row["route_decision"] == row["route_state"]
        assert row["generated_at"] == "2026-08-13T00:00:00Z"
        assert "live_balance_not_asserted" in row["credit_basis"]


def test_proof_debt_has_one_complete_row_for_each_non_tier_one_inventory_entry() -> None:
    payload = build_proof_debt(generated_at="2026-08-13T00:00:00Z")
    rows = payload["rows"]

    assert payload["status"] == "projection_ready"
    assert rows
    assert len({row["service"] for row in rows}) == len(rows)
    for row in rows:
        assert row["current_workspace_tier"] in {"Tier 2", "Tier 3", "Tier 4"}
        assert row["candidate_lane"]
        assert row["next_proof"]
        assert row["must_not_claim"]
        assert row["owner_review_required"] is True


def test_vexp_query_pack_has_twenty_bounded_owner_review_candidates(monkeypatch) -> None:
    assert len(QUERIES) == 20
    monkeypatch.setattr("scripts.query_ltd_opportunity_index._head", lambda: "a" * 40)
    payload = build_opportunities(execute=False)

    assert payload["status"] == "query_pack_ready"
    assert payload["query_count"] == 20
    assert all(row["status"] == "query_ready_not_executed" for row in payload["opportunities"])
    assert "no canon mutation" in payload["truth_posture"]
