from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from materialize_manfred_realtime_conversation_readiness import REQUIRED_LIVE_PROOF_AFTER_READINESS
from materialize_manfred_realtime_conversation_readiness import ACTION_METHOD
from materialize_manfred_realtime_conversation_readiness import EVIDENCE_MAX_AGE_SECONDS
from materialize_manfred_realtime_conversation_readiness import EVIDENCE_RECEIPTS
from materialize_manfred_realtime_conversation_readiness import MANFRED_PROOF_LABEL
from materialize_manfred_realtime_conversation_readiness import MANFRED_PROOF_PATH
from materialize_manfred_realtime_conversation_readiness import MANFRED_OPERATOR_ACTION_KEY
from materialize_manfred_realtime_conversation_readiness import MANFRED_VOICE_GOLD_LABEL
from materialize_manfred_realtime_conversation_readiness import MANFRED_VOICE_GOLD_PATH
from materialize_manfred_realtime_conversation_readiness import _load_evidence_receipt
from materialize_manfred_realtime_conversation_readiness import _operator_status_from_receipts
from materialize_manfred_realtime_conversation_readiness import _readiness_blocked_checks
from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint


DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "manfred_realtime_conversation_readiness.generated.json"


def verify_manfred_realtime_conversation_readiness(receipt_path: str | Path) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    issues: list[str] = []
    allowed_top_level_fields = {
        "blocked_checks",
        "captured_candidate_diagnostic",
        "contract_name",
        "current_label",
        "evidence_source",
        "generated_at",
        "generated_by",
        "goal_completion_claim_allowed",
        "head_semantics",
        "input_evidence",
        "interaction_acceptance",
        "next_action",
        "next_action_href",
        "next_action_label",
        "next_action_method",
        "operator_action",
        "operator_action_key",
        "operator_status",
        "premium_spoken_claim_allowed",
        "privacy",
        "ready_for_realtime_conversation_review",
        "realtime_conversation_claim_allowed",
        "required_live_proof_after_readiness",
        "room_audio_attestation",
        "source_git_head",
        "source_state_fingerprint",
        "source_state_fingerprint_semantics",
        "status",
        "stt",
        "tts",
    }
    if set(receipt) - allowed_top_level_fields:
        issues.append("manfred_realtime_top_level_fields_unexpected")
    if allowed_top_level_fields - set(receipt):
        issues.append("manfred_realtime_top_level_fields_missing")
    current_head = resolve_source_state_head(REPO_ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(REPO_ROOT)
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    fingerprint_matches = bool(current_fingerprint and recorded_fingerprint and current_fingerprint == recorded_fingerprint)
    if receipt.get("contract_name") != "ea.manfred_realtime_conversation_readiness.v1":
        issues.append("manfred_realtime_contract_name_mismatch")
    if receipt.get("head_semantics") != "source_state":
        issues.append("manfred_realtime_head_semantics_missing")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("manfred_realtime_source_fingerprint_semantics_missing")
    if not recorded_head:
        issues.append("manfred_realtime_source_git_head_missing")
    elif current_head and recorded_head != current_head and not fingerprint_matches:
        issues.append("manfred_realtime_source_head_stale")
    if not recorded_fingerprint:
        issues.append("manfred_realtime_source_fingerprint_missing")
    elif current_fingerprint and recorded_fingerprint != current_fingerprint:
        issues.append("manfred_realtime_source_fingerprint_stale")
    next_action = str(receipt.get("next_action") or "").strip()
    next_action_href = str(receipt.get("next_action_href") or "").strip()
    next_action_label = str(receipt.get("next_action_label") or "").strip()
    next_action_method = str(receipt.get("next_action_method") or "").strip().lower()
    operator_action_key = str(receipt.get("operator_action_key") or "").strip()
    operator_action = dict(receipt.get("operator_action") or {})
    if receipt.get("generated_by") != "ea/scripts/materialize_manfred_realtime_conversation_readiness.py":
        issues.append("manfred_realtime_generated_by_mismatch")
    evidence_source = str(receipt.get("evidence_source") or "").strip()
    if evidence_source not in {
        "provided_operator_status",
        "receipt_aggregation",
        "conservative_default",
    }:
        issues.append("manfred_realtime_evidence_source_invalid")
    raw_input_evidence = receipt.get("input_evidence")
    input_evidence = dict(raw_input_evidence) if isinstance(raw_input_evidence, dict) else {}
    if evidence_source == "receipt_aggregation":
        allowed_evidence_fields = {
            "receipt_name",
            "present",
            "contract_name",
            "contract_valid",
            "status",
            "generated_at",
            "max_age_seconds",
            "fresh",
            "receipt_sha256",
            "source_git_head_present",
            "source_git_head_matches_current",
            "source_state_fingerprint_present",
            "source_state_matches_current",
            "raw_private_context_exposed",
            "raw_transcript_fields_exposed",
            "raw_credentials_exposed",
            "raw_receipt_payload_exposed",
        }
        missing_evidence = sorted(set(EVIDENCE_RECEIPTS) - set(input_evidence))
        extra_evidence = sorted(set(input_evidence) - set(EVIDENCE_RECEIPTS))
        for key in missing_evidence:
            issues.append(f"manfred_realtime_input_evidence_missing:{key}")
        for key in extra_evidence:
            issues.append(f"manfred_realtime_input_evidence_unexpected:{key}")
        for key, (expected_name, expected_contract) in EVIDENCE_RECEIPTS.items():
            raw_row = input_evidence.get(key)
            if not isinstance(raw_row, dict):
                continue
            row = dict(raw_row)
            if set(row) - allowed_evidence_fields:
                issues.append(f"manfred_realtime_input_evidence_fields_unexpected:{key}")
            if row.get("receipt_name") != expected_name:
                issues.append(f"manfred_realtime_input_evidence_name_mismatch:{key}")
            if row.get("contract_name") != expected_contract:
                issues.append(f"manfred_realtime_input_evidence_contract_mismatch:{key}")
            receipt_sha256 = str(row.get("receipt_sha256") or "").strip()
            if row.get("present") is True and (
                len(receipt_sha256) != 64
                or any(character not in "0123456789abcdef" for character in receipt_sha256.lower())
            ):
                issues.append(f"manfred_realtime_input_evidence_sha256_invalid:{key}")
            for raw_key in (
                "raw_private_context_exposed",
                "raw_transcript_fields_exposed",
                "raw_credentials_exposed",
                "raw_receipt_payload_exposed",
            ):
                if row.get(raw_key) is not False:
                    issues.append(f"manfred_realtime_input_evidence_raw_flag_not_false:{key}:{raw_key}")
            _payload, actual_evidence = _load_evidence_receipt(
                root=Path(receipt_path).parent,
                receipt_name=expected_name,
                expected_contract=expected_contract,
                current_head=current_head,
                current_fingerprint=current_fingerprint,
                max_age_seconds=EVIDENCE_MAX_AGE_SECONDS[key],
            )
            if any(row.get(field) != actual_evidence.get(field) for field in allowed_evidence_fields):
                issues.append(f"manfred_realtime_input_evidence_not_current:{key}")
            if receipt.get("ready_for_realtime_conversation_review") is True and (
                row.get("present") is not True
                or row.get("contract_valid") is not True
                or row.get("source_state_matches_current") is not True
                or row.get("fresh") is not True
            ):
                issues.append(f"manfred_realtime_ready_input_evidence_not_current:{key}")

    stt = dict(receipt.get("stt") or {}) if isinstance(receipt.get("stt"), dict) else {}
    diagnostic = (
        dict(receipt.get("captured_candidate_diagnostic") or {})
        if isinstance(receipt.get("captured_candidate_diagnostic"), dict)
        else {}
    )
    tts = dict(receipt.get("tts") or {}) if isinstance(receipt.get("tts"), dict) else {}
    attestation = (
        dict(receipt.get("room_audio_attestation") or {})
        if isinstance(receipt.get("room_audio_attestation"), dict)
        else {}
    )
    if evidence_source == "receipt_aggregation":
        authoritative_status = _operator_status_from_receipts(Path(receipt_path).parent)
        if stt != dict(authoritative_status.get("spoken_conversation_stt") or {}):
            issues.append("manfred_realtime_stt_derivation_mismatch")
        if diagnostic != dict(authoritative_status.get("captured_candidate_diagnostic") or {}):
            issues.append("manfred_realtime_diagnostic_derivation_mismatch")
        if tts != dict(authoritative_status.get("spoken_conversation_tts") or {}):
            issues.append("manfred_realtime_tts_derivation_mismatch")
        if attestation != dict(authoritative_status.get("room_audio_attestation_packet") or {}):
            issues.append("manfred_realtime_attestation_derivation_mismatch")
    allowed_nested_fields = {
        "stt": {
            "status",
            "production_eligible",
            "production_provider",
            "provider_label",
            "passed_samples",
            "sample_count",
            "avg_token_f1",
            "avg_wer",
            "ground_truth_fixture_mode",
            "real_captured_fixture_status",
            "next_action",
            "receipt_path",
            "scoring",
        },
        "captured_candidate_diagnostic": {
            "status",
            "diagnostic_status",
            "promotion_allowed",
            "may_update_fixture_manifest",
            "captured_row_count",
            "row_failure_codes",
            "next_action",
            "receipt_path",
            "privacy",
        },
        "tts": {
            "status",
            "premium_status",
            "direct_tts_audio_status",
            "conversation_turn_audio_status",
            "direct_tts_f1",
            "conversation_turn_audio_f1",
            "browser_audio_ready_for_ui",
            "browser_audio_transport",
            "browser_play_calls",
            "browser_play_ended",
            "room_audio_receipt",
            "premium_failed_codes",
            "next_action",
            "receipt_path",
            "browser_receipt_path",
            "room_audio_receipt_path",
        },
        "room_audio_attestation": {
            "status",
            "manual_only",
            "ci_must_not_auto_assert",
            "required_check_ids",
            "operator_command",
            "next_action",
            "receipt_path",
            "source_state_matches_current",
            "evidence_fresh",
        },
    }
    for name, payload in (
        ("stt", stt),
        ("captured_candidate_diagnostic", diagnostic),
        ("tts", tts),
        ("room_audio_attestation", attestation),
    ):
        if set(payload) - allowed_nested_fields[name]:
            issues.append(f"manfred_realtime_nested_fields_unexpected:{name}")
    if isinstance(stt.get("scoring"), dict) and set(dict(stt["scoring"])) - {
        "raw_transcript_fields",
        "redacted_text_fields",
    }:
        issues.append("manfred_realtime_stt_scoring_fields_unexpected")
    stt_scoring = dict(stt.get("scoring") or {}) if isinstance(stt.get("scoring"), dict) else {}
    if stt_scoring.get("raw_transcript_fields") is not False:
        issues.append("manfred_realtime_stt_scoring_raw_transcript_flag")
    if stt_scoring.get("redacted_text_fields") is not True:
        issues.append("manfred_realtime_stt_scoring_redaction_flag")
    if isinstance(diagnostic.get("privacy"), dict) and set(dict(diagnostic["privacy"])) - {
        "candidate_raw_text_fields",
        "raw_transcript_fields",
        "redacted_text_fields",
    }:
        issues.append("manfred_realtime_diagnostic_privacy_fields_unexpected")
    diagnostic_privacy = (
        dict(diagnostic.get("privacy") or {})
        if isinstance(diagnostic.get("privacy"), dict)
        else {}
    )
    if diagnostic_privacy.get("candidate_raw_text_fields") is not False:
        issues.append("manfred_realtime_diagnostic_candidate_raw_flag")
    if diagnostic_privacy.get("raw_transcript_fields") is not False:
        issues.append("manfred_realtime_diagnostic_raw_transcript_flag")
    if diagnostic_privacy.get("redacted_text_fields") is not True:
        issues.append("manfred_realtime_diagnostic_redaction_flag")
    expected_blocked_checks = _readiness_blocked_checks(
        stt=stt,
        diagnostic=diagnostic,
        tts=tts,
        attestation=attestation,
        room_audio_receipt=tts.get("room_audio_receipt"),
        evidence_source=evidence_source,
    )
    blocked_checks = [
        str(item or "").strip()
        for item in list(receipt.get("blocked_checks") or [])
        if str(item or "").strip()
    ]
    if blocked_checks != expected_blocked_checks:
        issues.append("manfred_realtime_blocked_checks_inconsistent")
    expected_ready = not expected_blocked_checks
    expected_status = (
        "ready_for_realtime_conversation_review"
        if expected_ready
        else "blocked_realtime_prerequisites"
    )
    if receipt.get("status") != expected_status:
        issues.append("manfred_realtime_status_inconsistent")
    if receipt.get("ready_for_realtime_conversation_review") is not expected_ready:
        issues.append("manfred_realtime_ready_flag_inconsistent")
    if receipt.get("realtime_conversation_claim_allowed") is not False:
        issues.append("manfred_realtime_realtime_claim_inconsistent")
    if receipt.get("premium_spoken_claim_allowed") is not False:
        issues.append("manfred_realtime_premium_claim_inconsistent")
    if receipt.get("operator_status") != ("pass" if expected_ready else "blocked"):
        issues.append("manfred_realtime_operator_status_inconsistent")
    if receipt.get("current_label") != (
        "Memorial public-origin gold: pass"
        if expected_ready
        else "Memorial public-origin gold: blocked"
    ):
        issues.append("manfred_realtime_current_label_inconsistent")
    if receipt.get("goal_completion_claim_allowed") is True:
        issues.append("manfred_realtime_goal_completion_overclaim")
    if receipt.get("realtime_conversation_claim_allowed") is True and receipt.get("blocked_checks"):
        issues.append("manfred_realtime_claim_overclaim")
    if dict(receipt.get("captured_candidate_diagnostic") or {}).get("promotion_allowed") is True and receipt.get("blocked_checks"):
        issues.append("manfred_realtime_captured_diagnostic_overclaim")
    privacy = dict(receipt.get("privacy") or {}) if isinstance(receipt.get("privacy"), dict) else {}
    expected_privacy = {
        "raw_private_context_exposed": False,
        "raw_transcript_fields": False,
        "candidate_raw_text_fields": False,
        "redacted_text_fields": True,
    }
    if privacy != expected_privacy:
        issues.append("manfred_realtime_privacy_shape_or_value_mismatch")
    for key, value in privacy.items():
        if key != "redacted_text_fields" and value is not False:
            issues.append(f"manfred_realtime_privacy_flag_not_false:{key}")
    interaction_acceptance = (
        dict(receipt.get("interaction_acceptance") or {})
        if isinstance(receipt.get("interaction_acceptance"), dict)
        else {}
    )
    if interaction_acceptance != {"ongoing_cinematic_narration_not_scene_bound": True}:
        issues.append("manfred_realtime_interaction_acceptance_mismatch")
    proofs = set(receipt.get("required_live_proof_after_readiness") or [])
    if not set(REQUIRED_LIVE_PROOF_AFTER_READINESS) <= proofs:
        issues.append("manfred_realtime_required_live_proof_incomplete")
    if not next_action:
        issues.append("manfred_realtime_next_action_missing")
    if next_action_method != ACTION_METHOD:
        issues.append("manfred_realtime_next_action_method_missing")
    if not operator_action:
        issues.append("manfred_realtime_operator_action_missing")
    else:
        allowed_operator_action_fields = {
            "action_required_reason",
            "blocked_checks",
            "candidate_raw_text_fields_exposed",
            "ci_must_not_auto_assert",
            "claim_boundary",
            "delivery_policy",
            "instruction",
            "interruption_budget",
            "irreversible_actions_consent_gated",
            "kind",
            "manual_only",
            "next_action",
            "next_action_href",
            "next_action_label",
            "next_action_method",
            "non_action_progress_push_allowed",
            "operator_action_key",
            "quiet_hours_respected",
            "raw_chat_ids_exposed",
            "raw_private_context_exposed",
            "raw_secret_exposed",
            "raw_token_exposed",
            "raw_transcript_fields_exposed",
            "raw_voice_ids_exposed",
            "required_check_count",
            "required_check_ids",
            "required_next_receipt",
            "status",
            "telegram_push_allowed",
            "user_action_required",
        }
        required_operator_action_fields = {
            "action_required_reason",
            "blocked_checks",
            "candidate_raw_text_fields_exposed",
            "ci_must_not_auto_assert",
            "delivery_policy",
            "instruction",
            "interruption_budget",
            "irreversible_actions_consent_gated",
            "kind",
            "manual_only",
            "next_action",
            "next_action_href",
            "next_action_label",
            "next_action_method",
            "non_action_progress_push_allowed",
            "operator_action_key",
            "quiet_hours_respected",
            "raw_chat_ids_exposed",
            "raw_private_context_exposed",
            "raw_secret_exposed",
            "raw_token_exposed",
            "raw_transcript_fields_exposed",
            "raw_voice_ids_exposed",
            "required_check_count",
            "required_check_ids",
            "status",
            "telegram_push_allowed",
            "user_action_required",
        }
        if set(operator_action) - allowed_operator_action_fields:
            issues.append("manfred_realtime_operator_action_fields_unexpected")
        if required_operator_action_fields - set(operator_action):
            issues.append("manfred_realtime_operator_action_fields_missing")
        for raw_key in (
            "raw_private_context_exposed",
            "raw_chat_ids_exposed",
            "raw_token_exposed",
            "raw_secret_exposed",
            "raw_transcript_fields_exposed",
            "candidate_raw_text_fields_exposed",
            "raw_voice_ids_exposed",
        ):
            if operator_action.get(raw_key) is not False:
                issues.append(f"manfred_realtime_operator_action_raw_flag_not_false:{raw_key}")
        if operator_action.get("quiet_hours_respected") is not True:
            issues.append("manfred_realtime_operator_action_quiet_hours_missing")
        if operator_action.get("non_action_progress_push_allowed") is not False:
            issues.append("manfred_realtime_operator_action_non_action_push_allowed")
        if operator_action.get("irreversible_actions_consent_gated") is not True:
            issues.append("manfred_realtime_operator_action_consent_gate_missing")
        if operator_action.get("next_action") != next_action:
            issues.append("manfred_realtime_operator_action_next_action_mismatch")
        if operator_action.get("next_action_href") != next_action_href:
            issues.append("manfred_realtime_operator_action_href_mismatch")
        if operator_action.get("next_action_label") != next_action_label:
            issues.append("manfred_realtime_operator_action_label_mismatch")
        if str(operator_action.get("next_action_method") or "").lower() != next_action_method:
            issues.append("manfred_realtime_operator_action_method_mismatch")
    if receipt.get("status") == "ready_for_realtime_conversation_review":
        if operator_action_key:
            issues.append("manfred_realtime_operator_action_key_should_be_empty_when_ready")
        if operator_action and operator_action.get("status") != "not_required":
            issues.append("manfred_realtime_operator_action_ready_status_mismatch")
        if operator_action and operator_action.get("user_action_required") is not False:
            issues.append("manfred_realtime_operator_action_ready_user_required")
        if operator_action and operator_action.get("delivery_policy") != "queue_only":
            issues.append("manfred_realtime_operator_action_ready_delivery_policy")
        if operator_action and operator_action.get("telegram_push_allowed") is not False:
            issues.append("manfred_realtime_operator_action_ready_push_allowed")
        if next_action_href != MANFRED_PROOF_PATH:
            issues.append("manfred_realtime_ready_next_action_href_drift")
        if next_action_label != MANFRED_PROOF_LABEL:
            issues.append("manfred_realtime_ready_next_action_label_drift")
    elif blocked_checks:
        if operator_action_key != MANFRED_OPERATOR_ACTION_KEY:
            issues.append("manfred_realtime_operator_action_key_missing")
        if operator_action and operator_action.get("operator_action_key") != MANFRED_OPERATOR_ACTION_KEY:
            issues.append("manfred_realtime_operator_action_packet_key_missing")
        if operator_action and operator_action.get("status") != "action_required":
            issues.append("manfred_realtime_operator_action_status_mismatch")
        if operator_action and operator_action.get("user_action_required") is not True:
            issues.append("manfred_realtime_operator_action_must_require_user")
        if operator_action and operator_action.get("delivery_policy") != "action_required_only":
            issues.append("manfred_realtime_operator_action_delivery_policy_mismatch")
        if operator_action and operator_action.get("telegram_push_allowed") is not True:
            issues.append("manfred_realtime_operator_action_push_flag_mismatch")
        if operator_action and operator_action.get("interruption_budget") != "action_required":
            issues.append("manfred_realtime_operator_action_budget_mismatch")
        if operator_action and operator_action.get("manual_only") is not True:
            issues.append("manfred_realtime_operator_action_manual_only_missing")
        if operator_action and operator_action.get("ci_must_not_auto_assert") is not True:
            issues.append("manfred_realtime_operator_action_ci_guard_missing")
        if operator_action and int(operator_action.get("required_check_count") or 0) <= 0:
            issues.append("manfred_realtime_operator_action_required_checks_missing")
        room_audio_blocked = bool({"room_audio_receipt_passed", "manual_room_checks_confirmed"}.intersection(blocked_checks))
        expected_href = MANFRED_PROOF_PATH if room_audio_blocked else MANFRED_VOICE_GOLD_PATH
        expected_label = MANFRED_PROOF_LABEL if room_audio_blocked else MANFRED_VOICE_GOLD_LABEL
        if next_action_href != expected_href:
            issues.append("manfred_realtime_blocked_next_action_href_drift")
        if next_action_label != expected_label:
            issues.append("manfred_realtime_blocked_next_action_label_drift")
    return {"contract_name": "ea.manfred_realtime_conversation_readiness.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Manfred realtime conversation readiness.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_manfred_realtime_conversation_readiness(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
