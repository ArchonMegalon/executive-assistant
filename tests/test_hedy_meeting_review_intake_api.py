from __future__ import annotations

from datetime import datetime, timezone
import json
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.services.hedy_meeting_evidence import hedy_webhook_signature


SECRET = "test-hedy-review-secret"


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_API_TOKEN", "test-token")
    monkeypatch.setenv("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", "1")
    monkeypatch.setenv("EA_HEDY_DEFAULT_PRINCIPAL_ID", "")
    from app.api.app import create_app

    return TestClient(create_app())


def _sample_payload(*, consent: bool = True) -> dict[str, object]:
    return {
        "event_id": "evt-hedy-review-001",
        "type": "session.completed",
        "principal_id": "exec-hedy-review",
        "workspace_id": "workspace-hedy-review",
        "session": {
            "id": "sess-hedy-review-001",
            "title": "Leadership meeting",
            "recording_consent_confirmed": consent,
            "region": "eu",
            "transcript": "Tibor: Please send Marta the revised board pack.\nMarta: Decide if the budget is ready.",
            "summary": "One follow-up and one approval question were captured.",
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


def _body(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _headers(body: bytes) -> dict[str, str]:
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    return {
        "content-type": "application/json",
        "x-hedy-timestamp": timestamp,
        "x-hedy-signature": hedy_webhook_signature(body, SECRET, timestamp=timestamp),
    }


def _enable_hedy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_HEDY_MEETING_EVIDENCE_ENABLED", "1")
    monkeypatch.setenv("EA_HEDY_WEBHOOKS_ENABLED", "1")
    monkeypatch.setenv("HEDY_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("EA_HEDY_WEBHOOK_TOLERANCE_SECONDS", "300")


def test_hedy_webhook_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    body = _body(_sample_payload())

    response = client.post("/v1/integrations/hedy/webhook", content=body, headers=_headers(body))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "hedy_webhook_disabled"


def test_hedy_webhook_creates_one_review_task_and_dedupes_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_hedy(monkeypatch)
    client = _client(monkeypatch)
    body = _body(_sample_payload())

    first = client.post("/v1/integrations/hedy/webhook", content=body, headers=_headers(body))
    second = client.post("/v1/integrations/hedy/webhook", content=body, headers=_headers(body))

    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["contract_name"] == "ea.hedy_meeting_review_intake.v1"
    assert first_body["status"] == "review_required"
    assert first_body["created_review_task"] is True
    assert first_body["duplicate"] is False
    assert first_body["human_task"]["task_type"] == "hedy_meeting_review"
    assert first_body["candidate_counts"] == {
        "evidence": 2,
        "commitments": 1,
        "decisions": 1,
        "people_memory": 1,
        "drafts": 1,
    }
    assert second_body["created_review_task"] is False
    assert second_body["duplicate"] is True
    assert second_body["human_task"]["human_task_id"] == first_body["human_task"]["human_task_id"]

    task = client.app.state.container.orchestrator.fetch_human_task(
        first_body["human_task"]["human_task_id"],
        principal_id="exec-hedy-review",
    )
    assert task is not None
    assert task.priority == "high"
    assert task.authority_required == "principal_or_operator_review"
    assert task.input_json["hedy_idempotency_key"] == first_body["packet"]["idempotency_key"]
    hedy_packet = task.input_json["hedy_packet"]
    assert hedy_packet["commitment_write_allowed"] is False
    assert hedy_packet["decision_write_allowed"] is False
    assert hedy_packet["memory_write_allowed"] is False
    assert hedy_packet["followup_send_allowed"] is False
    assert "Please send Marta" in hedy_packet["evidence_candidates"][0]["content"]

    tasks = client.app.state.container.orchestrator.list_human_tasks(
        principal_id="exec-hedy-review",
        status="pending",
        limit=20,
    )
    assert [row.task_type for row in tasks].count("hedy_meeting_review") == 1


def test_hedy_webhook_rejects_bad_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_hedy(monkeypatch)
    client = _client(monkeypatch)
    body = _body(_sample_payload())

    response = client.post(
        "/v1/integrations/hedy/webhook",
        content=body,
        headers={
            "content-type": "application/json",
            "x-hedy-timestamp": str(int(datetime.now(timezone.utc).timestamp())),
            "x-hedy-signature": "sha256=not-valid",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "webhook_signature_mismatch"


def test_hedy_webhook_requires_a_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_hedy(monkeypatch)
    client = _client(monkeypatch)
    body = b"[]"

    response = client.post(
        "/v1/integrations/hedy/webhook",
        content=body,
        headers=_headers(body),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "hedy_payload_object_required"


def test_hedy_webhook_rejects_oversized_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_hedy(monkeypatch)
    monkeypatch.setenv("EA_HEDY_WEBHOOK_MAX_BODY_BYTES", "64")
    client = _client(monkeypatch)
    body = _body(_sample_payload())

    response = client.post(
        "/v1/integrations/hedy/webhook",
        content=body,
        headers=_headers(body),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "hedy_payload_too_large"


def test_hedy_webhook_blocks_unconsented_transcript_without_review_task(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_hedy(monkeypatch)
    client = _client(monkeypatch)
    body = _body(_sample_payload(consent=False))

    response = client.post("/v1/integrations/hedy/webhook", content=body, headers=_headers(body))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "privacy_blocked"
    assert payload["created_review_task"] is False
    assert payload["human_task"] == {}
    assert payload["packet"]["blocking_reason"] == "recording_consent_required"
    assert payload["packet"]["evidence_candidates"] == []
    tasks = client.app.state.container.orchestrator.list_human_tasks(
        principal_id="exec-hedy-review",
        status="pending",
        limit=20,
    )
    assert tasks == []
