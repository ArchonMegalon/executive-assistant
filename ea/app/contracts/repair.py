from __future__ import annotations

from app.supervisor import trigger_mum_brain


def open_repair_incident(
    *,
    db_conn,
    error_message: str,
    fallback_mode: str = "simplified-first",
    failure_class: str = "system_error",
    intent: str = "unknown",
    chat_id: str = "system",
) -> str:
    """Contract adapter for supervised fallback/repair escalation."""
    return trigger_mum_brain(
        db_conn,
        str(error_message),
        fallback_mode=str(fallback_mode),
        failure_class=str(failure_class),
        intent=str(intent),
        chat_id=str(chat_id),
    )

