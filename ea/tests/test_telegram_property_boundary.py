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


def test_command_replies_no_longer_advertise_property_features() -> None:
    start_reply = channels._telegram_command_turn_decision(_ctx("/start")).reply_text
    help_reply = channels._telegram_command_turn_decision(_ctx("/help")).reply_text
    status_reply = channels._telegram_command_turn_decision(_ctx("/status")).reply_text

    assert "property" not in start_reply.lower()
    assert "property" not in help_reply.lower()
    assert "/scout_update" not in help_reply.lower()
    assert "property" not in status_reply.lower()


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


def test_build_active_object_map_ignores_property_brief_items() -> None:
    property_brief = SimpleNamespace(
        title="2 Zimmer Wohnung in 1200 Wien",
        object_ref="willhaben:listing-123",
        why_now="High fit.",
        recommended_action="Compare it.",
        score=91.0,
        evidence_refs=(),
        profile_followup_refs=("profile:property",),
    )

    active_object_map = channels._telegram_build_active_object_map([property_brief], [])

    assert active_object_map == {}


def test_recent_persisted_property_memory_is_stripped_from_telegram_context() -> None:
    row = SimpleNamespace(
        channel="telegram",
        event_type="telegram.reply_sent",
        created_at="2026-07-02T10:00:00Z",
        observation_id="obs-1",
        payload={
            "active_object_map": {
                "active_property_candidate": "Wohnung | willhaben:listing-123",
                "active_queue_item": "Call electrician | queue-1",
            },
            "comparison_state": {
                "comparison_pair": "Wohnung A || Wohnung B",
                "comparison_primary": "Wohnung A",
            },
            "intent_state": {
                "active_intent": "property_review",
                "active_profile_themes": "profile:property",
            },
        },
    )
    container = SimpleNamespace(
        channel_runtime=SimpleNamespace(
            list_recent_observations=lambda **kwargs: [row],
        )
    )

    assert channels._telegram_recent_persisted_object_map(container, principal_id="principal-1") == {
        "active_queue_item": "Call electrician | queue-1",
    }
    assert channels._telegram_recent_persisted_comparison_state(container, principal_id="principal-1") == {}
    assert channels._telegram_recent_persisted_intent_state(container, principal_id="principal-1") == {}
