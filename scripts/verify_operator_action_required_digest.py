#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/ea_operator_action_required_digest.generated.json"
PRIVATE_EXPOSURE_FLAGS = (
    "raw_private_context_exposed",
    "raw_chat_ids_exposed",
    "raw_email_exposed",
    "raw_token_exposed",
    "raw_secret_exposed",
    "raw_voice_ids_exposed",
    "callback_tokens_exposed",
    "raw_public_share_url_exposed",
    "raw_track_url_exposed",
    "raw_acceptance_text_exposed",
    "raw_actor_identity_exposed",
    "raw_object_reference_exposed",
    "raw_transcript_fields_exposed",
    "candidate_raw_text_fields_exposed",
    "raw_expected_google_email_exposed",
    "raw_observed_google_email_exposed",
    "raw_client_id_exposed",
    "raw_client_secret_exposed",
    "raw_error_description_exposed",
    "raw_pair_url_exposed",
    "raw_qr_payload_exposed",
    "raw_whatsapp_session_ref_exposed",
)
ACTION_STATUSES = {
    "ready_to_send",
    "sent",
    "suppressed_duplicate",
    "blocked_telegram_not_ready",
    "blocked_telegram_send_failed",
}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _resolve_receipt_path(path_text: str, *, root: Path) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else root / path


def _issues_for_item(row: Mapping[str, Any], index: int) -> list[str]:
    issues: list[str] = []
    key = str(row.get("key") or "").strip() or f"item_{index}"
    if not str(row.get("key") or "").strip():
        issues.append(f"item missing key: {index}")
    if not str(row.get("instruction") or "").strip():
        issues.append(f"item missing instruction: {key}")
    if str(row.get("delivery_policy") or "").strip() != "action_required_only":
        issues.append(f"item delivery_policy must be action_required_only: {key}")
    if row.get("telegram_push_allowed") is not True:
        issues.append(f"item telegram_push_allowed must be true: {key}")
    if str(row.get("interruption_budget") or "").strip() != "action_required":
        issues.append(f"item interruption_budget must be action_required: {key}")
    if row.get("quiet_hours_respected") is not True:
        issues.append(f"item quiet_hours_respected must be true: {key}")
    if row.get("non_action_progress_push_allowed") is not False:
        issues.append(f"item non_action_progress_push_allowed must be false: {key}")
    if row.get("irreversible_actions_consent_gated") is not True:
        issues.append(f"item irreversible_actions_consent_gated must be true: {key}")
    for flag in PRIVATE_EXPOSURE_FLAGS:
        if flag in row and row.get(flag) is not False:
            issues.append(f"item must not expose {flag}: {key}")
    return issues


def verify_receipt(receipt: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if receipt.get("contract_name") != "ea.operator_action_required_digest.v1":
        issues.append("contract_name must be ea.operator_action_required_digest.v1")
    status = str(receipt.get("status") or "").strip()
    if status not in {*ACTION_STATUSES, "no_user_action_required"}:
        issues.append(f"unexpected status: {status or '<missing>'}")
    if str(receipt.get("delivery_policy") or "").strip() != "action_required_only":
        issues.append("delivery_policy must be action_required_only")
    if receipt.get("non_action_progress_push_allowed") is not False:
        issues.append("non_action_progress_push_allowed must be false")
    if receipt.get("quiet_hours_respected") is not True:
        issues.append("quiet_hours_respected must be true")
    if receipt.get("irreversible_actions_consent_gated") is not True:
        issues.append("irreversible_actions_consent_gated must be true")
    for flag in PRIVATE_EXPOSURE_FLAGS:
        if dict(receipt.get("privacy") or {}).get(flag) is not False:
            issues.append(f"privacy.{flag} must be false")
    items = [item for item in list(receipt.get("items") or []) if isinstance(item, dict)]
    item_count = int(receipt.get("item_count") or 0)
    if item_count != len(items):
        issues.append("item_count must match items length")
    included_keys = [
        str(item or "").strip()
        for item in list(receipt.get("included_action_keys") or [])
        if str(item or "").strip()
    ]
    item_keys = [str(item.get("key") or "").strip() for item in items if str(item.get("key") or "").strip()]
    if included_keys != item_keys:
        issues.append("included_action_keys must match item keys")
    counts = dict(receipt.get("counts") or {})
    if int(counts.get("included_count") or 0) != item_count:
        issues.append("counts.included_count must match item_count")
    if status in ACTION_STATUSES and item_count <= 0:
        issues.append("action status requires at least one item")
    if status == "no_user_action_required" and item_count != 0:
        issues.append("no_user_action_required requires item_count=0")
    if status == "suppressed_duplicate" and receipt.get("dedupe_suppressed") is not True:
        issues.append("suppressed_duplicate requires dedupe_suppressed=true")
    notification_items = [
        item for item in list(receipt.get("notification_items") or []) if isinstance(item, dict)
    ]
    notification_count = int(receipt.get("notification_item_count") or 0)
    if notification_count != len(notification_items):
        issues.append("notification_item_count must match notification_items length")
    notification_keys = [
        str(item or "").strip()
        for item in list(receipt.get("notification_action_keys") or [])
        if str(item or "").strip()
    ]
    notification_item_keys = [
        str(item.get("key") or "").strip()
        for item in notification_items
        if str(item.get("key") or "").strip()
    ]
    if notification_keys != notification_item_keys:
        issues.append("notification_action_keys must match notification item keys")
    if not set(notification_keys).issubset(set(item_keys)):
        issues.append("notification_action_keys must be a subset of included_action_keys")
    notification_status = str(receipt.get("notification_status") or "").strip()
    if status in {"ready_to_send", "sent", "blocked_telegram_not_ready", "blocked_telegram_send_failed"}:
        if notification_count <= 0:
            issues.append("sendable action status requires notification_item_count>0")
        if not str(receipt.get("notification_digest_sha256") or "").strip():
            issues.append("sendable action status requires notification_digest_sha256")
    if status == "suppressed_duplicate" and notification_count != 0:
        issues.append("suppressed_duplicate requires notification_item_count=0")
    if status == "no_user_action_required" and notification_count != 0:
        issues.append("no_user_action_required requires notification_item_count=0")
    send_result = dict(receipt.get("send_result") or {})
    if status == "sent":
        if notification_status != "sent":
            issues.append("sent status requires notification_status=sent")
        if receipt.get("send_attempted") is not True:
            issues.append("sent status requires send_attempted=true")
        if receipt.get("dry_run") is not False:
            issues.append("sent status requires dry_run=false")
        if receipt.get("state_updated") is not True:
            issues.append("sent status requires state_updated=true")
        if send_result.get("sent") is not True:
            issues.append("sent status requires send_result.sent=true")
        if int(send_result.get("message_count") or 0) <= 0:
            issues.append("sent status requires send_result.message_count>0")
    if receipt.get("send_attempted") is True and receipt.get("send_requested") is not True:
        issues.append("send_attempted requires send_requested=true")
    if notification_status == "dry_run_ready":
        if receipt.get("dry_run") is not True:
            issues.append("dry_run_ready requires dry_run=true")
        if receipt.get("send_attempted") is not True:
            issues.append("dry_run_ready requires send_attempted=true")
        if send_result.get("ready") is not True:
            issues.append("dry_run_ready requires send_result.ready=true")
        if send_result.get("sent") is not False:
            issues.append("dry_run_ready requires send_result.sent=false")
        if int(send_result.get("message_count") or 0) != 0:
            issues.append("dry_run_ready requires send_result.message_count=0")
        if receipt.get("state_updated") is not False:
            issues.append("dry_run_ready must not update dedupe state")
    if notification_count > 0 and not str(receipt.get("telegram_text") or "").strip():
        issues.append("action digest with notification items requires telegram_text")
    if notification_count == 0 and str(receipt.get("telegram_text") or "").strip():
        issues.append("action digest without notification items must not include telegram_text")
    for index, item in enumerate(items):
        issues.extend(_issues_for_item(item, index))
    for index, item in enumerate(notification_items):
        issues.extend(_issues_for_item(item, index))
    if not str(dict(receipt.get("source_receipt") or {}).get("path") or "").strip():
        issues.append("source_receipt.path must be present")
    return issues


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path = ROOT) -> list[str]:
    receipt = _load_json(path)
    issues = verify_receipt(receipt)
    if not receipt:
        return issues

    current_head = resolve_source_state_head(root)
    current_fingerprint = resolve_source_worktree_fingerprint(root)
    source_head = str(receipt.get("source_git_head") or "").strip()
    source_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    if receipt.get("head_semantics") != "source_state":
        issues.append("head_semantics must be source_state")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("source_state_fingerprint_semantics mismatch")
    if not source_head:
        issues.append("source_git_head missing")
    elif source_head != current_head and source_fingerprint != current_fingerprint:
        issues.append("source state stale")
    if not source_fingerprint:
        issues.append("source_state_fingerprint missing")
    elif source_fingerprint != current_fingerprint:
        issues.append("source_state_fingerprint stale")

    source_receipt = dict(receipt.get("source_receipt") or {})
    source_path_text = str(source_receipt.get("path") or "").strip()
    source_sha256 = str(source_receipt.get("sha256") or "").strip()
    if source_path_text:
        source_path = _resolve_receipt_path(source_path_text, root=root)
        source_payload = _load_json(source_path)
        if not source_payload:
            issues.append("source_receipt.path must point to a readable posture receipt")
        else:
            current_source_sha256 = _sha256_json(source_payload)
            if not source_sha256:
                issues.append("source_receipt.sha256 must be present")
            elif source_sha256 != current_source_sha256:
                issues.append("source_receipt.sha256 stale")
    return issues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify EA operator action-required digest receipt.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt_path = Path(args.receipt)
    issues = verify(receipt_path)
    payload = {
        "status": "pass" if not issues else "fail",
        "receipt": str(receipt_path),
        "issues": issues,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
