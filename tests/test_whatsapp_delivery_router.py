from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import whatsapp_delivery_router


def _binding(**overrides: object) -> SimpleNamespace:
    values = {
        "binding_id": "binding-1",
        "principal_id": "principal-1",
        "connector_name": "whatsapp_web_session",
        "external_account_ref": "+15550101000",
        "scope_json": {"scopes": ["whatsapp.send"]},
        "auth_metadata_json": {},
        "status": "enabled",
        "created_at": "2026-06-21T00:00:00Z",
        "updated_at": "2026-06-21T00:00:00Z",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _receipt(**overrides: object) -> SimpleNamespace:
    values = {
        "principal_id": "principal-1",
        "binding_id": "binding-1",
        "connector_name": "whatsapp_web_session",
        "recipient": "4368120864006",
        "message_ids": ("wamid.1",),
        "request_url": "https://wa-web.test/sessions/session-1/messages",
        "binding_status": "enabled",
        "external_account_ref": "+15550101000",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_router_sends_web_session_binding_through_web_session_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding()
    tool_runtime = SimpleNamespace(get_connector_binding=lambda binding_id: binding)
    captured: dict[str, object] = {}

    def _fake_web_send(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _receipt()

    monkeypatch.setattr(whatsapp_delivery_router.whatsapp_web_session_delivery, "send_whatsapp_web_session_text", _fake_web_send)

    routed = whatsapp_delivery_router.send_whatsapp_delivery_text(
        tool_runtime=tool_runtime,
        principal_id="principal-1",
        recipient="+43 681 208 640 06",
        text="through web",
        binding_id="binding-1",
    )

    assert captured["binding"] is binding
    assert captured["binding_id"] == "binding-1"
    assert captured["recipient"] == "+43 681 208 640 06"
    assert routed.delivery_transport == "whatsapp_web_session"
    assert routed.connector_name == "whatsapp_web_session"
    assert routed.message_ids == ("wamid.1",)


def test_router_passes_inline_buttons_to_web_session_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding()
    tool_runtime = SimpleNamespace(get_connector_binding=lambda binding_id: binding)
    captured: dict[str, object] = {}

    def _fake_web_send(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _receipt()

    monkeypatch.setattr(whatsapp_delivery_router.whatsapp_web_session_delivery, "send_whatsapp_web_session_text", _fake_web_send)

    whatsapp_delivery_router.send_whatsapp_delivery_text(
        tool_runtime=tool_runtime,
        principal_id="principal-1",
        recipient="4368120864006",
        text="Choose an audiobook voice.",
        binding_id="binding-1",
        buttons=[[("Use this", "ab|u|voice-token|zz|sig")]],
    )

    assert captured["buttons"] == [[("Use this", "ab|u|voice-token|zz|sig")]]


def test_router_passes_heyy_ai_override_to_web_session_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding()
    tool_runtime = SimpleNamespace(get_connector_binding=lambda binding_id: binding)
    captured: dict[str, object] = {}

    def _fake_web_send(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _receipt()

    monkeypatch.setattr(whatsapp_delivery_router.whatsapp_web_session_delivery, "send_whatsapp_web_session_text", _fake_web_send)

    whatsapp_delivery_router.send_whatsapp_delivery_text(
        tool_runtime=tool_runtime,
        principal_id="principal-1",
        recipient="4368120864006",
        text="Herta reach-out test",
        binding_id="binding-1",
        heyy_ai_key="empathetic_slow_typing_old_lady",
        heyy_ai_name="Herta (Heyy Lady)",
    )

    assert captured["heyy_ai_key"] == "empathetic_slow_typing_old_lady"
    assert captured["heyy_ai_name"] == "Herta (Heyy Lady)"


def test_router_preserves_supplied_web_session_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding(binding_id="provided-binding")
    captured: dict[str, object] = {}

    def _fake_web_send(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _receipt(binding_id="provided-binding")

    monkeypatch.setattr(whatsapp_delivery_router.whatsapp_web_session_delivery, "send_whatsapp_web_session_text", _fake_web_send)

    routed = whatsapp_delivery_router.send_whatsapp_delivery_text(
        tool_runtime=None,
        principal_id="principal-1",
        recipient="4368120864006",
        text="provided",
        binding=binding,
    )

    assert captured["binding"] is binding
    assert routed.binding_id == "provided-binding"
    assert routed.delivery_transport == "whatsapp_web_session"


def test_router_prefers_configured_default_web_session_binding_without_binding_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding(binding_id="default-web-binding")
    captured: dict[str, object] = {}

    def _fake_web_send(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _receipt(binding_id="default-web-binding")

    tool_runtime = SimpleNamespace(
        get_connector_binding=lambda binding_id: binding if binding_id == "default-web-binding" else None,
    )
    monkeypatch.setenv("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID", "default-web-binding")
    monkeypatch.setattr(whatsapp_delivery_router.whatsapp_web_session_delivery, "send_whatsapp_web_session_text", _fake_web_send)

    routed = whatsapp_delivery_router.send_whatsapp_delivery_text(
        tool_runtime=tool_runtime,
        principal_id="principal-1",
        recipient="4368120864006",
        text="default web route",
    )

    assert captured["binding"] is binding
    assert captured["binding_id"] == ""
    assert routed.binding_id == "default-web-binding"
    assert routed.delivery_transport == "whatsapp_web_session"


def test_router_prefers_latest_enabled_web_session_binding_for_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disabled_newer = _binding(binding_id="disabled-newer", status="staged", updated_at="2026-06-22T00:00:00Z")
    enabled_older = _binding(binding_id="enabled-older", updated_at="2026-06-20T00:00:00Z")
    enabled_newer = _binding(binding_id="enabled-newer", updated_at="2026-06-21T00:00:00Z")
    captured: dict[str, object] = {}

    def _fake_web_send(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _receipt(binding_id="enabled-newer")

    tool_runtime = SimpleNamespace(
        list_connector_bindings=lambda principal_id, limit=200: [disabled_newer, enabled_older, enabled_newer],
    )
    monkeypatch.delenv("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID", raising=False)
    monkeypatch.setattr(whatsapp_delivery_router.whatsapp_web_session_delivery, "send_whatsapp_web_session_text", _fake_web_send)

    routed = whatsapp_delivery_router.send_whatsapp_delivery_text(
        tool_runtime=tool_runtime,
        principal_id="principal-1",
        recipient="4368120864006",
        text="principal web route",
    )

    assert captured["binding"] is enabled_newer
    assert routed.binding_id == "enabled-newer"
    assert routed.delivery_transport == "whatsapp_web_session"


def test_router_uses_staged_web_session_binding_as_fail_closed_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged = _binding(binding_id="staged-web", status="staged")
    tool_runtime = SimpleNamespace(list_connector_bindings=lambda principal_id, limit=200: [staged])
    monkeypatch.delenv("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID", raising=False)

    with pytest.raises(RuntimeError, match="whatsapp_web_session_binding_disabled:staged-web"):
        whatsapp_delivery_router.send_whatsapp_delivery_text(
            tool_runtime=tool_runtime,
            principal_id="principal-1",
            recipient="4368120864006",
            text="fail closed web route",
        )


def test_router_sends_business_binding_through_legacy_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding(connector_name="whatsapp_business")
    tool_runtime = SimpleNamespace(get_connector_binding=lambda binding_id: binding)
    captured: dict[str, object] = {}

    def _fake_legacy_send(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _receipt(connector_name="whatsapp_business", request_url="https://graph.facebook.com/v21.0/123/messages")

    monkeypatch.setattr(whatsapp_delivery_router, "_send_legacy_whatsapp_text", _fake_legacy_send)

    routed = whatsapp_delivery_router.send_whatsapp_delivery_text(
        tool_runtime=tool_runtime,
        principal_id="principal-1",
        recipient="+43 681 208 640 06",
        text="through business",
        binding_id="binding-1",
    )

    assert captured["binding"] is binding
    assert routed.delivery_transport == "whatsapp_business"
    assert routed.connector_name == "whatsapp_business"
    assert routed.request_url == "https://graph.facebook.com/v21.0/123/messages"


def test_router_appends_button_fallback_for_legacy_business_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding(connector_name="whatsapp_business")
    tool_runtime = SimpleNamespace(get_connector_binding=lambda binding_id: binding)
    captured: dict[str, object] = {}

    class _LegacyModule:
        @staticmethod
        def send_whatsapp_text(**kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return _receipt(connector_name="whatsapp_business", request_url="https://graph.facebook.com/v21.0/123/messages")

    monkeypatch.setattr(whatsapp_delivery_router, "_legacy_whatsapp_delivery_module", lambda: _LegacyModule)

    whatsapp_delivery_router.send_whatsapp_delivery_text(
        tool_runtime=tool_runtime,
        principal_id="principal-1",
        recipient="4368120864006",
        text="Choose an audiobook voice.",
        binding_id="binding-1",
        buttons=[[("Use this", "ab|u|voice-token|zz|sig"), ("Dismiss", "ab|d|voice-token|zz|sig")]],
    )

    assert "Choices:" in captured["text"]
    assert "1. Use this [ab|u|voice-token|zz|sig]" in captured["text"]
    assert "2. Dismiss [ab|d|voice-token|zz|sig]" in captured["text"]


def test_router_legacy_path_reports_missing_legacy_module(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding(connector_name="whatsapp_business")
    monkeypatch.setattr(
        whatsapp_delivery_router,
        "_legacy_whatsapp_delivery_module",
        lambda: (_ for _ in ()).throw(RuntimeError("whatsapp_legacy_delivery_unavailable")),
    )

    with pytest.raises(RuntimeError, match="whatsapp_legacy_delivery_unavailable"):
        whatsapp_delivery_router.send_whatsapp_delivery_text(
            tool_runtime=None,
            principal_id="principal-1",
            recipient="4368120864006",
            text="legacy missing",
            binding=binding,
        )
