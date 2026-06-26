#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_RECEIPT = "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the proactive OODA live Telegram delivery receipt.")
    parser.add_argument("--receipt-path", default=DEFAULT_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    report = verify_receipt(Path(args.receipt_path))
    if args.pretty:
        print(_format_report(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


def verify_receipt(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = {}
        errors.append("receipt_missing")
    except json.JSONDecodeError:
        payload = {}
        errors.append("receipt_invalid_json")

    if payload:
        if payload.get("notification_status") != "sent":
            errors.append("receipt_not_sent")
        if payload.get("dry_run") is not False:
            errors.append("receipt_is_dry_run")
        if int(payload.get("item_count") or 0) < 1:
            errors.append("receipt_has_no_items")
        delivery_channel = str(payload.get("delivery_channel") or "").strip().lower()
        delivery_message_ids = payload.get("delivery_message_ids")
        telegram_message_ids = payload.get("telegram_message_ids")
        if not _non_empty_message_id_list(delivery_message_ids) and not _non_empty_message_id_list(telegram_message_ids):
            errors.append("receipt_missing_delivery_message_id")
        if delivery_channel in {"", "telegram"} and not _non_empty_message_id_list(telegram_message_ids) and not _non_empty_message_id_list(delivery_message_ids):
            errors.append("receipt_missing_telegram_message_id")
        if not _looks_sha256(payload.get("principal_id_hash")):
            errors.append("principal_hash_missing")
        refs = payload.get("notified_ref_hashes")
        if not isinstance(refs, list) or not refs or not all(_looks_sha256(item) for item in refs):
            errors.append("notified_ref_hashes_invalid")
        if payload.get("error_code"):
            errors.append("receipt_has_error_code")
        recipient_hash = str(payload.get("delivery_recipient_hash") or "").strip()
        if recipient_hash and not _looks_sha256(recipient_hash):
            errors.append("delivery_recipient_hash_invalid")
        for key in ("principal_id", "chat_id", "chat_ref", "recipient_ref", "recipient", "text", "message_text", "source_ref"):
            if key in payload:
                errors.append(f"receipt_contains_raw_{key}")

    return {
        "ok": not errors,
        "errors": errors,
        "receipt_path": str(path),
        "notification_status": payload.get("notification_status", ""),
        "item_count": int(payload.get("item_count") or 0),
        "delivery_channel": str(payload.get("delivery_channel") or ""),
        "delivery_message_count": _message_id_count(payload.get("delivery_message_ids") or payload.get("telegram_message_ids") or []),
        "telegram_message_count": _message_id_count(payload.get("telegram_message_ids") or []),
        "generated_at": payload.get("generated_at", ""),
    }


def _looks_sha256(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized)


def _non_empty_message_id_list(value: Any) -> bool:
    return isinstance(value, list) and any(str(item or "").strip() for item in value)


def _message_id_count(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    return len([item for item in value if str(item or "").strip()])


def _format_report(report: dict[str, Any]) -> str:
    status = "ok" if report["ok"] else "not ready"
    lines = [
        f"proactive OODA live receipt: {status}",
        f"status: {report['notification_status'] or 'missing'}",
        f"items: {report['item_count']}",
        f"channel: {report['delivery_channel'] or 'telegram'}",
        f"delivery messages: {report['delivery_message_count']}",
        f"telegram messages: {report['telegram_message_count']}",
        f"receipt: {report['receipt_path']}",
    ]
    if report["errors"]:
        lines.append(f"errors: {', '.join(report['errors'])}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
