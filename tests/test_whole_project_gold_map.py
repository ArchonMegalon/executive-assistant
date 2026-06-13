from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.materialize_whole_project_gold_map import build_gold_map
from scripts.verify_whole_project_gold_map import verify


ROOT = Path(__file__).resolve().parents[1]
GOLD_MAP_PATH = ROOT / ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"


def test_whole_project_gold_map_is_conservative_and_complete() -> None:
    receipt = build_gold_map(generated_at="2026-06-12T00:00:00Z")
    planes = {plane["key"]: plane for plane in receipt["planes"]}

    assert receipt["contract_name"] == "ea.whole_project_gold_map"
    assert receipt["claim_scope"] == "ea_controlled_receipt_set"
    assert "not a blanket authority claim" in receipt["claim_scope_label"]
    assert planes["ea_release_control"]["status"] == "pass"
    assert planes["design_surface"]["status"] == "bounded_pass"
    assert planes["chummer_core_rules"]["status"] == "pass"
    assert planes["chummer_desktop_ui"]["status"] == "pass"
    assert planes["chummer_hub_public_web"]["status"] == "pass"
    assert planes["mobile_and_second_device"]["status"] == "pass"
    assert planes["media_factory_publication"]["status"] == "bounded_pass"
    assert planes["memorial_voice_demo"]["status"] in {"pass", "separate_risk_zone"}
    if planes["memorial_voice_demo"]["status"] == "pass":
        assert receipt["overall_status"] == "gold"
        assert receipt["gold_claim_allowed"] is True
        assert receipt["blocking_planes"] == []
    else:
        assert receipt["overall_status"] == "not_gold"
        assert receipt["gold_claim_allowed"] is False
        assert receipt["blocking_planes"] == ["memorial_voice_demo"]
    assert planes["chummer_core_rules"]["evidence"]
    assert planes["chummer_desktop_ui"]["evidence"]
    assert planes["chummer_hub_public_web"]["evidence"]
    assert planes["mobile_and_second_device"]["evidence"]
    assert planes["media_factory_publication"]["evidence"]
    rules = "\n".join(receipt["rules"])
    assert "EA flagship readiness does not imply whole Chummer project readiness" in rules
    assert "Unknown external planes block whole-project gold claims" in rules
    assert "Gold here means EA-controlled receipt-set gold" in rules
    assert receipt["ltd_provider_lane_summary"]["poppy_runtime_enabled"] is False
    assert receipt["ltd_provider_lane_summary"]["poppy_lane_state"] == "verified_draft_operator_lane"


def test_whole_project_gold_map_verifier_rejects_gold_overclaim(tmp_path: Path) -> None:
    receipt = build_gold_map(generated_at="2026-06-12T00:00:00Z")
    path = tmp_path / "gold-map.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    assert verify(path) == []

    overclaim = copy.deepcopy(receipt)
    for plane in overclaim["planes"]:
        if plane["key"] == "memorial_voice_demo":
            plane["status"] = "separate_risk_zone"
    overclaim["overall_status"] = "gold"
    overclaim["gold_claim_allowed"] = True
    overclaim["blocking_planes"] = ["memorial_voice_demo"]
    path.write_text(json.dumps(overclaim), encoding="utf-8")

    issues = verify(path)
    assert any("gold_claim_allowed cannot be true" in issue for issue in issues)
    assert any("overall_status cannot be gold" in issue for issue in issues)


def test_materialized_whole_project_gold_map_exists() -> None:
    if not GOLD_MAP_PATH.exists():
        pytest.fail("Run `make materialize-release-assets` to write WHOLE_PROJECT_GOLD_MAP.generated.json")
