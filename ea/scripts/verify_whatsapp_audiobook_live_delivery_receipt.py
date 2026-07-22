from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint
from scripts.materialize_telegram_audiobook_live_delivery_receipt import HUMAN_LISTENED_CANARY_CONTRACT_NAME
from scripts.materialize_telegram_audiobook_live_delivery_receipt import LIVE_PROOF_FUTURE_SKEW_SECONDS
from scripts.materialize_telegram_audiobook_live_delivery_receipt import LIVE_PROOF_MAX_AGE_SECONDS
from scripts.materialize_telegram_audiobook_live_delivery_receipt import NARRATION_PLAN_CONTRACT_NAME
from scripts.materialize_telegram_audiobook_live_delivery_receipt import PUBLIC_LOAD_ERROR_CODES
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _canonical_acceptance_sha256
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _canary_receipt_hmac_key
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _parse_utc
from scripts.materialize_telegram_audiobook_live_delivery_receipt import _public_performance_evidence_valid


DEFAULT_RECEIPT = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_live_delivery.generated.json"
CONTRACT_NAME = "ea.whatsapp_audiobook_live_delivery_receipt.v2"
ALLOWED_STATUSES = {"pass", "blocked", "waiting_voice_choice", "waiting_provider_throttle", "waiting_for_live_epub"}
ALLOWED_CLAIM_SCOPES = {"none", "machine_playable_delivery_only", "machine_playable_delivery_and_human_accepted"}
PERCEPTUAL_ATTESTATION_CONTRACT_NAME = "ea.audiobook_perceptual_attestation.v1"
PERCEPTUAL_ATTESTATION_CHECKS = (
    "no_clipped_starts_or_ends",
    "no_abrupt_level_reset",
    "natural_paragraph_and_scene_timing",
    "distinct_dialogue_voice",
    "stable_speaker_identity",
    "correct_words",
    "useful_chapter_navigation",
)


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_int(value: object, *, default: int = -1) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _portable_output_path(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().replace("\\", "/")
    if (
        not normalized
        or normalized == "."
        or ":" in normalized
        or "://" in normalized
        or normalized.startswith(("/", "~/"))
        or not normalized.endswith(".json")
    ):
        return False
    parts = tuple(normalized.split("/"))
    return bool(parts) and all(part not in {"", ".", ".."} for part in parts)


def _verify_source_state(receipt: dict[str, Any], issues: list[str]) -> None:
    if receipt.get("head_semantics") != "source_state":
        issues.append("head_semantics must describe source_state")
    if (
        receipt.get("source_state_fingerprint_semantics")
        != "worktree_source_files_sha256_excluding_generated_only_paths"
    ):
        issues.append("source_state_fingerprint_semantics must describe the source worktree fingerprint")
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    current_head = resolve_source_state_head(ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(ROOT)
    if not recorded_head:
        issues.append("source_git_head missing")
    elif recorded_head != current_head and recorded_fingerprint != current_fingerprint:
        issues.append("source_git_head stale")
    if not recorded_fingerprint:
        issues.append("source_state_fingerprint missing")
    elif recorded_fingerprint != current_fingerprint:
        issues.append("source_state_fingerprint stale")


def _independent_canary_hmac_valid(
    canary: dict[str, Any],
    *,
    channel: str,
) -> bool:
    immutable_receipt = _as_dict(canary.get("immutable_receipt"))
    receipt_sha256 = str(
        immutable_receipt.get("receipt_sha256") or ""
    ).strip().lower()
    projected_receipt_sha256 = str(
        canary.get("receipt_sha256") or ""
    ).strip().lower()
    receipt_hmac_sha256 = str(
        canary.get("receipt_hmac_sha256") or ""
    ).strip().lower()
    is_sha256 = lambda value: len(value) == 64 and all(  # noqa: E731
        char in "0123456789abcdef" for char in value
    )
    key = _canary_receipt_hmac_key(channel)
    if (
        not key
        or not is_sha256(receipt_sha256)
        or projected_receipt_sha256 != receipt_sha256
        or not is_sha256(receipt_hmac_sha256)
    ):
        return False
    expected = hmac.new(
        key.encode("utf-8"),
        receipt_sha256.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(receipt_hmac_sha256, expected)


def _independent_perceptual_attestation_valid(
    canary: dict[str, Any],
    *,
    channel: str,
) -> bool:
    immutable_receipt = _as_dict(canary.get("immutable_receipt"))
    attestation = _as_dict(immutable_receipt.get("perceptual_attestation"))
    projected = _as_dict(canary.get("perceptual_attestation"))
    checks = _as_dict(attestation.get("checks"))
    canonical = {
        "contract_name": PERCEPTUAL_ATTESTATION_CONTRACT_NAME,
        "version": 1,
        "channel": channel,
        "checks": {
            key: checks.get(key) is True
            for key in PERCEPTUAL_ATTESTATION_CHECKS
        },
        "all_checks_attested": (
            attestation.get("all_checks_attested") is True
        ),
    }
    expected_sha256 = hashlib.sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return bool(
        projected == attestation
        and set(attestation)
        == {
            "contract_name",
            "version",
            "checks",
            "all_checks_attested",
            "channel_feedback_bound",
            "attestation_sha256",
            "raw_values_exposed",
        }
        and attestation.get("contract_name")
        == PERCEPTUAL_ATTESTATION_CONTRACT_NAME
        and attestation.get("version") == 1
        and not isinstance(attestation.get("version"), bool)
        and set(checks) == set(PERCEPTUAL_ATTESTATION_CHECKS)
        and all(checks.get(key) is True for key in PERCEPTUAL_ATTESTATION_CHECKS)
        and attestation.get("all_checks_attested") is True
        and attestation.get("channel_feedback_bound") is True
        and attestation.get("raw_values_exposed") is False
        and hmac.compare_digest(
            str(attestation.get("attestation_sha256") or "")
            .strip()
            .lower(),
            expected_sha256,
        )
    )


def verify(path: Path = DEFAULT_RECEIPT, *, now: datetime | None = None) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"whatsapp audiobook live delivery receipt missing or invalid: {path}"]

    if receipt.get("contract_name") != CONTRACT_NAME:
        issues.append(f"contract_name must be {CONTRACT_NAME}")
    if receipt.get("generated_by") != "ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py":
        issues.append("generated_by must point at the WhatsApp live delivery materializer")
    if not _portable_output_path(receipt.get("output_path")):
        issues.append("output_path must be a portable repository-relative artifact identity")
    _verify_source_state(receipt, issues)
    load_errors = receipt.get("load_errors")
    if not isinstance(load_errors, list):
        issues.append("load_errors must be an array")
    else:
        if any(
            not isinstance(item, str)
            or item not in PUBLIC_LOAD_ERROR_CODES
            for item in load_errors
        ):
            issues.append("load_errors contains invalid entries")
        if load_errors:
            issues.append("load_errors must be empty")
    generated_at = _parse_utc(receipt.get("generated_at"))
    observed_now = (now or datetime.now(UTC)).astimezone(UTC)
    if generated_at is None:
        issues.append("generated_at must be a timezone-aware timestamp")
    else:
        age_seconds = (observed_now - generated_at).total_seconds()
        if age_seconds < -LIVE_PROOF_FUTURE_SKEW_SECONDS:
            issues.append("generated_at is implausibly in the future")
        elif age_seconds > LIVE_PROOF_MAX_AGE_SECONDS:
            issues.append("live delivery receipt exceeds max-age freshness")

    status = str(receipt.get("status") or "").strip()
    if status not in ALLOWED_STATUSES:
        issues.append("status must stay within the allowed WhatsApp live-delivery states")

    claim_allowed = receipt.get("live_delivery_claim_allowed") is True
    claim_scope = str(receipt.get("live_delivery_claim_scope") or "").strip()
    human_claim_allowed = (
        receipt.get("human_playback_acceptance_claim_allowed") is True
    )
    real_user_verified = (
        receipt.get("real_user_playback_acceptance_verified") is True
    )
    canary_claim_allowed = receipt.get("canary_completion_claim_allowed") is True
    for field in (
        "live_delivery_claim_allowed",
        "fresh_live_job_receipt_proven",
        "historical_or_shadow_proof_only",
        "machine_playback_e2e_verified",
        "real_user_playback_acceptance_verified",
        "human_playback_acceptance_claim_allowed",
        "canary_completion_claim_allowed",
        "goal_completion_claim_allowed",
    ):
        if not isinstance(receipt.get(field), bool):
            issues.append(f"{field} must be a boolean")
    failed_codes_value = receipt.get("failed_codes")
    if not isinstance(failed_codes_value, list):
        issues.append("failed_codes must be an array")
    failed_codes = [
        str(item).strip()
        for item in _as_list(failed_codes_value)
        if str(item).strip()
    ]
    next_action = str(receipt.get("next_action") or "").strip()
    runtime = _as_dict(receipt.get("runtime_readiness"))
    audiobook_runtime = _as_dict(receipt.get("audiobook_runtime"))
    historical = _as_dict(receipt.get("historical_evidence"))
    proof_freshness = _as_dict(receipt.get("proof_freshness"))
    for field in (
        "fresh_live_job_receipt_present",
        "fresh_live_job_receipt_passed",
    ):
        if not isinstance(proof_freshness.get(field), bool):
            issues.append(f"proof_freshness.{field} must be a boolean")
    if not isinstance(receipt.get("human_playback_acceptance_evidence"), dict):
        issues.append("human_playback_acceptance_evidence must be an object")
    human_evidence = _as_dict(receipt.get("human_playback_acceptance_evidence"))
    if not isinstance(receipt.get("proof_semantics"), dict):
        issues.append("proof_semantics must be an object")
    proof_semantics = _as_dict(receipt.get("proof_semantics"))
    for field in (
        "claim_allowed",
        "accepted",
        "rejected",
        "rejected_claim_observed",
        "feedback_sha256_present",
        "feedback_sha256_valid",
        "feedback_sha256_required",
        "operator_grade",
    ):
        if field in human_evidence and not isinstance(human_evidence.get(field), bool):
            issues.append(
                f"human_playback_acceptance_evidence.{field} must be a boolean"
            )
    human_status = str(human_evidence.get("status") or "").strip()
    human_evidence_accepted = human_evidence.get("accepted") is True
    accepted_relation_complete = bool(
        human_evidence_accepted
        and human_evidence.get("claim_allowed") is True
        and human_claim_allowed
        and real_user_verified
        and canary_claim_allowed
    )
    rejected_claim_observed = human_evidence.get("rejected_claim_observed") is True
    feedback_sha256_valid = human_evidence.get("feedback_sha256_valid") is True
    operator_grade_rejected = (
        human_status == "rejected"
        and feedback_sha256_valid
        and human_evidence.get("operator_grade") is True
    )
    unhashed_rejected_claim = (
        (human_status == "rejected" and not feedback_sha256_valid)
        or (human_status == "not_human_verified" and rejected_claim_observed and not feedback_sha256_valid)
    )

    if claim_scope not in ALLOWED_CLAIM_SCOPES:
        issues.append("live_delivery_claim_scope must explicitly separate machine delivery from human acceptance")
    if human_status and human_status not in {"accepted", "rejected", "not_human_verified", "legacy_non_complete"}:
        issues.append("human_playback_acceptance_evidence.status must be accepted, rejected, not_human_verified, or legacy_non_complete")
    if human_claim_allowed != (human_evidence.get("claim_allowed") is True):
        issues.append("human_playback_acceptance_claim_allowed must match human evidence claim_allowed")
    if human_status == "accepted" and not accepted_relation_complete:
        issues.append(
            "accepted human evidence requires accepted=true and human, real-user, and canary claims"
        )
        issues.append(
            "incomplete human acceptance evidence must use legacy_non_complete or not_human_verified status"
        )
    elif human_status != "accepted" and human_evidence_accepted:
        issues.append(
            "human_playback_acceptance_evidence.accepted=true requires status=accepted"
        )
    if proof_semantics.get("live_delivery_claim_scope") != claim_scope:
        issues.append("proof_semantics.live_delivery_claim_scope must match live_delivery_claim_scope")
    if proof_semantics.get("human_acceptance_evidence") != human_status:
        issues.append("proof_semantics.human_acceptance_evidence must match human evidence status")
    if human_status == "rejected":
        if human_evidence.get("rejected") is not True:
            issues.append("rejected human playback evidence must set rejected=true")
        if human_evidence.get("feedback_sha256_present") is not True:
            issues.append("rejected human playback evidence requires feedback_sha256_present=true")
        if not feedback_sha256_valid:
            issues.append("rejected human playback evidence requires feedback_sha256_valid=true")
        if human_evidence.get("operator_grade") is not True:
            issues.append("rejected human playback evidence must be marked operator_grade=true")
    else:
        if human_evidence.get("rejected") is True:
            issues.append("rejected=true is only allowed for hashed operator-grade rejected playback evidence")
        if rejected_claim_observed and feedback_sha256_valid:
            issues.append("hashed rejected playback claims must be materialized as rejected evidence")

    if status == "pass":
        if not claim_allowed:
            issues.append("pass status requires live_delivery_claim_allowed=true")
        if receipt.get("machine_playback_e2e_verified") is not True:
            issues.append("pass status requires machine_playback_e2e_verified=true")
        if claim_scope not in {"machine_playable_delivery_only", "machine_playable_delivery_and_human_accepted"}:
            issues.append("pass status requires a machine-playable live_delivery_claim_scope")
        if failed_codes:
            issues.append("pass status must not carry failed_codes")
        if receipt.get("fresh_live_job_receipt_proven") is not True:
            issues.append("pass status requires fresh_live_job_receipt_proven=true")
        if receipt.get("historical_or_shadow_proof_only") is True:
            issues.append("pass status cannot be historical_or_shadow_proof_only")
        if proof_freshness.get("fresh_live_job_receipt_passed") is not True:
            issues.append("pass proof_freshness must show a passing fresh live job receipt")
        if proof_freshness.get("fresh_live_job_receipt_present") is not True:
            issues.append("pass proof_freshness must show a fresh live job receipt")
        if proof_freshness.get("max_age_seconds") != LIVE_PROOF_MAX_AGE_SECONDS:
            issues.append("pass status requires the governed live proof max age")
        if not all(
            _as_dict(proof_freshness.get(key)).get("fresh") is True
            for key in (
                "selected_job_receipt",
                "selected_audio_publication_gate",
                "selected_machine_playback",
            )
        ):
            issues.append("pass status requires fresh job, publication-gate, and machine-playback timestamps")
        selected = _as_dict(receipt.get("selected_delivery"))
        performance = _as_dict(selected.get("performance_evidence"))
        narration = _as_dict(performance.get("narration_plan"))
        if not _public_performance_evidence_valid(performance):
            issues.append("pass status requires exact plan, cast, mastering, quality, chapter, and STT proof")
        if narration.get("contract_name") != NARRATION_PLAN_CONTRACT_NAME:
            issues.append("pass status requires the current v5 narration plan")
        if not human_status:
            issues.append("pass status requires human_playback_acceptance_evidence.status")
        if human_claim_allowed:
            if receipt.get("real_user_playback_acceptance_verified") is not True:
                issues.append("human acceptance claim requires real_user_playback_acceptance_verified=true")
            if human_status != "accepted":
                issues.append("human acceptance claim requires accepted human evidence")
            if claim_scope != "machine_playable_delivery_and_human_accepted":
                issues.append("accepted human evidence requires machine_playable_delivery_and_human_accepted scope")
            if next_action != "close_operator_loop":
                issues.append("accepted human playback acceptance requires close_operator_loop next_action")
        else:
            if receipt.get("real_user_playback_acceptance_verified") is True:
                issues.append("real_user_playback_acceptance_verified=true requires human_playback_acceptance_claim_allowed=true")
            if claim_scope != "machine_playable_delivery_only":
                issues.append("unverified or rejected human acceptance requires machine_playable_delivery_only scope")
            if operator_grade_rejected and next_action != "review_audiobook_playback_problem":
                issues.append("operator-grade rejected human playback requires review_audiobook_playback_problem next_action")
            if (
                unhashed_rejected_claim
                and next_action != "capture_hashed_audiobook_playback_problem_feedback"
            ):
                issues.append("unhashed rejected human playback claims require hashed playback-problem feedback capture")
            if human_status != "rejected" and "capture_real_user_playback_acceptance" not in next_action:
                if not rejected_claim_observed:
                    issues.append("unverified human playback acceptance requires capture-real-user next_action")
        if proof_semantics.get("machine_playable_delivery_does_not_imply_human_acceptance") is not True:
            issues.append("proof_semantics must state machine delivery does not imply human acceptance")
        canary_claim = receipt.get("canary_completion_claim_allowed") is True
        canary_blocked_value = receipt.get("canary_completion_blocked_fields")
        if not isinstance(canary_blocked_value, list):
            issues.append("canary_completion_blocked_fields must be an array")
        canary_blocked = [
            str(item).strip()
            for item in _as_list(canary_blocked_value)
            if str(item).strip()
        ]
        canary = _as_dict(selected.get("human_listened_canary"))
        if canary_claim:
            if not human_claim_allowed or receipt.get("real_user_playback_acceptance_verified") is not True:
                issues.append("canary completion requires verified human playback acceptance")
            if canary.get("contract_name") != HUMAN_LISTENED_CANARY_CONTRACT_NAME:
                issues.append("canary completion requires the immutable human-listened contract")
            if (
                canary.get("status") != "accepted"
                or canary.get("receipt_digest_valid") is not True
                or canary.get("receipt_hmac_valid") is not True
            ):
                issues.append("canary completion requires accepted digest-and-hmac-valid human evidence")
            if not _independent_canary_hmac_valid(
                canary,
                channel="whatsapp",
            ):
                issues.append(
                    "canary completion requires independently verified receipt HMAC"
                )
            if not _independent_perceptual_attestation_valid(
                canary,
                channel="whatsapp",
            ):
                issues.append(
                    "canary completion requires independently verified perceptual attestation"
                )
            immutable_receipt = _as_dict(canary.get("immutable_receipt"))
            if (
                not immutable_receipt
                or immutable_receipt.get("receipt_sha256")
                != _canonical_acceptance_sha256(immutable_receipt)
            ):
                issues.append("canary completion requires independently verified immutable receipt digest")
            canary_fields = canary.get("blocked_fields")
            if not isinstance(canary_fields, list):
                issues.append("canary blocked_fields must be an array")
            if canary_blocked or _as_list(canary_fields):
                issues.append("canary completion cannot carry blocked fields")
        else:
            if human_claim_allowed or receipt.get("real_user_playback_acceptance_verified") is True:
                issues.append("human acceptance claim cannot exceed canary completion proof")
            if not canary_blocked:
                issues.append("non-complete delivery must expose canary_completion_blocked_fields")
    else:
        if claim_allowed:
            issues.append("non-pass status must not claim live delivery")
        if claim_scope != "none":
            issues.append("non-pass status requires live_delivery_claim_scope=none")
        if receipt.get("human_playback_acceptance_claim_allowed") is not False:
            issues.append("non-pass status must not claim human playback acceptance")
        if receipt.get("real_user_playback_acceptance_verified") is not False:
            issues.append("non-pass status must not claim real-user playback acceptance")
        if receipt.get("canary_completion_claim_allowed") is not False:
            issues.append("non-pass status must not claim canary completion")
        if not failed_codes:
            issues.append("non-pass status must carry failed_codes")
        if not next_action:
            issues.append("non-pass status must include next_action")
        if receipt.get("fresh_live_job_receipt_proven") is not False:
            issues.append("non-pass status cannot prove fresh live job receipt")

    if status == "waiting_for_live_epub":
        if _safe_int(receipt.get("candidate_count"), default=-1) != 0:
            issues.append("waiting_for_live_epub requires candidate_count=0")
        if runtime.get("ready") is not True:
            issues.append("waiting_for_live_epub requires runtime_readiness.ready=true")
        if audiobook_runtime.get("ready_for_live_intake") is not True:
            issues.append("waiting_for_live_epub requires audiobook_runtime.ready_for_live_intake=true")
        if historical.get("historical_live_path_proven") is not True:
            issues.append("waiting_for_live_epub requires historical_live_path_proven=true")

    if status == "waiting_voice_choice":
        if "choose_whatsapp_audiobook_voice_sample" not in next_action:
            issues.append("waiting_voice_choice must keep the explicit voice-choice next action")
        if "voice_selection_text_fallback_ready" not in receipt:
            issues.append("waiting_voice_choice must expose voice_selection_text_fallback_ready")
        elif not isinstance(receipt.get("voice_selection_text_fallback_ready"), bool):
            issues.append("voice_selection_text_fallback_ready must be a boolean")
        pending = [
            row
            for row in _as_list(receipt.get("pending_user_selected_voice_jobs"))
            if isinstance(row, dict) and (row.get("voice_selection_waiting") or row.get("replacement_choice_pending"))
        ]
        if pending and not all("voice_selection_text_fallback_ready" in row for row in pending):
            issues.append("waiting voice-choice pending jobs must expose voice_selection_text_fallback_ready")

    if status == "waiting_provider_throttle" and "wait_until_provider_retry_after" not in next_action:
        issues.append("waiting_provider_throttle must keep the retry-after next action")

    if not isinstance(receipt.get("stage_summary"), dict):
        issues.append("stage_summary must be an object")
    if not isinstance(receipt.get("historical_evidence"), dict):
        issues.append("historical_evidence must be an object")
    if not isinstance(receipt.get("runtime_readiness"), dict):
        issues.append("runtime_readiness must be an object")
    if not isinstance(receipt.get("audiobook_runtime"), dict):
        issues.append("audiobook_runtime must be an object")
    if not isinstance(receipt.get("proof_freshness"), dict):
        issues.append("proof_freshness must be an object")

    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("goal_completion_claim_allowed must remain false")

    return issues


def main() -> int:
    import sys

    if any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python ea/scripts/verify_whatsapp_audiobook_live_delivery_receipt.py [options]\n\n"
            "Verify the WhatsApp audiobook live delivery receipt."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify the WhatsApp audiobook live delivery receipt.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    issues = verify(args.receipt)
    payload = {"status": "pass" if not issues else "blocked", "issues": issues}
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
