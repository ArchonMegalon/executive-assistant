from __future__ import annotations

import importlib
import json

import scripts.verify_proactive_ooda_live_receipt as live_receipt_module
from scripts.verify_proactive_ooda_live_receipt import verify_receipt


def test_verify_proactive_ooda_live_receipt_accepts_redacted_sent_receipt(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-06-20T14:58:30+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "delivery_route_error": "whatsapp_web_session_not_ready:qr_required",
                "delivery_recovery_hint": "Scan the WhatsApp Web QR code and re-activate the session before preferring WhatsApp again.",
                "delivery_next_action": "scan_whatsapp_web_qr",
                "telegram_message_ids": ["3004"],
            }
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is True
    assert report["delivery_message_count"] == 1
    assert report["telegram_message_count"] == 1
    assert report["delivery_next_action"] == "scan_whatsapp_web_qr"


def test_verify_proactive_ooda_live_receipt_accepts_operator_safe_mirror_receipt(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "dry_run": False,
                "error_code": "mirrored_delivery_proof",
                "generated_at": "2026-07-01T00:34:10+00:00",
                "item_count": 1,
                "notification_status": "deferred",
                "delivery_message_ids": [],
                "telegram_message_ids": [],
                "principal_id_hash": "b" * 64,
                "stage_packet_ref_hashes": ["c" * 64],
                "safe_work_result_ref_hashes": ["d" * 64],
                "delivery_mirror": {
                    "enabled": True,
                    "mode": "operator_safe_mirror",
                    "user_notification_suppressed": True,
                    "approval_request_requires_user_action": True,
                    "packet_ref_hash": "e" * 64,
                    "staged_artifact_ref_hash": "f" * 64,
                    "notification_text_sha256": "1" * 64,
                    "raw_notification_text_exposed": False,
                    "raw_approval_prompt_exposed": False,
                    "raw_private_url_exposed": False,
                },
            }
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is True
    assert report["delivery_mode"] == "operator_safe_mirror"
    assert report["operator_safe_mirror_present"] is True
    assert report["delivery_message_count"] == 0
    assert report["telegram_message_count"] == 0


def test_verify_proactive_ooda_live_receipt_uses_archived_sent_receipt_when_latest_is_quiet(tmp_path) -> None:
    receipt = tmp_path / "proactive_ooda_latest_run.generated.json"
    archive_receipt = tmp_path / "proactive_ooda_run_receipts" / "20260629T103000Z-sent.json"
    receipt.write_text(
        json.dumps(
            {
                "dry_run": False,
                "error_code": "no_user_action_required",
                "generated_at": "2026-06-29T10:40:00+00:00",
                "item_count": 4,
                "notification_status": "deferred",
                "telegram_message_ids": [],
                "delivery_message_ids": [],
            }
        ),
        encoding="utf-8",
    )
    archive_receipt.parent.mkdir(parents=True, exist_ok=True)
    archive_receipt.write_text(
        json.dumps(
            {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-06-29T10:30:00+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "telegram_message_ids": ["3201"],
            }
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is True
    assert report["archived_sent_receipt_used"] is True
    assert report["receipt_path"] == str(archive_receipt)
    assert report["latest_receipt_path"] == str(receipt)
    assert report["latest_notification_status"] == "deferred"
    assert report["quiet_receipt_error_code"] == "no_user_action_required"


def test_verify_proactive_ooda_live_receipt_uses_archived_operator_safe_mirror_when_latest_has_no_items(
    tmp_path,
) -> None:
    receipt = tmp_path / "proactive_ooda_latest_run.generated.json"
    archive_receipt = tmp_path / "proactive_ooda_run_receipts" / "20260701T003410Z-deferred-mirror.json"
    receipt.write_text(
        json.dumps(
            {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-07-01T00:40:22+00:00",
                "item_count": 0,
                "notification_status": "skipped_no_items",
                "telegram_message_ids": [],
                "delivery_message_ids": [],
            }
        ),
        encoding="utf-8",
    )
    archive_receipt.parent.mkdir(parents=True, exist_ok=True)
    archive_receipt.write_text(
        json.dumps(
            {
                "dry_run": False,
                "error_code": "mirrored_delivery_proof",
                "generated_at": "2026-07-01T00:34:10+00:00",
                "item_count": 1,
                "notification_status": "deferred",
                "delivery_message_ids": [],
                "telegram_message_ids": [],
                "principal_id_hash": "b" * 64,
                "stage_packet_ref_hashes": ["c" * 64],
                "safe_work_result_ref_hashes": ["d" * 64],
                "delivery_mirror": {
                    "enabled": True,
                    "mode": "operator_safe_mirror",
                    "user_notification_suppressed": True,
                    "approval_request_requires_user_action": True,
                    "packet_ref_hash": "e" * 64,
                    "staged_artifact_ref_hash": "f" * 64,
                    "notification_text_sha256": "1" * 64,
                    "raw_notification_text_exposed": False,
                    "raw_approval_prompt_exposed": False,
                    "raw_private_url_exposed": False,
                },
            }
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is True
    assert report["archived_delivery_receipt_used"] is True
    assert report["archived_operator_safe_mirror_receipt_used"] is True
    assert report["archived_sent_receipt_used"] is False
    assert report["receipt_path"] == str(archive_receipt)
    assert report["latest_receipt_path"] == str(receipt)
    assert report["latest_notification_status"] == "skipped_no_items"
    assert report["quiet_receipt_error_code"] == "skipped_no_items"
    assert report["delivery_mode"] == "operator_safe_mirror"


def test_verify_proactive_ooda_live_receipt_rejects_raw_fields_in_quiet_latest_receipt(tmp_path) -> None:
    receipt = tmp_path / "proactive_ooda_latest_run.generated.json"
    archive_receipt = tmp_path / "proactive_ooda_run_receipts" / "20260629T103000Z-sent.json"
    receipt.write_text(
        json.dumps(
            {
                "dry_run": False,
                "error_code": "no_user_action_required",
                "generated_at": "2026-06-29T10:40:00+00:00",
                "item_count": 4,
                "notification_status": "deferred",
                "telegram_message_ids": [],
                "delivery_message_ids": [],
                "chat_id": "raw-chat-id",
            }
        ),
        encoding="utf-8",
    )
    archive_receipt.parent.mkdir(parents=True, exist_ok=True)
    archive_receipt.write_text(
        json.dumps(
            {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-06-29T10:30:00+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "telegram_message_ids": ["3201"],
            }
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is False
    assert report["archived_sent_receipt_used"] is True
    assert "quiet_receipt_contains_raw_chat_id" in report["errors"]


def test_verify_proactive_ooda_live_receipt_rejects_raw_fields(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-06-20T14:58:30+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "telegram_message_ids": ["3004"],
                "chat_id": "12345",
            }
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is False
    assert "receipt_contains_raw_chat_id" in report["errors"]


def test_verify_proactive_ooda_live_receipt_rejects_raw_approval_surface_fields(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-06-20T14:58:30+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "telegram_message_ids": ["3004"],
                "approval_surface": {"callback_token": "secret-token"},
            }
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is False
    assert "receipt_contains_raw_approval_surface_callback_token" in report["errors"]


def test_verify_proactive_ooda_live_receipt_rejects_missing_message_ids(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "dry_run": False,
                "error_code": "",
                "generated_at": "2026-06-20T14:58:30+00:00",
                "item_count": 1,
                "notification_status": "sent",
                "notified_ref_hashes": ["a" * 64],
                "principal_id_hash": "b" * 64,
                "telegram_message_ids": [],
            }
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is False
    assert "receipt_missing_delivery_message_id" in report["errors"]
    assert "receipt_missing_telegram_message_id" in report["errors"]


def test_verify_proactive_ooda_live_receipt_default_prefers_runtime_receipt_env(monkeypatch) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_RECEIPT_PATH", "/data/provider-ledger/proactive_ooda_latest_run.generated.json")
    monkeypatch.delenv("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_STATE_PATH", raising=False)

    module = importlib.reload(live_receipt_module)

    assert str(module.default_receipt_path()) == "/data/provider-ledger/proactive_ooda_latest_run.generated.json"


def test_verify_proactive_ooda_live_receipt_default_falls_back_to_state_sibling(monkeypatch) -> None:
    monkeypatch.delenv("EA_PROACTIVE_OODA_RECEIPT_PATH", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH", raising=False)
    monkeypatch.setenv("EA_PROACTIVE_OODA_STATE_PATH", "/data/provider-ledger/proactive_ooda_notified.json")

    module = importlib.reload(live_receipt_module)

    assert str(module.default_receipt_path()) == "/data/provider-ledger/proactive_ooda_latest_run.generated.json"


def test_verify_proactive_ooda_live_receipt_default_prefers_repo_state_when_env_is_unset(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("EA_PROACTIVE_OODA_RECEIPT_PATH", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH", raising=False)
    monkeypatch.delenv("EA_PROACTIVE_OODA_STATE_PATH", raising=False)

    module = importlib.reload(live_receipt_module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "proactive_ooda_notified.json").write_text("{}", encoding="utf-8")

    assert module.default_receipt_path() == tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
