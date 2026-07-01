#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/ea_operator_action_required_digest.generated.json"
PRIVATE_EXPOSURE_FLAGS = (
    "raw_private_context_exposed",
    "raw_chat_ids_exposed",
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
    if status == "sent" and dict(receipt.get("send_result") or {}).get("sent") is not True:
        issues.append("sent status requires send_result.sent=true")
    if receipt.get("send_attempted") is True and receipt.get("send_requested") is not True:
        issues.append("send_attempted requires send_requested=true")
    notification_status = str(receipt.get("notification_status") or "").strip()
    send_result = dict(receipt.get("send_result") or {})
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
    if item_count > 0 and not str(receipt.get("telegram_text") or "").strip():
        issues.append("action digest with items requires telegram_text")
    for index, item in enumerate(items):
        issues.extend(_issues_for_item(item, index))
    if not str(dict(receipt.get("source_receipt") or {}).get("path") or "").strip():
        issues.append("source_receipt.path must be present")
    return issues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify EA operator action-required digest receipt.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt_path = Path(args.receipt)
    receipt = _load_json(receipt_path)
    issues = verify_receipt(receipt)
    payload = {
        "status": "pass" if not issues else "fail",
        "receipt": str(receipt_path),
        "issues": issues,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
