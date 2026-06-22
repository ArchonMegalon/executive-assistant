from __future__ import annotations

import os
from typing import Any


def resolve_proactive_telegram_chat_id(*, principal_id: str) -> str:
    explicit = str(os.getenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID") or os.getenv("EA_TELEGRAM_DEFAULT_CHAT_ID") or "").strip()
    if explicit:
        return explicit
    database_url = str(os.getenv("DATABASE_URL") or "").strip()
    if not database_url:
        return ""
    try:
        import psycopg
    except Exception:
        return ""
    principals = _candidate_principal_ids(principal_id)
    try:
        with psycopg.connect(database_url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select external_account_ref, auth_metadata_json
                    from connector_bindings
                    where connector_name in ('telegram_identity', 'telegram_official_bot')
                      and status = 'enabled'
                      and principal_id = any(%s)
                    order by
                      case when connector_name = 'telegram_identity' then 0 else 1 end,
                      updated_at desc nulls last,
                      created_at desc nulls last
                    limit 5
                    """,
                    (principals,),
                )
                rows = cursor.fetchall()
    except Exception:
        return ""
    for external_ref, metadata in rows:
        chat_id = _chat_id_from_row(external_ref=external_ref, metadata=metadata)
        if chat_id:
            return chat_id
    return ""


def proactive_telegram_ready(*, principal_id: str) -> bool:
    token = str(os.getenv("EA_TELEGRAM_BOT_TOKEN") or "").strip()
    return bool(token and resolve_proactive_telegram_chat_id(principal_id=principal_id))


def _candidate_principal_ids(principal_id: str) -> list[str]:
    ordered: list[str] = []
    for value in (
        principal_id,
        os.getenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID"),
        os.getenv("EA_DEFAULT_PRINCIPAL_ID"),
    ):
        normalized = str(value or "").strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _chat_id_from_row(*, external_ref: Any, metadata: Any) -> str:
    if isinstance(metadata, dict):
        for key in ("default_chat_ref", "chat_id", "chat_ref"):
            candidate = str(metadata.get(key) or "").strip()
            if _looks_like_chat_id(candidate):
                return candidate
    candidate = str(external_ref or "").strip()
    return candidate if _looks_like_chat_id(candidate) else ""


def _looks_like_chat_id(value: str) -> bool:
    if not value:
        return False
    stripped = value[1:] if value.startswith("-") else value
    return stripped.isdigit() and len(stripped) >= 5
