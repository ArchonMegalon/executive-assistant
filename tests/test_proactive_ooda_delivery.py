from __future__ import annotations

from types import SimpleNamespace

from app.services import proactive_ooda_delivery as delivery
from app.services.proactive_ooda_service import ProactiveOodaService, build_run_receipt


def _delivery_preference(**overrides: object) -> SimpleNamespace:
    values = {
        "preference_id": "pref-1",
        "principal_id": "exec",
        "channel": "whatsapp",
        "recipient_ref": "+43 681 208 640 06",
        "cadence": "normal",
        "status": "active",
        "created_at": "2026-06-26T10:00:00+00:00",
        "updated_at": "2026-06-26T12:00:00+00:00",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _communication_policy(**overrides: object) -> SimpleNamespace:
    values = {
        "policy_id": "policy-1",
        "principal_id": "exec",
        "scope": "proactive_ooda",
        "preferred_channel": "telegram",
        "status": "active",
        "created_at": "2026-06-26T10:00:00+00:00",
        "updated_at": "2026-06-26T12:00:00+00:00",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _follow_up(**overrides: object) -> SimpleNamespace:
    values = {
        "follow_up_id": "follow-1",
        "principal_id": "exec",
        "channel_hint": "",
        "due_at": "2026-06-27T09:00:00+00:00",
        "updated_at": "2026-06-26T12:00:00+00:00",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _telegram_binding(**overrides: object) -> SimpleNamespace:
    values = {
        "binding_id": "tg-binding-1",
        "connector_name": "telegram_identity",
        "status": "enabled",
        "external_account_ref": "1354554303",
        "auth_metadata_json": {"default_chat_ref": "1354554303"},
        "updated_at": "2026-06-26T12:00:00+00:00",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _whatsapp_web_binding(**overrides: object) -> SimpleNamespace:
    values = {
        "binding_id": "wa-binding-1",
        "principal_id": "exec",
        "connector_name": "whatsapp_web_session",
        "external_account_ref": "+15550101000",
        "scope_json": {"scopes": ["whatsapp.send"]},
        "auth_metadata_json": {
            "session_ref": "session-exec",
            "session_store_ref": "vault://ea/whatsapp-web/session-exec",
            "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages",
            "session_status_url_template": "https://wa-web.test/sessions/{session_ref}/status",
            "session_api_token": "session-token",
        },
        "status": "enabled",
        "updated_at": "2026-06-26T12:00:00+00:00",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_delivery_status_prefers_active_whatsapp_delivery_preference(monkeypatch) -> None:
    memory_runtime = SimpleNamespace(
        list_delivery_preferences=lambda **_kwargs: [_delivery_preference()],
        list_communication_policies=lambda **_kwargs: [],
        list_follow_ups=lambda **_kwargs: [],
    )
    tool_runtime = SimpleNamespace(
        list_connector_bindings=lambda principal_id, limit=200: [_whatsapp_web_binding()],
    )
    monkeypatch.setattr(
        delivery,
        "check_whatsapp_web_session_readiness",
        lambda **_kwargs: SimpleNamespace(ready=True, reason="ready", probe_reason="ready"),
    )

    status = delivery.resolve_proactive_ooda_delivery_status(
        principal_id="exec",
        tool_runtime=tool_runtime,
        memory_runtime=memory_runtime,
    )

    assert status.ready is True
    assert status.selected_channel == "whatsapp"
    assert status.selected_transport == "whatsapp_web_session"
    assert status.selected_by == "delivery_preference"
    assert status.preference_id == "pref-1"
    assert status.binding_id == "wa-binding-1"
    assert status.recipient_ref_hash


def test_delivery_status_skips_urgent_only_whatsapp_preference_for_non_high_priority_digest(
    monkeypatch,
) -> None:
    memory_runtime = SimpleNamespace(
        list_delivery_preferences=lambda **_kwargs: [_delivery_preference(cadence="urgent_only")],
        list_communication_policies=lambda **_kwargs: [_communication_policy(preferred_channel="telegram")],
        list_follow_ups=lambda **_kwargs: [_follow_up(channel_hint="whatsapp")],
    )
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setattr(delivery, "resolve_primary_telegram_binding", lambda tool_runtime, *, principal_id: _telegram_binding())
    tool_runtime = SimpleNamespace()
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "signal:review",
                "signal_type": "operator_signal",
                "channel": "operator_feed",
                "title": "Review the staged packet",
                "summary": "Review this later.",
            }
        ],
    )

    status = delivery.resolve_proactive_ooda_delivery_status(
        principal_id="exec",
        tool_runtime=tool_runtime,
        memory_runtime=memory_runtime,
        digest=digest,
    )

    assert status.ready is True
    assert status.selected_channel == "telegram"
    assert status.selected_by == "communication_policy"
    assert "delivery_preference_ineligible:pref-1:high_priority_required" in status.errors


def test_delivery_status_blocks_qr_required_whatsapp_web_and_falls_back_to_telegram(monkeypatch) -> None:
    memory_runtime = SimpleNamespace(
        list_delivery_preferences=lambda **_kwargs: [_delivery_preference()],
        list_communication_policies=lambda **_kwargs: [_communication_policy(preferred_channel="telegram")],
        list_follow_ups=lambda **_kwargs: [],
    )
    tool_runtime = SimpleNamespace(
        list_connector_bindings=lambda principal_id, limit=200: [_whatsapp_web_binding()],
    )
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setattr(delivery, "resolve_primary_telegram_binding", lambda tool_runtime, *, principal_id: _telegram_binding())
    monkeypatch.setattr(
        delivery,
        "check_whatsapp_web_session_readiness",
        lambda **_kwargs: SimpleNamespace(ready=False, reason="probe_failed", probe_reason="qr_required"),
    )

    status = delivery.resolve_proactive_ooda_delivery_status(
        principal_id="exec",
        tool_runtime=tool_runtime,
        memory_runtime=memory_runtime,
    )

    assert status.ready is True
    assert status.selected_channel == "telegram"
    assert status.selected_by == "communication_policy"
    assert "whatsapp_web_session_not_ready:qr_required" in status.errors


def test_send_proactive_notification_queues_outbox_and_returns_generic_receipt(monkeypatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setattr(delivery, "resolve_primary_telegram_binding", lambda tool_runtime, *, principal_id: _telegram_binding())
    monkeypatch.setattr(
        delivery,
        "send_telegram_message_for_principal",
        lambda tool_runtime, *, principal_id, text: SimpleNamespace(message_ids=("tg-1",), chat_id="1354554303"),
    )
    events: dict[str, object] = {}

    class _ChannelRuntime:
        def queue_delivery(self, channel, recipient, content, metadata=None, *, principal_id="", idempotency_key=""):
            events["queued"] = {
                "channel": channel,
                "recipient": recipient,
                "content": content,
                "metadata": dict(metadata or {}),
                "principal_id": principal_id,
            }
            return SimpleNamespace(delivery_id="delivery-1", status="pending")

        def mark_delivery_sent(self, delivery_id, *, principal_id, receipt_json=None):
            events["sent"] = {
                "delivery_id": delivery_id,
                "principal_id": principal_id,
                "receipt_json": dict(receipt_json or {}),
            }
            return None

    receipt = delivery.send_proactive_ooda_notification(
        principal_id="exec",
        text="EA OODA packet",
        tool_runtime=SimpleNamespace(),
        channel_runtime=_ChannelRuntime(),
        memory_runtime=SimpleNamespace(
            list_delivery_preferences=lambda **_kwargs: [],
            list_communication_policies=lambda **_kwargs: [],
            list_follow_ups=lambda **_kwargs: [],
        ),
    )

    assert receipt.channel == "telegram"
    assert receipt.delivery_transport == "telegram"
    assert receipt.message_ids == ("tg-1",)
    assert receipt.telegram_message_ids == ("tg-1",)
    assert receipt.outbox_delivery_id == "delivery-1"
    assert events["queued"]["channel"] == "telegram"
    assert events["sent"]["receipt_json"]["channel"] == "telegram"


def test_build_run_receipt_keeps_generic_delivery_fields_for_whatsapp() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "signal:vendor",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Vendor shortlist ready today",
                "summary": "Review the shortlist.",
            }
        ],
    )
    notification_result = delivery.ProactiveOodaDeliveryReceipt(
        channel="whatsapp",
        delivery_transport="whatsapp_web_session",
        selected_by="delivery_preference",
        selected_reason="whatsapp preference selected",
        recipient_ref_hash="a" * 64,
        message_ids=("wa-1",),
        binding_id="wa-binding-1",
        outbox_delivery_id="delivery-1",
        telegram_message_ids=(),
    )

    receipt = build_run_receipt(
        digest=digest,
        dry_run=False,
        notification_result=notification_result,
    )

    assert receipt.notification_status == "sent"
    assert receipt.delivery_channel == "whatsapp"
    assert receipt.delivery_transport == "whatsapp_web_session"
    assert receipt.delivery_selected_by == "delivery_preference"
    assert receipt.delivery_message_ids == ("wa-1",)
    assert receipt.telegram_message_ids == ()
    assert receipt.delivery_recipient_hash == "a" * 64
    assert receipt.delivery_outbox_id_hash
