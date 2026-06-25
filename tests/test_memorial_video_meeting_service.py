from __future__ import annotations

from datetime import datetime, timezone
import json

from app.services import memorial_video_meeting
from app.services.hedy_meeting_evidence import hedy_webhook_signature


def test_public_video_meeting_payload_defaults_to_fallback(monkeypatch) -> None:
    monkeypatch.delenv("EA_MEMORIAL_VIDEO_MEETING_PROVIDER", raising=False)
    monkeypatch.delenv("EA_MEMORIAL_VIDEO_MEETING_ENABLED", raising=False)
    payload = memorial_video_meeting.public_video_meeting_payload(slug="manfred", person_name="Manfred Hoza")
    assert payload["integration_state"] == "fallback_only"
    assert payload["provider_key"] == ""
    assert payload["next_action"] == "fallback_to_portrait_voice"
    assert payload["provider_label"] == ""
    assert payload["fallback_mode"] == "portrait_voice"
    assert payload["session_endpoint"] == "/memorials/manfred/video-meeting/session"


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
    assert payload["provider_label"] == "Tavus"
    assert payload["recommended_provider"] == "tavus"
    assert payload["secondary_provider"] == "did"


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
    assert payload["provider_label"] == "D-ID"
    assert payload["client"]["camera_requested"] is True
    assert payload["client"]["personal_memory_enabled"] is False


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
    assert "personal_memory_enabled" not in seen["json"]
    assert payload["integration_state"] == "provider_live_session_created"
    assert payload["provider_key"] == "tavus"
    assert payload["next_action"] == "join_provider_session"
    assert payload["provider_session"]["conversation_url"] == "https://tavus.daily.co/c123"
    assert payload["provider_session"]["meeting_token"] == "jwt"
    assert payload["provider_session"]["callback_url"] == "https://example.test/callback"


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


def test_public_memorial_video_meeting_callback_uses_timestamped_hmac_contract(monkeypatch) -> None:
    from app.api.routes import public_memorials

    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_WEBHOOK_SECRET", "callback-secret")
    monkeypatch.setenv("EA_MEMORIAL_VIDEO_MEETING_WEBHOOK_TOLERANCE_SECONDS", "300")
    body = json.dumps({"conversation_id": "conv-123"}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))

    class _Headers(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class _Request:
        headers = _Headers(
            {
                "x-tavus-timestamp": timestamp,
                "x-tavus-signature": hedy_webhook_signature(body, "callback-secret", timestamp=timestamp),
            }
        )

    public_memorials._verify_public_memorial_video_meeting_callback(
        request=_Request(),
        provider_key="tavus",
        body=body,
    )
