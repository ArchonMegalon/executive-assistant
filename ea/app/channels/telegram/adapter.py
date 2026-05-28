from __future__ import annotations


class TelegramObservationAdapter:
    """Converts raw Telegram webhook/poll payloads into generic observation fields."""

    channel = "telegram"

    @staticmethod
    def _message_text_and_kind(msg: dict[str, object]) -> tuple[str, str, dict[str, object]]:
        text = str(msg.get("text") or msg.get("caption") or "")
        metadata: dict[str, object] = {}
        if text:
            return text, "text", metadata
        if isinstance(msg.get("voice"), dict):
            voice = dict(msg.get("voice") or {})
            metadata["file_id"] = voice.get("file_id")
            metadata["duration"] = voice.get("duration")
            return "Voice Message", "voice", metadata
        if isinstance(msg.get("audio"), dict):
            audio = dict(msg.get("audio") or {})
            metadata["file_id"] = audio.get("file_id")
            metadata["duration"] = audio.get("duration")
            metadata["file_name"] = audio.get("file_name")
            return "Audio Message", "audio", metadata
        if isinstance(msg.get("photo"), list) and msg.get("photo"):
            photos = list(msg.get("photo") or [])
            last = dict(photos[-1] or {}) if photos else {}
            metadata["file_id"] = last.get("file_id")
            return "Photo", "photo", metadata
        if isinstance(msg.get("video"), dict):
            video = dict(msg.get("video") or {})
            metadata["file_id"] = video.get("file_id")
            metadata["duration"] = video.get("duration")
            return "Video Message", "video", metadata
        if isinstance(msg.get("document"), dict):
            document = dict(msg.get("document") or {})
            filename = str(document.get("file_name") or "").strip()
            metadata["file_id"] = document.get("file_id")
            metadata["file_name"] = filename
            return (f"Document: {filename}" if filename else "Document"), "document", metadata
        return "", "unknown", metadata

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
        text, message_kind, message_metadata = self._message_text_and_kind(msg)
        message_id = str(msg.get("message_id") or "").strip()
        return {
            "chat_id": chat_id,
            "event_type": "telegram.message",
            "source_id": f"telegram:{chat_id}" if chat_id else "telegram",
            "external_id": message_id,
            "dedupe_key": f"telegram:{chat_id}:{message_id}" if chat_id and message_id else "",
            "payload": {
                "text": text,
                "kind": message_kind,
                "message_metadata": message_metadata,
                "message_id": msg.get("message_id"),
                "date": msg.get("date"),
                "raw": update,
            },
        }
