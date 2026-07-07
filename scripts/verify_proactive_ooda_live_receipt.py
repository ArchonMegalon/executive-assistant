#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
LEGACY_DEFAULT_RECEIPT = "/data/provider-ledger/proactive_ooda_live_sent_receipt.json"
CURRENT_DEFAULT_RECEIPT_NAME = "proactive_ooda_latest_run.generated.json"
CURRENT_RUNTIME_RECEIPT = Path("/data/provider-ledger") / CURRENT_DEFAULT_RECEIPT_NAME
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
    if CURRENT_RUNTIME_RECEIPT.exists():
        return CURRENT_RUNTIME_RECEIPT
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
    archived_delivery_receipt_used = False
    archived_sent_receipt_used = False
    archived_operator_safe_mirror_receipt_used = False
    quiet_receipt_errors: list[str] = []
    if payload and _receipt_allows_archived_delivery_fallback(payload):
        quiet_receipt_errors = _raw_payload_errors(payload)
        archived = _best_archived_delivery_receipt(path)
        if archived is not None:
            path, payload, delivery_mode = archived
            archived_delivery_receipt_used = True
            archived_sent_receipt_used = delivery_mode == "telegram_sent"
            archived_operator_safe_mirror_receipt_used = delivery_mode == "operator_safe_mirror"
            errors = []
        else:
            errors = ["delivery_receipt_missing_after_quiet"]
    if payload:
        if _receipt_proves_operator_safe_mirror(payload):
            errors.extend(_operator_safe_mirror_receipt_errors(payload))
        else:
            errors.extend(_sent_receipt_errors(payload))
    errors.extend(_followthrough_errors(latest_payload))
    errors.extend(f"quiet_{error}" for error in quiet_receipt_errors)
    delivery_mode = _delivery_mode(payload)
    delivery_guard = dict(payload.get("delivery_guard") or {})
    followthrough = _followthrough_payload(latest_payload)
    delivery_next_action = str(payload.get("delivery_next_action") or "").strip()
    if not delivery_next_action and _followthrough_requires_recovery(latest_payload):
        delivery_next_action = "repair_proactive_operator_runtime_posture"

    return {
        "ok": not errors,
        "errors": errors,
        "receipt_path": str(path),
        "latest_receipt_path": str(latest_path),
        "latest_notification_status": latest_payload.get("notification_status", ""),
        "archived_delivery_receipt_used": archived_delivery_receipt_used,
        "archived_sent_receipt_used": archived_sent_receipt_used,
        "archived_operator_safe_mirror_receipt_used": archived_operator_safe_mirror_receipt_used,
        "quiet_receipt_path": str(latest_path) if archived_delivery_receipt_used else "",
        "quiet_receipt_error_code": (
            str(latest_payload.get("error_code") or latest_payload.get("notification_status") or "")
            if archived_delivery_receipt_used
            else ""
        ),
        "delivery_mode": delivery_mode,
        "operator_safe_mirror_present": delivery_mode == "operator_safe_mirror",
        "notification_status": payload.get("notification_status", ""),
        "item_count": int(payload.get("item_count") or 0),
        "delivery_channel": str(payload.get("delivery_channel") or ""),
        "delivery_message_count": _message_id_count(payload.get("delivery_message_ids") or payload.get("telegram_message_ids") or []),
        "telegram_message_count": _message_id_count(payload.get("telegram_message_ids") or []),
        "delivery_route_error": str(payload.get("delivery_route_error") or ""),
        "delivery_recovery_hint": str(payload.get("delivery_recovery_hint") or ""),
        "delivery_next_action": delivery_next_action,
        "delivery_guard_state": str(delivery_guard.get("delivery_state") or ""),
        "delivery_guard_deferred_reason": str(delivery_guard.get("deferred_reason") or ""),
        "quiet_hours_active": bool(delivery_guard.get("quiet_hours_active")),
        "interruption_budget_exhausted": bool(delivery_guard.get("interruption_budget_exhausted")),
        "notification_requires_user_action": bool(delivery_guard.get("notification_requires_user_action")),
        "followthrough_status": str(followthrough.get("status") or ""),
        "followthrough_reason": str(followthrough.get("reason") or ""),
        "followthrough_error": str(followthrough.get("error") or ""),
        "followthrough_run_receipt_path": str(followthrough.get("run_receipt_path") or ""),
        "followthrough_operator_status": _followthrough_component_status(followthrough, "operator_status"),
        "followthrough_gold_acceptance_status": _followthrough_component_status(followthrough, "gold_acceptance"),
        "followthrough_goal_posture_status": _followthrough_component_status(followthrough, "goal_posture"),
        "followthrough_goal_posture_queue_count": _followthrough_component_int(
            followthrough,
            "goal_posture",
            "operator_action_queue_count",
        ),
        "followthrough_digest_status": _followthrough_component_status(followthrough, "operator_action_required_digest"),
        "followthrough_digest_notification_status": _followthrough_component_text(
            followthrough,
            "operator_action_required_digest",
            "notification_status",
        ),
        "followthrough_digest_item_count": _followthrough_component_int(
            followthrough,
            "operator_action_required_digest",
            "item_count",
        ),
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


def _best_archived_delivery_receipt(current_receipt_path: Path) -> tuple[Path, dict[str, Any], str] | None:
    receipt_dir = current_receipt_path.parent / RUN_RECEIPT_DIRNAME
    if not receipt_dir.is_dir():
        return None
    best: tuple[Path, dict[str, Any], str, float] | None = None
    for candidate in sorted(receipt_dir.glob("*.json")):
        payload, errors = _load_receipt(candidate)
        if errors:
            continue
        delivery_mode = _delivery_mode(payload)
        if delivery_mode == "operator_safe_mirror":
            receipt_errors = _operator_safe_mirror_receipt_errors(payload)
        else:
            receipt_errors = _sent_receipt_errors(payload)
            delivery_mode = "telegram_sent" if not receipt_errors else ""
        if receipt_errors or not delivery_mode:
            continue
        mtime = _safe_mtime(candidate)
        if best is None or mtime > best[3]:
            best = (candidate, payload, delivery_mode, mtime)
    if best is None:
        return None
    return best[0], best[1], best[2]


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


def _operator_safe_mirror_receipt_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("notification_status") != "deferred":
        errors.append("mirror_receipt_not_deferred")
    if payload.get("error_code") != "mirrored_delivery_proof":
        errors.append("mirror_receipt_error_code_invalid")
    if payload.get("dry_run") is not False:
        errors.append("receipt_is_dry_run")
    if int(payload.get("item_count") or 0) < 1:
        errors.append("receipt_has_no_items")
    if _message_id_count(payload.get("delivery_message_ids") or []) or _message_id_count(payload.get("telegram_message_ids") or []):
        errors.append("mirror_receipt_has_delivery_message_id")
    if not _looks_sha256(payload.get("principal_id_hash")):
        errors.append("principal_hash_missing")
    stage_hashes = payload.get("stage_packet_ref_hashes")
    if not isinstance(stage_hashes, list) or not stage_hashes or not all(_looks_sha256(item) for item in stage_hashes):
        errors.append("stage_packet_ref_hashes_invalid")
    safe_hashes = payload.get("safe_work_result_ref_hashes")
    if not isinstance(safe_hashes, list) or not safe_hashes or not all(_looks_sha256(item) for item in safe_hashes):
        errors.append("safe_work_result_ref_hashes_invalid")
    mirror = dict(payload.get("delivery_mirror") or {})
    if not mirror.get("enabled"):
        errors.append("delivery_mirror_missing")
    if str(mirror.get("mode") or "").strip() != "operator_safe_mirror":
        errors.append("delivery_mirror_mode_invalid")
    if mirror.get("user_notification_suppressed") is not True:
        errors.append("delivery_mirror_user_notification_not_suppressed")
    if mirror.get("approval_request_requires_user_action") is not True:
        errors.append("delivery_mirror_action_required_missing")
    for key in ("packet_ref_hash", "staged_artifact_ref_hash", "notification_text_sha256"):
        if not _looks_sha256(mirror.get(key)):
            errors.append(f"delivery_mirror_{key}_invalid")
    if mirror.get("raw_notification_text_exposed"):
        errors.append("delivery_mirror_raw_notification_text_exposed")
    if mirror.get("raw_approval_prompt_exposed"):
        errors.append("delivery_mirror_raw_approval_prompt_exposed")
    if mirror.get("raw_private_url_exposed"):
        errors.append("delivery_mirror_raw_private_url_exposed")
    errors.extend(_raw_payload_errors(payload))
    return errors


def _delivery_mode(payload: dict[str, Any]) -> str:
    if _receipt_proves_operator_safe_mirror(payload):
        return "operator_safe_mirror"
    if payload.get("notification_status") == "sent":
        return "telegram_sent"
    return ""


def _followthrough_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = payload.get("followthrough_artifacts")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _followthrough_component_status(followthrough: Mapping[str, Any], key: str) -> str:
    component = followthrough.get(key)
    if not isinstance(component, Mapping):
        return ""
    return str(component.get("status") or "").strip()


def _followthrough_component_text(followthrough: Mapping[str, Any], key: str, field: str) -> str:
    component = followthrough.get(key)
    if not isinstance(component, Mapping):
        return ""
    return str(component.get(field) or "").strip()


def _followthrough_component_int(followthrough: Mapping[str, Any], key: str, field: str) -> int:
    component = followthrough.get(key)
    if not isinstance(component, Mapping):
        return 0
    return int(component.get(field) or 0)


def _followthrough_requires_recovery(payload: Mapping[str, Any]) -> bool:
    return any(error.startswith("followthrough_") for error in _followthrough_errors(payload))


def _followthrough_errors(payload: Mapping[str, Any]) -> list[str]:
    if not payload:
        return []
    followthrough = _followthrough_payload(payload)
    if not followthrough:
        return ["followthrough_artifacts_missing"]
    errors: list[str] = []
    status = str(followthrough.get("status") or "").strip()
    if not status:
        errors.append("followthrough_status_missing")
    elif status != "ok":
        errors.append("followthrough_status_not_ok")
    for key in (
        "operator_status",
        "gold_acceptance",
        "goal_posture",
        "operator_action_required_digest",
    ):
        component = followthrough.get(key)
        if not isinstance(component, Mapping):
            errors.append(f"followthrough_{key}_missing")
            continue
        if not str(component.get("path") or "").strip():
            errors.append(f"followthrough_{key}_path_missing")
        component_status = str(component.get("status") or "").strip()
        if not component_status:
            errors.append(f"followthrough_{key}_status_missing")
        elif component_status == "pending":
            errors.append(f"followthrough_{key}_pending")
    return errors


def _receipt_proves_operator_safe_mirror(payload: dict[str, Any]) -> bool:
    mirror = dict(payload.get("delivery_mirror") or {})
    return bool(
        payload.get("notification_status") == "deferred"
        and payload.get("error_code") == "mirrored_delivery_proof"
        and int(payload.get("item_count") or 0) > 0
        and mirror.get("enabled")
        and str(mirror.get("mode") or "").strip() == "operator_safe_mirror"
        and mirror.get("user_notification_suppressed") is True
        and mirror.get("approval_request_requires_user_action") is True
    )


def _receipt_allows_archived_delivery_fallback(payload: dict[str, Any]) -> bool:
    if _receipt_proves_action_required_only_quiet_delivery(payload):
        return True
    return (
        payload.get("dry_run") is False
        and str(payload.get("notification_status") or "").strip().lower() == "skipped_no_items"
        and int(payload.get("item_count") or 0) == 0
        and _message_id_count(payload.get("delivery_message_ids") or []) == 0
        and _message_id_count(payload.get("telegram_message_ids") or []) == 0
    )


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
        f"mode: {report.get('delivery_mode') or 'none'}",
        f"items: {report['item_count']}",
        f"channel: {report['delivery_channel'] or 'telegram'}",
        f"delivery messages: {report['delivery_message_count']}",
        f"telegram messages: {report['telegram_message_count']}",
        f"receipt: {report['receipt_path']}",
    ]
    if report.get("followthrough_status"):
        followthrough_line = f"followthrough: {report['followthrough_status']}"
        if report.get("followthrough_reason"):
            followthrough_line = f"{followthrough_line} ({report['followthrough_reason']})"
        lines.append(followthrough_line)
    if report.get("archived_delivery_receipt_used"):
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
