from __future__ import annotations

import json

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
                "telegram_message_ids": ["3004"],
            }
        ),
        encoding="utf-8",
    )

    report = verify_receipt(receipt)

    assert report["ok"] is True
    assert report["delivery_message_count"] == 1
    assert report["telegram_message_count"] == 1


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
