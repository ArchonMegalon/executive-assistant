#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LEGACY_DEFAULT_RECEIPT = "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"
CURRENT_DEFAULT_RECEIPT_NAME = "proactive_ooda_latest_run.generated.json"
RUN_RECEIPT_DIRNAME = "proactive_ooda_run_receipts"


def default_receipt_path() -> Path:
    explicit = str(
        os.getenv("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH")
        or os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH")
        or ""
    ).strip()
    if explicit:
        return Path(explicit)
    state_path = str(os.getenv("EA_PROACTIVE_OODA_STATE_PATH") or "").strip()
    if state_path:
        return Path(state_path).expanduser().resolve().parent / CURRENT_DEFAULT_RECEIPT_NAME
    repo_state_path = ROOT / "state" / "proactive_ooda_notified.json"
    repo_receipt_path = repo_state_path.parent / CURRENT_DEFAULT_RECEIPT_NAME
    if repo_receipt_path.exists() or repo_state_path.exists():
        return repo_receipt_path
    return Path(LEGACY_DEFAULT_RECEIPT)


DEFAULT_RECEIPT = str(default_receipt_path())


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the proactive OODA live Telegram delivery receipt.")
    parser.add_argument("--receipt-path", default=str(default_receipt_path()))
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    report = verify_receipt(Path(args.receipt_path))
    if args.pretty:
        print(_format_report(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


def verify_receipt(path: Path) -> dict[str, Any]:
    payload, errors = _load_receipt(path)
    latest_payload = dict(payload)
    latest_path = path
    archived_sent_receipt_used = False
    quiet_receipt_errors: list[str] = []
    if payload and _receipt_proves_action_required_only_quiet_delivery(payload):
        quiet_receipt_errors = _raw_payload_errors(payload)
        archived = _best_archived_sent_receipt(path)
        if archived is not None:
            path, payload = archived
            archived_sent_receipt_used = True
            errors = []
        else:
            errors = ["sent_receipt_missing_after_quiet"]
    if payload:
        errors.extend(_sent_receipt_errors(payload))
    errors.extend(f"quiet_{error}" for error in quiet_receipt_errors)

    return {
        "ok": not errors,
        "errors": errors,
        "receipt_path": str(path),
        "latest_receipt_path": str(latest_path),
        "latest_notification_status": latest_payload.get("notification_status", ""),
        "archived_sent_receipt_used": archived_sent_receipt_used,
        "quiet_receipt_path": str(latest_path) if archived_sent_receipt_used else "",
        "quiet_receipt_error_code": str(latest_payload.get("error_code") or "") if archived_sent_receipt_used else "",
        "notification_status": payload.get("notification_status", ""),
        "item_count": int(payload.get("item_count") or 0),
        "delivery_channel": str(payload.get("delivery_channel") or ""),
        "delivery_message_count": _message_id_count(payload.get("delivery_message_ids") or payload.get("telegram_message_ids") or []),
        "telegram_message_count": _message_id_count(payload.get("telegram_message_ids") or []),
        "delivery_route_error": str(payload.get("delivery_route_error") or ""),
        "delivery_recovery_hint": str(payload.get("delivery_recovery_hint") or ""),
        "delivery_next_action": str(payload.get("delivery_next_action") or ""),
        "generated_at": payload.get("generated_at", ""),
    }


def _load_receipt(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, ["receipt_missing"]
    except json.JSONDecodeError:
        return {}, ["receipt_invalid_json"]
    return (dict(payload), []) if isinstance(payload, dict) else ({}, ["receipt_invalid_json"])


def _best_archived_sent_receipt(current_receipt_path: Path) -> tuple[Path, dict[str, Any]] | None:
    receipt_dir = current_receipt_path.parent / RUN_RECEIPT_DIRNAME
    if not receipt_dir.is_dir():
        return None
    best: tuple[Path, dict[str, Any], float] | None = None
    for candidate in sorted(receipt_dir.glob("*.json")):
        payload, errors = _load_receipt(candidate)
        if errors or _sent_receipt_errors(payload):
            continue
        mtime = _safe_mtime(candidate)
        if best is None or mtime > best[2]:
            best = (candidate, payload, mtime)
    if best is None:
        return None
    return best[0], best[1]


def _sent_receipt_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
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
    if (
        delivery_channel in {"", "telegram"}
        and not _non_empty_message_id_list(telegram_message_ids)
        and not _non_empty_message_id_list(delivery_message_ids)
    ):
        errors.append("receipt_missing_telegram_message_id")
    if not _looks_sha256(payload.get("principal_id_hash")):
        errors.append("principal_hash_missing")
    refs = payload.get("notified_ref_hashes")
    if not isinstance(refs, list) or not refs or not all(_looks_sha256(item) for item in refs):
        errors.append("notified_ref_hashes_invalid")
    if payload.get("error_code"):
        errors.append("receipt_has_error_code")
    errors.extend(_raw_payload_errors(payload))
    return errors


def _receipt_proves_action_required_only_quiet_delivery(payload: dict[str, Any]) -> bool:
    if payload.get("dry_run") is not False:
        return False
    if str(payload.get("notification_status") or "").strip().lower() != "deferred":
        return False
    if str(payload.get("error_code") or "").strip() != "no_user_action_required":
        return False
    if int(payload.get("item_count") or 0) <= 0:
        return False
    return (
        _message_id_count(payload.get("delivery_message_ids") or []) == 0
        and _message_id_count(payload.get("telegram_message_ids") or []) == 0
    )


def _raw_payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    recipient_hash = str(payload.get("delivery_recipient_hash") or "").strip()
    if recipient_hash and not _looks_sha256(recipient_hash):
        errors.append("delivery_recipient_hash_invalid")
    for key in ("principal_id", "chat_id", "chat_ref", "recipient_ref", "recipient", "text", "message_text", "source_ref"):
        if key in payload:
            errors.append(f"receipt_contains_raw_{key}")
    approval_surface = dict(payload.get("approval_surface") or {})
    for key in ("callback_token", "packet_ref", "staged_artifact_ref", "approval_prompt", "staged_action_url"):
        if key in approval_surface:
            errors.append(f"receipt_contains_raw_approval_surface_{key}")
    return errors


def _looks_sha256(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized)


def _non_empty_message_id_list(value: Any) -> bool:
    return isinstance(value, list) and any(str(item or "").strip() for item in value)


def _message_id_count(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    return len([item for item in value if str(item or "").strip()])


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


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
    if report.get("archived_sent_receipt_used"):
        lines.append(
            "latest: "
            f"{report.get('latest_notification_status') or 'missing'} "
            f"{report.get('quiet_receipt_error_code') or ''}".strip()
            + f" ({report.get('latest_receipt_path')})"
        )
    if report["delivery_route_error"] or report["delivery_next_action"] or report["delivery_recovery_hint"]:
        recovery = report["delivery_next_action"] or "inspect_proactive_delivery_route"
        if report["delivery_route_error"]:
            recovery = f"{recovery} ({report['delivery_route_error']})"
        if report["delivery_recovery_hint"]:
            recovery = f"{recovery} - {report['delivery_recovery_hint']}"
        lines.append(f"recovery: {recovery}")
    if report["errors"]:
        lines.append(f"errors: {', '.join(report['errors'])}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
