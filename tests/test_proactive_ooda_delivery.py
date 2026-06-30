from __future__ import annotations

from types import SimpleNamespace

from app.services import proactive_ooda_delivery as delivery
from app.services.proactive_ooda_telegram_policy import approval_request_needs_telegram_user_action
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


def test_approval_policy_suppresses_generic_shortlist_telegram_push() -> None:
    assert (
        approval_request_needs_telegram_user_action(
            {
                "packet_ref": "stage_packet:packet-1",
                "staged_artifact_ref": "safe_work_result:result-1",
                "approval_prompt": (
                    "Approve whether EA should proceed with this staged shortlist candidate. "
                    "Research, compare, or draft only; require explicit approval before purchase, booking, cancellation, sending, posting, or commitment."
                ),
                "staged_action_url": "https://example.com/candidate",
            }
        )
        is False
    )


def test_approval_policy_allows_shortlist_when_explicit_action_is_present() -> None:
    assert (
        approval_request_needs_telegram_user_action(
            {
                "packet_ref": "stage_packet:packet-1",
                "staged_artifact_ref": "safe_work_result:result-1",
                "approval_prompt": "Approve whether EA should proceed with this staged shortlist candidate.",
                "staged_action_url": "https://example.com/candidate",
                "approved_execution_mode": "record_outcome_only",
                "approved_action": "save_gmail_draft",
            }
        )
        is True
    )


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
    assert status.route_error == "whatsapp_web_session_not_ready:qr_required"
    assert status.next_action == "scan_whatsapp_web_qr"
    assert "Scan the WhatsApp Web QR code" in status.recovery_hint
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


def test_send_proactive_notification_sends_follow_up_approval_prompt_with_buttons(monkeypatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setattr(delivery, "resolve_primary_telegram_binding", lambda tool_runtime, *, principal_id: _telegram_binding())
    monkeypatch.setattr(
        delivery,
        "prepare_proactive_ooda_telegram_approval",
        lambda **kwargs: {
            "status": "pending",
            "callback_token_sha256": "b" * 64,
            "expires_at": "2026-07-05T10:00:00Z",
            "packet_ref_sha256": "c" * 64,
            "staged_artifact_ref_sha256": "d" * 64,
            "approval_prompt_sha256": "e" * 64,
            "staged_action_url_sha256": "f" * 64,
            "inline_buttons": [[("Approve", "po|a|token|1|sig")]],
            "url_buttons": [[("Open candidate", "https://example.com/candidate")]],
            "record_path": "/tmp/proactive-approval-record.json",
        },
    )
    sent: list[dict[str, object]] = []
    recorded: list[dict[str, object]] = []

    def fake_send(tool_runtime, *, principal_id, text, inline_buttons=None, url_buttons=None):
        sent.append(
            {
                "principal_id": principal_id,
                "text": text,
                "inline_buttons": inline_buttons,
                "url_buttons": url_buttons,
            }
        )
        return SimpleNamespace(message_ids=(f"tg-{len(sent)}",), chat_id="1354554303")

    monkeypatch.setattr(delivery, "send_telegram_message_for_principal", fake_send)
    monkeypatch.setattr(
        delivery,
        "record_proactive_ooda_telegram_approval_delivery",
        lambda **kwargs: recorded.append(dict(kwargs)) or {"status": kwargs.get("status", "")},
    )

    receipt = delivery.send_proactive_ooda_notification(
        principal_id="exec",
        text="EA OODA packet",
        tool_runtime=SimpleNamespace(),
        channel_runtime=None,
        memory_runtime=SimpleNamespace(
            list_delivery_preferences=lambda **_kwargs: [],
            list_communication_policies=lambda **_kwargs: [],
            list_follow_ups=lambda **_kwargs: [],
        ),
        approval_request={
            "packet_ref": "stage_packet:packet-1",
            "staged_artifact_ref": "safe_work_result:result-1",
            "approval_prompt": "Approve whether EA should keep this saved Gmail draft as the chosen next step.",
            "staged_action_url": "https://example.com/draft",
            "approved_execution_mode": "record_outcome_only",
            "approved_action": "save_gmail_draft",
        },
    )

    assert receipt.message_ids == ("tg-1",)
    assert receipt.approval_surface["status"] == "pending"
    assert receipt.approval_surface["callback_token_sha256"] == "b" * 64
    assert receipt.approval_surface["message_ids"] == ("tg-1",)
    assert len(sent) == 1
    assert sent[0]["text"] == "Approve whether EA should keep this saved Gmail draft as the chosen next step."
    assert sent[0]["inline_buttons"] == [[("Approve", "po|a|token|1|sig")]]
    assert sent[0]["url_buttons"] == [[("Open candidate", "https://example.com/candidate")]]
    assert recorded == [
        {
            "record_path": "/tmp/proactive-approval-record.json",
            "message_ids": ("tg-1",),
            "status": "pending",
        }
    ]


def test_send_proactive_notification_suppresses_generic_shortlist_approval(monkeypatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setattr(delivery, "resolve_primary_telegram_binding", lambda tool_runtime, *, principal_id: _telegram_binding())
    sent: list[dict[str, object]] = []

    def fake_send(tool_runtime, *, principal_id, text, inline_buttons=None, url_buttons=None):
        sent.append(
            {
                "principal_id": principal_id,
                "text": text,
                "inline_buttons": inline_buttons,
                "url_buttons": url_buttons,
            }
        )
        return SimpleNamespace(message_ids=(f"tg-{len(sent)}",), chat_id="1354554303")

    monkeypatch.setattr(delivery, "send_telegram_message_for_principal", fake_send)

    receipt = delivery.send_proactive_ooda_notification(
        principal_id="exec",
        text="EA OODA packet",
        tool_runtime=SimpleNamespace(),
        channel_runtime=None,
        memory_runtime=SimpleNamespace(
            list_delivery_preferences=lambda **_kwargs: [],
            list_communication_policies=lambda **_kwargs: [],
            list_follow_ups=lambda **_kwargs: [],
        ),
        approval_request={
            "packet_ref": "stage_packet:packet-1",
            "staged_artifact_ref": "safe_work_result:result-1",
            "approval_prompt": (
                "Approve whether EA should proceed with this staged shortlist candidate. "
                "Research, compare, or draft only; require explicit approval before purchase, booking, cancellation, sending, posting, or commitment."
            ),
            "staged_action_url": "https://example.com/candidate",
        },
    )

    assert receipt.message_ids == ()
    assert receipt.route_error == "telegram_notification_suppressed_non_actionable"
    assert dict(receipt.approval_surface or {}).get("status") == "suppressed_non_actionable"
    assert sent == []


def test_send_proactive_notification_marks_approval_surface_delivery_failed_when_prompt_send_fails(monkeypatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setattr(delivery, "resolve_primary_telegram_binding", lambda tool_runtime, *, principal_id: _telegram_binding())
    monkeypatch.setattr(
        delivery,
        "prepare_proactive_ooda_telegram_approval",
        lambda **kwargs: {
            "status": "pending",
            "callback_token_sha256": "b" * 64,
            "expires_at": "2026-07-05T10:00:00Z",
            "packet_ref_sha256": "c" * 64,
            "staged_artifact_ref_sha256": "d" * 64,
            "approval_prompt_sha256": "e" * 64,
            "staged_action_url_sha256": "f" * 64,
            "inline_buttons": [[("Approve", "po|a|token|1|sig")]],
            "url_buttons": [],
            "record_path": "/tmp/proactive-approval-record.json",
        },
    )
    recorded: list[dict[str, object]] = []
    send_count = {"count": 0}

    def fake_send(tool_runtime, *, principal_id, text, inline_buttons=None, url_buttons=None):
        send_count["count"] += 1
        if send_count["count"] == 1:
            raise RuntimeError("telegram_send_failed")
        return SimpleNamespace(message_ids=("tg-1",), chat_id="1354554303")

    monkeypatch.setattr(delivery, "send_telegram_message_for_principal", fake_send)
    monkeypatch.setattr(
        delivery,
        "record_proactive_ooda_telegram_approval_delivery",
        lambda **kwargs: recorded.append(dict(kwargs)) or {"status": kwargs.get("status", "")},
    )

    try:
        delivery.send_proactive_ooda_notification(
            principal_id="exec",
            text="EA OODA packet",
            tool_runtime=SimpleNamespace(),
            channel_runtime=None,
            memory_runtime=SimpleNamespace(
                list_delivery_preferences=lambda **_kwargs: [],
                list_communication_policies=lambda **_kwargs: [],
                list_follow_ups=lambda **_kwargs: [],
            ),
                approval_request={
                    "packet_ref": "stage_packet:packet-1",
                    "staged_artifact_ref": "safe_work_result:result-1",
                    "approval_prompt": "Approve whether EA should keep this saved Gmail draft as the chosen next step.",
                    "approved_execution_mode": "record_outcome_only",
                    "approved_action": "save_gmail_draft",
                },
            )
        raise AssertionError("send should fail when the action surface cannot be delivered")
    except RuntimeError as exc:
        assert str(exc) == "telegram_approval_prompt_delivery_failed"

    assert send_count["count"] == 1
    assert recorded == [
        {
            "record_path": "/tmp/proactive-approval-record.json",
            "message_ids": (),
            "status": "delivery_failed",
            "delivery_error_code": "telegram_approval_prompt_delivery_failed",
        }
    ]


def test_send_proactive_notification_passes_record_outcome_only_mode_to_approval_prompt(monkeypatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setattr(delivery, "resolve_primary_telegram_binding", lambda tool_runtime, *, principal_id: _telegram_binding())
    captured_prepare: dict[str, object] = {}
    monkeypatch.setattr(
        delivery,
        "prepare_proactive_ooda_telegram_approval",
        lambda **kwargs: captured_prepare.update(kwargs) or {
            "status": "pending",
            "callback_token_sha256": "b" * 64,
            "expires_at": "2026-07-05T10:00:00Z",
            "packet_ref_sha256": "c" * 64,
            "staged_artifact_ref_sha256": "d" * 64,
            "approval_prompt_sha256": "e" * 64,
            "staged_action_url_sha256": "f" * 64,
            "inline_buttons": [[("Approve", "po|a|token|1|sig")]],
            "url_buttons": [],
            "record_path": "/tmp/proactive-approval-record.json",
        },
    )
    monkeypatch.setattr(
        delivery,
        "send_telegram_message_for_principal",
        lambda tool_runtime, *, principal_id, text, inline_buttons=None, url_buttons=None: SimpleNamespace(
            message_ids=("tg-1",),
            chat_id="1354554303",
        ),
    )
    monkeypatch.setattr(
        delivery,
        "record_proactive_ooda_telegram_approval_delivery",
        lambda **kwargs: {"status": kwargs.get("status", "")},
    )

    receipt = delivery.send_proactive_ooda_notification(
        principal_id="exec",
        text="EA OODA packet",
        tool_runtime=SimpleNamespace(),
        channel_runtime=None,
        memory_runtime=SimpleNamespace(
            list_delivery_preferences=lambda **_kwargs: [],
            list_communication_policies=lambda **_kwargs: [],
            list_follow_ups=lambda **_kwargs: [],
        ),
        approval_request={
            "packet_ref": "stage_packet:packet-1",
            "staged_artifact_ref": "safe_work_result:result-1",
            "approval_prompt": "Approve whether EA should keep this saved Gmail draft.",
            "approved_execution_mode": "record_outcome_only",
            "approved_action": "save_gmail_draft",
        },
    )

    assert receipt.approval_surface["status"] == "pending"
    assert captured_prepare["approved_execution_mode"] == "record_outcome_only"
    assert captured_prepare["approved_action"] == "save_gmail_draft"


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
        route_error="whatsapp_web_session_not_ready:qr_required",
        recovery_hint="Scan the WhatsApp Web QR code and re-activate the session before preferring WhatsApp again.",
        next_action="scan_whatsapp_web_qr",
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
    assert receipt.delivery_route_error == "whatsapp_web_session_not_ready:qr_required"
    assert receipt.delivery_next_action == "scan_whatsapp_web_qr"


def test_build_run_receipt_derives_delivery_recovery_from_failed_error_code() -> None:
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

    receipt = build_run_receipt(
        digest=digest,
        dry_run=False,
        error_code="whatsapp_web_session_not_ready:qr_required",
    )

    assert receipt.notification_status == "failed"
    assert receipt.delivery_route_error == "whatsapp_web_session_not_ready:qr_required"
    assert receipt.delivery_next_action == "scan_whatsapp_web_qr"
    assert "Scan the WhatsApp Web QR code" in receipt.delivery_recovery_hint


def test_build_run_receipt_derives_telegram_delivery_recovery_from_failed_error_code() -> None:
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

    receipt = build_run_receipt(
        digest=digest,
        dry_run=False,
        error_code="telegram_sendmessage_http_403:bot_was_blocked_by_the_user",
    )

    assert receipt.notification_status == "failed"
    assert receipt.delivery_route_error == "telegram_sendmessage_http_403:bot_was_blocked_by_the_user"
    assert receipt.delivery_next_action == "repair_telegram_proactive_delivery"
    assert "press Start if needed" in receipt.delivery_recovery_hint
