from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.api.routes import channels


class _FakeChannelRuntime:
    def __init__(self, rows: list[SimpleNamespace] | None = None) -> None:
        self.rows = list(rows or [])

    def list_recent_observations(self, limit: int = 50, *, principal_id: str | None = None) -> list[SimpleNamespace]:
        return list(self.rows)[:limit]

    def ingest_observation(
        self,
        principal_id: str,
        channel: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        *,
        source_id: str = "",
        external_id: str = "",
        dedupe_key: str = "",
        **_: object,
    ) -> SimpleNamespace:
        row = SimpleNamespace(
            principal_id=principal_id,
            channel=channel,
            event_type=event_type,
            payload=dict(payload or {}),
            source_id=source_id,
            external_id=external_id,
            dedupe_key=dedupe_key,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.rows.insert(0, row)
        return row


def _pairing_prompt(chat_id: str = "42") -> SimpleNamespace:
    return SimpleNamespace(
        principal_id="principal",
        channel="telegram",
        event_type="telegram.reply_sent",
        payload={
            "chat_id": chat_id,
            "reply_text": (
                "EA WhatsApp Web pairing is required. session=tibor-wa-web status=qr_required "
                "qr_age_seconds=10 pair_url=http://127.0.0.1:8098/sessions/tibor-wa-web/pair "
                "pair_url_scope=host_local"
            ),
        },
        source_id=f"telegram:{chat_id}",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _message(text: str, *, chat_id: str = "42", message_id: str = "101", kind: str = "text") -> SimpleNamespace:
    return SimpleNamespace(
        principal_id="principal",
        channel="telegram",
        event_type="telegram.message",
        payload={"chat_id": chat_id, "text": text, "kind": kind, "message_id": message_id},
        source_id=f"telegram:{chat_id}",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def test_whatsapp_pairing_retry_later_followup_is_not_treated_as_generic_task() -> None:
    runtime = _FakeChannelRuntime([_pairing_prompt()])
    container = SimpleNamespace(channel_runtime=runtime)

    decision = channels._telegram_session_turn(
        container=container,
        principal_id="principal",
        text="couldnt link device try again later",
        payload={"kind": "text", "text": "couldnt link device try again later"},
        bot_handle="",
        current_message_id="101",
        chat_id="42",
        dedupe_key="telegram:42:101",
    )

    assert decision.reply_text == ""
    assert decision.schedule_async is False
    suppressed = [row for row in runtime.rows if row.event_type == "telegram.reply_suppressed"]
    assert len(suppressed) == 1
    assert suppressed[0].payload["reason"] == "whatsapp_pairing_followup_retry_later"
    assert suppressed[0].payload["user_action_required"] is False
    assert suppressed[0].payload["next_operator_action"] == "retry_whatsapp_pairing_prompt_after_cooldown"


def test_media_only_updates_after_pairing_retry_later_do_not_create_extra_acks() -> None:
    runtime = _FakeChannelRuntime(
        [
            _message("couldnt link device try again later", message_id="101"),
            _pairing_prompt(),
        ]
    )
    container = SimpleNamespace(channel_runtime=runtime)

    decision = channels._telegram_session_turn(
        container=container,
        principal_id="principal",
        text="Photo",
        payload={"kind": "photo", "text": "Photo", "message_id": "102"},
        bot_handle="",
        current_message_id="102",
        chat_id="42",
        dedupe_key="telegram:42:102",
    )

    assert decision.reply_text == ""
    assert decision.schedule_async is False
    suppressed = [row for row in runtime.rows if row.event_type == "telegram.reply_suppressed"]
    assert len(suppressed) == 1
    assert suppressed[0].payload["source_kind"] == "photo"
    assert suppressed[0].dedupe_key == "telegram:42:102:whatsapp_pairing_followup_suppressed"
