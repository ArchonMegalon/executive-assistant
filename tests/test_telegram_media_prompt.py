from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.routes import channels as channels_route


def test_telegram_media_acknowledgement_reply_triggers_for_video_and_document() -> None:
    video_reply = channels_route._telegram_media_acknowledgement_reply(
        {"kind": "video", "text": ""},
        text="",
    )
    assert video_reply == (
        "Got the video. Add one short instruction (summarize it, look for risks, pull key points), "
        "and I will run it in the next assistant step."
    )

    video_caption_reply = channels_route._telegram_media_acknowledgement_reply(
        {"kind": "video", "text": "Meeting notes"},
        text="Meeting notes",
    )
    assert video_caption_reply.startswith("Got the video.")

    document_reply = channels_route._telegram_media_acknowledgement_reply(
        {"kind": "document", "text": "Some PDF"},
        text="Some PDF",
    )
    assert document_reply == (
        "Got the document. Add a short note (extract text, summarize, or flag action items), "
        "and I will proceed."
    )


def test_telegram_media_acknowledgement_reply_keeps_old_text_variants() -> None:
    for text in ("video", "video message", "VIDEO", "Video Message", "  video   message  "):
        normalized_reply = channels_route._telegram_media_acknowledgement_reply(
            {"kind": "video", "text": text},
            text=text,
        )
        assert normalized_reply.startswith("Got the video.")
        assert "and I will run it in the next assistant step." in normalized_reply

    for text in ("document", "  Document  ", "DOC", "Document upload", "My PDF"):
        normalized_reply = channels_route._telegram_media_acknowledgement_reply(
            {"kind": "document", "text": text},
            text=text,
        )
        assert normalized_reply.startswith("Got the document.")
        assert "and I will proceed." in normalized_reply


def test_telegram_media_acknowledgement_reply_ignores_non_media() -> None:
    text_reply = channels_route._telegram_media_acknowledgement_reply({"kind": "photo", "text": ""}, text="")
    assert text_reply == ""


def test_telegram_whatsapp_pairing_followup_suppresses_generic_media_noise() -> None:
    recent_pairing_reply = SimpleNamespace(
        channel="telegram",
        event_type="telegram.reply_sent",
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        payload={
            "chat_id": "chat-1",
            "reply_text": (
                "EA WhatsApp Web pairing is required. session=tibor-wa-web "
                "status=qr_required pair_url=http://127.0.0.1:8098/sessions/tibor-wa-web/pair"
            ),
        },
    )
    container = SimpleNamespace(
        channel_runtime=SimpleNamespace(list_recent_observations=lambda **_kwargs: [recent_pairing_reply])
    )

    text_reply, schedule_async, _retry_budget, _suppress_async_ack = channels_route._telegram_command_reply_text(
        container=container,
        principal_id="exec-1",
        text="couldnt link device try again later",
        payload={"kind": "text", "text": "couldnt link device try again later"},
        bot_handle="",
        chat_id="chat-1",
    )
    assert text_reply == ""
    assert schedule_async is False

    video_reply, schedule_async, _retry_budget, _suppress_async_ack = channels_route._telegram_command_reply_text(
        container=container,
        principal_id="exec-1",
        text="Video Message",
        payload={"kind": "video", "text": "Video Message"},
        bot_handle="",
        chat_id="chat-1",
    )
    assert video_reply == ""
    assert schedule_async is False


def test_telegram_whatsapp_pairing_followup_suppresses_explicit_failure_without_context() -> None:
    container = SimpleNamespace(channel_runtime=SimpleNamespace(list_recent_observations=lambda **_kwargs: []))

    assert channels_route._telegram_strong_whatsapp_pairing_followup_text("couldn't link device try again later")
    assert not channels_route._telegram_strong_whatsapp_pairing_followup_text(
        "couldn't link my Alexa device, can you help?"
    )

    text_reply, schedule_async, _retry_budget, _suppress_async_ack = channels_route._telegram_command_reply_text(
        container=container,
        principal_id="exec-1",
        text="couldn't link device try again later",
        payload={"kind": "text", "text": "couldn't link device try again later"},
        bot_handle="",
        chat_id="chat-1",
    )

    assert text_reply == ""
    assert schedule_async is False


def test_telegram_whatsapp_pairing_recent_failure_suppresses_following_media() -> None:
    recent_failure = SimpleNamespace(
        channel="telegram",
        event_type="telegram.message",
        source_id="telegram:chat-1",
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        payload={"kind": "text", "text": "couldnt link device try again later"},
    )
    container = SimpleNamespace(channel_runtime=SimpleNamespace(list_recent_observations=lambda **_kwargs: [recent_failure]))

    video_reply, schedule_async, _retry_budget, _suppress_async_ack = channels_route._telegram_command_reply_text(
        container=container,
        principal_id="exec-1",
        text="Video Message",
        payload={"kind": "video", "text": "Video Message"},
        bot_handle="",
        chat_id="chat-1",
    )
    assert video_reply == ""
    assert schedule_async is False

    photo_reply, schedule_async, _retry_budget, _suppress_async_ack = channels_route._telegram_command_reply_text(
        container=container,
        principal_id="exec-1",
        text="Photo",
        payload={"kind": "photo", "text": "Photo"},
        bot_handle="",
        chat_id="chat-1",
    )
    assert photo_reply == ""
    assert schedule_async is False
