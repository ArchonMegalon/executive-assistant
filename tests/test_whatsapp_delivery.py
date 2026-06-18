from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.models import ConnectorBinding
from app.services import whatsapp_delivery


def test_send_whatsapp_text_uses_binding_credentials_and_normalizes_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = ConnectorBinding(
        binding_id="binding-1",
        principal_id="principal-whatsapp-1",
        connector_name="whatsapp_export",
        external_account_ref="acc-ref-1",
        scope_json={},
        auth_metadata_json={
            "access_token": "bind-token",
            "phone_number_id": "91112222333",
        },
        status="enabled",
        created_at="2026-03-30T00:00:00Z",
        updated_at="2026-03-30T00:00:00Z",
    )
    tool_runtime = SimpleNamespace(get_connector_binding=lambda binding_id: binding if binding_id == "binding-1" else None)
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
                "payload": dict(payload),
                "token": token,
                "auth_header_name": auth_header_name,
                "auth_header_prefix": auth_header_prefix,
                "timeout": timeout,
            }
        )
        return {"messages": [{"id": "msg-1"}, "msg-2"]}

    monkeypatch.setattr(whatsapp_delivery, "_send_whatsapp_http_request", _fake_send_request)
    monkeypatch.setenv("EA_WHATSAPP_REQUEST_TIMEOUT_SECONDS", "11.5")

    receipt = whatsapp_delivery.send_whatsapp_text(
        tool_runtime=tool_runtime,
        principal_id="principal-whatsapp-1",
        recipient="+43 111 222 33",
        text="Hallo, ich denke an dich.",
        binding_id="binding-1",
    )

    assert receipt.recipient == "4311122233"
    assert receipt.principal_id == "principal-whatsapp-1"
    assert receipt.binding_id == "binding-1"
    assert receipt.connector_name == "whatsapp_export"
    assert receipt.binding_status == "enabled"
    assert receipt.message_ids == ("msg-1", "msg-2")
    assert captured["request_url"] == "https://graph.facebook.com/v20.0/91112222333/messages"
    assert captured["payload"]["to"] == "4311122233"
    assert captured["payload"]["text"] == {"body": "Hallo, ich denke an dich."}
    assert captured["payload"]["recipient_type"] == "individual"
    assert captured["token"] == "bind-token"
    assert captured["auth_header_name"] == "Authorization"
    assert captured["auth_header_prefix"] == "Bearer "
    assert captured["timeout"] == 11.5


def test_send_whatsapp_text_fails_when_binding_lacks_phone_id(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = ConnectorBinding(
        binding_id="binding-2",
        principal_id="principal-whatsapp-2",
        connector_name="whatsapp_export",
        external_account_ref="",
        scope_json={},
        auth_metadata_json={"access_token": "bind-token"},
        status="enabled",
        created_at="2026-03-30T00:00:00Z",
        updated_at="2026-03-30T00:00:00Z",
    )
    tool_runtime = SimpleNamespace(
        get_connector_binding=lambda binding_id: binding if binding_id == "binding-2" else None,
        list_connector_bindings=lambda principal_id, limit=200: [binding],
    )

    with pytest.raises(RuntimeError, match="whatsapp_phone_id_missing"):
        whatsapp_delivery.send_whatsapp_text(
            tool_runtime=tool_runtime,
            principal_id="principal-whatsapp-2",
            recipient="+49 555 9999",
            text="Noch etwas.",
            binding_id="binding-2",
        )


def test_send_whatsapp_text_fails_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_runtime = SimpleNamespace(
        get_connector_binding=lambda binding_id: None,
        list_connector_bindings=lambda principal_id, limit=200: [],
    )
    monkeypatch.delenv("EA_WHATSAPP_CREDENTIAL_REGISTRY_JSON", raising=False)
    monkeypatch.delenv("EA_WHATSAPP_DEFAULT_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("EA_WHATSAPP_DEFAULT_PHONE_NUMBER_ID", raising=False)

    with pytest.raises(RuntimeError, match="whatsapp_delivery_config_missing"):
        whatsapp_delivery.send_whatsapp_text(
            tool_runtime=tool_runtime,
            principal_id="principal-whatsapp-3",
            recipient="+41 555 4444",
            text="Ein Versuch.",
        )
