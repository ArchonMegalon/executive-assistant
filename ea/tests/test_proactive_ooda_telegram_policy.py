from __future__ import annotations

from app.services.proactive_ooda_telegram_policy import (
    approval_request_needs_telegram_user_action,
    telegram_ooda_text_is_internal_noise,
)


def test_flat_search_text_is_internal_noise() -> None:
    assert telegram_ooda_text_is_internal_noise("flat search disabled")
    assert telegram_ooda_text_is_internal_noise("flat_provider_search_blocked:flat_search_disabled")
    assert telegram_ooda_text_is_internal_noise("I suppressed flat search flow for safety")


def test_low_value_research_prompt_is_not_telegram_user_action() -> None:
    assert not approval_request_needs_telegram_user_action(
        {
            "packet_ref": "packet:research",
            "staged_artifact_ref": "artifact:research",
            "approval_prompt": (
                "Approve whether EA should research further or change constraints. "
                "Research, compare, or draft only; require explicit approval before purchase, booking, "
                "cancellation, sending, posting, or commitment."
            ),
        }
    )


def test_reversible_executable_draft_prompt_is_telegram_user_action() -> None:
    assert approval_request_needs_telegram_user_action(
        {
            "packet_ref": "packet:draft",
            "staged_artifact_ref": "artifact:draft",
            "approval_prompt": "Approve whether EA should keep this saved Gmail draft as the chosen next step.",
            "approved_execution_mode": "record_outcome_only",
            "approved_action": "save_gmail_draft",
        }
    )
