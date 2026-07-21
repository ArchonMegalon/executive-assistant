from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path

import pytest

from ea.scripts import verify_telegram_audiobook_live_delivery_receipt as verifier
from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import (
    HUMAN_LISTENED_CANARY_DIGEST_FIELDS,
)
from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_TIME = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
GENERATED_AT = "2026-07-19T11:59:00Z"
SOURCE_HEAD = "a" * 40
SOURCE_FINGERPRINT = "b" * 64
CANARY_HMAC_KEY = b"test-only-telegram-canary-hmac-key"


@pytest.fixture(autouse=True)
def _stable_source_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY",
        CANARY_HMAC_KEY.decode("ascii"),
    )
    monkeypatch.setattr(verifier, "resolve_source_state_head", lambda _root: SOURCE_HEAD)
    monkeypatch.setattr(
        verifier,
        "resolve_source_worktree_fingerprint",
        lambda _root: SOURCE_FINGERPRINT,
    )


def _write(path: Path, **payload: object) -> None:
    payload.setdefault("source_git_head", resolve_source_state_head(ROOT))
    payload.setdefault("head_semantics", "source_state")
    payload.setdefault("source_state_fingerprint", resolve_source_worktree_fingerprint(ROOT))
    payload.setdefault(
        "source_state_fingerprint_semantics",
        "worktree_source_files_sha256_excluding_generated_only_paths",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _verify(path: Path) -> list[str]:
    return verifier.verify(path, now=REFERENCE_TIME)


def _source_state() -> dict[str, object]:
    return {
        "source_git_head": SOURCE_HEAD,
        "head_semantics": "source_state",
        "source_state_fingerprint": SOURCE_FINGERPRINT,
        "source_state_fingerprint_semantics": (
            "worktree_source_files_sha256_excluding_generated_only_paths"
        ),
    }


def _freshness() -> dict[str, object]:
    return {
        "timestamp_present": True,
        "fresh": True,
        "age_seconds": 60.0,
        "max_age_seconds": 86_400,
        "future_skew_seconds": 0.0,
    }


def _performance_evidence() -> dict[str, object]:
    return {
        "status": "pass",
        "all_required_proof_passed": True,
        "expected_chapter_count": 2,
        "publication_chapter_count": 2,
        "chapter_metadata_verified": True,
        "chapter_metadata_contract": (
            "ea.audiobook_m4b_chapter_metadata_proof.v1"
        ),
        "chapter_metadata_sha256": "0" * 64,
        "narration_plan": {
            "contract_name": "ea.audiobook_narration_plan.v5",
            "status": "ready",
            "coverage_complete": True,
            "source_integrity_verified": True,
            "chapter_count": 2,
            "speaker_count": 2,
            "plan_sha256": "1" * 64,
            "source_aggregate_sha256": "2" * 64,
            "render_signature": "3" * 64,
        },
        "dialogue_cast": {
            "required": True,
            "status": "ready",
            "ready_and_distinct": True,
            "dialogue_span_count": 4,
            "speaker_count": 2,
            "resolved_speaker_count": 2,
            "distinct_dialogue_voice_count": 2,
            "narrator_voice_excluded": True,
            "cast_map_sha256": "4" * 64,
            "assignment_count": 2,
            "assignments_complete": True,
            "assignments": [
                {
                    "speaker_id_sha256": "a" * 64,
                    "voice_id_sha256": "c" * 64,
                    "distinct_from_narrator": True,
                },
                {
                    "speaker_id_sha256": "b" * 64,
                    "voice_id_sha256": "d" * 64,
                    "distinct_from_narrator": True,
                },
            ],
            "raw_voice_ids_exposed": False,
        },
        "mastering": {
            "status": "mastered",
            "final_track_mode": "chapter_masters",
            "contract_sha256": "5" * 64,
            "signature_set_sha256": "6" * 64,
            "expected_final_track_count": 2,
            "final_track_ready_count": 2,
            "signature_published_or_verified_count": 2,
            "segment_mastering": False,
            "final_audio_quality_pass": True,
        },
        "publication_stt": {
            "status": "pass",
            "required": True,
            "enabled": True,
            "alignment_verified": True,
            "alignment_contract": "chapter_time_token_window_v1",
            "chapter_metadata_contract": (
                "ea.audiobook_m4b_chapter_metadata_proof.v1"
            ),
            "chapter_metadata_sha256": "0" * 64,
            "source_text_sha256": "a" * 64,
            "source_token_count": 240,
            "source_chapter_count": 2,
            "probe_chapter_count": 2,
            "sample_count": 2,
            "passed_samples": 2,
            "failed_samples": 0,
            "sample_seconds": 30,
            "min_transcript_tokens": 8,
            "min_book_token_overlap": 0.55,
            "min_ordered_token_overlap": 0.55,
            "max_position_drift_ratio": 0.125,
            "minimum_hash_token_count": 8,
                    "short_book_text_tolerance": "v2",
            "distinct_source_window_count": 2,
            "samples": [
                {
                    "index": 1,
                    "offset_seconds": 0.0,
                    "primary_offset_seconds": 0.0,
                    "attempt_count": 1,
                    "status": "pass",
                    "issue": "",
                    "warning": "",
                    "transcript_sha256": "e" * 64,
                    "transcript_hash_withheld_low_entropy": False,
                    "transcript_token_count": 12,
                    "book_token_overlap": 0.92,
                    "book_unique_token_overlap": 0.91,
                    "ordered_token_overlap": 0.88,
                    "source_window_sha256": "b" * 64,
                    "source_window_hash_withheld_low_entropy": False,
                    "source_window_token_count": 24,
                    "source_window_padding_token_count": 4,
                    "source_chapter_indices": [1],
                    "position_alignment_verified": True,
                    "raw_text_exposed": False,
                },
                {
                    "index": 2,
                    "offset_seconds": 30.0,
                    "primary_offset_seconds": 30.0,
                    "attempt_count": 1,
                    "status": "pass",
                    "issue": "",
                    "warning": "",
                    "transcript_sha256": "f" * 64,
                    "transcript_hash_withheld_low_entropy": False,
                    "transcript_token_count": 11,
                    "book_token_overlap": 0.89,
                    "book_unique_token_overlap": 0.87,
                    "ordered_token_overlap": 0.84,
                    "source_window_sha256": "c" * 64,
                    "source_window_hash_withheld_low_entropy": False,
                    "source_window_token_count": 23,
                    "source_window_padding_token_count": 4,
                    "source_chapter_indices": [2],
                    "position_alignment_verified": True,
                    "raw_text_exposed": False,
                },
            ],
            "issues": [],
            "warnings": [],
            "raw_text_exposed": False,
        },
        "source_sha256": "7" * 64,
        "artifact_sha256": "8" * 64,
        "publication_gate_sha256": "9" * 64,
        "cinematic_timeline_sha256": "",
        "issues": [],
    }


def _perceptual_attestation(*, channel: str) -> dict[str, object]:
    checks = {
        key: True for key in verifier.PERCEPTUAL_ATTESTATION_CHECKS
    }
    canonical = {
        "contract_name": verifier.PERCEPTUAL_ATTESTATION_CONTRACT_NAME,
        "version": 1,
        "channel": channel,
        "checks": checks,
        "all_checks_attested": True,
    }
    return {
        "contract_name": verifier.PERCEPTUAL_ATTESTATION_CONTRACT_NAME,
        "version": 1,
        "checks": checks,
        "all_checks_attested": True,
        "channel_feedback_bound": True,
        "attestation_sha256": hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "raw_values_exposed": False,
    }


def _human_listened_canary(*, channel: str) -> dict[str, object]:
    performance = _performance_evidence()
    narration = dict(performance["narration_plan"])
    cast = dict(performance["dialogue_cast"])
    mastering = dict(performance["mastering"])
    perceptual_attestation = _perceptual_attestation(channel=channel)
    immutable: dict[str, object] = {
        "contract_name": "ea.audiobook_human_listened_canary_acceptance.v1",
        "status": "listened_canary_accepted",
        "accepted": True,
        "listened": True,
        "canary_binding_status": "complete",
        "binding_issues": [],
        "channel": channel,
        "source": f"{channel}_button",
        "recorded_at": GENERATED_AT,
        "artifact_sha256": performance["artifact_sha256"],
        "source_sha256": performance["source_sha256"],
        "source_aggregate_sha256": narration["source_aggregate_sha256"],
        "narration_plan_sha256": narration["plan_sha256"],
        "render_signature_sha256": narration["render_signature"],
        "cast_map_sha256": cast["cast_map_sha256"],
        "mastering_signature_set_sha256": mastering["signature_set_sha256"],
        "cinematic_timeline_sha256": "",
        "publication_gate_sha256": performance["publication_gate_sha256"],
        "channel_public_share_message_id_sha256": "c" * 64,
        "public_share_url_sha256": "d" * 64,
        "message_id_sha256": "e" * 64,
        "feedback_sha256": "f" * 64,
        "perceptual_attestation": perceptual_attestation,
        "listener_reference_sha256": "0" * 64,
        "language": "en",
        "dialogue_turn_count": 4,
        "expected_chapter_count": 2,
        "actual_chapter_count": 2,
        "raw_feedback_exposed": False,
        "raw_message_id_exposed": False,
        "raw_listener_reference_exposed": False,
    }
    binding = {key: immutable.get(key) for key in HUMAN_LISTENED_CANARY_DIGEST_FIELDS}
    receipt_sha256 = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    immutable["receipt_sha256"] = receipt_sha256
    receipt_hmac_sha256 = hmac.new(
        CANARY_HMAC_KEY,
        receipt_sha256.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "contract_name": "ea.audiobook_human_listened_canary_acceptance.v1",
        "required_contract_name": "ea.audiobook_human_listened_canary_acceptance.v1",
        "status": "accepted",
        "claim_allowed": True,
        "accepted": True,
        "listened": True,
        "channel": channel,
        "recorded_at": GENERATED_AT,
        "freshness": _freshness(),
        "artifact_sha256": immutable["artifact_sha256"],
        "source_sha256": immutable["source_sha256"],
        "source_aggregate_sha256": immutable["source_aggregate_sha256"],
        "narration_plan_sha256": immutable["narration_plan_sha256"],
        "render_signature_sha256": immutable["render_signature_sha256"],
        "cast_map_sha256": immutable["cast_map_sha256"],
        "mastering_signature_set_sha256": immutable[
            "mastering_signature_set_sha256"
        ],
        "publication_gate_sha256": immutable["publication_gate_sha256"],
        "channel_public_share_message_id_sha256": immutable[
            "channel_public_share_message_id_sha256"
        ],
        "public_share_url_sha256": immutable["public_share_url_sha256"],
        "feedback_sha256": immutable["feedback_sha256"],
        "perceptual_attestation": perceptual_attestation,
        "listener_reference_sha256": immutable["listener_reference_sha256"],
        "language": "en",
        "dialogue_turn_count": 4,
        "expected_chapter_count": 2,
        "actual_chapter_count": 2,
        "receipt_sha256": receipt_sha256,
        "receipt_digest_valid": True,
        "receipt_hmac_sha256": receipt_hmac_sha256,
        "receipt_hmac_valid": True,
        "immutable_receipt": immutable,
        "blocked_fields": [],
        "raw_feedback_exposed": False,
        "raw_message_id_exposed": False,
        "raw_voice_ids_exposed": False,
    }


def _resign_canary(canary: dict[str, object]) -> None:
    immutable = canary["immutable_receipt"]
    assert isinstance(immutable, dict)
    binding = {
        key: immutable.get(key) for key in HUMAN_LISTENED_CANARY_DIGEST_FIELDS
    }
    receipt_sha256 = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    immutable["receipt_sha256"] = receipt_sha256
    canary["receipt_sha256"] = receipt_sha256
    canary["receipt_hmac_sha256"] = hmac.new(
        CANARY_HMAC_KEY,
        receipt_sha256.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _pass_receipt(*, human_accepted: bool = False) -> dict[str, object]:
    next_action = (
        "close_operator_loop"
        if human_accepted
        else "capture_real_user_playback_acceptance_or_close_operator_loop"
    )
    next_href = "/app/channel-loop" if human_accepted else "/integrations/telegram"
    next_label = "Open channel loop" if human_accepted else "Open Telegram"
    canary = (
        _human_listened_canary(channel="telegram")
        if human_accepted
        else {
            "status": "blocked",
            "claim_allowed": False,
            "receipt_digest_valid": False,
            "receipt_hmac_valid": False,
            "blocked_fields": ["human_listened_acceptance"],
        }
    )
    return {
        "contract_name": "ea.telegram_audiobook_live_delivery_receipt.v2",
        **_source_state(),
        "generated_at": GENERATED_AT,
        "generated_by": "ea/scripts/materialize_telegram_audiobook_live_delivery_receipt.py",
        "output_path": ".codex-studio/published/telegram_audiobook_live_delivery.generated.json",
        "load_errors": [],
        "status": "pass",
        "live_delivery_claim_allowed": True,
        "proof_freshness": {
            "max_age_seconds": 86_400,
            "fresh_live_job_receipt_present": True,
            "fresh_live_job_receipt_passed": True,
            "selected_job_receipt": _freshness(),
            "selected_audio_publication_gate": _freshness(),
            "selected_machine_playback": _freshness(),
        },
        "machine_playback_e2e_verified": True,
        "real_user_playback_acceptance_verified": human_accepted,
        "human_playback_acceptance_claim_allowed": human_accepted,
        "canary_completion_claim_allowed": human_accepted,
        "canary_completion_blocked_fields": (
            [] if human_accepted else ["current_human_listened_canary_receipt"]
        ),
        "goal_completion_claim_allowed": False,
        "failed_codes": [],
        "next_action": next_action,
        "next_action_href": next_href,
        "next_action_label": next_label,
        "next_action_method": "get",
        "operator_action_packet": {
            "user_action_required": False,
            "reason": (
                "telegram_audiobook_live_delivery_closed"
                if human_accepted
                else "no_user_voice_choice_required"
            ),
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        },
        "duplicate_suppression": {
            "action_required_only": True,
            "only_current_jobs_can_require_user_action": True,
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
            "duplicate_active_pending_source_key_count": 0,
            "active_pending_voice_job_count": 0,
        },
        "pending_user_selected_voice_job_count": 0,
        "selected_delivery": {
            "performance_evidence": _performance_evidence(),
            "human_listened_canary": canary,
        },
        "privacy": {
            "provider_secret_exposed": False,
            "audiobookshelf_token_exposed": False,
        },
    }


def test_telegram_audiobook_live_delivery_verifier_accepts_machine_playable_pass(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    _write(receipt, **_pass_receipt())

    assert _verify(receipt) == []


def test_telegram_audiobook_live_delivery_verifier_rejects_machine_only_human_claim_tamper(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    payload["human_playback_acceptance_claim_allowed"] = True
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert (
        "human_playback_acceptance_claim_allowed must equal "
        "canary_completion_claim_allowed"
    ) in issues
    assert (
        "human acceptance claims require "
        "real_user_playback_acceptance_verified=true"
    ) in issues


def test_telegram_audiobook_live_delivery_verifier_rejects_nonportable_output_and_blocked_human_claims(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    payload.update(
        status="blocked",
        live_delivery_claim_allowed=False,
        output_path="/docker/EA/private/telegram.generated.json",
        real_user_playback_acceptance_verified=True,
        human_playback_acceptance_claim_allowed=True,
        canary_completion_claim_allowed=True,
        failed_codes=["valid_live_audiobook_delivery_missing"],
        next_action="capture_real_user_playback_acceptance_or_close_operator_loop",
        next_action_href="/integrations/telegram",
        next_action_label="Open Telegram",
        next_action_method="get",
    )
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert "output_path must be a portable repository-relative artifact identity" in issues
    assert "blocked status must not claim real-user playback acceptance" in issues
    assert "blocked status must not claim human playback acceptance" in issues
    assert "blocked status must not claim canary completion" in issues


@pytest.mark.parametrize(
    "bad_path",
    [123, ".", "file:///private/receipt.json", "https://host/receipt.json", ["/docker/EA/private"]],
)
def test_telegram_audiobook_live_delivery_verifier_rejects_nonartifact_output_identity(
    tmp_path: Path,
    bad_path: object,
) -> None:
    receipt = tmp_path / "telegram-audiobook-receipt.json"
    payload = _pass_receipt()
    payload["output_path"] = bad_path
    _write(receipt, **payload)

    assert (
        "output_path must be a portable repository-relative artifact identity"
        in _verify(receipt)
    )


@pytest.mark.parametrize("forged_value", ["true", 1, [], {}])
def test_telegram_blocked_receipt_requires_literal_false_claim_flags(
    tmp_path: Path,
    forged_value: object,
) -> None:
    receipt = tmp_path / "telegram-audiobook-receipt.json"
    payload = _pass_receipt()
    payload.update(
        status="blocked",
        live_delivery_claim_allowed=False,
        real_user_playback_acceptance_verified=forged_value,
        human_playback_acceptance_claim_allowed=forged_value,
        canary_completion_claim_allowed=forged_value,
        failed_codes=["valid_live_audiobook_delivery_missing"],
    )
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert "real_user_playback_acceptance_verified must be a boolean" in issues
    assert "human_playback_acceptance_claim_allowed must be a boolean" in issues
    assert "canary_completion_claim_allowed must be a boolean" in issues
    assert "blocked status must not claim real-user playback acceptance" in issues
    assert "blocked status must not claim human playback acceptance" in issues
    assert "blocked status must not claim canary completion" in issues


@pytest.mark.parametrize(
    "field",
    [
        "live_delivery_claim_allowed",
        "machine_playback_e2e_verified",
        "real_user_playback_acceptance_verified",
        "human_playback_acceptance_claim_allowed",
        "canary_completion_claim_allowed",
        "goal_completion_claim_allowed",
    ],
)
@pytest.mark.parametrize("forged_value", ["true", 1, 0, ""])
def test_telegram_pass_critical_claims_require_literal_booleans(
    tmp_path: Path,
    field: str,
    forged_value: object,
) -> None:
    receipt = tmp_path / "telegram-audiobook-receipt.json"
    payload = _pass_receipt()
    payload[field] = forged_value
    _write(receipt, **payload)

    assert f"{field} must be a boolean" in _verify(receipt)


@pytest.mark.parametrize(
    "field",
    ["fresh_live_job_receipt_present", "fresh_live_job_receipt_passed"],
)
@pytest.mark.parametrize("forged_value", ["true", 1, 0, ""])
def test_telegram_fresh_proof_claims_require_literal_booleans(
    tmp_path: Path,
    field: str,
    forged_value: object,
) -> None:
    receipt = tmp_path / "telegram-audiobook-receipt.json"
    payload = _pass_receipt()
    proof_freshness = deepcopy(payload["proof_freshness"])
    proof_freshness[field] = forged_value
    payload["proof_freshness"] = proof_freshness
    _write(receipt, **payload)

    assert f"proof_freshness.{field} must be a boolean" in _verify(receipt)


@pytest.mark.parametrize(
    ("load_errors", "expected_issue"),
    [
        ("receipt_load_failed", "load_errors must be an array"),
        (["not_a_public_code"], "load_errors contains invalid entries"),
        (["receipt_load_failed"], "load_errors must be empty"),
    ],
)
def test_telegram_load_errors_always_fail_closed(
    tmp_path: Path,
    load_errors: object,
    expected_issue: str,
) -> None:
    receipt = tmp_path / "telegram-audiobook-receipt.json"
    payload = _pass_receipt()
    payload["load_errors"] = load_errors
    _write(receipt, **payload)

    assert expected_issue in _verify(receipt)


@pytest.mark.parametrize(
    "malformed_location",
    [
        "selected_delivery",
        "human_listened_canary",
        "immutable_receipt",
        "projected_attestation",
        "immutable_attestation",
        "attestation_checks",
    ],
)
def test_telegram_malformed_nested_canary_shapes_fail_closed_without_crashing(
    tmp_path: Path,
    malformed_location: str,
) -> None:
    receipt = tmp_path / "telegram-audiobook-receipt.json"
    payload = _pass_receipt(human_accepted=True)
    if malformed_location == "selected_delivery":
        payload["selected_delivery"] = "forged"
    else:
        selected = deepcopy(payload["selected_delivery"])
        canary = selected["human_listened_canary"]
        if malformed_location == "human_listened_canary":
            selected["human_listened_canary"] = "forged"
        elif malformed_location == "immutable_receipt":
            canary["immutable_receipt"] = "forged"
        elif malformed_location == "projected_attestation":
            canary["perceptual_attestation"] = "forged"
        elif malformed_location == "immutable_attestation":
            canary["immutable_receipt"]["perceptual_attestation"] = "forged"
        else:
            canary["immutable_receipt"]["perceptual_attestation"]["checks"] = (
                "forged"
            )
        payload["selected_delivery"] = selected
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert issues
    assert (
        "canary completion requires independently verified perceptual attestation"
        in issues
    )


def test_telegram_nonboolean_attestation_check_fails_after_valid_resign(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram-audiobook-receipt.json"
    payload = _pass_receipt(human_accepted=True)
    selected = deepcopy(payload["selected_delivery"])
    canary = selected["human_listened_canary"]
    immutable = canary["immutable_receipt"]
    attestation = immutable["perceptual_attestation"]
    attestation["checks"]["correct_words"] = "true"
    canonical = {
        "contract_name": verifier.PERCEPTUAL_ATTESTATION_CONTRACT_NAME,
        "version": 1,
        "channel": "telegram",
        "checks": {
            key: attestation["checks"].get(key) is True
            for key in verifier.PERCEPTUAL_ATTESTATION_CHECKS
        },
        "all_checks_attested": True,
    }
    attestation["attestation_sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    canary["perceptual_attestation"] = deepcopy(attestation)
    _resign_canary(canary)
    payload["selected_delivery"] = selected
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert (
        "canary completion requires independently verified perceptual attestation"
        in issues
    )
    assert "canary completion requires independently verified receipt HMAC" not in issues
    assert (
        "canary completion requires independently verified immutable receipt digest"
        not in issues
    )


def test_telegram_audiobook_live_delivery_verifier_accepts_human_listened_canary_closeout(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    _write(receipt, **_pass_receipt(human_accepted=True))

    assert _verify(receipt) == []


def test_telegram_audiobook_live_delivery_verifier_rejects_missing_surface(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    payload.update(
        status="blocked",
        live_delivery_claim_allowed=False,
        machine_playback_e2e_verified=False,
        failed_codes=["user_selected_voice_delivery_not_ready"],
        next_action="choose_one_telegram_audiobook_voice_sample",
        next_action_href="",
        next_action_label="",
        next_action_method="",
        operator_action_packet={
            "user_action_required": True,
            "operator_action": "choose_one_telegram_audiobook_voice_sample",
            "instruction": "Choose one sent voice sample.",
            "candidate_count": 1,
            "candidate_labels": ["Sample A"],
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
        },
    )
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert "next_action_href must match the mapped Telegram operator surface" in issues
    assert "next_action_label must match the mapped Telegram operator surface" in issues
    assert "next_action_method must match the mapped Telegram operator surface" in issues


def test_telegram_audiobook_live_delivery_verifier_rejects_human_canary_without_closeout(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    payload = _pass_receipt(human_accepted=True)
    payload.update(
        next_action="capture_real_user_playback_acceptance_or_close_operator_loop",
        next_action_href="/integrations/telegram",
        next_action_label="Open Telegram",
    )
    _write(receipt, **payload)

    assert "accepted human playback must close the operator loop" in _verify(receipt)


def test_telegram_audiobook_live_delivery_verifier_rejects_stale_and_unbound_gate_proof(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    payload["generated_at"] = "2026-07-17T11:59:00Z"
    proof_freshness = deepcopy(payload["proof_freshness"])
    proof_freshness["selected_audio_publication_gate"]["fresh"] = False
    payload["proof_freshness"] = proof_freshness
    selected = deepcopy(payload["selected_delivery"])
    selected["performance_evidence"]["publication_gate_sha256"] = "not-a-digest"
    payload["selected_delivery"] = selected
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert "live delivery receipt exceeds max-age freshness" in issues
    assert (
        "pass status requires fresh job, publication-gate, and machine-playback timestamps"
        in issues
    )
    assert (
        "pass status requires exact plan, cast, mastering, quality, chapter, and STT proof"
        in issues
    )


def test_telegram_audiobook_live_delivery_verifier_rejects_tampered_listener_digest_and_hmac(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    payload = _pass_receipt(human_accepted=True)
    selected = deepcopy(payload["selected_delivery"])
    canary = selected["human_listened_canary"]
    canary["immutable_receipt"]["listener_reference_sha256"] = "a" * 64
    canary["receipt_hmac_sha256"] = "1" * 64
    payload["selected_delivery"] = selected
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert "canary completion requires independently verified immutable receipt digest" in issues
    assert "canary completion requires independently verified receipt HMAC" in issues


def test_telegram_audiobook_live_delivery_verifier_rejects_legacy_v1_contract(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    payload["contract_name"] = "ea.telegram_audiobook_live_delivery_receipt.v1"
    _write(receipt, **payload)

    assert (
        "contract_name must be ea.telegram_audiobook_live_delivery_receipt.v2"
        in _verify(receipt)
    )


def test_telegram_audiobook_live_delivery_verifier_blocks_malformed_performance_numeric(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    selected = deepcopy(payload["selected_delivery"])
    selected["performance_evidence"]["expected_chapter_count"] = (
        "PRIVATE-not-an-integer"
    )
    payload["selected_delivery"] = selected
    _write(receipt, **payload)

    assert (
        "pass status requires exact plan, cast, mastering, quality, chapter, and STT proof"
        in _verify(receipt)
    )


@pytest.mark.parametrize(
    "assignment_corruption",
    ["zero", "missing", "duplicate_speaker", "tampered_voice_digest"],
)
def test_telegram_audiobook_live_delivery_verifier_rejects_incomplete_cast_assignments(
    tmp_path: Path,
    assignment_corruption: str,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    selected = deepcopy(payload["selected_delivery"])
    dialogue_cast = selected["performance_evidence"]["dialogue_cast"]
    assignments = dialogue_cast["assignments"]
    if assignment_corruption == "zero":
        dialogue_cast.update(
            speaker_count=0,
            resolved_speaker_count=0,
            distinct_dialogue_voice_count=0,
            assignment_count=0,
            assignments=[],
        )
    elif assignment_corruption == "missing":
        dialogue_cast.pop("assignments")
    elif assignment_corruption == "duplicate_speaker":
        assignments[1] = dict(assignments[0])
    else:
        assignments[0]["voice_id_sha256"] = "not-a-sha256"
    payload["selected_delivery"] = selected
    _write(receipt, **payload)

    assert (
        "pass status requires exact plan, cast, mastering, quality, chapter, and STT proof"
        in _verify(receipt)
    )


@pytest.mark.parametrize(
    "proof_corruption",
    [
        "metadata_unverified",
        "metadata_contract",
        "metadata_sha256",
        "stt_metadata_sha256",
        "alignment_contract",
        "sample_missing",
        "position_unverified",
        "transcript_sha256",
        "ordered_overlap_below_threshold",
        "declared_overlap_below_release_floor",
        "position_drift_above_release_max",
        "padding_missing",
        "distinct_window_count_mismatch",
    ],
)
def test_telegram_audiobook_live_delivery_verifier_rejects_publication_alignment_tamper(
    tmp_path: Path,
    proof_corruption: str,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    selected = deepcopy(payload["selected_delivery"])
    performance = selected["performance_evidence"]
    stt = performance["publication_stt"]
    if proof_corruption == "metadata_unverified":
        performance["chapter_metadata_verified"] = False
    elif proof_corruption == "metadata_contract":
        performance["chapter_metadata_contract"] = "legacy.chapter.proof"
    elif proof_corruption == "metadata_sha256":
        performance["chapter_metadata_sha256"] = "not-a-sha256"
    elif proof_corruption == "stt_metadata_sha256":
        stt["chapter_metadata_sha256"] = "f" * 64
    elif proof_corruption == "alignment_contract":
        stt["alignment_contract"] = "whole_book_bag_of_words_v0"
    elif proof_corruption == "sample_missing":
        stt["samples"].pop()
    elif proof_corruption == "position_unverified":
        stt["samples"][0]["position_alignment_verified"] = False
    elif proof_corruption == "transcript_sha256":
        stt["samples"][0]["transcript_sha256"] = "not-a-sha256"
    elif proof_corruption == "ordered_overlap_below_threshold":
        stt["samples"][0]["ordered_token_overlap"] = 0.1
    elif proof_corruption == "declared_overlap_below_release_floor":
        stt["min_book_token_overlap"] = 0.1
    elif proof_corruption == "position_drift_above_release_max":
        stt["max_position_drift_ratio"] = 0.25
    elif proof_corruption == "padding_missing":
        stt["samples"][0]["source_window_padding_token_count"] = 0
    else:
        stt["distinct_source_window_count"] = 1
    payload["selected_delivery"] = selected
    _write(receipt, **payload)

    assert (
        "pass status requires exact plan, cast, mastering, quality, chapter, and STT proof"
        in _verify(receipt)
    )


def test_telegram_audiobook_live_delivery_verifier_accepts_repeated_aligned_source_window(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    selected = deepcopy(payload["selected_delivery"])
    stt = selected["performance_evidence"]["publication_stt"]
    stt["samples"][1]["source_window_sha256"] = stt["samples"][0][
        "source_window_sha256"
    ]
    stt["distinct_source_window_count"] = 1
    payload["selected_delivery"] = selected
    _write(receipt, **payload)

    assert _verify(receipt) == []


def test_telegram_audiobook_live_delivery_verifier_accepts_withheld_low_entropy_window_hash(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "telegram_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    selected = deepcopy(payload["selected_delivery"])
    stt = selected["performance_evidence"]["publication_stt"]
    sample = stt["samples"][0]
    sample["source_window_token_count"] = 4
    sample["source_window_sha256"] = ""
    sample["source_window_hash_withheld_low_entropy"] = True
    payload["selected_delivery"] = selected
    _write(receipt, **payload)

    assert _verify(receipt) == []
