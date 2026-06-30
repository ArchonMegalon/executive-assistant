from __future__ import annotations

import hashlib

from app.services import telegram_business_signal_ingest
from app.services.proactive_signal_discovery import observation_row_to_signal


def _hash(value: str, *, salt: str = "") -> str:
    material = f"{salt}:{value}" if salt else value
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def test_allowlisted_business_message_becomes_read_only_signal_candidate() -> None:
    update = {
        "update_id": 101,
        "business_message": {
            "business_connection_id": "biz-1",
            "message_id": 77,
            "chat": {"id": 1200, "type": "private"},
            "from": {"id": 42, "first_name": "Ada"},
            "text": "Bitte suche einen Elektriker und speichere nur einen Draft.",
            "document": {"file_id": "raw-file-id", "file_unique_id": "unique-doc", "mime_type": "application/pdf"},
        },
    }

    result = telegram_business_signal_ingest.normalize_telegram_business_update(
        update,
        allowed_chat_ids={"1200"},
        hash_salt="test-salt",
    )

    assert result.status == "signal_candidate"
    assert result.event_type == "telegram_business.signal_candidate"
    assert result.source_id == f"telegram_business:{_hash('1200', salt='test-salt')}"
    assert result.candidate["source"] == "telegram_business"
    assert result.candidate["chat_scope"] == "allowlisted"
    assert result.candidate["chat_id_hash"] == _hash("1200", salt="test-salt")
    assert result.candidate["sender_label"] == "known_contact_or_redacted"
    assert result.candidate["sender_ref_hash"] == _hash("42", salt="test-salt")
    assert result.candidate["text_preview"] == "Bitte suche einen Elektriker und speichere nur einen Draft."
    assert result.candidate["signal_type"] == "candidate"
    assert result.candidate["human_review_required"] is True
    assert result.candidate["memory_candidate_allowed"] is False
    assert result.candidate["reply_allowed"] is False
    assert result.candidate["raw_payload_exposed"] is False
    assert result.candidate["raw_chat_id_exposed"] is False
    assert result.candidate["raw_sender_id_exposed"] is False
    assert result.candidate["attachment_refs"][0]["file_ref_hashes"] == [_hash("unique-doc", salt="test-salt")]
    assert "raw-file-id" not in str(result.candidate)
    assert "1200" not in result.source_id


def test_blocked_business_message_does_not_store_message_text_or_sender() -> None:
    result = telegram_business_signal_ingest.normalize_telegram_business_update(
        {
            "update_id": 102,
            "business_message": {
                "message_id": 78,
                "chat": {"id": 999, "type": "private"},
                "from": {"id": 44, "first_name": "Private"},
                "text": "This private chat text must not become a candidate.",
            },
        },
        allowed_chat_ids={"1200"},
        hash_salt="test-salt",
    )

    assert result.status == "ignored_not_allowlisted"
    assert result.event_type == "telegram_business.update_blocked"
    assert result.candidate["signal_type"] == "ignored"
    assert result.candidate["human_review_required"] is False
    assert result.candidate["text_preview"] == ""
    assert result.candidate["sender_label"] == "redacted"
    assert "This private chat text" not in str(result.candidate)
    assert "Private" not in str(result.candidate)
    assert "999" not in result.source_id


def test_allowed_private_chat_label_becomes_signal_candidate() -> None:
    update = {
        "update_id": 104,
        "business_message": {
            "message_id": 79,
            "chat": {"id": 1201, "type": "private", "first_name": "Helmut", "last_name": "Jilka"},
            "from": {"id": 43, "first_name": "Helmut", "last_name": "Jilka"},
            "text": "Bitte morgen nachfassen.",
        },
    }

    result = telegram_business_signal_ingest.normalize_telegram_business_update(
        update,
        allowed_chat_labels={"helmut jilka"},
        hash_salt="test-salt",
    )

    assert result.status == "signal_candidate"
    assert result.candidate["chat_scope"] == "allowlisted"
    assert result.candidate["text_preview"] == "Bitte morgen nachfassen."
    assert result.candidate["chat_id_hash"] == _hash("1201", salt="test-salt")
    assert "1201" not in result.source_id


def test_allowed_group_title_becomes_signal_candidate_case_insensitive() -> None:
    update = {
        "update_id": 105,
        "business_message": {
            "message_id": 80,
            "chat": {"id": -1202, "type": "group", "title": "Developer Circle"},
            "from": {"id": 45, "first_name": "Ada"},
            "text": "Deploy ist fertig.",
        },
    }

    result = telegram_business_signal_ingest.normalize_telegram_business_update(
        update,
        allowed_chat_labels={"developer circle"},
        hash_salt="test-salt",
    )

    assert result.status == "signal_candidate"
    assert result.candidate["chat_scope"] == "allowlisted"
    assert result.candidate["text_preview"] == "Deploy ist fertig."
    assert result.candidate["chat_id_hash"] == _hash("-1202", salt="test-salt")
    assert "-1202" not in result.source_id


def test_deleted_business_messages_are_allowlisted_without_text_preview() -> None:
    result = telegram_business_signal_ingest.normalize_telegram_business_update(
        {
            "update_id": 103,
            "deleted_business_messages": {
                "business_connection_id": "biz-1",
                "chat": {"id": 1200},
                "message_ids": [1, 2, 3],
            },
        },
        allowed_chat_hashes={_hash("1200")},
    )

    assert result.status == "signal_candidate"
    assert result.update_type == "deleted_business_messages"
    assert result.candidate["text_preview"] == ""
    assert result.candidate["message_id"] == "1,2,3"
    assert result.candidate["reply_allowed"] is False


def test_allowed_updates_are_exact_telegram_business_secretary_surface() -> None:
    assert telegram_business_signal_ingest.allowed_updates() == [
        "business_connection",
        "business_message",
        "edited_business_message",
        "deleted_business_messages",
    ]


def test_proactive_discovery_sees_only_reviewable_business_candidates() -> None:
    signal = observation_row_to_signal(
        observation_id="obs-1",
        principal_id="principal",
        channel="telegram_business",
        event_type="telegram_business.signal_candidate",
        payload={
            "signal_type": "candidate",
            "human_review_required": True,
            "text_preview": "Suche einen Rauchfangkehrer in 1200 Wien.",
            "message_id": "77",
        },
        created_at="2026-06-30T08:00:00+00:00",
        source_id="telegram_business:hash",
        external_id="77",
        dedupe_key="telegram_business:business_message:101:hash:77",
    )

    assert signal is not None
    assert signal.signal_type == "telegram_business_signal_candidate"
    assert signal.counterparty == "Telegram Business"
    assert signal.title == "Suche einen Rauchfangkehrer in 1200 Wien."

    ignored = observation_row_to_signal(
        observation_id="obs-2",
        principal_id="principal",
        channel="telegram_business",
        event_type="telegram_business.signal_candidate",
        payload={"signal_type": "ignored", "human_review_required": False},
        created_at="2026-06-30T08:00:00+00:00",
    )
    assert ignored is None
