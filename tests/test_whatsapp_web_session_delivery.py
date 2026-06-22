from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import whatsapp_web_session_delivery


def _binding(**overrides: object) -> SimpleNamespace:
    values = {
        "binding_id": "wa-web-binding-1",
        "principal_id": "principal-wa-web-1",
        "connector_name": "whatsapp_web_session",
        "external_account_ref": "+15550101000",
        "scope_json": {"scopes": ["whatsapp.send"]},
        "auth_metadata_json": {
            "session_ref": "session-principal",
            "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages",
            "session_api_token": "session-token",
        },
        "status": "enabled",
        "created_at": "2026-06-21T00:00:00Z",
        "updated_at": "2026-06-21T00:00:00Z",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_send_whatsapp_web_session_text_uses_binding_session_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding()
    tool_runtime = SimpleNamespace(get_connector_binding=lambda binding_id: binding if binding_id == "wa-web-binding-1" else None)
    captured: dict[str, object] = {}

    def _fake_send_request(
        *,
        request_url: str,
        payload: dict[str, object],
        token: str,
        auth_header_name: str,
        auth_header_prefix: str,
        timeout: float,
    ) -> dict[str, object]:
        captured.update(
            {
                "request_url": request_url,
                "payload": payload,
                "token": token,
                "auth_header_name": auth_header_name,
                "auth_header_prefix": auth_header_prefix,
                "timeout": timeout,
            }
        )
        return {"messages": [{"id": "wamid.web.1"}]}

    monkeypatch.setattr(whatsapp_web_session_delivery, "_send_session_http_request", _fake_send_request)
    monkeypatch.setenv("EA_WHATSAPP_WEB_SESSION_REQUEST_TIMEOUT_SECONDS", "7.5")

    receipt = whatsapp_web_session_delivery.send_whatsapp_web_session_text(
        tool_runtime=tool_runtime,
        principal_id="principal-wa-web-1",
        recipient="+43 681 208 640 06",
        text="EA route test",
        binding_id="wa-web-binding-1",
    )

    assert receipt.binding_id == "wa-web-binding-1"
    assert receipt.connector_name == "whatsapp_web_session"
    assert receipt.recipient == "4368120864006"
    assert receipt.session_ref == "session-principal"
    assert receipt.message_ids == ("wamid.web.1",)
    assert captured["request_url"] == "https://wa-web.test/sessions/session-principal/messages"
    assert captured["payload"]["session_ref"] == "session-principal"
    assert captured["payload"]["to"] == "4368120864006"
    assert captured["payload"]["text"] == "EA route test"
    assert captured["payload"]["metadata"]["transport"] == "whatsapp_web_session"
    assert captured["token"] == "session-token"
    assert captured["auth_header_name"] == "Authorization"
    assert captured["auth_header_prefix"] == "Bearer "
    assert captured["timeout"] == 7.5


def test_send_whatsapp_web_session_text_includes_inline_buttons(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding()
    tool_runtime = SimpleNamespace(get_connector_binding=lambda binding_id: binding if binding_id == "wa-web-binding-1" else None)
    captured: dict[str, object] = {}

    def _fake_send_request(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"message_id": "wamid.buttons.1"}

    monkeypatch.setattr(whatsapp_web_session_delivery, "_send_session_http_request", _fake_send_request)

    receipt = whatsapp_web_session_delivery.send_whatsapp_web_session_text(
        tool_runtime=tool_runtime,
        principal_id="principal-wa-web-1",
        recipient="4368120864006",
        text="Choose an audiobook voice.",
        binding_id="wa-web-binding-1",
        buttons=[[("Use this", "ab|u|voice-token|zz|sig"), ("Dismiss", "ab|d|voice-token|zz|sig")]],
    )

    payload = captured["payload"]
    assert receipt.message_ids == ("wamid.buttons.1",)
    assert payload["buttons"][0][0]["text"] == "Use this"
    assert payload["buttons"][0][0]["callback_data"].startswith("ab|u|")
    assert payload["buttons"][0][1]["text"] == "Dismiss"
    assert payload["metadata"]["button_count"] == 2
    assert payload["metadata"]["button_surface"] == "whatsapp_web_session"


def test_send_whatsapp_web_session_text_can_override_heyy_ai_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding()
    captured: dict[str, object] = {}

    def _fake_send_request(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"message_id": "wamid.herta.1"}

    monkeypatch.setattr(whatsapp_web_session_delivery, "_send_session_http_request", _fake_send_request)

    receipt = whatsapp_web_session_delivery.send_whatsapp_web_session_text(
        tool_runtime=None,
        principal_id="principal-wa-web-1",
        recipient="4368120864006",
        text="Herta reach-out test",
        binding=binding,
        heyy_ai_key="empathetic_slow_typing_old_lady",
        heyy_ai_name="Herta (Heyy Lady)",
    )

    payload = captured["payload"]
    assert receipt.message_ids == ("wamid.herta.1",)
    assert payload["heyy_ai_key"] == "empathetic_slow_typing_old_lady"
    assert payload["heyy_ai_name"] == "Herta (Heyy Lady)"
    assert payload["metadata"]["heyy_ai_key"] == "empathetic_slow_typing_old_lady"
    assert payload["metadata"]["heyy_ai_name"] == "Herta (Heyy Lady)"
    assert captured["timeout"] >= 900 + (len("Herta reach-out test") * 4) + 30


def test_send_whatsapp_web_session_text_rejects_overlong_button_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding()
    monkeypatch.setattr(
        whatsapp_web_session_delivery,
        "_send_session_http_request",
        lambda **_: pytest.fail("overlong callback should not be sent"),
    )

    with pytest.raises(RuntimeError, match="whatsapp_web_session_button_callback_too_long"):
        whatsapp_web_session_delivery.send_whatsapp_web_session_text(
            tool_runtime=None,
            principal_id="principal-wa-web-1",
            recipient="4368120864006",
            text="Choose an audiobook voice.",
            binding=binding,
            buttons=[[("Use this", "x" * 257)]],
        )


def test_send_whatsapp_web_session_text_can_resolve_default_enabled_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    older = _binding(binding_id="old-binding", status="disabled", updated_at="2026-06-20T00:00:00Z")
    newer = _binding(binding_id="new-binding", updated_at="2026-06-21T00:00:00Z")
    tool_runtime = SimpleNamespace(list_connector_bindings=lambda principal_id, limit=200: [older, newer])

    monkeypatch.setattr(
        whatsapp_web_session_delivery,
        "_send_session_http_request",
        lambda **_: {"message_id": "wamid.default.1"},
    )

    receipt = whatsapp_web_session_delivery.send_whatsapp_web_session_text(
        tool_runtime=tool_runtime,
        principal_id="principal-wa-web-1",
        recipient="4368120864006",
        text="default route",
    )

    assert receipt.binding_id == "new-binding"
    assert receipt.message_ids == ("wamid.default.1",)


def test_send_whatsapp_web_session_text_rejects_non_web_session_binding() -> None:
    binding = _binding(connector_name="whatsapp_business")

    with pytest.raises(RuntimeError, match="whatsapp_web_session_connector_mismatch"):
        whatsapp_web_session_delivery.send_whatsapp_web_session_text(
            tool_runtime=None,
            principal_id="principal-wa-web-1",
            recipient="4368120864006",
            text="wrong connector",
            binding=binding,
        )


def test_send_whatsapp_web_session_text_requires_session_ref() -> None:
    binding = _binding(auth_metadata_json={"session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages"})

    with pytest.raises(RuntimeError, match="whatsapp_web_session_ref_missing"):
        whatsapp_web_session_delivery.send_whatsapp_web_session_text(
            tool_runtime=None,
            principal_id="principal-wa-web-1",
            recipient="4368120864006",
            text="missing session",
            binding=binding,
        )


def test_send_whatsapp_web_session_text_requires_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding(auth_metadata_json={"session_ref": "session-principal"})
    monkeypatch.delenv("EA_WHATSAPP_WEB_SESSION_SEND_URL_TEMPLATE", raising=False)
    monkeypatch.delenv("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="whatsapp_web_session_endpoint_missing"):
        whatsapp_web_session_delivery.send_whatsapp_web_session_text(
            tool_runtime=None,
            principal_id="principal-wa-web-1",
            recipient="4368120864006",
            text="missing endpoint",
            binding=binding,
        )
