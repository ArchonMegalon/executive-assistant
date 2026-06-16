from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.materialize_whole_project_gold_map import build_gold_map, _git_head
from scripts.verify_whole_project_gold_map import verify


ROOT = Path(__file__).resolve().parents[1]
GOLD_MAP_PATH = ROOT / ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"


def test_whole_project_gold_map_is_conservative_and_complete() -> None:
    receipt = build_gold_map(generated_at="2026-06-12T00:00:00Z")
    planes = {plane["key"]: plane for plane in receipt["planes"]}

    assert receipt["contract_name"] == "ea.whole_project_gold_map"
    assert receipt["claim_scope"] == "whole_project_plane_set"
    assert "memorial public-origin experience" in receipt["claim_scope_label"]
    assert planes["ea_release_control"]["status"] in {"pass", "blocked"}
    assert planes["design_surface"]["status"] == "bounded_pass"
    assert planes["chummer_core_rules"]["status"] in {"pass", "unknown_missing_receipt"}
    assert planes["chummer_desktop_ui"]["status"] in {"pass", "unknown_missing_receipt"}
    assert planes["chummer_hub_public_web"]["status"] in {"pass", "unknown_missing_receipt"}
    assert planes["mobile_and_second_device"]["status"] in {"pass", "unknown_missing_receipt"}
    assert planes["media_factory_publication"]["status"] in {"bounded_pass", "unknown_missing_receipt"}
    assert planes["memorial_voice_demo"]["status"] in {"pass", "separate_risk_zone"}
    assert planes["memorial_public_origin_gold"]["status"] in {"pass", "blocked"}
    if planes["memorial_public_origin_gold"]["status"] == "blocked":
        assert receipt["overall_status"] == "not_gold"
        assert receipt["gold_claim_allowed"] is False
        assert "memorial_public_origin_gold" in receipt["blocking_planes"]
    if planes["ea_release_control"]["status"] == "blocked":
        assert receipt["overall_status"] == "not_gold"
        assert receipt["gold_claim_allowed"] is False
        assert "ea_release_control" in receipt["blocking_planes"]
    if planes["chummer_core_rules"]["status"] != "pass":
        assert receipt["overall_status"] == "not_gold"
        assert "chummer_core_rules" in receipt["blocking_planes"]
    if planes["chummer_desktop_ui"]["status"] != "pass":
        assert receipt["overall_status"] == "not_gold"
        assert "chummer_desktop_ui" in receipt["blocking_planes"]
    if planes["chummer_hub_public_web"]["status"] != "pass":
        assert receipt["overall_status"] == "not_gold"
        assert "chummer_hub_public_web" in receipt["blocking_planes"]
    if planes["mobile_and_second_device"]["status"] != "pass":
        assert receipt["overall_status"] == "not_gold"
        assert "mobile_and_second_device" in receipt["blocking_planes"]
    if planes["chummer_core_rules"]["status"] == "pass":
        assert planes["chummer_core_rules"]["evidence"]
    else:
        assert planes["chummer_core_rules"]["missing_evidence"]
    if planes["chummer_desktop_ui"]["status"] == "pass":
        assert planes["chummer_desktop_ui"]["evidence"]
    else:
        assert planes["chummer_desktop_ui"]["missing_evidence"]
    if planes["chummer_hub_public_web"]["status"] == "pass":
        assert planes["chummer_hub_public_web"]["evidence"]
    else:
        assert planes["chummer_hub_public_web"]["missing_evidence"]
    if planes["mobile_and_second_device"]["status"] == "pass":
        assert planes["mobile_and_second_device"]["evidence"]
    else:
        assert planes["mobile_and_second_device"]["missing_evidence"]
    if planes["media_factory_publication"]["status"] == "bounded_pass":
        assert planes["media_factory_publication"]["evidence"]
    else:
        assert planes["media_factory_publication"]["missing_evidence"]
    rules = "\n".join(receipt["rules"])
    assert "EA flagship readiness does not imply whole Chummer project readiness" in rules
    assert "Unknown external planes block whole-project gold claims" in rules
    assert "Whole-project gold requires every listed plane to pass" in rules
    assert receipt["ltd_provider_lane_summary"]["poppy_runtime_enabled"] is False
    assert receipt["ltd_provider_lane_summary"]["poppy_lane_state"] == "verified_draft_operator_lane"
    if receipt["overall_status"] != "gold":
        assert "memorial_room_audio_public_origin.generated.json" in receipt["required_next_receipts"]
    memorial_public_plane = planes["memorial_public_origin_gold"]
    if memorial_public_plane["status"] == "blocked":
        assert "public-origin room/device audio intelligibility receipt" in memorial_public_plane["missing_evidence"]
    assert all(not str(path).startswith("/tmp/") for path in planes["memorial_voice_demo"]["evidence"])
    assert all(not str(path).startswith("/tmp/") for path in memorial_public_plane["evidence"])
    assert all(str(path).startswith(".codex-studio/") for path in planes["memorial_voice_demo"]["evidence"])
    assert all(str(path).startswith(".codex-studio/") for path in memorial_public_plane["evidence"])


def test_whole_project_gold_map_verifier_rejects_gold_overclaim(tmp_path: Path) -> None:
    from scripts import verify_whole_project_gold_map as module

    current_head = _git_head()
    flagship_receipt_path = tmp_path / ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json"
    flagship_receipt_path.parent.mkdir(parents=True, exist_ok=True)
    flagship_receipt_path.write_text(
        json.dumps({"status": "pass", "source_git_head": current_head, "head_semantics": "source_state"}),
        encoding="utf-8",
    )
    weekly_pulse_path = tmp_path / ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json"
    weekly_pulse_path.write_text(
        json.dumps(
            {
                "release_health": {"state": "pass"},
                "flagship_readiness": {"state": "pass"},
                "source_git_head": current_head,
                "head_semantics": "source_state",
            }
        ),
        encoding="utf-8",
    )
    browser_proof_path = tmp_path / ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"
    browser_proof_path.parent.mkdir(parents=True, exist_ok=True)
    browser_proof_path.write_text(
        json.dumps({"status": "pass", "source_git_head": current_head, "head_semantics": "source_state"}),
        encoding="utf-8",
    )
    memorial_voice_receipt = json.loads((ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json").read_text(encoding="utf-8"))
    memorial_voice_receipt["source_git_head"] = current_head
    memorial_voice_receipt["head_semantics"] = "source_state"
    memorial_voice_path = tmp_path / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"
    memorial_voice_path.parent.mkdir(parents=True, exist_ok=True)
    memorial_voice_path.write_text(json.dumps(memorial_voice_receipt), encoding="utf-8")

    receipt = build_gold_map(
        generated_at="2026-06-12T00:00:00Z",
        flagship_receipt_path=flagship_receipt_path,
        weekly_pulse_path=weekly_pulse_path,
        browser_proof_path=browser_proof_path,
        memorial_voice_roundtrip_receipt=memorial_voice_path,
    )
    for plane in receipt["planes"]:
        if plane["key"] == "memorial_voice_demo":
            plane["evidence"] = [".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"]
    path = tmp_path / "gold-map.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    original_root = module.ROOT
    module.ROOT = tmp_path
    try:
        assert module.verify(path) == []
    finally:
        module.ROOT = original_root

    overclaim = copy.deepcopy(receipt)
    for plane in overclaim["planes"]:
        if plane["key"] == "memorial_public_origin_gold":
            plane["status"] = "blocked"
    overclaim["overall_status"] = "gold"
    overclaim["gold_claim_allowed"] = True
    overclaim["blocking_planes"] = ["memorial_public_origin_gold"]
    path.write_text(json.dumps(overclaim), encoding="utf-8")

    module.ROOT = tmp_path
    try:
        issues = module.verify(path)
    finally:
        module.ROOT = original_root
    assert any("gold_claim_allowed cannot be true" in issue for issue in issues)
    assert any("overall_status cannot be gold" in issue for issue in issues)


def test_materialized_whole_project_gold_map_exists() -> None:
    if not GOLD_MAP_PATH.exists():
        pytest.fail("Run `make materialize-release-assets` to write WHOLE_PROJECT_GOLD_MAP.generated.json")


def test_whole_project_gold_map_treats_operator_status_as_generated_only_artifact() -> None:
    from scripts import verify_whole_project_gold_map as module

    assert ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json" in module.GENERATED_RECEIPT_PATHS


def test_whole_project_gold_map_verifier_rejects_tmp_evidence_paths(tmp_path: Path) -> None:
    receipt = build_gold_map(generated_at="2026-06-12T00:00:00Z")
    for plane in receipt["planes"]:
        if plane["key"] == "memorial_public_origin_gold":
            plane["evidence"] = ["/tmp/ea-memorial-refresh-123/.codex-studio/published/memorial_room_audio_public_origin.generated.json"]
    path = tmp_path / "gold-map.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    issues = verify(path)
    assert any("memorial public-origin evidence paths must be repo-relative" in issue for issue in issues)
