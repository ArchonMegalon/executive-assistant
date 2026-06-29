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
    assert receipt["ready_for_realtime_conversation_review"] is False
    assert receipt["realtime_conversation_claim_allowed"] is False
    assert receipt["premium_spoken_claim_allowed"] is False
    assert receipt["goal_completion_claim_allowed"] is False
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

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_manfred_realtime_readiness_can_be_ready_without_closing_whole_goal(tmp_path: Path) -> None:
    materializer = _load_script("materialize_manfred_realtime_conversation_readiness")
    verifier = _load_script("verify_manfred_realtime_conversation_readiness")
    receipt_path = tmp_path / "manfred-realtime-ready.generated.json"

    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        operator_status=_operator_status(ready=True),
    )

    assert receipt["status"] == "ready_for_realtime_conversation_review"
    assert receipt["ready_for_realtime_conversation_review"] is True
    assert receipt["realtime_conversation_claim_allowed"] is True
    assert receipt["premium_spoken_claim_allowed"] is True
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["blocked_checks"] == []
    assert receipt["interaction_acceptance"]["ongoing_cinematic_narration_not_scene_bound"] is True
    assert "operator acceptance that this behaves like an ongoing spoken conversation" in receipt["required_live_proof_after_readiness"]
    assert receipt["next_action"] == "review_realtime_conversation_in_real_room"
    assert receipt["next_action_href"] == "/memorials/manfred/voice-config"
    assert receipt["next_action_label"] == "Spoken conversation proof"
    assert receipt["next_action_method"] == "get"

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
    receipt["goal_completion_claim_allowed"] = True
    receipt["realtime_conversation_claim_allowed"] = True
    receipt["captured_candidate_diagnostic"]["promotion_allowed"] = True
    receipt["privacy"]["candidate_raw_text_fields"] = True
    receipt["required_live_proof_after_readiness"] = []
    receipt["next_action_href"] = ""
    receipt["next_action_label"] = ""
    receipt["next_action_method"] = ""
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_manfred_realtime_conversation_readiness(receipt_path)

    assert verification["status"] == "fail"
    assert "manfred_realtime_goal_completion_overclaim" in verification["issues"]
    assert "manfred_realtime_claim_overclaim" in verification["issues"]
    assert "manfred_realtime_captured_diagnostic_overclaim" in verification["issues"]
    assert "manfred_realtime_privacy_flag_not_false:candidate_raw_text_fields" in verification["issues"]
    assert "manfred_realtime_required_live_proof_incomplete" in verification["issues"]
    assert "manfred_realtime_next_action_method_missing" in verification["issues"]
    assert "manfred_realtime_blocked_next_action_href_drift" in verification["issues"]
    assert "manfred_realtime_blocked_next_action_label_drift" in verification["issues"]


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
