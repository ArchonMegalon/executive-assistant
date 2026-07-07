#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/ea_operator_action_required_dedupe_proof.generated.json"
PRIVATE_FLAGS = (
    "raw_private_context_exposed",
    "raw_chat_ids_exposed",
    "raw_message_ids_exposed",
    "raw_token_exposed",
    "raw_secret_exposed",
    "raw_voice_ids_exposed",
    "raw_pair_url_exposed",
    "raw_qr_payload_exposed",
    "raw_whatsapp_session_ref_exposed",
    "callback_tokens_exposed",
    "raw_acceptance_text_exposed",
    "raw_actor_identity_exposed",
    "raw_object_reference_exposed",
    "raw_transcript_fields_exposed",
    "candidate_raw_text_fields_exposed",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def verify_receipt(receipt: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if receipt.get("contract_name") != "ea.operator_action_required_dedupe_proof.v1":
        issues.append("contract_name must be ea.operator_action_required_dedupe_proof.v1")
    if str(receipt.get("status") or "").strip() != "pass":
        issues.append("status must be pass")
    if str(receipt.get("delivery_policy") or "").strip() != "action_required_only":
        issues.append("delivery_policy must be action_required_only")
    if receipt.get("dedupe_checked") is not True:
        issues.append("dedupe_checked must be true")
    if receipt.get("send_attempted") is not False:
        issues.append("send_attempted must be false")
    if receipt.get("send_requested") is not False:
        issues.append("send_requested must be false")
    suppressed_duplicate_expected = receipt.get("suppressed_duplicate_expected") is True
    notification_count_without_force = int(receipt.get("notification_item_count_without_force") or 0)
    notification_mode_without_force = str(receipt.get("notification_mode_without_force") or "").strip()
    proof_outcome = str(receipt.get("proof_outcome") or "").strip()
    if suppressed_duplicate_expected:
        if proof_outcome and proof_outcome != "duplicate_suppression_valid":
            issues.append("proof_outcome must be duplicate_suppression_valid when suppression is expected")
        if receipt.get("would_send_without_force") is not False:
            issues.append("would_send_without_force must be false when suppression is expected")
        if receipt.get("force_required_to_resend") is not True:
            issues.append("force_required_to_resend must be true when suppression is expected")
        if receipt.get("current_actions_covered_by_prior_state") is not True:
            issues.append("current_actions_covered_by_prior_state must be true when suppression is expected")
        if notification_count_without_force != 0:
            issues.append("notification_item_count_without_force must be zero when suppression is expected")
        if notification_mode_without_force not in {"duplicate_suppressed", "covered_by_previous_send"}:
            issues.append("notification_mode_without_force must suppress resend when suppression is expected")
    else:
        if proof_outcome != "notification_required":
            issues.append("proof_outcome must be notification_required when suppression is not expected")
        if receipt.get("would_send_without_force") is not True:
            issues.append("would_send_without_force must be true when notification is required")
        if receipt.get("force_required_to_resend") is not False:
            issues.append("force_required_to_resend must be false when notification is required")
        if receipt.get("current_actions_covered_by_prior_state") is not False:
            issues.append("current_actions_covered_by_prior_state must be false when notification is required")
        if notification_count_without_force <= 0:
            issues.append("notification_item_count_without_force must be positive when notification is required")
        if notification_mode_without_force in {"duplicate_suppressed", "covered_by_previous_send", "none"}:
            issues.append("notification_mode_without_force must not suppress resend when notification is required")
    if not str(receipt.get("current_digest_sha256") or "").strip():
        issues.append("current_digest_sha256 must be present")
    item_count = int(receipt.get("item_count") or 0)
    if item_count <= 0:
        issues.append("item_count must be positive")
    included_keys = [str(item or "").strip() for item in list(receipt.get("included_action_keys") or []) if str(item or "").strip()]
    if len(included_keys) != item_count:
        issues.append("included_action_keys length must match item_count")
    counts = dict(receipt.get("counts") or {})
    if int(counts.get("included_count") or 0) != item_count:
        issues.append("counts.included_count must match item_count")

    state = dict(receipt.get("state") or {})
    if state.get("present") is not True:
        issues.append("state.present must be true")
    covered_by_prior_state = receipt.get("current_actions_covered_by_prior_state") is True
    notification_required = not suppressed_duplicate_expected
    if state.get("last_digest_match") is not True and not (covered_by_prior_state or notification_required):
        issues.append("state.last_digest_match must be true unless current actions are covered by prior state")
    if state.get("last_item_keys_match") is not True and not (covered_by_prior_state or notification_required):
        issues.append("state.last_item_keys_match must be true unless current actions are covered by prior state")
    if state.get("last_sent_at_present") is not True:
        issues.append("state.last_sent_at_present must be true")
    if int(state.get("message_id_count") or 0) <= 0:
        issues.append("state.message_id_count must be positive")
    for key in ("raw_chat_ref_stored", "raw_message_ids_stored", "raw_token_stored", "raw_secret_stored"):
        if state.get(key) is not False:
            issues.append(f"state.{key} must be false")

    source_receipts = dict(receipt.get("source_receipts") or {})
    posture = dict(source_receipts.get("posture") or {})
    if posture.get("present") is not True:
        issues.append("source_receipts.posture.present must be true")
    if not str(posture.get("sha256") or "").strip():
        issues.append("source_receipts.posture.sha256 must be present")
    sent_digest = dict(source_receipts.get("sent_digest") or {})
    if sent_digest.get("present") is not True:
        issues.append("source_receipts.sent_digest.present must be true")
    sent_digest_status = str(sent_digest.get("status") or "").strip()
    sent_digest_notification_status = str(sent_digest.get("notification_status") or "").strip()
    allowed_sent_statuses = {"sent", "suppressed_duplicate"} if suppressed_duplicate_expected else {"ready_to_send"}
    if sent_digest_status not in allowed_sent_statuses:
        issues.append(
            "source_receipts.sent_digest.status must match suppression outcome"
        )
    allowed_notification_statuses = (
        {"sent", "suppressed_duplicate"} if suppressed_duplicate_expected else {"ready_to_send"}
    )
    if sent_digest_notification_status not in allowed_notification_statuses:
        issues.append(
            "source_receipts.sent_digest.notification_status must match suppression outcome"
        )
    if sent_digest.get("digest_match") is not True:
        issues.append("source_receipts.sent_digest.digest_match must be true")
    if sent_digest_status == "sent" and int(sent_digest.get("message_count") or 0) <= 0:
        issues.append("source_receipts.sent_digest.message_count must be positive")
    if not suppressed_duplicate_expected:
        sent_notification_count = int(sent_digest.get("notification_item_count") or 0)
        if sent_notification_count != notification_count_without_force:
            issues.append("source_receipts.sent_digest.notification_item_count must match notification_item_count_without_force")
        sent_notification_keys = [
            str(item or "").strip()
            for item in list(sent_digest.get("notification_action_keys") or [])
            if str(item or "").strip()
        ]
        notification_keys = [
            str(item or "").strip()
            for item in list(receipt.get("notification_action_keys_without_force") or [])
            if str(item or "").strip()
        ]
        if sent_notification_keys != notification_keys:
            issues.append("source_receipts.sent_digest.notification_action_keys must match notification_action_keys_without_force")

    privacy = dict(receipt.get("privacy") or {})
    for flag in PRIVATE_FLAGS:
        if privacy.get(flag) is not False:
            issues.append(f"privacy.{flag} must be false")
    return issues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify EA operator action digest duplicate-suppression proof.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt_path = Path(args.receipt)
    issues = verify_receipt(_load_json(receipt_path))
    payload = {"status": "pass" if not issues else "fail", "receipt": str(receipt_path), "issues": issues}
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
