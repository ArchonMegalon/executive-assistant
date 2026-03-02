from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any

_INVALID_TEMPLATE_RE = re.compile(r"(?i)(invalid template id|source/data/id:\s*invalid template id|template[_ /-]?id)")
_RENDERER_UNAVAILABLE_RE = re.compile(r"(?i)(renderer unavailable|markupgo.*timeout|markupgo.*http\s*5\d\d|markupgo.*temporar|markupgo.*unavailable)")
_BREAKER_OPEN_RE = re.compile(r"(?i)(breaker open|EA render guard: markupgo breaker open)")
_BREAKER_UNTIL = 0.0


def _now() -> float:
    return time.time()


def known_good_template_ids() -> list[str]:
    keys = (
        "EA_MARKUPGO_TEMPLATE_ID_SAFE",
        "EA_MARKUPGO_TEMPLATE_ID_KNOWN_GOOD",
        "MARKUPGO_TEMPLATE_ID_SAFE",
        "MARKUPGO_TEMPLATE_ID_KNOWN_GOOD",
    )
    vals: list[str] = []
    seen: set[str] = set()
    for key in keys:
        value = (os.getenv(key, "") or "").strip()
        if value and value not in seen:
            seen.add(value)
            vals.append(value)
    return vals


def classify_markupgo_error(exc_or_text: Any) -> str:
    text = "" if exc_or_text is None else str(exc_or_text)
    if _BREAKER_OPEN_RE.search(text):
        return "breaker_open"
    if _INVALID_TEMPLATE_RE.search(text):
        return "invalid_template_id"
    if _RENDERER_UNAVAILABLE_RE.search(text):
        return "renderer_unavailable"
    return "unknown"


def markupgo_breaker_open() -> bool:
    return _now() < _BREAKER_UNTIL


def _safe_meta(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return "none"
    if len(text) > 96:
        return text[:93] + "..."
    return text.replace("\n", " ")


def log_render_guard(recipe: str, reason: str, **meta: Any) -> None:
    fields = [
        f"recipe={_safe_meta(recipe)}",
        f"reason={_safe_meta(reason)}",
        f"known_good_ids={len(known_good_template_ids())}",
    ]
    for key, value in meta.items():
        fields.append(f"{key}={_safe_meta(value)}")
    print("[EA RENDER GUARD] " + " ".join(fields))


def open_markupgo_breaker(reason: str, *, skill: str = "markupgo", location: str = "unknown") -> None:
    global _BREAKER_UNTIL
    ttl = max(60, int(os.getenv("EA_MARKUPGO_BREAKER_TTL_SEC", "21600")))
    _BREAKER_UNTIL = max(_BREAKER_UNTIL, _now() + ttl)
    log_render_guard("breaker_open_optional_skill", reason, skill=skill, location=location, ttl_sec=ttl)


def promote_known_good_template_if_needed(current_template_id: str, *, tenant: str = "ea_bot") -> str:
    template_id = (current_template_id or "").strip()
    known = known_good_template_ids()
    if not known:
        return template_id
    is_placeholder = (not template_id) or template_id.lower().startswith("ooda_auto_tpl_") or template_id.upper() == "YOUR_ID"
    if (not is_placeholder) and template_id in known:
        return template_id
    candidate = known[0]
    try:
        from app.db import get_db

        now = datetime.now(timezone.utc)
        get_db().execute(
            """
            INSERT INTO template_registry (tenant, key, provider, template_id, is_active, version)
            VALUES (%s, 'briefing.image', 'markupgo', %s, TRUE, 999)
            ON CONFLICT (tenant, key, provider)
            DO UPDATE SET template_id = EXCLUDED.template_id, is_active = TRUE
            """,
            (tenant, candidate),
        )
        # Keep ea_bot canonical row aligned too if tenant differs.
        if tenant != "ea_bot":
            get_db().execute(
                """
                INSERT INTO template_registry (tenant, key, provider, template_id, is_active, version)
                VALUES ('ea_bot', 'briefing.image', 'markupgo', %s, TRUE, 999)
                ON CONFLICT (tenant, key, provider)
                DO UPDATE SET template_id = EXCLUDED.template_id, is_active = TRUE
                """,
                (candidate,),
            )
        log_render_guard("renderer_template_swap", "known_good_promoted", tenant=tenant, from_template=template_id or "none", to_template=candidate, ts=str(now))
        return candidate
    except Exception as exc:
        log_render_guard("renderer_template_swap", "promotion_failed", tenant=tenant, err=str(exc)[:120])
        return template_id
