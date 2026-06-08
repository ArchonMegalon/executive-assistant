from __future__ import annotations

from app.services import memorial_video_meeting


def test_public_video_meeting_payload_defaults_to_fallback(monkeypatch) -> None:
    monkeypatch.delenv("EA_MEMORIAL_VIDEO_MEETING_PROVIDER", raising=False)
    monkeypatch.delenv("EA_MEMORIAL_VIDEO_MEETING_ENABLED", raising=False)
    payload = memorial_video_meeting.public_video_meeting_payload(slug="manfred", person_name="Manfred Hoza")
    assert payload["integration_state"] == "fallback_only"
    assert payload["provider_key"] == ""
    assert payload["next_action"] == "fallback_to_portrait_voice"


def test_public_video_meeting_payload_marks_tavus_live_ready_when_fully_configured(monkeypatch) -> None:
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_PROVIDER", "tavus")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_ALLOW_PROVIDER_SESSION", "1")
    monkeypatch.setenv("TAVUS_API_KEY", "key")
    monkeypatch.setenv("TAVUS_PERSONA_ID", "persona")
    monkeypatch.setenv("TAVUS_REPLICA_ID", "replica")
    payload = memorial_video_meeting.public_video_meeting_payload(slug="manfred", person_name="Manfred Hoza")
    assert payload["integration_state"] == "provider_live_session_ready"
    assert payload["provider_key"] == "tavus"
    assert payload["next_action"] == "create_provider_session"


def test_create_video_meeting_session_returns_fallback_when_not_live_ready(monkeypatch) -> None:
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_PROVIDER", "did")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_ENABLED", "1")
    monkeypatch.setenv("D_ID_API_KEY", "key")
    payload = memorial_video_meeting.create_video_meeting_session(
        slug="manfred",
        person_name="Manfred Hoza",
        camera_requested=True,
        personal_memory_enabled=False,
        request_host="https://myexternalbrain.com",
    )
    assert payload["integration_state"] == "provider_configured_contract_only"
    assert payload["provider_key"] == "did"
    assert payload["next_action"] == "provider_client_sdk_not_implemented"


def test_create_video_meeting_session_uses_tavus_when_live_ready(monkeypatch) -> None:
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_PROVIDER", "tavus")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_ALLOW_PROVIDER_SESSION", "1")
    monkeypatch.setenv("TAVUS_API_KEY", "key")
    monkeypatch.setenv("TAVUS_PERSONA_ID", "persona")
    monkeypatch.setenv("TAVUS_REPLICA_ID", "replica")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "conversation_id": "c123",
                "conversation_url": "https://tavus.daily.co/c123",
                "meeting_token": "jwt",
                "status": "active",
                "created_at": "2026-06-08T12:00:00Z",
                "callback_url": "https://example.test/callback",
            }

    seen: dict[str, object] = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        seen["json"] = json
        return _Response()

    monkeypatch.setattr(memorial_video_meeting.requests, "post", _fake_post)
    payload = memorial_video_meeting.create_video_meeting_session(
        slug="manfred",
        person_name="Manfred Hoza",
        camera_requested=False,
        personal_memory_enabled=True,
        request_host="https://myexternalbrain.com",
    )
    assert seen["url"] == "https://tavusapi.com/v2/conversations"
    assert seen["headers"]["x-api-key"] == "key"
    assert seen["json"]["persona_id"] == "persona"
    assert seen["json"]["replica_id"] == "replica"
    assert seen["json"]["require_auth"] is True
    assert payload["integration_state"] == "provider_live_session_created"
    assert payload["provider_key"] == "tavus"
    assert payload["next_action"] == "join_provider_session"
    assert payload["provider_session"]["conversation_url"] == "https://tavus.daily.co/c123"


def test_sanitize_provider_callback_strips_tavus_payload_to_summary() -> None:
    payload = memorial_video_meeting.sanitize_provider_callback(
        "tavus",
        {
            "event_type": "conversation.updated",
            "conversation_id": "conv-123",
            "status": "ended",
            "meeting_token": "secret",
            "created_at": "2026-06-08T12:00:00Z",
            "updated_at": "2026-06-08T12:03:00Z",
            "ended_at": "2026-06-08T12:04:00Z",
            "persona_id": "persona-123",
            "replica_id": "replica-123",
            "participant_count": 2,
        },
    )
    assert payload == {
        "provider_key": "tavus",
        "event_type": "conversation.updated",
        "conversation_id": "conv-123",
        "status": "ended",
        "created_at": "2026-06-08T12:00:00Z",
        "updated_at": "2026-06-08T12:03:00Z",
        "ended_at": "2026-06-08T12:04:00Z",
        "persona_id": "persona-123",
        "replica_id": "replica-123",
        "participant_count": 2,
    }
