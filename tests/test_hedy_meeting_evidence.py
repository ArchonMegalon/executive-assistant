from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from app.services.hedy_meeting_evidence import (
    HedyMeetingEvidenceService,
    build_hedy_meeting_review_packet,
    hedy_webhook_signature,
    verify_hedy_webhook_signature,
)


NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)
SECRET = "test-hedy-webhook-secret"


def _body(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _signed_headers(body: bytes, *, timestamp: str = "1781784000") -> dict[str, str]:
    return {
        "x-hedy-timestamp": timestamp,
        "x-hedy-signature": hedy_webhook_signature(body, SECRET, timestamp=timestamp),
    }


def _sample_payload() -> dict[str, object]:
    return {
        "event_id": "evt-hedy-001",
        "type": "session.completed",
        "session": {
            "id": "sess-board-001",
            "title": "Board prep",
            "recording_consent_confirmed": True,
            "region": "eu",
            "transcript": "Tibor: Please send Marta the revised board pack.\nMarta: Decide if the budget is ready.",
            "summary": "Board prep produced one follow-up and one approval question.",
            "action_items": [
                {
                    "title": "Send Marta the revised board pack",
                    "assignee": "Tibor",
                    "due_at": "2026-06-20T09:00:00+00:00",
                    "confidence": 0.91,
                }
            ],
            "decisions": [
                {
                    "question": "Approve the revised budget for the board pack?",
                    "options": ["Approve", "Request changes", "Defer"],
                    "priority": "high",
                    "confidence": 0.87,
                }
            ],
            "participants": [{"name": "Marta Weiss", "role": "CFO"}],
            "follow_ups": [
                {
                    "recipient": "Marta Weiss",
                    "intent": "board pack follow-up",
                    "draft_text": "Marta, I will send the revised board pack by Friday morning.",
                }
            ],
        },
    }


def test_missing_recording_consent_blocks_packet_without_storing_transcript() -> None:
    payload = _sample_payload()
    session = dict(payload["session"])  # type: ignore[index]
    session["recording_consent_confirmed"] = False
    payload["session"] = session

    packet = build_hedy_meeting_review_packet(payload, principal_id="principal-1", now=NOW)

    assert packet["status"] == "privacy_blocked"
    assert packet["blocking_reason"] == "recording_consent_required"
    assert packet["evidence_candidates"] == []
    assert packet["commitment_candidates"] == []
    assert packet["decision_candidates"] == []
    assert packet["people_memory_candidates"] == []
    assert packet["draft_candidates"] == []
    assert packet["memory_write_allowed"] is False
    assert packet["commitment_write_allowed"] is False
    assert packet["decision_write_allowed"] is False


def test_signed_webhook_maps_session_into_review_only_ea_objects() -> None:
    payload = _sample_payload()
    body = _body(payload)
    service = HedyMeetingEvidenceService(webhook_secret=SECRET, clock=lambda: NOW)

    packet = service.ingest_webhook(
        body=body,
        headers=_signed_headers(body),
        principal_id="principal-1",
        workspace_id="workspace-1",
    )

    assert packet["status"] == "review_required"
    assert packet["provider"] == "hedy.ai"
    assert packet["webhook_verification"]["status"] == "pass"  # type: ignore[index]
    assert packet["publication_allowed"] is False
    assert packet["followup_send_allowed"] is False
    assert packet["memory_write_allowed"] is False
    assert packet["commitment_write_allowed"] is False
    assert packet["decision_write_allowed"] is False

    evidence = packet["evidence_candidates"]  # type: ignore[index]
    assert evidence[0]["data_classification"] == "restricted"
    assert "Please send Marta" in evidence[0]["content"]
    assert evidence[0]["retention_until"].startswith("2026-09-16")

    commitments = packet["commitment_candidates"]  # type: ignore[index]
    assert commitments[0]["object_type"] == "commitment_candidate"
    assert commitments[0]["status"] == "review_required"
    assert commitments[0]["title"] == "Send Marta the revised board pack"

    decisions = packet["decision_candidates"]  # type: ignore[index]
    assert decisions[0]["object_type"] == "decision_candidate"
    assert decisions[0]["authority_required"] == "principal"
    assert decisions[0]["options"] == ["Approve", "Request changes", "Defer"]

    people = packet["people_memory_candidates"]  # type: ignore[index]
    assert people[0]["object_type"] == "people_memory_candidate"
    assert people[0]["promotion_allowed_without_review"] is False
    assert people[0]["display_name"] == "Marta Weiss"

    drafts = packet["draft_candidates"]  # type: ignore[index]
    assert drafts[0]["requires_approval"] is True
    assert drafts[0]["send_allowed_without_approval"] is False

    review_objects = packet["ea_review_objects"]  # type: ignore[index]
    assert {item["object_type"] for item in review_objects} >= {
        "evidence",
        "commitment_candidate",
        "decision_candidate",
        "people_memory_candidate",
        "draft_candidate",
    }


def test_webhook_signature_rejects_missing_secret_and_bad_signature() -> None:
    body = _body(_sample_payload())

    missing_secret = verify_hedy_webhook_signature(body=body, signature_header="sha256=abc", secret="")
    assert missing_secret.ok is False
    assert missing_secret.reason == "webhook_secret_required"

    service = HedyMeetingEvidenceService(webhook_secret=SECRET, clock=lambda: NOW)
    with pytest.raises(PermissionError, match="webhook_signature_mismatch"):
        service.ingest_webhook(
            body=body,
            headers={"x-hedy-signature": "sha256=not-valid", "x-hedy-timestamp": "1781784000"},
            principal_id="principal-1",
        )


def test_webhook_timestamp_replay_is_rejected() -> None:
    body = _body(_sample_payload())
    old_timestamp = str(int((NOW - timedelta(minutes=12)).timestamp()))
    service = HedyMeetingEvidenceService(webhook_secret=SECRET, clock=lambda: NOW, tolerance_seconds=300)

    with pytest.raises(PermissionError, match="webhook_timestamp_outside_tolerance"):
        service.ingest_webhook(
            body=body,
            headers=_signed_headers(body, timestamp=old_timestamp),
            principal_id="principal-1",
        )


def test_webhook_retry_is_idempotent_and_does_not_create_duplicate_review_work() -> None:
    payload = _sample_payload()
    body = _body(payload)
    headers = _signed_headers(body)
    service = HedyMeetingEvidenceService(webhook_secret=SECRET, clock=lambda: NOW)

    first = service.ingest_webhook(body=body, headers=headers, principal_id="principal-1")
    second = service.ingest_webhook(body=body, headers=headers, principal_id="principal-1")

    assert first["packet_id"] == second["packet_id"]
    assert first["idempotency_key"] == second["idempotency_key"]
    assert first["ingest_status"] == "created"
    assert second["ingest_status"] == "duplicate"
    assert second["idempotent_replay"] is True
    assert service.ingested_count == 1
