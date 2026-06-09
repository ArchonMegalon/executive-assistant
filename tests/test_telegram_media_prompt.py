from __future__ import annotations

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
