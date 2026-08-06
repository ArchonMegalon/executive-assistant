from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services import proactive_ooda_telegram_approval
from scripts import run_proactive_ooda


def _write_pending_callback(
    path: Path,
    *,
    packet_ref: str,
    staged_artifact_ref: str,
    delivered_at: str = "2026-07-02T15:00:05Z",
) -> None:
    payload = {
        "schema": proactive_ooda_telegram_approval.PROACTIVE_OODA_TELEGRAM_APPROVAL_CALLBACK_SCHEMA,
        "callback_token": path.stem,
        "status": "pending",
        "created_at": "2026-07-02T15:00:00Z",
        "delivered_at": delivered_at,
        "expires_at": "2099-07-09T15:00:00Z",
        "principal_id_hash": proactive_ooda_telegram_approval._hash_value("principal-1"),  # noqa: SLF001
        "chat_id_hash": proactive_ooda_telegram_approval._hash_value("telegram-chat-1"),  # noqa: SLF001
        "packet_ref": packet_ref,
        "packet_ref_sha256": proactive_ooda_telegram_approval._hash_value(packet_ref),  # noqa: SLF001
        "staged_artifact_ref": staged_artifact_ref,
        "staged_artifact_ref_sha256": proactive_ooda_telegram_approval._hash_value(staged_artifact_ref),  # noqa: SLF001
        "approved_execution_mode": "record_outcome_only",
        "approved_action": "save_gmail_draft",
        "approval_prompt_sha256": proactive_ooda_telegram_approval._hash_value("Approve this saved Gmail draft."),  # noqa: SLF001
        "staged_action_url_sha256": proactive_ooda_telegram_approval._hash_value("https://example.test/app/queue"),  # noqa: SLF001
        "prompt_message_count": 1,
        "prompt_message_ids": ["1234"],
        "privacy": {
            "raw_principal_id_stored": False,
            "raw_chat_id_stored": False,
            "raw_approval_prompt_stored": False,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_cleanup_approval_callbacks_supersedes_noncurrent_pending_for_current_user_action(tmp_path: Path) -> None:
    receipt_path = tmp_path / "artifacts" / "proactive_ooda_latest_run.generated.json"
    callback_dir = receipt_path.parent / "proactive_ooda_approval_callbacks"
    current_path = callback_dir / "current.json"
    noncurrent_path = callback_dir / "older.json"
    _write_pending_callback(
        current_path,
        packet_ref="stage_packet:current",
        staged_artifact_ref="safe_work_result:current",
        delivered_at="2026-07-02T15:01:05Z",
    )
    _write_pending_callback(
        noncurrent_path,
        packet_ref="stage_packet:older",
        staged_artifact_ref="safe_work_result:older",
        delivered_at="2026-07-02T15:00:05Z",
    )

    args = argparse.Namespace(
        dry_run=False,
        state_path="state/proactive_ooda_notified.json",
        receipt_path=str(receipt_path),
    )

    result = run_proactive_ooda._cleanup_approval_callbacks(  # noqa: SLF001
        args,
        approval_request={
            "packet_ref": "stage_packet:current",
            "staged_artifact_ref": "safe_work_result:current",
            "approval_prompt": "Approve this saved Gmail draft.",
        },
    )

    current_payload = json.loads(current_path.read_text(encoding="utf-8"))
    noncurrent_payload = json.loads(noncurrent_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["approval_request_requires_user_action"] is True
    assert result["supersede_noncurrent_requested"] is True
    assert result["supersede_active_pending_requested"] is False
    assert result["superseded_count"] == 1
    assert current_payload["status"] == "pending"
    assert noncurrent_payload["status"] == "superseded"


def test_cleanup_approval_callbacks_does_not_supersede_pending_without_current_user_action(tmp_path: Path) -> None:
    receipt_path = tmp_path / "artifacts" / "proactive_ooda_latest_run.generated.json"
    callback_dir = receipt_path.parent / "proactive_ooda_approval_callbacks"
    pending_path = callback_dir / "pending.json"
    _write_pending_callback(
        pending_path,
        packet_ref="stage_packet:older",
        staged_artifact_ref="safe_work_result:older",
    )

    args = argparse.Namespace(
        dry_run=False,
        state_path="state/proactive_ooda_notified.json",
        receipt_path=str(receipt_path),
    )

    result = run_proactive_ooda._cleanup_approval_callbacks(  # noqa: SLF001
        args,
        approval_request=None,
    )

    payload = json.loads(pending_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["approval_request_requires_user_action"] is False
    assert result["supersede_noncurrent_requested"] is False
    assert result["supersede_active_pending_requested"] is False
    assert result["superseded_count"] == 0
    assert payload["status"] == "pending"


def test_cleanup_approval_callbacks_supersedes_current_pending_for_internal_action_packet(tmp_path: Path) -> None:
    receipt_path = tmp_path / "artifacts" / "proactive_ooda_latest_run.generated.json"
    callback_dir = receipt_path.parent / "proactive_ooda_approval_callbacks"
    current_path = callback_dir / "current.json"
    older_path = callback_dir / "older-assistant-grade.json"
    _write_pending_callback(
        current_path,
        packet_ref="stage_packet:current",
        staged_artifact_ref="safe_work_result:current",
        delivered_at="2026-07-02T15:01:05Z",
    )
    _write_pending_callback(
        older_path,
        packet_ref="stage_packet:older-assistant-grade",
        staged_artifact_ref="safe_work_result:older-assistant-grade",
        delivered_at="2026-07-02T15:00:05Z",
    )

    args = argparse.Namespace(
        dry_run=False,
        state_path="state/proactive_ooda_notified.json",
        receipt_path=str(receipt_path),
    )

    result = run_proactive_ooda._cleanup_approval_callbacks(  # noqa: SLF001
        args,
        approval_request={
            "packet_ref": "stage_packet:current",
            "staged_artifact_ref": "safe_work_result:current",
            "approval_prompt": "Open Google setup and add the work account as a test user.",
            "staged_action_url": "https://myexternalbrain.com/integrations/google",
            "work_type": "record_internal_action",
        },
    )

    payload = json.loads(current_path.read_text(encoding="utf-8"))
    older_payload = json.loads(older_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["approval_request_requires_user_action"] is False
    assert result["supersede_noncurrent_requested"] is False
    assert result["supersede_active_pending_requested"] is True
    assert result["superseded_count"] == 1
    assert payload["status"] == "superseded"
    assert payload["superseded_reason"] == "current_packet_no_longer_requires_user_action"
    assert older_payload["status"] == "pending"
