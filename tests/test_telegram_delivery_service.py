from __future__ import annotations

import json

from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.telegram_delivery import _chunk_telegram_text, send_telegram_message_for_principal
from app.services.tool_runtime import ToolRuntimeService


def _tool_runtime() -> ToolRuntimeService:
    return ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )


def test_chunk_telegram_text_splits_long_messages() -> None:
    text = ("alpha " * 900).strip()
    chunks = _chunk_telegram_text(text)
    assert len(chunks) >= 2
    assert all(len(chunk) <= 4000 for chunk in chunks)


def test_send_telegram_message_for_principal_uses_bound_chat(monkeypatch) -> None:
    runtime = _tool_runtime()
    runtime.upsert_connector_binding(
        principal_id="exec-telegram-send",
        connector_name="telegram_identity",
        external_account_ref="42",
        auth_metadata_json={"default_chat_ref": "42", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )

    sent: list[dict[str, object]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 7}}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        sent.append(
            {
                "url": request.full_url,
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_delivery.urllib.request.urlopen", _fake_urlopen)
    receipt = send_telegram_message_for_principal(runtime, principal_id="exec-telegram-send", text="Hello from EA")
    assert receipt.chat_id == "42"
    assert receipt.bot_key == "default"
    assert receipt.message_ids == ("7",)
    assert sent and sent[0]["payload"]["chat_id"] == "42"
    assert sent[0]["payload"]["text"] == "Hello from EA"
