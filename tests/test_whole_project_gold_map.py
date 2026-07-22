from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.materialize_whole_project_gold_map import build_gold_map, _git_head, _room_receipt_status
from scripts.verify_whole_project_gold_map import verify


ROOT = Path(__file__).resolve().parents[1]
GOLD_MAP_PATH = ROOT / ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"


def test_whole_project_gold_map_accepts_repo_relative_output_path() -> None:
    receipt = build_gold_map(
        output_path=Path(".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"),
        generated_at="2026-06-12T00:00:00Z",
    )

    assert receipt["output_path"] == ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"


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
    assert planes["telegram_video_delivery"]["status"] in {"pass", "bounded_pass", "blocked", "unknown_missing_receipt"}
    assert planes["memorial_voice_demo"]["status"] in {"pass", "separate_risk_zone"}
    assert planes["memorial_public_origin_gold"]["status"] in {"pass", "blocked"}
    assert "design_surface" in receipt["blocking_planes"]
    assert "ltd_provider_lanes" in receipt["blocking_planes"]
    assert any("canonical Chummer product/UI design review receipt" in item for item in planes["design_surface"]["missing_evidence"])
    assert any("documentation humanization review receipt" in item for item in planes["design_surface"]["missing_evidence"])
    assert any("asset-specific media factory publication receipt" in item for item in planes["media_factory_publication"]["missing_evidence"])
    assert any("human publication approval receipt" in item for item in planes["media_factory_publication"]["missing_evidence"])
    assert any("canonical Chummer product/UI design review receipt" in item for item in receipt["required_next_receipts"])
    assert any("asset-specific media factory publication receipt" in item for item in receipt["required_next_receipts"])
    assert receipt["overall_status"] == "not_gold"
    assert receipt["gold_claim_allowed"] is False
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
    if planes["telegram_video_delivery"]["status"] == "pass":
        assert planes["telegram_video_delivery"]["evidence"]
    else:
        assert planes["telegram_video_delivery"]["missing_evidence"]
    rules = "\n".join(receipt["rules"])
    assert "EA flagship readiness does not imply whole Chummer project readiness" in rules
    assert "Unknown external planes block whole-project gold claims" in rules
    assert "Whole-project gold requires every listed plane to pass" in rules
    assert "Telegram video delivery requires a dedicated live delivery receipt" in rules
    assert receipt["ltd_provider_lane_summary"]["poppy_runtime_enabled"] is False
    assert receipt["ltd_provider_lane_summary"]["poppy_lane_state"] == "verified_draft_operator_lane"
    assert receipt["ltd_provider_lane_summary"]["missing_lane_checks"]
    provider_contracts = dict(receipt["ltd_provider_lane_summary"]["provider_contracts"])
    assert provider_contracts["status"] in {"contract_pass_live_provider_pending", "missing"}
    if provider_contracts["status"] == "contract_pass_live_provider_pending":
        assert provider_contracts["proof_scope"] == "local_contract_exercise"
        assert provider_contracts["live_provider_runtime_verified"] is False
        assert receipt["ltd_provider_lane_summary"]["contract_backed_check_count"] >= 10
    assert "poppy_draft_workbench" in receipt["ltd_provider_lane_summary"]["whole_project_excluded_lanes"]
    assert "public_signal_ingest" in receipt["ltd_provider_lane_summary"]["whole_project_excluded_lanes"]
    assert "hedy_meeting_evidence" in receipt["ltd_provider_lane_summary"]["whole_project_pending_lanes"]
    assert "subscribr_chummer_script_factory" in receipt["ltd_provider_lane_summary"]["whole_project_pending_lanes"]
    ltd_plane = planes["ltd_provider_lanes"]
    assert ltd_plane["missing_evidence"]
    assert any("hedy_meeting_evidence:hedy_provider_capability" in item for item in ltd_plane["missing_evidence"])
    assert any("subscribr_chummer_script_factory:script_roundtrip" in item for item in ltd_plane["missing_evidence"])
    assert any("provider_contract_status=" in item for item in ltd_plane["design_notes"])
    assert any("provider_contract_live_verified=False" in item for item in ltd_plane["design_notes"])
    assert not any("promotion or explicit whole-project exclusion receipt" in item for item in ltd_plane["missing_evidence"])
    assert not any("poppy_draft_workbench" in item for item in ltd_plane["missing_evidence"])
    if planes["memorial_public_origin_gold"]["status"] == "blocked":
        assert any("room/device audio intelligibility" in item for item in receipt["required_next_receipts"])
    memorial_public_plane = planes["memorial_public_origin_gold"]
    if memorial_public_plane["status"] == "blocked":
        assert "public-origin room/device audio intelligibility receipt with manual attestation" in memorial_public_plane["missing_evidence"]
    assert ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json" not in memorial_public_plane["evidence"]
    assert all(not str(path).startswith("/tmp/") for path in planes["memorial_voice_demo"]["evidence"])
    assert all(not str(path).startswith("/tmp/") for path in memorial_public_plane["evidence"])
    assert all(str(path).startswith(".codex-studio/") for path in planes["memorial_voice_demo"]["evidence"])
    assert all(
        str(path).startswith(".codex-studio/") or str(path).startswith(".codex-design/")
        for path in memorial_public_plane["evidence"]
    )


def test_whole_project_gold_map_rejects_old_room_audio_receipts_without_spoken_loop_checks(tmp_path: Path) -> None:
    receipt = {
        "status": "pass",
        "proof_type": "manual_room_attestation",
        "manual_attestation": {
            "attestation_id": "room-review-001",
            "signed_at": "2026-06-18T12:00:00Z",
            "ci_must_not_auto_assert": True,
        },
        "checks": {
            "actual_device_checked": True,
            "actual_speaker_checked": True,
            "first_syllable_not_clipped": True,
            "intelligibility_confirmed": True,
            "answer_text_fallback_visible": True,
            "no_internet_search_confirmed": True,
        },
    }
    path = tmp_path / "room.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    assert _room_receipt_status(path) == "blocked"

    receipt["checks"].update(
        {
            "normal_spoken_turn_confirmed": True,
            "interruption_behavior_confirmed": True,
            "retry_path_confirmed": True,
        }
    )
    path.write_text(json.dumps(receipt), encoding="utf-8")

    assert _room_receipt_status(path) == "pass"


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


def test_whole_project_gold_map_does_not_consume_memorial_operator_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.materialize_whole_project_gold_map as materialize
    import scripts.verify_whole_project_gold_map as verify_module

    operator_status_path = (
        ROOT / ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json"
    ).resolve()
    materializer_reads: list[Path] = []
    original_materializer_json = materialize._json

    def tracked_materializer_json(path: Path) -> dict[str, object]:
        assert path.resolve() != operator_status_path
        materializer_reads.append(path)
        return original_materializer_json(path)

    monkeypatch.setattr(materialize, "_json", tracked_materializer_json)
    receipt = materialize.build_gold_map(generated_at="2026-06-12T00:00:00Z")
    plane = next(plane for plane in receipt["planes"] if plane["key"] == "memorial_public_origin_gold")
    assert materializer_reads
    assert not any(
        str(item).endswith(
            ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json"
        )
        for item in plane["evidence"]
    )

    path = tmp_path / "gold-map.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    original_verifier_json = verify_module._json

    def guarded_verifier_json(candidate: Path) -> dict[str, object]:
        assert candidate.resolve() != operator_status_path
        return original_verifier_json(candidate)

    monkeypatch.setattr(verify_module, "_json", guarded_verifier_json)
    verify_module.verify(path)


def test_whole_project_gold_map_source_head_skips_generated_only_head_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.materialize_whole_project_gold_map as module

    monkeypatch.setattr(module, "resolve_source_state_head", lambda root: "SOURCE_HEAD")

    receipt = module.build_gold_map(generated_at="2026-06-12T00:00:00Z")

    assert receipt["source_git_head"] == "SOURCE_HEAD"


def test_whole_project_gold_map_promotes_telegram_video_delivery_only_with_live_receipt(tmp_path: Path) -> None:
    from app.domain.models import ObservationEvent
    from scripts.materialize_telegram_video_delivery_live_receipt import EVENT_TYPE
    from scripts.materialize_telegram_video_delivery_live_receipt import build_receipt as build_live_receipt

    operator_path = tmp_path / ".codex-studio/published/telegram_video_delivery_operator.generated.json"
    operator_path.parent.mkdir(parents=True, exist_ok=True)
    operator_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.telegram_video_delivery_operator_receipt",
                "status": "bounded_pass",
                "blocking_checks": [],
            }
        ),
        encoding="utf-8",
    )
    live_path = tmp_path / ".codex-studio/published/telegram_video_delivery_live.generated.json"
    build_live_receipt(
        output_path=live_path,
        observations=[
            ObservationEvent(
                observation_id="obs-live-video-1",
                principal_id="principal-tibor",
                channel="telegram",
                event_type=EVENT_TYPE,
                payload={
                    "receipt_type": "telegram_video_delivery",
                    "delivery_kind": "video",
                    "telegram_method": "sendVideo",
                    "chat_id": "123456789",
                    "source_message_id": "source-message-42",
                    "provider": "local_source_video_fx",
                    "status": "sent",
                    "message_ids": ["sent-video-77"],
                    "source_video": {
                        "has_source_video": True,
                        "source_url_raw_stored": False,
                        "source_url_sha256": "a" * 64,
                        "source_host": "api.telegram.org",
                        "source_path_redacted": "/file/bot<redacted>/videos/file.mp4",
                    },
                },
                created_at="2026-06-18T10:00:00+00:00",
                source_id="telegram:123456789",
                external_id="source-message-42",
                dedupe_key="telegram-video-delivery:123456789:source-message-42:sent-video-77",
            )
        ],
        generated_at="2026-06-18T10:00:00Z",
    )

    receipt = build_gold_map(
        telegram_video_delivery_receipt=operator_path,
        telegram_video_delivery_live_receipt=live_path,
        generated_at="2026-06-18T10:00:00Z",
    )
    telegram_plane = {plane["key"]: plane for plane in receipt["planes"]}["telegram_video_delivery"]

    assert telegram_plane["status"] == "pass"
    assert telegram_plane["missing_evidence"] == []
    assert any("telegram_video_delivery_operator.generated.json" in item for item in telegram_plane["evidence"])
    assert any("telegram_video_delivery_live.generated.json" in item for item in telegram_plane["evidence"])
