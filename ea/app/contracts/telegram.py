from __future__ import annotations

from app.telegram.safety import sanitize_for_telegram, sanitize_telegram_text


def sanitize_user_copy(text: str, *, placeholder: bool = False) -> str:
    """Contract adapter for Telegram-bound user copy."""
    return sanitize_telegram_text(text, placeholder=bool(placeholder))


def sanitize_incident_copy(text: str, *, correlation_id: str | None, mode: str) -> str:
    """Contract adapter for fallback incident-safe user messaging."""
    return sanitize_for_telegram(text, correlation_id=correlation_id, mode=mode)

