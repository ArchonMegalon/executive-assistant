from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.render_guard import (
    classify_markupgo_error,
    close_markupgo_breaker,
    known_good_template_ids,
    log_render_guard,
    markupgo_breaker_open,
    open_markupgo_breaker,
    promote_known_good_template_if_needed,
)


@dataclass
class RepairResult:
    ok: bool
    action: str
    detail: str = ""


def _is_placeholder(template_id: str) -> bool:
    tid = (template_id or "").strip()
    return (not tid) or tid.lower().startswith("ooda_auto_tpl_") or tid.upper() == "YOUR_ID"


def _markupgo_cfg() -> tuple[str, str]:
    base = (os.getenv("MARKUPGO_BASE_URL", "https://api.markupgo.com/api/v1") or "").rstrip("/")
    key = (os.getenv("MARKUPGO_API_KEY", "") or "").strip()
    return base, key


def _headers(key: str) -> dict[str, str]:
    return {"x-api-key": key, "Content-Type": "application/json"}


def _db_upsert_template(db: Any, template_id: str, *, tenant: str = "ea_bot") -> None:
    db.execute(
        """
        INSERT INTO template_registry (tenant, key, provider, template_id, is_active, version)
        VALUES (%s, 'briefing.image', 'markupgo', %s, TRUE, 999)
        ON CONFLICT (tenant, key, provider)
        DO UPDATE SET template_id = EXCLUDED.template_id, is_active = TRUE
        """,
        (tenant, template_id),
    )
    if tenant != "ea_bot":
        db.execute(
            """
            INSERT INTO template_registry (tenant, key, provider, template_id, is_active, version)
            VALUES ('ea_bot', 'briefing.image', 'markupgo', %s, TRUE, 999)
            ON CONFLICT (tenant, key, provider)
            DO UPDATE SET template_id = EXCLUDED.template_id, is_active = TRUE
            """,
            (template_id,),
        )


def _probe_template(base: str, key: str, template_id: str) -> tuple[bool, str]:
    payload = {
        "source": {
            "type": "template",
            "data": {
                "id": template_id,
                "context": {"briefing_text": "EA healthcheck"},
            },
        },
        "options": {"format": "png"},
    }
    with httpx.Client(timeout=20.0) as c:
        r = c.post(f"{base}/image/buffer", headers=_headers(key), json=payload)
    if r.status_code == 200 and (r.content or b"").startswith(b"\x89PNG"):
        return True, "ok"
    return False, f"http_{r.status_code}:{(r.text or '')[:220]}"


def _list_templates(base: str, key: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=20.0) as c:
        r = c.get(f"{base}/templates", headers=_headers(key))
    if r.status_code != 200:
        return []
    try:
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _create_default_template(base: str, key: str) -> tuple[str, str]:
    payload = {
        "name": f"EA Auto Template {int(time.time())}",
        "html": "<div style='white-space:pre-wrap;font-family:Arial,sans-serif;font-size:22px;color:#111;'>{{briefing_text}}</div>",
        "css": "body{margin:24px;background:#fff;color:#111;}",
        "width": 1200,
        "height": 1800,
        "autoHeight": True,
        "context": "briefing_text",
        "libraries": {"js": [], "css": []},
    }
    with httpx.Client(timeout=25.0) as c:
        r = c.post(f"{base}/templates", headers=_headers(key), json=payload)
    if r.status_code != 201:
        return "", f"create_http_{r.status_code}:{(r.text or '')[:220]}"
    try:
        obj = r.json()
    except Exception:
        return "", "create_invalid_json"
    tid = str((obj or {}).get("id") or "").strip()
    if not tid:
        return "", "create_missing_id"
    return tid, "created"


def heal_renderer_template(db: Any, *, tenant: str = "ea_bot") -> RepairResult:
    base, key = _markupgo_cfg()
    if not key:
        log_render_guard("renderer_template_swap", "missing_api_key", tenant=tenant)
        return RepairResult(False, "missing_api_key", "MARKUPGO_API_KEY missing")

    row = db.fetchone(
        "SELECT template_id FROM template_registry WHERE tenant=%s AND key='briefing.image' AND is_active=TRUE ORDER BY version DESC LIMIT 1",
        (tenant,),
    )
    current = str((row or {}).get("template_id") or "").strip()
    promoted = promote_known_good_template_if_needed(current, tenant=tenant)
    if promoted != current:
        current = promoted

    if current and not _is_placeholder(current):
        ok, detail = _probe_template(base, key, current)
        if ok:
            close_markupgo_breaker("validated_current_template", skill="markupgo", location="mum_brain")
            log_render_guard("renderer_template_swap", "validated_current", tenant=tenant, template_id=current)
            return RepairResult(True, "validated_current", current)

    for kid in known_good_template_ids():
        if not kid:
            continue
        ok, detail = _probe_template(base, key, kid)
        if ok:
            _db_upsert_template(db, kid, tenant=tenant)
            close_markupgo_breaker("known_good_verified", skill="markupgo", location="mum_brain")
            log_render_guard("renderer_template_swap", "known_good_adopted", tenant=tenant, template_id=kid)
            return RepairResult(True, "known_good_adopted", kid)

    templates = _list_templates(base, key)
    for t in templates:
        tid = str((t or {}).get("id") or "").strip()
        if not tid:
            continue
        ok, detail = _probe_template(base, key, tid)
        if ok:
            _db_upsert_template(db, tid, tenant=tenant)
            close_markupgo_breaker("existing_template_verified", skill="markupgo", location="mum_brain")
            log_render_guard("renderer_template_swap", "existing_template_adopted", tenant=tenant, template_id=tid)
            return RepairResult(True, "existing_template_adopted", tid)

    created_id, detail = _create_default_template(base, key)
    if not created_id:
        reason = classify_markupgo_error(detail)
        if reason in ("invalid_template_id", "renderer_unavailable") or "http_5" in detail:
            open_markupgo_breaker(detail, skill="markupgo", location="mum_brain")
            return RepairResult(True, "degraded_safe_mode", detail)
        return RepairResult(False, "template_create_failed", detail)

    ok, probe_detail = _probe_template(base, key, created_id)
    if not ok:
        reason = classify_markupgo_error(probe_detail)
        if reason in ("invalid_template_id", "renderer_unavailable") or "http_5" in probe_detail:
            open_markupgo_breaker(probe_detail, skill="markupgo", location="mum_brain")
            return RepairResult(True, "degraded_safe_mode", probe_detail)
        return RepairResult(False, "template_probe_failed", probe_detail)

    _db_upsert_template(db, created_id, tenant=tenant)
    close_markupgo_breaker("auto_template_created", skill="markupgo", location="mum_brain")
    log_render_guard("renderer_template_swap", "auto_template_created", tenant=tenant, template_id=created_id)
    return RepairResult(True, "auto_template_created", created_id)


def open_optional_breaker(db: Any, *, reason: str = "optional_skill_fault", correlation_id: str = "") -> RepairResult:
    ttl = max(60, int(os.getenv("EA_MARKUPGO_BREAKER_TTL_SEC", "21600")))
    db.execute(
        """
        INSERT INTO circuit_breakers (breaker_key, state, reason, opened_at, expires_at, correlation_id)
        VALUES ('markupgo_optional', 'open', %s, NOW(), NOW() + (%s || ' seconds')::interval, %s)
        ON CONFLICT (breaker_key)
        DO UPDATE SET state='open', reason=EXCLUDED.reason, opened_at=NOW(), expires_at=EXCLUDED.expires_at, correlation_id=EXCLUDED.correlation_id
        """,
        (reason[:200], str(ttl), correlation_id[:64]),
    )
    open_markupgo_breaker(reason, skill="markupgo", location="mum_brain")
    return RepairResult(True, "breaker_opened", reason)


def process_recipe(db: Any, recipe_key: str, *, fault_class: str = "", correlation_id: str = "", tenant: str = "ea_bot") -> RepairResult:
    recipe = (recipe_key or "").strip().lower()
    if recipe == "renderer_template_swap":
        return heal_renderer_template(db, tenant=tenant)
    if recipe in ("breaker_open_optional", "breaker_open_optional_skill"):
        return open_optional_breaker(db, reason=fault_class or "optional_skill_fault", correlation_id=correlation_id)
    return RepairResult(False, "unknown_recipe", recipe_key or "empty")


def system_health_snapshot(db: Any) -> dict[str, Any]:
    row = db.fetchone(
        """
        SELECT
          (SELECT count(*) FROM repair_jobs WHERE status='pending') AS pending,
          (SELECT count(*) FROM repair_jobs WHERE status='running') AS running,
          (SELECT count(*) FROM repair_jobs WHERE status='completed' AND finished_at > NOW() - interval '1 day') AS completed_24h,
          (SELECT count(*) FROM repair_jobs WHERE status='failed' AND finished_at > NOW() - interval '1 day') AS failed_24h,
          (SELECT count(*) FROM replay_events WHERE status IN ('queued','retry')) AS replay_q,
          (SELECT count(*) FROM replay_events WHERE status='deadletter') AS dead_q
        """
    )
    return {
        "pending": int((row or {}).get("pending") or 0),
        "running": int((row or {}).get("running") or 0),
        "completed_24h": int((row or {}).get("completed_24h") or 0),
        "failed_24h": int((row or {}).get("failed_24h") or 0),
        "replay_q": int((row or {}).get("replay_q") or 0),
        "dead_q": int((row or {}).get("dead_q") or 0),
        "breaker_open": bool(markupgo_breaker_open()),
    }
