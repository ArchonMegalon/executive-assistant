from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path

import pytest

from ea.scripts import verify_whatsapp_audiobook_live_delivery_receipt as verifier
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
CANARY_HMAC_KEY = b"test-only-whatsapp-canary-hmac-key"


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
        "narration_plan": {
            "contract_name": "ea.audiobook_narration_plan.v5",
            "status": "ready",
            "coverage_complete": True,
            "source_integrity_verified": True,
            "chapter_count": 2,
            "plan_sha256": "1" * 64,
            "source_aggregate_sha256": "2" * 64,
            "render_signature": "3" * 64,
        },
        "dialogue_cast": {
            "required": True,
            "status": "ready",
            "ready_and_distinct": True,
            "dialogue_span_count": 4,
            "distinct_dialogue_voice_count": 2,
            "narrator_voice_excluded": True,
            "cast_map_sha256": "4" * 64,
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
            "sample_count": 2,
            "passed_samples": 2,
            "failed_samples": 0,
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


def _human_listened_canary() -> dict[str, object]:
    performance = _performance_evidence()
    narration = dict(performance["narration_plan"])
    cast = dict(performance["dialogue_cast"])
    mastering = dict(performance["mastering"])
    perceptual_attestation = _perceptual_attestation(channel="whatsapp")
    immutable: dict[str, object] = {
        "contract_name": "ea.audiobook_human_listened_canary_acceptance.v1",
        "status": "listened_canary_accepted",
        "accepted": True,
        "listened": True,
        "canary_binding_status": "complete",
        "binding_issues": [],
        "channel": "whatsapp",
        "source": "whatsapp_button",
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
        "channel": "whatsapp",
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


def _unverified_canary() -> dict[str, object]:
    return {
        "status": "blocked",
        "claim_allowed": False,
        "receipt_digest_valid": False,
        "receipt_hmac_valid": False,
        "blocked_fields": ["human_listened_acceptance"],
    }


def _pass_receipt(*, human_accepted: bool = False) -> dict[str, object]:
    human_evidence: dict[str, object] = (
        {
            "status": "accepted",
            "claim_allowed": True,
            "accepted": True,
            "rejected": False,
            "operator_grade": True,
            "evidence_grade": "operator",
            "canary_contract_name": (
                "ea.audiobook_human_listened_canary_acceptance.v1"
            ),
            "canary_receipt_digest_valid": True,
            "canary_blocked_fields": [],
        }
        if human_accepted
        else {
            "status": "not_human_verified",
            "claim_allowed": False,
            "accepted": False,
            "rejected": False,
            "rejected_claim_observed": False,
            "operator_grade": False,
            "evidence_grade": "not_operator_evidence",
        }
    )
    claim_scope = (
        "machine_playable_delivery_and_human_accepted"
        if human_accepted
        else "machine_playable_delivery_only"
    )
    return {
        "contract_name": "ea.whatsapp_audiobook_live_delivery_receipt.v2",
        **_source_state(),
        "generated_at": GENERATED_AT,
        "generated_by": "ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py",
        "output_path": ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json",
        "load_errors": [],
        "status": "pass",
        "live_delivery_claim_allowed": True,
        "live_delivery_claim_scope": claim_scope,
        "fresh_live_job_receipt_proven": True,
        "historical_or_shadow_proof_only": False,
        "proof_freshness": {
            "fresh_live_job_receipt_present": True,
            "fresh_live_job_receipt_passed": True,
            "max_age_seconds": 86_400,
            "selected_job_receipt": _freshness(),
            "selected_audio_publication_gate": _freshness(),
            "selected_machine_playback": _freshness(),
        },
        "machine_playback_e2e_verified": True,
        "real_user_playback_acceptance_verified": human_accepted,
        "human_playback_acceptance_claim_allowed": human_accepted,
        "human_playback_acceptance_evidence": human_evidence,
        "canary_completion_claim_allowed": human_accepted,
        "canary_completion_blocked_fields": (
            [] if human_accepted else ["current_human_listened_canary_receipt"]
        ),
        "proof_semantics": {
            "machine_playable_delivery_does_not_imply_human_acceptance": True,
            "live_delivery_claim_scope": claim_scope,
            "human_acceptance_evidence": human_evidence["status"],
        },
        "goal_completion_claim_allowed": False,
        "failed_codes": [],
        "next_action": (
            "close_operator_loop"
            if human_accepted
            else "capture_real_user_playback_acceptance_or_close_operator_loop"
        ),
        "candidate_count": 1,
        "stage_summary": {"counts": {"delivered_playable": 1}},
        "historical_evidence": {},
        "runtime_readiness": {},
        "audiobook_runtime": {},
        "selected_delivery": {
            "performance_evidence": _performance_evidence(),
            "human_listened_canary": (
                _human_listened_canary() if human_accepted else _unverified_canary()
            ),
        },
    }


def _waiting_for_live_epub_receipt() -> dict[str, object]:
    payload = _pass_receipt()
    payload.update(
        status="waiting_for_live_epub",
        live_delivery_claim_allowed=False,
        live_delivery_claim_scope="none",
        fresh_live_job_receipt_proven=False,
        historical_or_shadow_proof_only=True,
        machine_playback_e2e_verified=False,
        failed_codes=[
            "valid_live_audiobook_delivery_missing",
            "whatsapp_audiobook_job_missing",
        ],
        next_action="send_epub_over_whatsapp_to_refresh_live_delivery_receipt",
        candidate_count=0,
        stage_summary={"counts": {}, "latest_by_stage": {}},
        historical_evidence={"historical_live_path_proven": True, "present": True},
        runtime_readiness={"ready": True, "receipt_present": True, "status": "ready"},
        audiobook_runtime={"ready_for_live_intake": True, "status": "pass"},
        selected_delivery={},
    )
    payload["proof_freshness"] = {
        "fresh_live_job_receipt_present": False,
        "fresh_live_job_receipt_passed": False,
        "max_age_seconds": 86_400,
        "historical_evidence_present": True,
        "historical_live_path_proven": True,
    }
    payload["proof_semantics"] = {
        "machine_playable_delivery_does_not_imply_human_acceptance": True,
        "live_delivery_claim_scope": "none",
        "human_acceptance_evidence": "not_human_verified",
    }
    return payload


def test_whatsapp_audiobook_live_delivery_verifier_accepts_machine_playable_without_human_acceptance(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
    _write(receipt, **_pass_receipt())

    assert _verify(receipt) == []


def test_whatsapp_audiobook_live_delivery_verifier_rejects_machine_only_accepted_status_tamper(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    human_evidence = deepcopy(payload["human_playback_acceptance_evidence"])
    human_evidence["status"] = "accepted"
    payload["human_playback_acceptance_evidence"] = human_evidence
    proof_semantics = deepcopy(payload["proof_semantics"])
    proof_semantics["human_acceptance_evidence"] = "accepted"
    payload["proof_semantics"] = proof_semantics
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert (
        "accepted human evidence requires accepted=true and human, real-user, "
        "and canary claims"
    ) in issues
    assert (
        "incomplete human acceptance evidence must use legacy_non_complete or "
        "not_human_verified status"
    ) in issues


def test_whatsapp_audiobook_live_delivery_verifier_rejects_nonportable_output_and_nonpass_human_claims(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
    payload = _waiting_for_live_epub_receipt()
    payload.update(
        output_path="/workspace/private/whatsapp.generated.json",
        real_user_playback_acceptance_verified=True,
        human_playback_acceptance_claim_allowed=True,
        canary_completion_claim_allowed=True,
    )
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert "output_path must be a portable repository-relative artifact identity" in issues
    assert "non-pass status must not claim real-user playback acceptance" in issues
    assert "non-pass status must not claim human playback acceptance" in issues
    assert "non-pass status must not claim canary completion" in issues


@pytest.mark.parametrize(
    "bad_path",
    [123, ".", "file:///private/receipt.json", "https://host/receipt.json", ["/workspace/private"]],
)
def test_whatsapp_audiobook_live_delivery_verifier_rejects_nonartifact_output_identity(
    tmp_path: Path,
    bad_path: object,
) -> None:
    receipt = tmp_path / "whatsapp-audiobook-receipt.json"
    payload = _pass_receipt()
    payload["output_path"] = bad_path
    _write(receipt, **payload)

    assert (
        "output_path must be a portable repository-relative artifact identity"
        in _verify(receipt)
    )


@pytest.mark.parametrize("forged_value", ["true", 1, [], {}])
def test_whatsapp_nonpass_receipt_requires_literal_false_claim_flags(
    tmp_path: Path,
    forged_value: object,
) -> None:
    receipt = tmp_path / "whatsapp-audiobook-receipt.json"
    payload = _waiting_for_live_epub_receipt()
    payload.update(
        real_user_playback_acceptance_verified=forged_value,
        human_playback_acceptance_claim_allowed=forged_value,
        canary_completion_claim_allowed=forged_value,
    )
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert "real_user_playback_acceptance_verified must be a boolean" in issues
    assert "human_playback_acceptance_claim_allowed must be a boolean" in issues
    assert "canary_completion_claim_allowed must be a boolean" in issues
    assert "non-pass status must not claim real-user playback acceptance" in issues
    assert "non-pass status must not claim human playback acceptance" in issues
    assert "non-pass status must not claim canary completion" in issues


@pytest.mark.parametrize(
    "field",
    [
        "live_delivery_claim_allowed",
        "fresh_live_job_receipt_proven",
        "historical_or_shadow_proof_only",
        "machine_playback_e2e_verified",
        "real_user_playback_acceptance_verified",
        "human_playback_acceptance_claim_allowed",
        "canary_completion_claim_allowed",
        "goal_completion_claim_allowed",
    ],
)
@pytest.mark.parametrize("forged_value", ["true", 1, 0, ""])
def test_whatsapp_pass_critical_claims_require_literal_booleans(
    tmp_path: Path,
    field: str,
    forged_value: object,
) -> None:
    receipt = tmp_path / "whatsapp-audiobook-receipt.json"
    payload = _pass_receipt()
    payload[field] = forged_value
    _write(receipt, **payload)

    assert f"{field} must be a boolean" in _verify(receipt)


@pytest.mark.parametrize(
    "field",
    ["fresh_live_job_receipt_present", "fresh_live_job_receipt_passed"],
)
@pytest.mark.parametrize("forged_value", ["true", 1, 0, ""])
def test_whatsapp_fresh_proof_claims_require_literal_booleans(
    tmp_path: Path,
    field: str,
    forged_value: object,
) -> None:
    receipt = tmp_path / "whatsapp-audiobook-receipt.json"
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
def test_whatsapp_load_errors_always_fail_closed(
    tmp_path: Path,
    load_errors: object,
    expected_issue: str,
) -> None:
    receipt = tmp_path / "whatsapp-audiobook-receipt.json"
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
def test_whatsapp_malformed_nested_canary_shapes_fail_closed_without_crashing(
    tmp_path: Path,
    malformed_location: str,
) -> None:
    receipt = tmp_path / "whatsapp-audiobook-receipt.json"
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


def test_whatsapp_nonboolean_attestation_check_fails_after_valid_resign(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp-audiobook-receipt.json"
    payload = _pass_receipt(human_accepted=True)
    selected = deepcopy(payload["selected_delivery"])
    canary = selected["human_listened_canary"]
    immutable = canary["immutable_receipt"]
    attestation = immutable["perceptual_attestation"]
    attestation["checks"]["correct_words"] = "true"
    canonical = {
        "contract_name": verifier.PERCEPTUAL_ATTESTATION_CONTRACT_NAME,
        "version": 1,
        "channel": "whatsapp",
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


def test_whatsapp_audiobook_live_delivery_verifier_accepts_operator_grade_rejection_with_review_action(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    human_evidence = {
        "status": "rejected",
        "claim_allowed": False,
        "accepted": False,
        "rejected": True,
        "rejected_claim_observed": True,
        "feedback_sha256_present": True,
        "feedback_sha256_valid": True,
        "feedback_sha256_required": True,
        "operator_grade": True,
    }
    payload["human_playback_acceptance_evidence"] = human_evidence
    payload["proof_semantics"]["human_acceptance_evidence"] = "rejected"
    payload["next_action"] = "review_audiobook_playback_problem"
    _write(receipt, **payload)

    assert _verify(receipt) == []


def test_whatsapp_audiobook_live_delivery_verifier_requires_hash_capture_for_unhashed_rejected_claim(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    payload["human_playback_acceptance_evidence"] = {
        "status": "not_human_verified",
        "claim_allowed": False,
        "accepted": False,
        "rejected": False,
        "rejected_claim_observed": True,
        "feedback_sha256_present": False,
        "feedback_sha256_valid": False,
        "feedback_sha256_required": True,
    }
    _write(receipt, **payload)

    assert (
        "unhashed rejected human playback claims require hashed playback-problem feedback capture"
        in _verify(receipt)
    )


def test_whatsapp_audiobook_live_delivery_verifier_rejects_human_claim_without_canary(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    payload["human_playback_acceptance_claim_allowed"] = True
    payload["live_delivery_claim_scope"] = (
        "machine_playable_delivery_and_human_accepted"
    )
    payload["proof_semantics"]["live_delivery_claim_scope"] = payload[
        "live_delivery_claim_scope"
    ]
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert "human acceptance claim requires real_user_playback_acceptance_verified=true" in issues
    assert "human acceptance claim requires accepted human evidence" in issues
    assert "human acceptance claim cannot exceed canary completion proof" in issues


def test_whatsapp_audiobook_live_delivery_verifier_accepts_human_listened_canary_scope(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
    _write(receipt, **_pass_receipt(human_accepted=True))

    assert _verify(receipt) == []


def test_whatsapp_audiobook_live_delivery_verifier_accepts_waiting_for_live_epub(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
    _write(receipt, **_waiting_for_live_epub_receipt())

    assert _verify(receipt) == []


def test_whatsapp_audiobook_live_delivery_verifier_rejects_bad_waiting_for_live_epub(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
    payload = _waiting_for_live_epub_receipt()
    payload["candidate_count"] = 2
    payload["historical_evidence"] = {"historical_live_path_proven": False}
    payload["runtime_readiness"] = {"ready": False}
    payload["audiobook_runtime"] = {"ready_for_live_intake": False}
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert "waiting_for_live_epub requires candidate_count=0" in issues
    assert "waiting_for_live_epub requires runtime_readiness.ready=true" in issues
    assert "waiting_for_live_epub requires historical_live_path_proven=true" in issues


def test_whatsapp_audiobook_live_delivery_verifier_requires_text_fallback_signal_for_waiting_voice_choice(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
    payload = _waiting_for_live_epub_receipt()
    payload.update(
        status="waiting_voice_choice",
        historical_or_shadow_proof_only=False,
        candidate_count=1,
        failed_codes=["user_selected_voice_delivery_not_ready"],
        next_action="choose_whatsapp_audiobook_voice_sample",
        stage_summary={"counts": {"waiting_voice_choice": 1}},
        historical_evidence={},
        runtime_readiness={},
        audiobook_runtime={},
        pending_user_selected_voice_jobs=[
            {
                "voice_selection_waiting": True,
                "replacement_choice_pending": False,
            }
        ],
    )
    _write(receipt, **payload)

    issues = _verify(receipt)
    assert "waiting_voice_choice must expose voice_selection_text_fallback_ready" in issues
    assert (
        "waiting voice-choice pending jobs must expose voice_selection_text_fallback_ready"
        in issues
    )


def test_whatsapp_audiobook_live_delivery_verifier_rejects_stale_gate_and_performance_tamper(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    payload["generated_at"] = "2026-07-17T11:59:00Z"
    freshness = deepcopy(payload["proof_freshness"])
    freshness["selected_audio_publication_gate"]["fresh"] = False
    payload["proof_freshness"] = freshness
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


def test_whatsapp_audiobook_live_delivery_verifier_rejects_tampered_listener_digest_and_hmac(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
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


def test_whatsapp_audiobook_live_delivery_verifier_rejects_legacy_v1_contract(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
    payload = _pass_receipt()
    payload["contract_name"] = "ea.whatsapp_audiobook_live_delivery_receipt.v1"
    _write(receipt, **payload)

    assert (
        "contract_name must be ea.whatsapp_audiobook_live_delivery_receipt.v2"
        in _verify(receipt)
    )


def test_whatsapp_audiobook_live_delivery_verifier_blocks_malformed_performance_numeric(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "whatsapp_audiobook_live_delivery.generated.json"
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
