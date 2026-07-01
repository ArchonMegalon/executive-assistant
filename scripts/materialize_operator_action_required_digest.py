#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/ea_operator_action_required_digest.generated.json"
DEFAULT_STATE = ROOT / ".runtime/ea_operator_action_required_digest_state.json"
DEFAULT_QUEUE_URL = "https://myexternalbrain.com/admin/goals"

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
    "raw_client_id_exposed",
    "raw_client_secret_exposed",
    "raw_error_description_exposed",
    "raw_pair_url_exposed",
    "raw_qr_payload_exposed",
    "raw_whatsapp_session_ref_exposed",
)


TelegramSender = Callable[[str, str, bool, float], dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dumps(payload), encoding="utf-8")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _git_head(root: Path) -> str:
    return resolve_source_state_head(root)


def _source_fingerprint(root: Path) -> str:
    return resolve_source_worktree_fingerprint(root)


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def _text(value: object, *, limit: int = 220) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(limit - 3, 0)].rstrip() + "..."


def _bool_is_false_or_missing(row: dict[str, Any], key: str) -> bool:
    return key not in row or row.get(key) is False


def _row_is_action_required_push(row: dict[str, Any]) -> bool:
    if row.get("user_action_required") is not True:
        return False
    if str(row.get("delivery_policy") or "").strip() != "action_required_only":
        return False
    if row.get("telegram_push_allowed") is not True:
        return False
    if str(row.get("interruption_budget") or "").strip() != "action_required":
        return False
    if row.get("quiet_hours_respected") is not True:
        return False
    if row.get("non_action_progress_push_allowed") is not False:
        return False
    if row.get("irreversible_actions_consent_gated") is not True:
        return False
    return all(_bool_is_false_or_missing(row, key) for key in PRIVATE_EXPOSURE_FLAGS)


def _sanitize_action_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": _text(row.get("key"), limit=96),
        "title": _text(row.get("title"), limit=120),
        "required_next_receipt": _text(row.get("required_next_receipt"), limit=180),
        "instruction": _text(row.get("instruction"), limit=180),
        "action_required_reason": _text(row.get("action_required_reason"), limit=120),
        "source_action_packet_present": bool(row.get("source_action_packet_present")),
        "source_action_packet_status": _text(row.get("source_action_packet_status"), limit=80),
        "required_form_fields": [
            _text(item, limit=80)
            for item in list(row.get("required_form_fields") or [])
            if _text(item, limit=80)
        ],
        "next_action": _text(row.get("next_action"), limit=120),
        "next_action_label": _text(row.get("next_action_label"), limit=80),
        "next_action_form_href": _text(row.get("next_action_form_href"), limit=180),
        "next_action_form_label": _text(row.get("next_action_form_label"), limit=80),
        "next_action_form_method": _text(row.get("next_action_form_method"), limit=16).lower(),
        "telegram_message": _text(row.get("telegram_message"), limit=320),
        "console_deep_link": _text(row.get("console_deep_link"), limit=220),
        "auth_link_template": _text(row.get("auth_link_template"), limit=260),
        "external_setup_url": _text(row.get("external_setup_url"), limit=260),
        "delivery_policy": "action_required_only",
        "telegram_push_allowed": True,
        "interruption_budget": "action_required",
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "raw_private_context_exposed": False,
        "raw_chat_ids_exposed": False,
        "raw_email_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_voice_ids_exposed": False,
        "callback_tokens_exposed": False,
        "raw_expected_google_email_exposed": False,
        "raw_client_id_exposed": False,
        "raw_client_secret_exposed": False,
        "raw_error_description_exposed": False,
        "raw_pair_url_exposed": False,
        "raw_qr_payload_exposed": False,
        "raw_whatsapp_session_ref_exposed": False,
    }


def _select_items(posture: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = [row for row in list(posture.get("operator_action_queue") or []) if isinstance(row, dict)]
    included = [_sanitize_action_item(row) for row in rows if _row_is_action_required_push(row)]
    queue_only = 0
    privacy_blocked = 0
    policy_blocked = 0
    for row in rows:
        if _row_is_action_required_push(row):
            continue
        if row.get("user_action_required") is not True or str(row.get("delivery_policy") or "").strip() == "queue_only":
            queue_only += 1
        elif not all(_bool_is_false_or_missing(row, key) for key in PRIVATE_EXPOSURE_FLAGS):
            privacy_blocked += 1
        else:
            policy_blocked += 1
    return included, {
        "input_count": len(rows),
        "included_count": len(included),
        "suppressed_queue_only_count": queue_only,
        "suppressed_privacy_blocked_count": privacy_blocked,
        "suppressed_policy_blocked_count": policy_blocked,
    }


def _digest_material(items: list[dict[str, Any]], queue_url: str) -> dict[str, Any]:
    return {
        "queue_url": queue_url,
        "items": [
            {
                "key": item.get("key"),
                "instruction": item.get("instruction"),
                "next_action": item.get("next_action"),
                "next_action_form_href": item.get("next_action_form_href"),
                "external_setup_url": item.get("external_setup_url"),
            }
            for item in items
        ],
    }


def _item_hash(item: dict[str, Any]) -> str:
    return _sha256_json(
        {
            "key": item.get("key"),
            "instruction": item.get("instruction"),
            "next_action": item.get("next_action"),
            "next_action_form_href": item.get("next_action_form_href"),
            "external_setup_url": item.get("external_setup_url"),
        }
    )


def _item_hashes_by_key(items: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(item.get("key") or "").strip(): _item_hash(item)
        for item in items
        if str(item.get("key") or "").strip()
    }


def _notification_items(
    *,
    items: list[dict[str, Any]],
    state: dict[str, Any],
    digest_sha256: str,
    force: bool,
) -> tuple[list[dict[str, Any]], str]:
    if not items:
        return [], "none"
    if force:
        return list(items), "forced_full"
    if digest_sha256 and state.get("last_digest_sha256") == digest_sha256:
        return [], "duplicate_suppressed"

    state_hashes = {
        str(key or "").strip(): str(value or "").strip()
        for key, value in dict(state.get("last_item_hashes") or {}).items()
        if str(key or "").strip() and str(value or "").strip()
    }
    if state_hashes:
        changed = [item for item in items if state_hashes.get(str(item.get("key") or "").strip()) != _item_hash(item)]
        if not changed:
            return [], "covered_by_previous_send"
        return changed, "delta"

    state_keys = [
        str(item or "").strip()
        for item in list(state.get("last_item_keys") or [])
        if str(item or "").strip()
    ]
    if state_keys:
        state_key_set = set(state_keys)
        new_items = [item for item in items if str(item.get("key") or "").strip() not in state_key_set]
        if new_items:
            return new_items, "delta_legacy_key_state"
        current_keys = [str(item.get("key") or "").strip() for item in items if str(item.get("key") or "").strip()]
        if current_keys == state_keys:
            return list(items), "changed_full_legacy_key_state"
        return list(items), "changed_full"

    return list(items), "full"


def _telegram_text(items: list[dict[str, Any]], queue_url: str) -> str:
    lines = ["Action needed for EA:"]
    for index, item in enumerate(items[:8], start=1):
        instruction = _text(
            item.get("telegram_message") or item.get("instruction") or item.get("title") or item.get("next_action"),
            limit=260,
        )
        lines.append(f"{index}. {instruction}")
        console_link = _text(item.get("console_deep_link"), limit=220)
        if console_link:
            lines.append(f"   Console: {console_link}")
        auth_template = _text(item.get("auth_link_template"), limit=260)
        if auth_template:
            lines.append(f"   Retry: {auth_template}")
        setup_url = _text(item.get("external_setup_url"), limit=260)
        if setup_url:
            lines.append(f"   Setup: {setup_url}")
    if len(items) > 8:
        lines.append(f"+ {len(items) - 8} more in the queue")
    lines.append(f"Queue: {queue_url}")
    return "\n".join(lines)


def _run_telegram_sender(principal_id: str, text: str, dry_run: bool, timeout_seconds: float) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts/ea_live_ops.py"),
        "send-telegram",
        "--text",
        text,
        "--timeout-seconds",
        str(float(timeout_seconds or 30.0)),
    ]
    if principal_id:
        command.extend(["--principal-id", principal_id])
    if dry_run:
        command.append("--dry-run")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=max(timeout_seconds, 1.0) + 5.0,
    )
    try:
        payload = json.loads(completed.stdout)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["process_exit_code"] = completed.returncode
    payload["stderr_present"] = bool(completed.stderr.strip())
    return payload


def build_operator_action_required_digest(
    *,
    root: Path = ROOT,
    input_path: Path = DEFAULT_INPUT,
    output_path: Path = DEFAULT_OUTPUT,
    state_path: Path = DEFAULT_STATE,
    principal_id: str = "",
    queue_url: str = DEFAULT_QUEUE_URL,
    send: bool = False,
    dry_run: bool = False,
    force: bool = False,
    timeout_seconds: float = 30.0,
    generated_at: str | None = None,
    telegram_sender: TelegramSender | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or _utc_now()
    posture = _load_json(input_path)
    source_sha256 = _sha256_json(posture) if posture else ""
    items, counts = _select_items(posture)
    digest_sha256 = _sha256_json(_digest_material(items, queue_url)) if items else ""
    state = _load_json(state_path)
    notification_items, notification_mode = _notification_items(
        items=items,
        state=state,
        digest_sha256=digest_sha256,
        force=bool(force),
    )
    duplicate_suppressed = bool(
        items
        and not notification_items
        and notification_mode in {"duplicate_suppressed", "covered_by_previous_send"}
    )
    text = _telegram_text(notification_items, queue_url) if notification_items else ""
    notification_digest_sha256 = (
        _sha256_json(_digest_material(notification_items, queue_url)) if notification_items else ""
    )
    current_item_hashes = _item_hashes_by_key(items)
    send_result: dict[str, Any] = {}
    send_attempted = False
    state_updated = False

    if not items:
        status = "no_user_action_required"
        notification_status = "skipped_no_items"
    elif not notification_items:
        status = "suppressed_duplicate"
        notification_status = "suppressed_duplicate"
    elif send:
        send_attempted = True
        sender = telegram_sender or _run_telegram_sender
        send_result = sender(str(principal_id or "").strip(), text, bool(dry_run), float(timeout_seconds or 30.0))
        if send_result.get("sent") is True:
            status = "sent"
            notification_status = "sent"
            state_updated = True
            _write_json(
                state_path,
                {
                    "last_digest_sha256": digest_sha256,
                    "last_sent_at": generated_at,
                    "last_item_keys": [item["key"] for item in items],
                    "last_item_hashes": current_item_hashes,
                    "last_notification_digest_sha256": notification_digest_sha256,
                    "last_notification_item_keys": [item["key"] for item in notification_items],
                    "last_notification_mode": notification_mode,
                    "message_id_count": len(list(send_result.get("message_ids") or [])),
                },
            )
        elif dry_run and send_result.get("reason") == "dry_run" and send_result.get("ready") is True:
            status = "ready_to_send"
            notification_status = "dry_run_ready"
        elif dry_run:
            status = "blocked_telegram_not_ready"
            notification_status = "blocked"
        else:
            status = "blocked_telegram_send_failed"
            notification_status = "blocked"
    else:
        status = "ready_to_send"
        notification_status = "ready_to_send"

    receipt = {
        "contract_name": "ea.operator_action_required_digest.v1",
        "generated_at": generated_at,
        "generated_by": "scripts/materialize_operator_action_required_digest.py",
        "source_git_head": _git_head(root),
        "head_semantics": "source_state",
        "source_state_fingerprint": _source_fingerprint(root),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "output_path": _display_path(output_path, root),
        "status": status,
        "notification_status": notification_status,
        "delivery_policy": "action_required_only",
        "non_action_progress_push_allowed": False,
        "quiet_hours_respected": True,
        "irreversible_actions_consent_gated": True,
        "telegram_push_allowed": bool(items),
        "send_requested": bool(send),
        "send_attempted": send_attempted,
        "dry_run": bool(dry_run),
        "dedupe_checked": True,
        "dedupe_suppressed": duplicate_suppressed,
        "state_updated": state_updated,
        "force": bool(force),
        "digest_sha256": digest_sha256,
        "notification_mode": notification_mode,
        "notification_digest_sha256": notification_digest_sha256,
        "source_receipt": {
            "path": _display_path(input_path, root),
            "present": bool(posture),
            "status": str(posture.get("status") or posture.get("overall_status") or "").strip(),
            "sha256": source_sha256,
        },
        "item_count": len(items),
        "included_action_keys": [item["key"] for item in items],
        "items": items,
        "notification_item_count": len(notification_items),
        "notification_action_keys": [item["key"] for item in notification_items],
        "notification_items": notification_items,
        "counts": counts,
        "telegram_text": text,
        "telegram_text_sha256": _sha256_text(text) if text else "",
        "telegram_text_preview": _text(text, limit=500),
        "send_result": {
            "sent": bool(send_result.get("sent")),
            "reason": str(send_result.get("reason") or "").strip(),
            "ready": bool(send_result.get("ready")),
            "readiness_status": str(send_result.get("readiness_status") or "").strip(),
            "chat_ref_present": bool(send_result.get("chat_ref_present")),
            "chat_ref_sha256": str(send_result.get("chat_ref_sha256") or "").strip(),
            "bot_key": str(send_result.get("bot_key") or "").strip(),
            "bot_handle": str(send_result.get("bot_handle") or "").strip(),
            "message_count": int(send_result.get("message_count") or len(list(send_result.get("message_ids") or []))),
            "process_exit_code": int(send_result.get("process_exit_code") or 0),
        },
        "privacy": {
            "raw_private_context_exposed": False,
            "raw_chat_ids_exposed": False,
            "raw_email_exposed": False,
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
            "raw_voice_ids_exposed": False,
            "callback_tokens_exposed": False,
            "raw_public_share_url_exposed": False,
            "raw_track_url_exposed": False,
            "raw_acceptance_text_exposed": False,
            "raw_actor_identity_exposed": False,
            "raw_object_reference_exposed": False,
            "raw_transcript_fields_exposed": False,
            "candidate_raw_text_fields_exposed": False,
            "raw_expected_google_email_exposed": False,
            "raw_client_id_exposed": False,
            "raw_client_secret_exposed": False,
            "raw_error_description_exposed": False,
            "raw_pair_url_exposed": False,
            "raw_qr_payload_exposed": False,
            "raw_whatsapp_session_ref_exposed": False,
        },
        "rules": [
            "Only operator_action_queue items that require user action may enter this digest.",
            "Telegram is an action surface, not a progress log; non-action progress remains queue-only.",
            "Purchases, bookings, cancellations, external sends, posts, payments, and commitments still require explicit approval elsewhere.",
            "Duplicate suppression stores a digest hash in local runtime state, not raw private context or chat identifiers.",
        ],
    }
    _write_json(output_path, receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize EA's action-required-only operator digest.")
    parser.add_argument("--input", dest="input_path", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", dest="output_path", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--state-path", default=str(DEFAULT_STATE))
    parser.add_argument("--principal-id", default="")
    parser.add_argument("--queue-url", default=DEFAULT_QUEUE_URL)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = build_operator_action_required_digest(
        input_path=Path(args.input_path),
        output_path=Path(args.output_path),
        state_path=Path(args.state_path),
        principal_id=str(args.principal_id or "").strip(),
        queue_url=str(args.queue_url or DEFAULT_QUEUE_URL).strip() or DEFAULT_QUEUE_URL,
        send=bool(args.send or args.dry_run),
        dry_run=bool(args.dry_run),
        force=bool(args.force),
        timeout_seconds=float(args.timeout_seconds or 30.0),
    )
    print(_json_dumps(receipt), end="")
    return 0 if str(receipt.get("status") or "").startswith(("ready", "sent", "suppressed", "no_user_action")) else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
