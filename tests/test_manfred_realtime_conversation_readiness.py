from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


GENERATED_AT = "2026-06-20T10:15:00Z"
ROOM_CHECK_IDS = [
    "actual_device_checked",
    "actual_speaker_checked",
    "first_syllable_not_clipped",
    "intelligibility_confirmed",
    "answer_text_fallback_visible",
    "no_internet_search_confirmed",
    "normal_spoken_turn_confirmed",
    "interruption_behavior_confirmed",
    "retry_path_confirmed",
]


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_manfred_contact_opening_captured_audio_has_explicit_known_fingerprint() -> None:
    route_source = (
        Path(__file__).resolve().parents[1] / "ea" / "app" / "api" / "routes" / "public_memorials.py"
    ).read_text(encoding="utf-8")

    assert "a5589abeb9b81ab6fb991d280e285d3416ec1c29a92013bc5e47fee3d2198d88" in route_source
    assert "Hallo Manfred, kannst du jetzt mit mir sprechen?" in route_source
    assert "local_non_silent_contact_opening_rescue" not in route_source


def _operator_status(*, ready: bool) -> dict[str, object]:
    return {
        "status": "pass" if ready else "blocked",
        "current_label": "Memorial public-origin gold: pass" if ready else "Memorial public-origin gold: blocked",
        "room_audio_receipt": "pass" if ready else "missing_or_blocked",
        "spoken_conversation_stt": {
            "status": "pass",
            "production_eligible": True,
            "production_provider": "full_runtime",
            "provider_label": "cartesia/ink-whisper+enhanced_wav",
            "passed_samples": 4,
            "sample_count": 4,
            "avg_token_f1": 1.0,
            "avg_wer": 0.0,
            "ground_truth_fixture_mode": "captured_external" if ready else "synthetic_only",
            "real_captured_fixture_status": "captured_candidate_benchmark_pass" if ready else "captured_candidate_diagnostic_blocked",
            "next_action": "" if ready else "rerun_operator_local_full_text_benchmark_or_correct_ground_truth_transcript",
            "receipt_path": ".codex-studio/published/memorial_stt_provider_benchmark.generated.json",
            "scoring": {
                "raw_transcript_fields": False,
                "redacted_text_fields": True,
            },
        },
        "captured_candidate_diagnostic": {
            "status": "ready" if ready else "blocked",
            "diagnostic_status": "ready",
            "promotion_allowed": ready,
            "may_update_fixture_manifest": ready,
            "captured_row_count": 1,
            "row_failure_codes": [] if ready else ["transcript_hash_mismatch", "required_tokens_missing"],
            "next_action": "" if ready else "rerun_operator_local_full_text_benchmark_or_correct_ground_truth_transcript",
            "receipt_path": ".codex-studio/published/memorial_stt_captured_candidate_diagnostic.generated.json",
            "privacy": {
                "candidate_raw_text_fields": False,
                "raw_transcript_fields": False,
                "redacted_text_fields": True,
            },
        },
        "spoken_conversation_tts": {
            "status": "pass",
            "premium_status": "pass" if ready else "blocked",
            "direct_tts_audio_status": "pass",
            "conversation_turn_audio_status": "pass",
            "direct_tts_f1": 1.0,
            "conversation_turn_audio_f1": 1.0,
            "browser_audio_ready_for_ui": True,
            "browser_audio_transport": "ui_playback_probe",
            "browser_play_calls": 1,
            "browser_play_ended": 1,
            "room_audio_receipt": "pass" if ready else "blocked",
            "premium_failed_codes": [] if ready else ["room_audio_attestation_not_pass"],
            "next_action": "" if ready else "collect_real_room_audio_attestation",
            "receipt_path": ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
            "browser_receipt_path": ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
            "room_audio_receipt_path": ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
        },
        "room_audio_attestation_packet": {
            "status": "ready",
            "manual_only": True,
            "ci_must_not_auto_assert": True,
            "required_check_ids": ROOM_CHECK_IDS,
            "operator_command": "make materialize-memorial-room-audio-gold-clean",
            "next_action": "collect_real_room_audio_attestation",
            "receipt_path": ".codex-studio/published/memorial_room_audio_attestation_packet.generated.json",
        },
    }


def _ready_evidence_payloads(
    materializer: ModuleType,
    *,
    generated_at: str,
) -> dict[str, dict[str, object]]:
    source_state = {
        "generated_at": generated_at,
        "source_git_head": materializer.resolve_source_state_head(materializer.REPO_ROOT),
        "source_state_fingerprint": materializer.resolve_source_worktree_fingerprint(materializer.REPO_ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }
    return {
        "memorial_stt_provider_benchmark.generated.json": {
            "contract_name": "ea.memorial_stt_provider_benchmark",
            "status": "pass",
            "fixture_quality_status": "pass",
            "fixture_quality_failed_codes": [],
            "provider_ranking": [
                {
                    "provider": "full_runtime",
                    "production_eligible": True,
                    "passed_samples": 4,
                    "sample_count": 4,
                    "avg_token_f1": 1.0,
                    "avg_wer": 0.0,
                }
            ],
            "rows": [
                {
                    "sample": "captured_candidate",
                    "variant": "captured",
                    "full_runtime": {"passed": True},
                }
            ],
            **source_state,
        },
        "memorial_stt_captured_candidate_diagnostic.generated.json": {
            "contract_name": "ea.memorial_stt_captured_candidate_diagnostic",
            "status": "pass",
            "diagnostic_status": "ready",
            "promotion_allowed": True,
            "may_update_fixture_manifest": True,
            "captured_row_count": 1,
            "blocker_summary": {"row_failure_codes": []},
            **source_state,
        },
        "memorial_voice_roundtrip_public_origin.generated.json": {
            "contract_name": "ea.memorial_voice_roundtrip_exit_gate",
            "status": "pass",
            "gold_claim_allowed": True,
            "failed_codes": [],
            "metrics": {
                "direct_tts_f1": 1.0,
                "conversation_turn_audio_f1": 1.0,
            },
            **source_state,
        },
        "memorial_realtime_browser_public_origin.generated.json": {
            "contract_name": "ea.memorial_realtime_browser_exit_gate",
            "status": "pass",
            "failed_codes": [],
            "audio_ready_for_ui": True,
            "ui_audio_play_calls": 1,
            "ui_audio_play_ended": 1,
            **source_state,
        },
        "memorial_room_audio_public_origin.generated.json": {
            "contract_name": "ea.memorial_room_audio_public_origin",
            "status": "pass",
            "gold_claim_allowed": True,
            "failed_codes": [],
            **source_state,
        },
        "memorial_room_audio_attestation_packet.generated.json": {
            "contract_name": "ea.memorial_room_audio_attestation_packet",
            "status": "ready",
            "manual_only": True,
            "ci_must_not_auto_assert": True,
            "operator_command": "make materialize-memorial-room-audio-gold-clean",
            "required_checks": [{"id": check_id} for check_id in ROOM_CHECK_IDS],
            **source_state,
        },
    }


def _write_evidence_payloads(root: Path, payloads: dict[str, dict[str, object]]) -> None:
    for name, payload in payloads.items():
        (root / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def test_manfred_realtime_refresh_aggregates_current_redacted_receipts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    secret = "private-transcript-must-not-cross-readiness-boundary"
    source_state = {
        "generated_at": materializer._now(),
        "source_git_head": materializer.resolve_source_state_head(materializer.REPO_ROOT),
        "source_state_fingerprint": materializer.resolve_source_worktree_fingerprint(materializer.REPO_ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }
    receipts = {
        "memorial_stt_provider_benchmark.generated.json": {
            "contract_name": "ea.memorial_stt_provider_benchmark",
            "status": "blocked",
            "fixture_quality_status": "pass",
            "provider_ranking": [
                {
                    "provider": "full_runtime",
                    "production_eligible": False,
                    "passed_samples": 3,
                    "sample_count": 4,
                    "avg_token_f1": 0.97,
                    "avg_wer": 0.03,
                }
            ],
            "rows": [
                {
                    "sample": "captured_candidate",
                    "variant": "captured",
                    "full_runtime": {"passed": False, "actual_text": secret},
                }
            ],
            "private_debug": secret,
            **source_state,
        },
        "memorial_stt_captured_candidate_diagnostic.generated.json": {
            "contract_name": "ea.memorial_stt_captured_candidate_diagnostic",
            "status": "blocked",
            "diagnostic_status": "ready",
            "promotion_allowed": False,
            "may_update_fixture_manifest": False,
            "captured_row_count": 1,
            "blocker_summary": {"row_failure_codes": ["transcript_hash_mismatch"]},
            "private_debug": secret,
            **source_state,
        },
        "memorial_voice_roundtrip_public_origin.generated.json": {
            "contract_name": "ea.memorial_voice_roundtrip_exit_gate",
            "status": "pass",
            "gold_claim_allowed": True,
            "failed_codes": [],
            "metrics": {
                "direct_tts_f1": 1.0,
                "conversation_turn_audio_f1": 1.0,
            },
            "private_debug": secret,
            **source_state,
        },
        "memorial_realtime_browser_public_origin.generated.json": {
            "contract_name": "ea.memorial_realtime_browser_exit_gate",
            "status": "pass",
            "failed_codes": [],
            "audio_ready_for_ui": True,
            "ui_audio_play_calls": 1,
            "ui_audio_play_ended": 1,
            "private_debug": secret,
            **source_state,
        },
        "memorial_room_audio_public_origin.generated.json": {
            "contract_name": "ea.memorial_room_audio_public_origin",
            "status": "fail",
            "gold_claim_allowed": False,
            "failed_codes": ["manual_attestation_id_missing"],
            "private_notes": secret,
            **source_state,
        },
        "memorial_room_audio_attestation_packet.generated.json": {
            "contract_name": "ea.memorial_room_audio_attestation_packet",
            "status": "ready",
            "manual_only": True,
            "ci_must_not_auto_assert": True,
            "operator_command": "make materialize-memorial-room-audio-gold-clean",
            "required_checks": [{"id": check_id} for check_id in ROOM_CHECK_IDS],
            "private_notes": secret,
            **source_state,
        },
    }
    for name, payload in receipts.items():
        (tmp_path / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    status = materializer._operator_status_from_receipts(tmp_path)
    monkeypatch.setattr(materializer, "_operator_status_from_receipts", lambda: status)
    receipt_path = tmp_path / "manfred-realtime-refreshed.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )

    assert receipt["evidence_source"] == "receipt_aggregation"
    assert receipt["status"] == "blocked_realtime_prerequisites"
    assert receipt["ready_for_realtime_conversation_review"] is False
    assert receipt["stt"]["status"] == "blocked"
    assert receipt["captured_candidate_diagnostic"]["status"] == "blocked"
    assert receipt["tts"]["status"] == "pass"
    assert receipt["tts"]["premium_status"] == "blocked"
    assert receipt["tts"]["room_audio_receipt"] == "blocked"
    assert set(receipt["input_evidence"]) == set(materializer.EVIDENCE_RECEIPTS)
    for evidence in receipt["input_evidence"].values():
        assert len(evidence["receipt_sha256"]) == 64
        assert evidence["source_state_matches_current"] is True
        assert evidence["fresh"] is True
        assert evidence["raw_private_context_exposed"] is False
        assert evidence["raw_transcript_fields_exposed"] is False
        assert evidence["raw_credentials_exposed"] is False
        assert evidence["raw_receipt_payload_exposed"] is False
    assert secret not in json.dumps(receipt, sort_keys=True)

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_manfred_realtime_refresh_allows_only_fresh_current_ready_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    _write_evidence_payloads(
        tmp_path,
        _ready_evidence_payloads(materializer, generated_at=materializer._now()),
    )
    status = materializer._operator_status_from_receipts(tmp_path)
    monkeypatch.setattr(materializer, "_operator_status_from_receipts", lambda: status)
    receipt_path = tmp_path / "manfred-realtime-ready-aggregated.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )

    assert receipt["status"] == "ready_for_realtime_conversation_review"
    assert receipt["ready_for_realtime_conversation_review"] is True
    assert receipt["blocked_checks"] == []
    assert all(row["fresh"] is True for row in receipt["input_evidence"].values())
    assert all(
        row["source_state_matches_current"] is True
        for row in receipt["input_evidence"].values()
    )
    assert verifier.verify_manfred_realtime_conversation_readiness(receipt_path)["status"] == "pass"


def test_manfred_realtime_verifier_reaggregates_source_receipt_content(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    _write_evidence_payloads(tmp_path, payloads)
    aggregate = materializer._operator_status_from_receipts
    status = aggregate(tmp_path)
    monkeypatch.setattr(materializer, "_operator_status_from_receipts", lambda: status)
    receipt_path = tmp_path / "manfred-realtime-source-bound.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )
    payloads["memorial_room_audio_public_origin.generated.json"]["failed_codes"] = [
        "manual_attestation_invalid"
    ]
    _write_evidence_payloads(tmp_path, payloads)
    refreshed_evidence = aggregate(tmp_path)["input_evidence"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["input_evidence"] = refreshed_evidence
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_tts_derivation_mismatch" in verification["issues"]


def test_manfred_realtime_verifier_rejects_ready_claim_outside_aggregation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    _write_evidence_payloads(
        tmp_path,
        _ready_evidence_payloads(materializer, generated_at=materializer._now()),
    )
    status = materializer._operator_status_from_receipts(tmp_path)
    monkeypatch.setattr(materializer, "_operator_status_from_receipts", lambda: status)
    receipt_path = tmp_path / "manfred-realtime-source-bypass.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["evidence_source"] = "conservative_default"
    receipt["input_evidence"] = {}
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_blocked_checks_inconsistent" in verification["issues"]
    assert "manfred_realtime_status_inconsistent" in verification["issues"]


def test_manfred_realtime_refresh_rejects_expired_ready_evidence(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    _write_evidence_payloads(
        tmp_path,
        _ready_evidence_payloads(materializer, generated_at="2020-01-01T00:00:00Z"),
    )

    status = materializer._operator_status_from_receipts(tmp_path)

    assert status["status"] == "blocked"
    assert status["spoken_conversation_stt"]["production_eligible"] is False
    assert status["spoken_conversation_tts"]["status"] == "blocked"
    assert status["room_audio_attestation_packet"]["status"] == "blocked"
    assert all(row["fresh"] is False for row in status["input_evidence"].values())


def test_manfred_realtime_refresh_rejects_contradictory_or_wrong_contract_evidence(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    payloads["memorial_room_audio_public_origin.generated.json"]["failed_codes"] = [
        "manual_attestation_invalid"
    ]
    _write_evidence_payloads(tmp_path, payloads)

    contradictory = materializer._operator_status_from_receipts(tmp_path)

    assert contradictory["status"] == "blocked"
    assert contradictory["spoken_conversation_tts"]["room_audio_receipt"] == "blocked"

    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    payloads["memorial_room_audio_public_origin.generated.json"]["failed_codes"] = (
        "manual_attestation_invalid"
    )
    _write_evidence_payloads(tmp_path, payloads)

    malformed_failure_codes = materializer._operator_status_from_receipts(tmp_path)

    assert malformed_failure_codes["status"] == "blocked"
    assert (
        malformed_failure_codes["spoken_conversation_tts"]["room_audio_receipt"]
        == "blocked"
    )

    payloads = _ready_evidence_payloads(materializer, generated_at=materializer._now())
    payloads["memorial_stt_provider_benchmark.generated.json"]["contract_name"] = "wrong.contract"
    _write_evidence_payloads(tmp_path, payloads)

    wrong_contract = materializer._operator_status_from_receipts(tmp_path)

    assert wrong_contract["status"] == "blocked"
    assert wrong_contract["spoken_conversation_stt"]["production_eligible"] is False
    assert wrong_contract["input_evidence"]["stt_benchmark"]["contract_valid"] is False


def test_manfred_realtime_provided_status_is_strictly_sanitized(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    secret = "raw-private-transcript-and-api-key"
    operator_status = _operator_status(ready=False)
    operator_status["spoken_conversation_stt"]["raw_transcript"] = secret  # type: ignore[index]
    operator_status["captured_candidate_diagnostic"]["api_key"] = secret  # type: ignore[index]
    operator_status["spoken_conversation_tts"]["private_audio_path"] = secret  # type: ignore[index]
    operator_status["room_audio_attestation_packet"]["private_notes"] = secret  # type: ignore[index]
    operator_status["input_evidence"] = {"raw": secret}
    receipt_path = tmp_path / "provided-status-sanitized.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=operator_status,
    )

    assert receipt["evidence_source"] == "provided_operator_status"
    assert receipt["input_evidence"] == {}
    assert "current_evidence_aggregation_required" in receipt["blocked_checks"]
    assert receipt["realtime_conversation_claim_allowed"] is False
    assert secret not in json.dumps(receipt, sort_keys=True)
    assert verifier.verify_manfred_realtime_conversation_readiness(receipt_path)["status"] == "pass"


def test_manfred_realtime_verifier_rejects_unsafe_aggregated_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "unsafe-evidence.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=_operator_status(ready=False),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["evidence_source"] = "receipt_aggregation"
    receipt["raw_private_transcript"] = "must-not-pass"
    receipt["operator_action"]["raw_private_payload"] = "must-not-pass"
    receipt["input_evidence"] = {
        key: {
            "receipt_name": receipt_name,
            "present": True,
            "contract_name": contract_name,
            "contract_valid": True,
            "status": "pass",
            "generated_at": GENERATED_AT,
            "receipt_sha256": "a" * 64,
            "source_git_head_present": True,
            "source_git_head_matches_current": True,
            "source_state_fingerprint_present": True,
            "source_state_matches_current": True,
            "raw_private_context_exposed": key == "stt_benchmark",
            "raw_transcript_fields_exposed": False,
            "raw_credentials_exposed": False,
            "raw_receipt_payload_exposed": False,
        }
        for key, (receipt_name, contract_name) in materializer.EVIDENCE_RECEIPTS.items()
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_top_level_fields_unexpected" in verification["issues"]
    assert "manfred_realtime_operator_action_fields_unexpected" in verification["issues"]
    assert (
        "manfred_realtime_input_evidence_raw_flag_not_false:stt_benchmark:raw_private_context_exposed"
        in verification["issues"]
    )
    assert "manfred_realtime_input_evidence_not_current:stt_benchmark" in verification["issues"]


def test_manfred_realtime_readiness_blocks_real_stt_and_room_audio_without_overclaiming(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "manfred-realtime.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=_operator_status(ready=False),
    )

    assert receipt["status"] == "blocked_realtime_prerequisites"
    assert receipt["generated_by"] == "ea/scripts/materialize_manfred_realtime_conversation_readiness.py"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["source_git_head"]
    assert receipt["source_state_fingerprint"]
    assert (
        receipt["source_state_fingerprint_semantics"]
        == "worktree_source_files_sha256_excluding_generated_only_paths"
    )
    assert receipt["ready_for_realtime_conversation_review"] is False
    assert receipt["realtime_conversation_claim_allowed"] is False
    assert receipt["premium_spoken_claim_allowed"] is False
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["evidence_source"] == "provided_operator_status"
    assert "real_captured_stt_fixture_ready" in receipt["blocked_checks"]
    assert "captured_candidate_diagnostic_clean" in receipt["blocked_checks"]
    assert "room_audio_receipt_passed" in receipt["blocked_checks"]
    assert "manual_room_checks_confirmed" in receipt["blocked_checks"]
    assert receipt["room_audio_attestation"]["manual_only"] is True
    assert receipt["room_audio_attestation"]["ci_must_not_auto_assert"] is True
    assert "interruption_behavior_confirmed" in receipt["room_audio_attestation"]["required_check_ids"]
    assert receipt["privacy"]["raw_private_context_exposed"] is False
    assert receipt["next_action"] == "collect_real_room_audio_attestation"
    assert receipt["next_action_href"] == "/memorials/manfred/voice-config"
    assert receipt["next_action_label"] == "Spoken conversation proof"
    assert receipt["next_action_method"] == "get"
    assert receipt["operator_action_key"] == "manfred_stt_tts_realtime_conversation"
    operator_action = receipt["operator_action"]
    assert operator_action["status"] == "action_required"
    assert operator_action["operator_action_key"] == "manfred_stt_tts_realtime_conversation"
    assert operator_action["user_action_required"] is True
    assert operator_action["delivery_policy"] == "action_required_only"
    assert operator_action["telegram_push_allowed"] is True
    assert operator_action["manual_only"] is True
    assert operator_action["ci_must_not_auto_assert"] is True
    assert operator_action["required_check_count"] == len(ROOM_CHECK_IDS)
    assert operator_action["raw_private_context_exposed"] is False
    assert operator_action["raw_transcript_fields_exposed"] is False

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_manfred_realtime_readiness_can_be_ready_without_closing_whole_goal(monkeypatch, tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    _write_evidence_payloads(
        tmp_path,
        _ready_evidence_payloads(materializer, generated_at=materializer._now()),
    )
    status = materializer._operator_status_from_receipts(tmp_path)
    monkeypatch.setattr(materializer, "_operator_status_from_receipts", lambda: status)
    receipt_path = tmp_path / "manfred-realtime-ready.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )

    assert receipt["status"] == "ready_for_realtime_conversation_review"
    assert receipt["ready_for_realtime_conversation_review"] is True
    assert receipt["realtime_conversation_claim_allowed"] is False
    assert receipt["premium_spoken_claim_allowed"] is False
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["evidence_source"] == "receipt_aggregation"
    assert receipt["blocked_checks"] == []
    assert receipt["interaction_acceptance"]["ongoing_cinematic_narration_not_scene_bound"] is True
    assert "operator acceptance that this behaves like an ongoing spoken conversation" in receipt["required_live_proof_after_readiness"]
    assert receipt["next_action"] == "review_realtime_conversation_in_real_room"
    assert receipt["next_action_href"] == "/memorials/manfred/voice-config"
    assert receipt["next_action_label"] == "Spoken conversation proof"
    assert receipt["next_action_method"] == "get"
    assert receipt["operator_action_key"] == ""
    assert receipt["operator_action"]["status"] == "not_required"
    assert receipt["operator_action"]["user_action_required"] is False
    assert receipt["operator_action"]["delivery_policy"] == "queue_only"
    assert receipt["operator_action"]["telegram_push_allowed"] is False

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_manfred_realtime_readiness_verifier_rejects_overclaims(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "tampered.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=_operator_status(ready=False),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["contract_name"] = "wrong.contract"
    receipt["goal_completion_claim_allowed"] = True
    receipt["generated_by"] = "wrong"
    receipt["realtime_conversation_claim_allowed"] = True
    receipt["captured_candidate_diagnostic"]["promotion_allowed"] = True
    receipt["privacy"]["candidate_raw_text_fields"] = True
    receipt["required_live_proof_after_readiness"] = []
    receipt["next_action_href"] = ""
    receipt["next_action_label"] = ""
    receipt["next_action_method"] = ""
    receipt["operator_action"]["raw_token_exposed"] = True
    receipt["operator_action"]["telegram_push_allowed"] = False
    receipt["operator_action_key"] = ""
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_contract_name_mismatch" in verification["issues"]
    assert "manfred_realtime_generated_by_mismatch" in verification["issues"]
    assert "manfred_realtime_goal_completion_overclaim" in verification["issues"]
    assert "manfred_realtime_claim_overclaim" in verification["issues"]
    assert "manfred_realtime_realtime_claim_inconsistent" in verification["issues"]
    assert "manfred_realtime_captured_diagnostic_overclaim" in verification["issues"]
    assert "manfred_realtime_privacy_flag_not_false:candidate_raw_text_fields" in verification["issues"]
    assert "manfred_realtime_required_live_proof_incomplete" in verification["issues"]
    assert "manfred_realtime_next_action_method_missing" in verification["issues"]
    assert "manfred_realtime_blocked_next_action_href_drift" in verification["issues"]
    assert "manfred_realtime_blocked_next_action_label_drift" in verification["issues"]
    assert "manfred_realtime_operator_action_raw_flag_not_false:raw_token_exposed" in verification["issues"]
    assert "manfred_realtime_operator_action_push_flag_mismatch" in verification["issues"]
    assert "manfred_realtime_operator_action_key_missing" in verification["issues"]


def test_manfred_realtime_readiness_verifier_rejects_stale_source_state(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "stale.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=_operator_status(ready=False),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source_git_head"] = "old-source-head"
    receipt["source_state_fingerprint"] = "old-source-fingerprint"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_source_head_stale" in verification["issues"]
    assert "manfred_realtime_source_fingerprint_stale" in verification["issues"]


def test_manfred_realtime_readiness_verifier_rejects_missing_source_stamp(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "unstamped.generated.json"
    materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=_operator_status(ready=False),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for key in (
        "source_git_head",
        "head_semantics",
        "source_state_fingerprint",
        "source_state_fingerprint_semantics",
    ):
        receipt.pop(key, None)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_source_git_head_missing" in verification["issues"]
    assert "manfred_realtime_source_fingerprint_missing" in verification["issues"]
    assert "manfred_realtime_head_semantics_missing" in verification["issues"]
    assert "manfred_realtime_source_fingerprint_semantics_missing" in verification["issues"]


def test_manfred_realtime_readiness_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    receipt_path = tmp_path / "cli-manfred-realtime.generated.json"
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_manfred_realtime_conversation_readiness.py"),
            "--receipt",
            str(receipt_path),
            "--generated-at",
            GENERATED_AT,
            "--no-refresh",
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    assert receipt_path.is_file()
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["evidence_source"] == "conservative_default"

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_manfred_realtime_conversation_readiness.py"),
            "--receipt",
            str(receipt_path),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )

    assert verified.returncode == 0, verified.stderr + verified.stdout
    assert json.loads(verified.stdout)["status"] == "pass"
