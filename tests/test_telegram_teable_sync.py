from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "sync_telegram_conversations_to_teable.py"


def _module():
    spec = importlib.util.spec_from_file_location("sync_telegram_conversations_to_teable", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_message_fields_cover_telegram_conversation_projection_schema() -> None:
    module = _module()

    field_names = {field["name"] for field in module.MESSAGE_FIELDS}

    assert "projection_id" in field_names
    assert "observation_id" in field_names
    assert "principal_id" in field_names
    assert "event_type" in field_names
    assert "chat_ref" in field_names
    assert "direction" in field_names
    assert "message_kind" in field_names
    assert "body_text" in field_names
    assert "body_present" in field_names
    assert "message_timestamp" in field_names
    assert "event_created_at" in field_names
    assert "synced_at" in field_names
    assert all("notNull" not in field and "unique" not in field for field in module.MESSAGE_FIELDS)


def test_message_rows_from_observations_only_project_conversation_events() -> None:
    module = _module()

    rows = module._message_rows_from_observations(
        [
            {
                "observation_id": "obs-1",
                "principal_id": "principal-1",
                "channel": "telegram",
                "event_type": "telegram.message",
                "payload": {"text": "Hallo", "kind": "text", "date": "1710000000"},
                "created_at": "2026-06-22T10:00:00Z",
                "source_id": "telegram:12345",
                "external_id": "msg-1",
                "dedupe_key": "telegram:12345:msg-1",
            },
            {
                "observation_id": "obs-2",
                "principal_id": "principal-1",
                "channel": "telegram",
                "event_type": "telegram.reply_async_sent",
                "payload": {"chat_id": "12345", "reply_text": "Antwort"},
                "created_at": "2026-06-22T10:00:01Z",
                "source_id": "telegram:12345",
                "external_id": "msg-1",
                "dedupe_key": "msg-1:assistant_async_sent",
            },
            {
                "observation_id": "obs-3",
                "principal_id": "principal-1",
                "channel": "telegram",
                "event_type": "telegram.reply_async_started",
                "payload": {"chat_id": "12345", "prompt_text": "ignored"},
                "created_at": "2026-06-22T10:00:02Z",
                "source_id": "telegram:12345",
                "external_id": "msg-1",
                "dedupe_key": "msg-1:assistant_async_started",
            },
        ]
    )

    assert len(rows) == 2
    inbound = rows[0]
    outbound = rows[1]

    assert inbound["event_type"] == "telegram.message"
    assert inbound["direction"] == "inbound"
    assert inbound["chat_ref"] == "12345"
    assert inbound["body_text"] == "Hallo"
    assert inbound["body_present"] is True
    assert inbound["message_kind"] == "text"
    assert inbound["message_timestamp"] == "1710000000"

    assert outbound["event_type"] == "telegram.reply_async_sent"
    assert outbound["direction"] == "outbound"
    assert outbound["chat_ref"] == "12345"
    assert outbound["body_text"] == "Antwort"
    assert outbound["message_kind"] == "text"
    assert outbound["message_timestamp"] == "2026-06-22T10:00:01Z"


def test_main_compose_declares_telegram_teable_sync_service() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "ea-telegram-teable-sync:" in compose
    assert "container_name: ea-telegram-teable-sync" in compose
    assert "EA_TELEGRAM_TEABLE_SYNC_ENABLED=${EA_TELEGRAM_TEABLE_SYNC_ENABLED:-0}" in compose
    assert "EA_TELEGRAM_TEABLE_SYNC_INTERVAL_SECONDS=${EA_TELEGRAM_TEABLE_SYNC_INTERVAL_SECONDS:-60}" in compose
    assert "EA_TELEGRAM_TEABLE_SYNC_BATCH_SIZE=${EA_TELEGRAM_TEABLE_SYNC_BATCH_SIZE:-500}" in compose
    assert "EA_TELEGRAM_TEABLE_BASE_ID=${EA_TELEGRAM_TEABLE_BASE_ID:-}" in compose
    assert "EA_TELEGRAM_MESSAGES_TEABLE_TABLE_ID=${EA_TELEGRAM_MESSAGES_TEABLE_TABLE_ID:-}" in compose
    assert "EA_TELEGRAM_MESSAGES_TEABLE_TABLE_NAME=${EA_TELEGRAM_MESSAGES_TEABLE_TABLE_NAME:-ea_telegram_conversation_messages}" in compose
    assert "EA_TELEGRAM_TEABLE_SYNC_STATE_FILE=${EA_TELEGRAM_TEABLE_SYNC_STATE_FILE:-/data/telegram-teable-sync/state.json}" in compose
    assert "EA_RESPONSES_PROVIDER_LEDGER_DIR=/data/telegram-teable-sync" in compose
    assert "python /app/scripts/sync_telegram_conversations_to_teable.py || true" in compose
    assert "telegram_teable_sync_idle" in compose
    assert '"host.docker.internal:host-gateway"' in compose
    assert "ea_telegram_teable_sync:/data/telegram-teable-sync" in compose


def test_list_records_paginates_teable_reads(monkeypatch) -> None:
    module = _module()
    seen_paths: list[str] = []

    def _fake_teable_request(**kwargs):
        path = str(kwargs["path"])
        seen_paths.append(path)
        if "skip=0" in path:
            return {"records": [{"id": "rec-1", "fields": {"projection_id": "a"}}] * module.TEABLE_LIST_PAGE_SIZE}
        return {"records": [{"id": "rec-2", "fields": {"projection_id": "b"}}]}

    monkeypatch.setattr(module, "_teable_request", _fake_teable_request)

    rows = module._list_records(base_url="http://teable.test", api_key="token", table_id="tbl", fields=["projection_id"])

    assert len(rows) == module.TEABLE_LIST_PAGE_SIZE + 1
    assert any("skip=0" in path for path in seen_paths)
    assert any(f"skip={module.TEABLE_LIST_PAGE_SIZE}" in path for path in seen_paths)
