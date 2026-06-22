from __future__ import annotations

from types import SimpleNamespace

from app.services import whatsapp_web_session_readiness


def _binding(**overrides: object) -> SimpleNamespace:
    values = {
        "binding_id": "wa-web-binding-1",
        "principal_id": "principal-wa-web-1",
        "connector_name": "whatsapp_web_session",
        "external_account_ref": "+15550101000",
        "scope_json": {
            "scopes": ["whatsapp.send"],
            "service_routes": {"applies_to": ["connector.dispatch", "executive_assistant_channel_send"]},
        },
        "auth_metadata_json": {
            "session_ref": "session-principal",
            "session_store_ref": "vault://ea/whatsapp-web/session-principal",
            "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages",
            "session_status_url_template": "https://wa-web.test/sessions/{session_ref}/status",
            "session_api_token": "session-token",
        },
        "status": "enabled",
        "created_at": "2026-06-21T00:00:00Z",
        "updated_at": "2026-06-21T00:00:00Z",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_readiness_reports_ready_for_complete_enabled_binding() -> None:
    readiness = whatsapp_web_session_readiness.check_whatsapp_web_session_readiness(
        tool_runtime=None,
        principal_id="principal-wa-web-1",
        binding=_binding(),
    )

    assert readiness.ready is True
    assert readiness.reason == "ready"
    assert readiness.binding_id == "wa-web-binding-1"
    assert readiness.session_ref_present is True
    assert readiness.session_store_ref_present is True
    assert readiness.endpoint_present is True
    assert readiness.token_present is True
    assert readiness.service_routes == ("connector.dispatch", "executive_assistant_channel_send")
    assert readiness.as_dict()["ready"] is True


def test_readiness_reports_missing_binding() -> None:
    tool_runtime = SimpleNamespace(get_connector_binding=lambda binding_id: None)

    readiness = whatsapp_web_session_readiness.check_whatsapp_web_session_readiness(
        tool_runtime=tool_runtime,
        principal_id="principal-wa-web-1",
        binding_id="missing",
    )

    assert readiness.ready is False
    assert readiness.reason == "binding_not_found"


def test_readiness_rejects_wrong_connector() -> None:
    readiness = whatsapp_web_session_readiness.check_whatsapp_web_session_readiness(
        tool_runtime=None,
        principal_id="principal-wa-web-1",
        binding=_binding(connector_name="whatsapp_business"),
    )

    assert readiness.ready is False
    assert readiness.reason == "connector_mismatch"


def test_readiness_requires_enabled_status() -> None:
    readiness = whatsapp_web_session_readiness.check_whatsapp_web_session_readiness(
        tool_runtime=None,
        principal_id="principal-wa-web-1",
        binding=_binding(status="staged"),
    )

    assert readiness.ready is False
    assert readiness.reason == "binding_disabled"


def test_readiness_requires_session_store_ref() -> None:
    readiness = whatsapp_web_session_readiness.check_whatsapp_web_session_readiness(
        tool_runtime=None,
        principal_id="principal-wa-web-1",
        binding=_binding(auth_metadata_json={
            "session_ref": "session-principal",
            "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages",
        }),
    )

    assert readiness.ready is False
    assert readiness.reason == "session_store_ref_missing"


def test_readiness_probe_reports_probe_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        whatsapp_web_session_readiness,
        "_probe_session_status_url",
        lambda **_: {"ok": False, "reason": "qr_required"},
    )

    readiness = whatsapp_web_session_readiness.check_whatsapp_web_session_readiness(
        tool_runtime=None,
        principal_id="principal-wa-web-1",
        binding=_binding(),
        probe_session=True,
    )

    assert readiness.ready is False
    assert readiness.reason == "probe_failed"
    assert readiness.probe_reason == "qr_required"


def test_readiness_probe_reports_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        whatsapp_web_session_readiness,
        "_probe_session_status_url",
        lambda **_: {"ok": True, "reason": "ready"},
    )

    readiness = whatsapp_web_session_readiness.check_whatsapp_web_session_readiness(
        tool_runtime=None,
        principal_id="principal-wa-web-1",
        binding=_binding(),
        probe_session=True,
    )

    assert readiness.ready is True
    assert readiness.reason == "ready"
    assert readiness.probe_reason == "ready"
