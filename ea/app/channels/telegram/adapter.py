from __future__ import annotations


class TelegramObservationAdapter:
    """Converts raw Telegram webhook/poll payloads into generic observation fields."""

    channel = "telegram"

    def to_observation_fields(self, update: dict[str, object]) -> dict[str, object]:
        msg = update.get("message") if isinstance(update, dict) else None
        if not isinstance(msg, dict):
            return {
                "chat_id": "",
                "event_type": "telegram.update",
                "payload": dict(update if isinstance(update, dict) else {}),
                "source_id": "telegram",
                "external_id": "",
                "dedupe_key": "",
            }
        chat = msg.get("chat")
        chat_id = ""
        if isinstance(chat, dict):
            chat_id = str(chat.get("id") or "")
        text = str(msg.get("text") or "")
        message_id = str(msg.get("message_id") or "").strip()
        return {
            "chat_id": chat_id,
            "event_type": "telegram.message",
            "source_id": f"telegram:{chat_id}" if chat_id else "telegram",
            "external_id": message_id,
            "dedupe_key": f"telegram:{chat_id}:{message_id}" if chat_id and message_id else "",
            "payload": {
                "text": text,
                "message_id": msg.get("message_id"),
                "date": msg.get("date"),
                "raw": update,
            },
        }
