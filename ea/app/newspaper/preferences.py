from __future__ import annotations

import asyncio

from app.articles_digest import collect_user_signal_terms


def _cfg_value(cfg: dict, key: str, default: str = "") -> str:
    try:
        return str((cfg or {}).get(key) or default)
    except Exception:
        return str(default)


async def build_preference_snapshot(tenant_name: str, tenant_cfg: dict, chat_id: int) -> dict:
    prioritize: list[str] = []
    avoid: list[str] = []
    try:
        terms = await collect_user_signal_terms(
            openclaw_container=_cfg_value(tenant_cfg, "openclaw_container", ""),
            google_account=_cfg_value(tenant_cfg, "google_account", ""),
        )
        prioritize = sorted([t for t in terms if t and len(t) > 3])[:12]
    except Exception:
        pass
    try:
        from app.db import get_db

        db = get_db()
        tenant_keys = []
        for key in (tenant_name, _cfg_value(tenant_cfg, "google_account", "")):
            k = str(key or "").strip()
            if k and k not in tenant_keys:
                tenant_keys.append(k)
        rows = []
        for tk in tenant_keys:
            part = await asyncio.to_thread(
                db.fetchall,
                """
                SELECT concept_key, weight, hard_dislike
                FROM user_interest_profiles
                WHERE tenant_key=%s AND principal_id=%s
                ORDER BY hard_dislike DESC, weight ASC
                LIMIT 20
                """,
                (tk, str(chat_id)),
            ) or []
            rows.extend(part)
        for r in rows:
            concept = str(r.get("concept_key") or "").strip()
            if not concept:
                continue
            if bool(r.get("hard_dislike")) or float(r.get("weight") or 0.0) < -0.35:
                avoid.append(concept)
            elif float(r.get("weight") or 0.0) > 0.25:
                prioritize.append(concept)
    except Exception:
        pass
    prioritize = list(dict.fromkeys(prioritize))[:12]
    avoid = list(dict.fromkeys(avoid))[:12]
    return {"prioritize": prioritize, "avoid": avoid}
