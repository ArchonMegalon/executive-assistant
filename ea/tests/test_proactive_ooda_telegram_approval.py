from __future__ import annotations

import json
from pathlib import Path

from app.services import proactive_ooda_telegram_approval


def test_prepare_reuses_existing_live_pending_callback(tmp_path: Path) -> None:
    first = proactive_ooda_telegram_approval.prepare_proactive_ooda_telegram_approval(
        principal_id="principal-1",
        packet_ref="stage_packet:packet-1",
        staged_artifact_ref="safe_work_result:result-1",
        approval_prompt="Approve this saved Gmail draft.",
        chat_id="telegram-chat-1",
        bot_token="telegram-bot-token",
        staged_action_url="https://example.test/app/queue",
        approved_execution_mode="record_outcome_only",
        approved_action="save_gmail_draft",
        callback_dir=tmp_path,
        created_at="2026-07-02T15:00:00Z",
    )

    second = proactive_ooda_telegram_approval.prepare_proactive_ooda_telegram_approval(
        principal_id="principal-1",
        packet_ref="stage_packet:packet-1",
        staged_artifact_ref="safe_work_result:result-1",
        approval_prompt="Approve this saved Gmail draft.",
        chat_id="telegram-chat-1",
        bot_token="telegram-bot-token",
        staged_action_url="https://example.test/app/queue",
        approved_execution_mode="record_outcome_only",
        approved_action="save_gmail_draft",
        callback_dir=tmp_path,
        created_at="2026-07-02T15:05:00Z",
    )

    assert first["callback_token"]
    assert second["callback_token"] == first["callback_token"]
    assert second["reused_existing"] is True
    assert second["superseded_duplicate_count"] == 0
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_prepare_collapses_duplicate_live_pending_callbacks_to_one_record(tmp_path: Path) -> None:
    approval_prompt = "Approve this saved Gmail draft."
    staged_action_url = "https://example.test/app/queue"
    principal_id = "principal-1"
    chat_id = "telegram-chat-1"
    packet_ref = "stage_packet:packet-1"
    staged_artifact_ref = "safe_work_result:result-1"
    prompt_sha = proactive_ooda_telegram_approval._hash_value(approval_prompt)  # noqa: SLF001
    action_url_sha = proactive_ooda_telegram_approval._hash_value(staged_action_url)  # noqa: SLF001
    principal_hash = proactive_ooda_telegram_approval._hash_value(principal_id)  # noqa: SLF001
    chat_hash = proactive_ooda_telegram_approval._hash_value(chat_id)  # noqa: SLF001

    older_record = {
        "schema": proactive_ooda_telegram_approval.PROACTIVE_OODA_TELEGRAM_APPROVAL_CALLBACK_SCHEMA,
        "callback_token": "oldercallback01",
        "status": "pending",
        "created_at": "2026-07-02T15:00:00Z",
        "delivered_at": "2026-07-02T15:00:05Z",
        "expires_at": "2099-07-09T15:00:00Z",
        "principal_id_hash": principal_hash,
        "chat_id_hash": chat_hash,
        "packet_ref": packet_ref,
        "packet_ref_sha256": proactive_ooda_telegram_approval._hash_value(packet_ref),  # noqa: SLF001
        "staged_artifact_ref": staged_artifact_ref,
        "staged_artifact_ref_sha256": proactive_ooda_telegram_approval._hash_value(staged_artifact_ref),  # noqa: SLF001
        "approved_execution_mode": "record_outcome_only",
        "approved_action": "save_gmail_draft",
        "approval_prompt_sha256": prompt_sha,
        "staged_action_url_sha256": action_url_sha,
        "prompt_message_count": 1,
        "prompt_message_ids": ["1234"],
        "privacy": {
            "raw_principal_id_stored": False,
            "raw_chat_id_stored": False,
            "raw_approval_prompt_stored": False,
        },
    }
    newer_duplicate = {
        **older_record,
        "callback_token": "newercallback02",
        "created_at": "2026-07-02T15:04:00Z",
        "delivered_at": "",
        "prompt_message_count": 0,
        "prompt_message_ids": [],
    }
    (tmp_path / "older.json").write_text(json.dumps(older_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (tmp_path / "newer.json").write_text(json.dumps(newer_duplicate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    prepared = proactive_ooda_telegram_approval.prepare_proactive_ooda_telegram_approval(
        principal_id=principal_id,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
        approval_prompt=approval_prompt,
        chat_id=chat_id,
        bot_token="telegram-bot-token",
        staged_action_url=staged_action_url,
        approved_execution_mode="record_outcome_only",
        approved_action="save_gmail_draft",
        callback_dir=tmp_path,
        created_at="2026-07-02T15:05:00Z",
    )

    assert prepared["callback_token"] == "oldercallback01"
    assert prepared["reused_existing"] is True
    assert prepared["superseded_duplicate_count"] == 1

    older_payload = json.loads((tmp_path / "older.json").read_text(encoding="utf-8"))
    newer_payload = json.loads((tmp_path / "newer.json").read_text(encoding="utf-8"))
    assert older_payload["status"] == "pending"
    assert newer_payload["status"] == "superseded"
    assert newer_payload["superseded_reason"] == "duplicate_live_callback_replaced"


def test_cleanup_supersedes_duplicate_current_packet_live_pending_callbacks(tmp_path: Path) -> None:
    approval_prompt = "Approve this saved Gmail draft."
    staged_action_url = "https://example.test/app/queue"
    principal_id = "principal-1"
    chat_id = "telegram-chat-1"
    packet_ref = "stage_packet:packet-1"
    staged_artifact_ref = "safe_work_result:result-1"
    prompt_sha = proactive_ooda_telegram_approval._hash_value(approval_prompt)  # noqa: SLF001
    action_url_sha = proactive_ooda_telegram_approval._hash_value(staged_action_url)  # noqa: SLF001
    principal_hash = proactive_ooda_telegram_approval._hash_value(principal_id)  # noqa: SLF001
    chat_hash = proactive_ooda_telegram_approval._hash_value(chat_id)  # noqa: SLF001

    first = {
        "schema": proactive_ooda_telegram_approval.PROACTIVE_OODA_TELEGRAM_APPROVAL_CALLBACK_SCHEMA,
        "callback_token": "firstcallback01",
        "status": "pending",
        "created_at": "2026-07-02T15:00:00Z",
        "delivered_at": "2026-07-02T15:00:05Z",
        "expires_at": "2099-07-09T15:00:00Z",
        "principal_id_hash": principal_hash,
        "chat_id_hash": chat_hash,
        "packet_ref": packet_ref,
        "packet_ref_sha256": proactive_ooda_telegram_approval._hash_value(packet_ref),  # noqa: SLF001
        "staged_artifact_ref": staged_artifact_ref,
        "staged_artifact_ref_sha256": proactive_ooda_telegram_approval._hash_value(staged_artifact_ref),  # noqa: SLF001
        "approved_execution_mode": "record_outcome_only",
        "approved_action": "save_gmail_draft",
        "approval_prompt_sha256": prompt_sha,
        "staged_action_url_sha256": action_url_sha,
        "prompt_message_count": 1,
        "prompt_message_ids": ["1234"],
        "privacy": {
            "raw_principal_id_stored": False,
            "raw_chat_id_stored": False,
            "raw_approval_prompt_stored": False,
        },
    }
    second = {
        **first,
        "callback_token": "secondcallback2",
        "created_at": "2026-07-02T15:01:00Z",
        "delivered_at": "2026-07-02T15:01:05Z",
        "prompt_message_ids": ["1235"],
    }
    (tmp_path / "first.json").write_text(json.dumps(first, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (tmp_path / "second.json").write_text(json.dumps(second, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = proactive_ooda_telegram_approval.expire_stale_proactive_ooda_telegram_approval_callbacks(
        callback_dir=tmp_path,
        active_packet_ref=packet_ref,
        active_staged_artifact_ref=staged_artifact_ref,
    )

    assert result["status"] == "ok"
    assert result["superseded_count"] == 1

    first_payload = json.loads((tmp_path / "first.json").read_text(encoding="utf-8"))
    second_payload = json.loads((tmp_path / "second.json").read_text(encoding="utf-8"))
    assert first_payload["status"] == "superseded"
    assert first_payload["superseded_reason"] == "duplicate_live_callback_replaced"
    assert second_payload["status"] == "pending"


def test_cleanup_can_supersede_current_pending_when_packet_no_longer_requires_user_action(tmp_path: Path) -> None:
    approval_prompt = "Open Google setup and add the work account as a test user."
    principal_id = "principal-1"
    chat_id = "telegram-chat-1"
    packet_ref = "stage_packet:packet-1"
    staged_artifact_ref = "safe_work_result:result-1"
    prompt_sha = proactive_ooda_telegram_approval._hash_value(approval_prompt)  # noqa: SLF001
    principal_hash = proactive_ooda_telegram_approval._hash_value(principal_id)  # noqa: SLF001
    chat_hash = proactive_ooda_telegram_approval._hash_value(chat_id)  # noqa: SLF001

    current = {
        "schema": proactive_ooda_telegram_approval.PROACTIVE_OODA_TELEGRAM_APPROVAL_CALLBACK_SCHEMA,
        "callback_token": "currentcallback",
        "status": "pending",
        "created_at": "2026-07-02T15:00:00Z",
        "delivered_at": "2026-07-02T15:00:05Z",
        "expires_at": "2099-07-09T15:00:00Z",
        "principal_id_hash": principal_hash,
        "chat_id_hash": chat_hash,
        "packet_ref": packet_ref,
        "packet_ref_sha256": proactive_ooda_telegram_approval._hash_value(packet_ref),  # noqa: SLF001
        "staged_artifact_ref": staged_artifact_ref,
        "staged_artifact_ref_sha256": proactive_ooda_telegram_approval._hash_value(staged_artifact_ref),  # noqa: SLF001
        "approved_execution_mode": "",
        "approved_action": "",
        "approval_prompt_sha256": prompt_sha,
        "staged_action_url_sha256": proactive_ooda_telegram_approval._hash_value("https://myexternalbrain.com/integrations/google"),  # noqa: SLF001
        "prompt_message_count": 1,
        "prompt_message_ids": ["1234"],
        "privacy": {
            "raw_principal_id_stored": False,
            "raw_chat_id_stored": False,
            "raw_approval_prompt_stored": False,
        },
    }
    (tmp_path / "current.json").write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = proactive_ooda_telegram_approval.expire_stale_proactive_ooda_telegram_approval_callbacks(
        callback_dir=tmp_path,
        supersede_noncurrent=True,
        supersede_active_pending=True,
        active_packet_ref=packet_ref,
        active_staged_artifact_ref=staged_artifact_ref,
    )

    payload = json.loads((tmp_path / "current.json").read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["superseded_count"] == 1
    assert payload["status"] == "superseded"
    assert payload["superseded_reason"] == "current_packet_no_longer_requires_user_action"
