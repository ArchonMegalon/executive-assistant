from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import hmac
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from materialize_telegram_audiobook_live_delivery_receipt import ACTION_METHOD
    from materialize_telegram_audiobook_live_delivery_receipt import CONTRACT_NAME
    from materialize_telegram_audiobook_live_delivery_receipt import DEFAULT_OUTPUT
    from materialize_telegram_audiobook_live_delivery_receipt import HUMAN_LISTENED_CANARY_CONTRACT_NAME
    from materialize_telegram_audiobook_live_delivery_receipt import LIVE_PROOF_FUTURE_SKEW_SECONDS
    from materialize_telegram_audiobook_live_delivery_receipt import LIVE_PROOF_MAX_AGE_SECONDS
    from materialize_telegram_audiobook_live_delivery_receipt import NARRATION_PLAN_CONTRACT_NAME
    from materialize_telegram_audiobook_live_delivery_receipt import PUBLIC_LOAD_ERROR_CODES
    from materialize_telegram_audiobook_live_delivery_receipt import TELEGRAM_ACTION_SURFACES
    from materialize_telegram_audiobook_live_delivery_receipt import _canonical_acceptance_sha256
    from materialize_telegram_audiobook_live_delivery_receipt import _canary_receipt_hmac_key
    from materialize_telegram_audiobook_live_delivery_receipt import _parse_utc
    from materialize_telegram_audiobook_live_delivery_receipt import _public_performance_evidence_valid
except ModuleNotFoundError:  # pragma: no cover - package import path
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import ACTION_METHOD
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import CONTRACT_NAME
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import DEFAULT_OUTPUT
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import HUMAN_LISTENED_CANARY_CONTRACT_NAME
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import LIVE_PROOF_FUTURE_SKEW_SECONDS
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import LIVE_PROOF_MAX_AGE_SECONDS
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import NARRATION_PLAN_CONTRACT_NAME
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import PUBLIC_LOAD_ERROR_CODES
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import TELEGRAM_ACTION_SURFACES
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import _canonical_acceptance_sha256
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import _canary_receipt_hmac_key
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import _parse_utc
    from ea.scripts.materialize_telegram_audiobook_live_delivery_receipt import _public_performance_evidence_valid

from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint


ALLOWED_STATUSES = {"pass", "blocked"}
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
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
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


def verify(path: Path = DEFAULT_OUTPUT, *, now: datetime | None = None) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"telegram audiobook live delivery receipt missing or invalid: {path}"]

    if receipt.get("contract_name") != CONTRACT_NAME:
        issues.append(f"contract_name must be {CONTRACT_NAME}")
    if receipt.get("generated_by") != "ea/scripts/materialize_telegram_audiobook_live_delivery_receipt.py":
        issues.append("generated_by must point at the Telegram live delivery materializer")
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
        issues.append("status must stay within the allowed Telegram live-delivery states")

    claim_allowed = receipt.get("live_delivery_claim_allowed") is True
    for field in (
        "live_delivery_claim_allowed",
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
    next_action_href = str(receipt.get("next_action_href") or "").strip()
    next_action_label = str(receipt.get("next_action_label") or "").strip()
    next_action_method = str(receipt.get("next_action_method") or "").strip().lower()
    expected_surface = TELEGRAM_ACTION_SURFACES.get(next_action)
    if not next_action:
        issues.append("next_action must be present")
    elif expected_surface is None:
        issues.append("next_action must map to a known Telegram operator surface")
    else:
        expected_href, expected_label, expected_method = expected_surface
        if next_action_href != expected_href:
            issues.append("next_action_href must match the mapped Telegram operator surface")
        if next_action_label != expected_label:
            issues.append("next_action_label must match the mapped Telegram operator surface")
        if next_action_method != expected_method.lower():
            issues.append("next_action_method must match the mapped Telegram operator surface")
    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("goal_completion_claim_allowed must remain false")
    operator_action_packet = _as_dict(receipt.get("operator_action_packet"))
    if not operator_action_packet:
        issues.append("operator_action_packet must be present")
    else:
        if not isinstance(operator_action_packet.get("user_action_required"), bool):
            issues.append("operator_action_packet.user_action_required must be a boolean")
        if operator_action_packet.get("raw_voice_ids_exposed") is not False:
            issues.append("operator_action_packet.raw_voice_ids_exposed must remain false")
        if operator_action_packet.get("callback_tokens_exposed") is not False:
            issues.append("operator_action_packet.callback_tokens_exposed must remain false")
        if bool(operator_action_packet.get("user_action_required")):
            if not str(operator_action_packet.get("operator_action") or "").strip():
                issues.append("action-required operator_action_packet must include operator_action")
            if not str(operator_action_packet.get("instruction") or "").strip():
                issues.append("action-required operator_action_packet must include instruction")
            if _safe_int(operator_action_packet.get("candidate_count"), default=0) <= 0:
                issues.append("action-required operator_action_packet must include candidate_count")
            labels = _as_list(operator_action_packet.get("candidate_labels"))
            if not labels:
                issues.append("action-required operator_action_packet must include candidate_labels")
            if operator_action_packet.get("next_action_href") != next_action_href:
                issues.append("operator_action_packet next_action_href must match receipt next_action_href")
            if operator_action_packet.get("next_action_label") != next_action_label:
                issues.append("operator_action_packet next_action_label must match receipt next_action_label")
            if str(operator_action_packet.get("next_action_method") or "").strip().lower() != next_action_method:
                issues.append("operator_action_packet next_action_method must match receipt next_action_method")
    duplicate_suppression = _as_dict(receipt.get("duplicate_suppression"))
    if not duplicate_suppression:
        issues.append("duplicate_suppression must be present")
    else:
        if duplicate_suppression.get("action_required_only") is not True:
            issues.append("duplicate_suppression.action_required_only must be true")
        if duplicate_suppression.get("only_current_jobs_can_require_user_action") is not True:
            issues.append("duplicate_suppression.only_current_jobs_can_require_user_action must be true")
        if duplicate_suppression.get("raw_voice_ids_exposed") is not False:
            issues.append("duplicate_suppression.raw_voice_ids_exposed must remain false")
        if duplicate_suppression.get("callback_tokens_exposed") is not False:
            issues.append("duplicate_suppression.callback_tokens_exposed must remain false")
        if _safe_int(
            duplicate_suppression.get("duplicate_active_pending_source_key_count"),
            default=-1,
        ) != 0:
            issues.append("duplicate_suppression must not leave duplicate active pending source keys")
        if _safe_int(
            duplicate_suppression.get("active_pending_voice_job_count"),
        ) != _safe_int(
            receipt.get("pending_user_selected_voice_job_count"),
            default=-2,
        ):
            issues.append("duplicate_suppression active pending count must match pending_user_selected_voice_job_count")
    privacy = _as_dict(receipt.get("privacy"))
    for key in ("provider_secret_exposed", "audiobookshelf_token_exposed"):
        if privacy.get(key) is not False:
            issues.append(f"privacy.{key} must remain false")

    real_user_accepted = (
        receipt.get("real_user_playback_acceptance_verified") is True
    )
    machine_verified = receipt.get("machine_playback_e2e_verified") is True
    human_claim = receipt.get("human_playback_acceptance_claim_allowed") is True
    canary_claim = receipt.get("canary_completion_claim_allowed") is True
    if human_claim != canary_claim:
        issues.append(
            "human_playback_acceptance_claim_allowed must equal canary_completion_claim_allowed"
        )
    if (human_claim or canary_claim) and not real_user_accepted:
        issues.append(
            "human acceptance claims require real_user_playback_acceptance_verified=true"
        )
    canary_blocked_fields_value = receipt.get("canary_completion_blocked_fields")
    if not isinstance(canary_blocked_fields_value, list):
        issues.append("canary_completion_blocked_fields must be an array")
    canary_blocked_fields = [
        str(item).strip()
        for item in _as_list(canary_blocked_fields_value)
        if str(item).strip()
    ]
    proof_freshness = _as_dict(receipt.get("proof_freshness"))
    for field in (
        "fresh_live_job_receipt_present",
        "fresh_live_job_receipt_passed",
    ):
        if not isinstance(proof_freshness.get(field), bool):
            issues.append(f"proof_freshness.{field} must be a boolean")
    selected = _as_dict(receipt.get("selected_delivery"))
    performance = _as_dict(selected.get("performance_evidence"))
    canary = _as_dict(selected.get("human_listened_canary"))
    if status == "pass":
        if not claim_allowed:
            issues.append("pass status requires live_delivery_claim_allowed=true")
        if failed_codes:
            issues.append("pass status must not carry failed_codes")
        if not machine_verified:
            issues.append("pass status requires machine_playback_e2e_verified=true")
        if proof_freshness.get("max_age_seconds") != LIVE_PROOF_MAX_AGE_SECONDS:
            issues.append("pass status requires the governed live proof max age")
        if proof_freshness.get("fresh_live_job_receipt_present") is not True:
            issues.append("pass status requires a fresh job receipt")
        if proof_freshness.get("fresh_live_job_receipt_passed") is not True:
            issues.append("pass status requires a fresh passing job receipt")
        if not all(
            _as_dict(proof_freshness.get(key)).get("fresh") is True
            for key in (
                "selected_job_receipt",
                "selected_audio_publication_gate",
                "selected_machine_playback",
            )
        ):
            issues.append("pass status requires fresh job, publication-gate, and machine-playback timestamps")
        if not _public_performance_evidence_valid(performance):
            issues.append("pass status requires exact plan, cast, mastering, quality, chapter, and STT proof")
        narration = _as_dict(performance.get("narration_plan"))
        if narration.get("contract_name") != NARRATION_PLAN_CONTRACT_NAME:
            issues.append("pass status requires the current v5 narration plan")
        if real_user_accepted:
            if not canary_claim:
                issues.append("human acceptance cannot be verified without canary completion proof")
            if next_action != "close_operator_loop":
                issues.append("accepted human playback must close the operator loop")
        else:
            if canary_claim:
                issues.append("machine-only delivery cannot claim canary completion")
            if next_action != "capture_real_user_playback_acceptance_or_close_operator_loop":
                issues.append("machine-only pass must keep playback-acceptance capture as the next action")
        if canary_claim:
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
                channel="telegram",
            ):
                issues.append(
                    "canary completion requires independently verified receipt HMAC"
                )
            if not _independent_perceptual_attestation_valid(
                canary,
                channel="telegram",
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
            if canary_blocked_fields or _as_list(canary_fields):
                issues.append("canary completion cannot carry blocked fields")
        elif not canary_blocked_fields:
            issues.append("non-complete delivery must expose canary_completion_blocked_fields")
    else:
        if claim_allowed:
            issues.append("blocked status must not claim live delivery")
        if receipt.get("real_user_playback_acceptance_verified") is not False:
            issues.append("blocked status must not claim real-user playback acceptance")
        if receipt.get("human_playback_acceptance_claim_allowed") is not False:
            issues.append("blocked status must not claim human playback acceptance")
        if receipt.get("canary_completion_claim_allowed") is not False:
            issues.append("blocked status must not claim canary completion")
        if not failed_codes:
            issues.append("blocked status must carry failed_codes")
        if next_action == "close_operator_loop":
            issues.append("blocked status cannot close the operator loop")
        user_choice_actions = {
            "choose_one_telegram_audiobook_voice_sample",
            "choose_explicit_replacement_voice_or_restore_selected_provider",
            "choose_sent_replacement_voice_sample",
        }
        if (
            "audiobook_voice_choice_pending" in failed_codes
            or "explicit_replacement_voice_choice_pending" in failed_codes
        ) and next_action in user_choice_actions:
            if operator_action_packet.get("user_action_required") is not True:
                issues.append("voice-choice blocked status must set operator_action_packet.user_action_required=true")
        if next_action == "send_missing_telegram_audiobook_voice_samples_before_user_choice":
            if operator_action_packet.get("user_action_required") is not False:
                issues.append("under-delivered voice samples must remain an internal operator action")
            if "voice_sample_delivery_underfilled" not in failed_codes:
                issues.append("under-delivered voice sample action must include voice_sample_delivery_underfilled")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Telegram audiobook live delivery receipt.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_OUTPUT)
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
