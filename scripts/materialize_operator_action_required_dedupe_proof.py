#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts import materialize_operator_action_required_digest as digest
except ModuleNotFoundError:  # pragma: no cover - script execution path
    import materialize_operator_action_required_digest as digest  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = digest.DEFAULT_INPUT
DEFAULT_STATE = digest.DEFAULT_STATE
DEFAULT_SENT_RECEIPT = digest.DEFAULT_OUTPUT
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/ea_operator_action_required_dedupe_proof.generated.json"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def _current_digest(posture_path: Path, queue_url: str) -> tuple[list[dict[str, Any]], dict[str, int], str, str]:
    posture = digest._load_json(posture_path)
    items, counts = digest._select_items(posture)
    digest_sha256 = digest._sha256_json(digest._digest_material(items, queue_url)) if items else ""
    source_sha256 = digest._sha256_json(posture) if posture else ""
    return items, counts, digest_sha256, source_sha256


def build_operator_action_required_dedupe_proof(
    *,
    root: Path = ROOT,
    input_path: Path = DEFAULT_INPUT,
    state_path: Path = DEFAULT_STATE,
    sent_receipt_path: Path = DEFAULT_SENT_RECEIPT,
    output_path: Path = DEFAULT_OUTPUT,
    queue_url: str = digest.DEFAULT_QUEUE_URL,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or _utc_now()
    items, counts, current_digest_sha256, source_sha256 = _current_digest(input_path, queue_url)
    state = digest._load_json(state_path)
    sent_receipt = digest._load_json(sent_receipt_path)

    included_keys = [str(item.get("key") or "").strip() for item in items if str(item.get("key") or "").strip()]
    state_item_keys = [str(item or "").strip() for item in list(state.get("last_item_keys") or []) if str(item or "").strip()]
    state_present = bool(state)
    state_digest = str(state.get("last_digest_sha256") or "").strip()
    last_sent_at_present = bool(str(state.get("last_sent_at") or "").strip())
    message_id_count = int(state.get("message_id_count") or 0)
    state_matches_current_digest = bool(current_digest_sha256 and state_digest == current_digest_sha256)
    state_item_keys_match = state_item_keys == included_keys
    notification_items, notification_mode = digest._notification_items(
        items=items,
        state=state,
        digest_sha256=current_digest_sha256,
        force=False,
    )
    current_actions_covered_by_prior_state = bool(
        items
        and not notification_items
        and notification_mode in {"duplicate_suppressed", "covered_by_previous_send"}
        and state_present
        and last_sent_at_present
        and message_id_count > 0
    )
    sent_receipt_digest_match = (
        str(sent_receipt.get("digest_sha256") or "").strip() == current_digest_sha256
        and (
            (
                str(sent_receipt.get("status") or "").strip() == "sent"
                and str(sent_receipt.get("notification_status") or "").strip() == "sent"
            )
            or (
                str(sent_receipt.get("status") or "").strip() == "suppressed_duplicate"
                and str(sent_receipt.get("notification_status") or "").strip() == "suppressed_duplicate"
            )
        )
    )
    suppressed_duplicate_expected = current_actions_covered_by_prior_state
    status = "pass" if suppressed_duplicate_expected and sent_receipt_digest_match else "blocked"

    receipt = {
        "contract_name": "ea.operator_action_required_dedupe_proof.v1",
        "generated_at": generated_at,
        "generated_by": "scripts/materialize_operator_action_required_dedupe_proof.py",
        "source_git_head": digest._git_head(root),
        "head_semantics": "source_state",
        "source_state_fingerprint": digest._source_fingerprint(root),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "output_path": _display_path(output_path, root),
        "status": status,
        "delivery_policy": "action_required_only",
        "dedupe_checked": True,
        "send_attempted": False,
        "send_requested": False,
        "would_send_without_force": False if suppressed_duplicate_expected else True,
        "suppressed_duplicate_expected": suppressed_duplicate_expected,
        "force_required_to_resend": suppressed_duplicate_expected,
        "notification_mode_without_force": notification_mode,
        "notification_item_count_without_force": len(notification_items),
        "current_actions_covered_by_prior_state": current_actions_covered_by_prior_state,
        "current_digest_sha256": current_digest_sha256,
        "item_count": len(items),
        "included_action_keys": included_keys,
        "counts": counts,
        "state": {
            "path": _display_path(state_path, root),
            "present": state_present,
            "last_digest_match": state_matches_current_digest,
            "last_item_keys_match": state_item_keys_match,
            "last_sent_at_present": last_sent_at_present,
            "message_id_count": message_id_count,
            "raw_chat_ref_stored": False,
            "raw_message_ids_stored": False,
            "raw_token_stored": False,
            "raw_secret_stored": False,
        },
        "source_receipts": {
            "posture": {
                "path": _display_path(input_path, root),
                "present": bool(source_sha256),
                "sha256": source_sha256,
            },
            "sent_digest": {
                "path": _display_path(sent_receipt_path, root),
                "present": bool(sent_receipt),
                "status": str(sent_receipt.get("status") or "").strip(),
                "notification_status": str(sent_receipt.get("notification_status") or "").strip(),
                "digest_match": sent_receipt_digest_match,
                "message_count": int(dict(sent_receipt.get("send_result") or {}).get("message_count") or 0),
                "notification_item_count": int(sent_receipt.get("notification_item_count") or 0),
            },
        },
        "privacy": {
            "raw_private_context_exposed": False,
            "raw_chat_ids_exposed": False,
            "raw_message_ids_exposed": False,
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
            "raw_voice_ids_exposed": False,
            "raw_pair_url_exposed": False,
            "raw_qr_payload_exposed": False,
            "raw_whatsapp_session_ref_exposed": False,
            "callback_tokens_exposed": False,
            "raw_acceptance_text_exposed": False,
            "raw_actor_identity_exposed": False,
            "raw_object_reference_exposed": False,
            "raw_transcript_fields_exposed": False,
            "candidate_raw_text_fields_exposed": False,
        },
        "rules": [
            "This receipt proves duplicate suppression from local digest state without attempting a Telegram send.",
            "A matching digest may be resent only with an explicit force path or after the action set changes.",
            "The proof may expose action keys and hashes, but not raw chat references, message IDs, tokens, or private context.",
        ],
    }
    _write_json(output_path, receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize EA operator action digest duplicate-suppression proof.")
    parser.add_argument("--input", dest="input_path", default=str(DEFAULT_INPUT))
    parser.add_argument("--state-path", default=str(DEFAULT_STATE))
    parser.add_argument("--sent-receipt", default=str(DEFAULT_SENT_RECEIPT))
    parser.add_argument("--output", dest="output_path", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--queue-url", default=digest.DEFAULT_QUEUE_URL)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = build_operator_action_required_dedupe_proof(
        input_path=Path(args.input_path),
        state_path=Path(args.state_path),
        sent_receipt_path=Path(args.sent_receipt),
        output_path=Path(args.output_path),
        queue_url=str(args.queue_url or digest.DEFAULT_QUEUE_URL).strip() or digest.DEFAULT_QUEUE_URL,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if str(receipt.get("status") or "") == "pass" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
