from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.api.routes import channels
from app.services.telegram_session_service import TelegramTurnContext


def _ctx(text: str) -> TelegramTurnContext:
    normalized = str(text or "").strip()
    lower = normalized.lower()
    return TelegramTurnContext(
        container=SimpleNamespace(),
        principal_id="principal-1",
        text=normalized,
        payload={},
        current_message_id="msg-1",
        chat_id="chat-1",
        normalized=normalized,
        lower=lower,
        alpha_words=tuple(part for part in lower.split() if part),
    )


def test_meta_assistant_reply_no_longer_advertises_property_scouting() -> None:
    reply = channels._telegram_meta_assistant_reply_text("what can you do")

    assert reply == "I can help with schedule, inbox, links, and grounded EA follow-ups. Ask directly."
    assert "property" not in reply.lower()


def test_property_link_turn_returns_product_boundary_reply() -> None:
    with patch.object(channels, "_telegram_supported_property_link", return_value="https://example.com/listing"):
        decision = channels._telegram_link_turn_decision(_ctx("https://example.com/listing"))

    assert decision.reply_text == channels._telegram_property_boundary_reply_text()
    assert decision.schedule_async is False


def test_scout_update_turn_returns_product_boundary_reply() -> None:
    decision = channels._telegram_scout_update_turn_decision(_ctx("/scout_update https://example.com/listing"))

    assert decision.reply_text == channels._telegram_property_boundary_reply_text()
    assert decision.schedule_async is False


def test_property_pdf_turn_returns_product_boundary_reply() -> None:
    with patch.object(channels, "_telegram_property_pdf_document_payload", return_value={"source_pdf_filename": "listing.pdf"}):
        decision = channels._telegram_property_pdf_turn_decision(_ctx("listing.pdf"))

    assert decision.reply_text == channels._telegram_property_boundary_reply_text()
    assert decision.schedule_async is False
