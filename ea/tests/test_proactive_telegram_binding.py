from __future__ import annotations

import json

from app.services import proactive_ooda_delivery, proactive_telegram_binding


def test_resolve_proactive_telegram_target_includes_proactive_default_principal(monkeypatch: object) -> None:
    captured: list[str] = []

    def _rows(principals: list[str]):  # type: ignore[no-untyped-def]
        captured.extend(principals)
        return [
            (
                "principal-default",
                "telegram_identity",
                "123456",
                {"default_chat_ref": "123456", "bot_key": "ops"},
                "2026-07-02T17:00:00Z",
                "2026-07-02T16:00:00Z",
            )
        ]

    monkeypatch.setenv("EA_PROACTIVE_OODA_PRINCIPAL_ID", "principal-default")
    monkeypatch.setattr(proactive_telegram_binding, "_query_proactive_telegram_binding_rows", _rows)

    target = proactive_telegram_binding.resolve_proactive_telegram_target(
        principal_id="cf-email:tibor.girschele@gmail.com"
    )

    assert target["chat_id"] == "123456"
    assert target["bot_key"] == "ops"
    assert "principal-default" in captured


def test_proactive_telegram_ready_uses_registry_token_for_bound_bot_key(monkeypatch: object) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("EA_TELEGRAM_BOT_REGISTRY_JSON", json.dumps({"ops": {"token": "bot-token-ops"}}))
    monkeypatch.setattr(
        proactive_telegram_binding,
        "_query_proactive_telegram_binding_rows",
        lambda principals: [
            (
                "principal-default",
                "telegram_identity",
                "123456",
                {"default_chat_ref": "123456", "bot_key": "ops"},
                "2026-07-02T17:00:00Z",
                "2026-07-02T16:00:00Z",
            )
        ],
    )

    assert proactive_telegram_binding.proactive_telegram_ready(principal_id="principal-default") is True


def test_telegram_route_status_uses_db_bound_target_without_tool_runtime(monkeypatch: object) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("EA_TELEGRAM_BOT_REGISTRY_JSON", json.dumps({"ops": {"token": "bot-token-ops"}}))
    monkeypatch.setattr(
        proactive_telegram_binding,
        "_query_proactive_telegram_binding_rows",
        lambda principals: [
            (
                "principal-default",
                "telegram_identity",
                "123456",
                {"default_chat_ref": "123456", "bot_key": "ops"},
                "2026-07-02T17:00:00Z",
                "2026-07-02T16:00:00Z",
            )
        ],
    )

    status = proactive_ooda_delivery._telegram_route_status(
        principal_id="principal-default",
        tool_runtime=None,
    )

    assert status.ready is True
    assert status.selected_channel == "telegram"
    assert status.selected_by == "env_telegram_fallback"
    assert bool(status.recipient_ref_hash) is True


def test_send_telegram_message_from_env_uses_registry_token_for_bound_bot_key(monkeypatch: object) -> None:
    monkeypatch.delenv("EA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("EA_TELEGRAM_BOT_REGISTRY_JSON", json.dumps({"ops": {"token": "bot-token-ops"}}))
    monkeypatch.setattr(
        proactive_telegram_binding,
        "_query_proactive_telegram_binding_rows",
        lambda principals: [
            (
                "principal-default",
                "telegram_identity",
                "123456",
                {"default_chat_ref": "123456", "bot_key": "ops"},
                "2026-07-02T17:00:00Z",
                "2026-07-02T16:00:00Z",
            )
        ],
    )
    sent: dict[str, object] = {}

    def _send_json(*, token: str, method: str, payload: dict[str, object], timeout: int = 30) -> dict[str, object]:
        sent.update({"token": token, "method": method, "payload": dict(payload), "timeout": timeout})
        return {"message_id": "42"}

    monkeypatch.setattr(proactive_ooda_delivery, "_telegram_send_json", _send_json)

    receipt = proactive_ooda_delivery._send_telegram_message_from_env(
        principal_id="principal-default",
        text="Action needed.",
    )

    assert sent["token"] == "bot-token-ops"
    assert sent["method"] == "sendMessage"
    assert dict(sent["payload"])["chat_id"] == "123456"
    assert receipt["message_id"] == "42"
