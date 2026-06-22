from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import whatsapp_delivery_outbox


class _ChannelRuntime:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.sent: list[tuple[str, dict[str, object]]] = []
        self.failed: list[tuple[str, dict[str, object]]] = []

    def list_pending_delivery(self, limit: int = 400):
        return self.rows[:limit]

    def mark_delivery_sent(self, delivery_id: str, **kwargs: object) -> None:
        self.sent.append((delivery_id, kwargs))

    def mark_delivery_failed(self, delivery_id: str, **kwargs: object) -> None:
        self.failed.append((delivery_id, kwargs))


def _row(**overrides: object) -> SimpleNamespace:
    values = {
        "delivery_id": "delivery-1",
        "principal_id": "principal-1",
        "channel": "whatsapp",
        "recipient": "+43 681 208 640 06",
        "content": "queued message",
        "metadata": {"binding_id": "binding-1"},
        "created_at": "2026-06-21T09:59:50+00:00",
        "attempt_count": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_drain_whatsapp_outbox_marks_web_session_delivery_sent(monkeypatch) -> None:
    binding = SimpleNamespace(binding_id="binding-1", connector_name="whatsapp_web_session")
    button_rows = [[{"text": "Use this", "callback_data": "ab|u|voice-token|zz|sig"}]]
    channel_runtime = _ChannelRuntime([_row(metadata={"binding_id": "binding-1", "inline_buttons": button_rows})])
    container = SimpleNamespace(
        channel_runtime=channel_runtime,
        tool_runtime=SimpleNamespace(get_connector_binding=lambda binding_id: binding),
    )
    captured: dict[str, object] = {}

    def _fake_send(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            principal_id="principal-1",
            binding_id="binding-1",
            connector_name="whatsapp_web_session",
            recipient="4368120864006",
            message_ids=("wamid.web.1",),
            request_url="https://wa-web.test/sessions/session-1/messages",
            binding_status="enabled",
            external_account_ref="+15550101000",
            delivery_transport="whatsapp_web_session",
        )

    monkeypatch.setattr(whatsapp_delivery_outbox.whatsapp_delivery_router, "send_whatsapp_delivery_text", _fake_send)

    result = whatsapp_delivery_outbox.drain_whatsapp_delivery_outbox(
        container=container,
        observed_at=datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc),
    )

    assert result == {"ran": True, "drained": 1, "pending": 0, "skipped": 0, "errors": 0, "dead_lettered": 0}
    assert captured["binding"] is binding
    assert captured["binding_id"] == "binding-1"
    assert captured["buttons"] == button_rows
    assert channel_runtime.sent[0][0] == "delivery-1"
    receipt = channel_runtime.sent[0][1]["receipt_json"]
    assert receipt["delivery_transport"] == "whatsapp_web_session"
    assert receipt["message_ids"] == ["wamid.web.1"]


def test_drain_whatsapp_outbox_leaves_new_rows_pending(monkeypatch) -> None:
    channel_runtime = _ChannelRuntime([
        _row(created_at=(datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc) - timedelta(seconds=1)).isoformat())
    ])
    container = SimpleNamespace(channel_runtime=channel_runtime, tool_runtime=SimpleNamespace(get_connector_binding=lambda _: None))
    called = False

    def _fake_send(**_: object) -> SimpleNamespace:
        nonlocal called
        called = True
        raise AssertionError("should not send young rows")

    monkeypatch.setattr(whatsapp_delivery_outbox.whatsapp_delivery_router, "send_whatsapp_delivery_text", _fake_send)

    result = whatsapp_delivery_outbox.drain_whatsapp_delivery_outbox(
        container=container,
        observed_at=datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc),
        min_age_seconds=2.0,
    )

    assert result["pending"] == 1
    assert called is False
    assert channel_runtime.sent == []
    assert channel_runtime.failed == []


def test_drain_whatsapp_outbox_schedules_retry_on_send_error(monkeypatch) -> None:
    channel_runtime = _ChannelRuntime([_row()])
    container = SimpleNamespace(channel_runtime=channel_runtime, tool_runtime=SimpleNamespace(get_connector_binding=lambda _: None))
    monkeypatch.setattr(
        whatsapp_delivery_outbox.whatsapp_delivery_router,
        "send_whatsapp_delivery_text",
        lambda **_: (_ for _ in ()).throw(RuntimeError("send failed")),
    )

    result = whatsapp_delivery_outbox.drain_whatsapp_delivery_outbox(
        container=container,
        observed_at=datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc),
        retry_backoff_seconds=3,
    )

    assert result["errors"] == 1
    assert channel_runtime.failed[0][1]["error"] == "whatsapp_send_failed"
    assert channel_runtime.failed[0][1]["dead_letter"] is False
    assert channel_runtime.failed[0][1]["next_attempt_at"] == "2026-06-21T10:00:03+00:00"


def test_drain_whatsapp_outbox_dead_letters_exhausted_delivery(monkeypatch) -> None:
    channel_runtime = _ChannelRuntime([_row(attempt_count=2)])
    container = SimpleNamespace(channel_runtime=channel_runtime, tool_runtime=SimpleNamespace(get_connector_binding=lambda _: None))
    monkeypatch.setattr(
        whatsapp_delivery_outbox.whatsapp_delivery_router,
        "send_whatsapp_delivery_text",
        lambda **_: (_ for _ in ()).throw(RuntimeError("send failed")),
    )

    result = whatsapp_delivery_outbox.drain_whatsapp_delivery_outbox(
        container=container,
        observed_at=datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc),
        max_attempts=3,
    )

    assert result["dead_lettered"] == 1
    assert channel_runtime.failed[0][1]["error"] == "whatsapp_delivery_retry_limit_reached"
    assert channel_runtime.failed[0][1]["dead_letter"] is True
