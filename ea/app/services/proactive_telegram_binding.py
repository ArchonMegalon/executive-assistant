from __future__ import annotations

import json
import os
import time
from typing import Any
import urllib.parse
import urllib.request

from app.services import google_oauth as google_oauth_service

_CHAT_VALIDATION_CACHE: dict[tuple[str, str], tuple[float, bool]] = {}


def resolve_proactive_telegram_target(*, principal_id: str) -> dict[str, str]:
    explicit_chat_id = str(
        os.getenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID")
        or os.getenv("EA_TELEGRAM_DEFAULT_CHAT_ID")
        or ""
    ).strip()
    if explicit_chat_id:
        return {
            "chat_id": explicit_chat_id,
            "bot_key": "default",
            "connector_name": "env_telegram_fallback",
            "principal_id": "",
            "source": "env",
        }

    ranked_rows = _ranked_proactive_telegram_rows(principal_id=principal_id)
    if ranked_rows:
        top_row = ranked_rows[0]
        return {
            "chat_id": str(top_row.get("chat_id") or "").strip(),
            "bot_key": str(top_row.get("bot_key") or "default").strip() or "default",
            "connector_name": str(top_row.get("connector_name") or "").strip(),
            "principal_id": str(top_row.get("principal_id") or "").strip(),
            "source": "connector_binding",
        }
    return {
        "chat_id": "",
        "bot_key": "",
        "connector_name": "",
        "principal_id": "",
        "source": "",
    }


def resolve_proactive_telegram_chat_id(*, principal_id: str) -> str:
    return str(resolve_proactive_telegram_target(principal_id=principal_id).get("chat_id") or "").strip()


def proactive_telegram_ready(*, principal_id: str) -> bool:
    target = resolve_proactive_telegram_target(principal_id=principal_id)
    chat_id = str(target.get("chat_id") or "").strip()
    if not chat_id:
        return False
    token = _telegram_bot_token(str(target.get("bot_key") or "").strip() or "default")
    return bool(token)


def _candidate_principal_ids(principal_id: str) -> list[str]:
    candidates = list(
        google_oauth_service._principal_alias_candidates(
            container=None,
            principal_ids=(
                str(principal_id or "").strip(),
                str(os.getenv("EA_PROACTIVE_OODA_PRINCIPAL_ID") or "").strip(),
                str(os.getenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID") or "").strip(),
                str(os.getenv("EA_DEFAULT_PRINCIPAL_ID") or "").strip(),
            ),
            include_local_user=True,
        )
    )
    return [candidate for candidate in candidates if str(candidate or "").strip()]


def _ranked_proactive_telegram_rows(*, principal_id: str) -> list[dict[str, str]]:
    principals = _candidate_principal_ids(principal_id)
    rows = _query_proactive_telegram_binding_rows(principals)
    principal_priority = {candidate: index for index, candidate in enumerate(principals)}
    ranked_rows: list[tuple[tuple[int, int, int, str], dict[str, str]]] = []
    for row_principal_id, connector_name, external_ref, metadata, updated_at, created_at in rows:
        chat_id = _chat_id_from_row(external_ref=external_ref, metadata=metadata)
        if not chat_id:
            continue
        metadata_dict = metadata if isinstance(metadata, dict) else {}
        ranked_rows.append(
            (
                _chat_sort_key(
                    chat_id=chat_id,
                    connector_name=str(connector_name or "").strip(),
                    principal_priority=principal_priority.get(str(row_principal_id or "").strip(), len(principals)),
                    updated_at=str(updated_at or created_at or "").strip(),
                ),
                {
                    "chat_id": chat_id,
                    "bot_key": str(metadata_dict.get("bot_key") or "default").strip() or "default",
                    "connector_name": str(connector_name or "").strip(),
                    "principal_id": str(row_principal_id or "").strip(),
                    "updated_at": str(updated_at or created_at or "").strip(),
                },
            )
        )
    ranked_rows.sort(key=lambda item: item[0], reverse=True)
    resolved_rows = [dict(row) for _sort_key, row in ranked_rows]
    if len(resolved_rows) <= 1:
        return resolved_rows
    reachable_rows: list[dict[str, str]] = []
    fallback_rows: list[dict[str, str]] = []
    for row in resolved_rows:
        token = _telegram_bot_token(str(row.get("bot_key") or "").strip() or "default")
        if token and _telegram_chat_reachable(chat_id=str(row.get("chat_id") or "").strip(), token=token):
            reachable_rows.append(row)
        else:
            fallback_rows.append(row)
    return [*reachable_rows, *fallback_rows] if reachable_rows else resolved_rows


def _query_proactive_telegram_binding_rows(
    principals: list[str],
) -> list[tuple[object, object, object, object, object, object]]:
    database_url = str(os.getenv("DATABASE_URL") or "").strip()
    if not database_url or not principals:
        return []
    try:
        import psycopg
    except Exception:
        return []
    try:
        with psycopg.connect(database_url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select principal_id, connector_name, external_account_ref, auth_metadata_json, updated_at, created_at
                    from connector_bindings
                    where connector_name in ('telegram_identity', 'telegram_official_bot')
                      and status = 'enabled'
                      and principal_id = any(%s)
                    order by updated_at desc nulls last, created_at desc nulls last
                    limit 20
                    """,
                    (principals,),
                )
                rows = cursor.fetchall()
    except Exception:
        return []
    return list(rows)


def _chat_id_from_row(*, external_ref: Any, metadata: Any) -> str:
    if isinstance(metadata, dict):
        for key in ("default_chat_ref", "chat_id", "chat_ref"):
            candidate = str(metadata.get(key) or "").strip()
            if _looks_like_chat_id(candidate):
                return candidate
    candidate = str(external_ref or "").strip()
    return candidate if _looks_like_chat_id(candidate) else ""


def _chat_sort_key(*, chat_id: str, connector_name: str, principal_priority: int, updated_at: str) -> tuple[int, int, int, int, str]:
    stripped = chat_id[1:] if chat_id.startswith("-") else chat_id
    numeric = 1 if stripped.isdigit() else 0
    plausible_numeric = 1 if numeric and int(stripped) > 1000 else 0
    connector_priority = 1 if str(connector_name or "").strip() == "telegram_identity" else 0
    return (plausible_numeric, numeric, connector_priority, -principal_priority, str(updated_at or ""))


def _looks_like_chat_id(value: str) -> bool:
    if not value:
        return False
    stripped = value[1:] if value.startswith("-") else value
    return stripped.isdigit() and len(stripped) >= 5


def _telegram_chat_reachable(*, chat_id: str, token: str) -> bool:
    normalized_chat_id = str(chat_id or "").strip()
    normalized_token = str(token or "").strip()
    if not normalized_chat_id or not normalized_token:
        return False
    cache_key = (normalized_chat_id, normalized_token)
    now = time.time()
    cached = _CHAT_VALIDATION_CACHE.get(cache_key)
    ttl_seconds = _telegram_chat_validation_ttl_seconds()
    if cached is not None and now - cached[0] <= ttl_seconds:
        return bool(cached[1])
    reachable = False
    try:
        encoded_chat_id = urllib.parse.quote(normalized_chat_id, safe="")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{normalized_token}/getChat?chat_id={encoded_chat_id}",
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        reachable = bool(payload.get("ok"))
    except Exception:
        reachable = False
    _CHAT_VALIDATION_CACHE[cache_key] = (now, reachable)
    return reachable


def _telegram_chat_validation_ttl_seconds() -> float:
    raw = str(os.getenv("EA_TELEGRAM_CHAT_VALIDATION_TTL_SECONDS") or "300").strip()
    try:
        return max(float(raw or "300"), 0.0)
    except Exception:
        return 300.0


def _telegram_bot_token(bot_key: str) -> str:
    normalized_key = str(bot_key or "default").strip() or "default"
    raw_registry = str(os.getenv("EA_TELEGRAM_BOT_REGISTRY_JSON") or "").strip()
    if raw_registry:
        try:
            parsed = json.loads(raw_registry)
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            row = parsed.get(normalized_key)
            if isinstance(row, dict):
                token = str(row.get("token") or "").strip()
                if token:
                    return token
    if normalized_key == "default":
        return str(os.getenv("EA_TELEGRAM_BOT_TOKEN") or "").strip()
    return ""
