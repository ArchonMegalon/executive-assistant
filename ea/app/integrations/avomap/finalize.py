from __future__ import annotations

import hashlib
import json
from typing import Any

from app.db import get_db
from app.settings import settings


def _pick(payload: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        cur: Any = payload
        ok = True
        for part in path:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            return cur
    return None


def _is_success(payload: dict[str, Any]) -> bool:
    status = str(
        _pick(payload, ("status",), ("result", "status"), ("data", "status")) or ""
    ).strip().lower()
    if status in {"ok", "success", "completed", "ready", "done"}:
        return True
    if status in {"failed", "error", "timeout"}:
        return False
    return bool(_pick(payload, ("object_ref",), ("data", "object_ref"), ("asset_url",), ("data", "asset_url")))


def _record_places(db, *, tenant: str, person_id: str, route_stops: list[dict[str, Any]]) -> None:
    for stop in route_stops[:10]:
        place_key = str(
            stop.get("place_key")
            or f"{str(stop.get('city') or '').strip().lower()}|{str(stop.get('country') or '').strip().lower()}"
        ).strip()
        if not place_key:
            continue
        db.execute(
            """
            INSERT INTO travel_place_history (
                tenant, person_id, place_key, city, country, lat, lon, first_seen, last_seen, seen_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), 1)
            ON CONFLICT (tenant, person_id, place_key)
            DO UPDATE SET
                city = COALESCE(EXCLUDED.city, travel_place_history.city),
                country = COALESCE(EXCLUDED.country, travel_place_history.country),
                lat = COALESCE(EXCLUDED.lat, travel_place_history.lat),
                lon = COALESCE(EXCLUDED.lon, travel_place_history.lon),
                last_seen = NOW(),
                seen_count = travel_place_history.seen_count + 1
            """,
            (
                tenant,
                person_id,
                place_key,
                stop.get("city"),
                stop.get("country"),
                stop.get("lat"),
                stop.get("lon"),
            ),
        )


def finalize_avomap_render_event(
    *,
    event_id: str,
    tenant: str,
    workflow: str,
    payload: dict[str, Any],
    db=None,
) -> dict[str, Any]:
    if workflow != settings.avomap_browseract_workflow:
        return {"ok": False, "status": "ignored_workflow"}

    db = db or get_db()
    data = payload if isinstance(payload, dict) else {}
    spec_id = str(
        _pick(data, ("spec_id",), ("data", "spec_id"), ("meta", "spec_id")) or ""
    ).strip()
    cache_key = str(
        _pick(data, ("cache_key",), ("data", "cache_key"), ("meta", "cache_key")) or ""
    ).strip()
    external_id = str(
        _pick(data, ("render_id",), ("data", "render_id"), ("job_id",), ("id",)) or ""
    ).strip()
    if not external_id:
        external_id = hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()

    object_ref = str(
        _pick(data, ("object_ref",), ("data", "object_ref"), ("asset_url",), ("data", "asset_url")) or ""
    ).strip()
    duration_sec = _pick(data, ("duration_sec",), ("data", "duration_sec"), ("video", "duration_sec"))
    mime_type = str(_pick(data, ("mime_type",), ("data", "mime_type")) or "video/mp4").strip()

    if not spec_id and cache_key:
        row = db.fetchone(
            """
            SELECT spec_id
            FROM travel_video_specs
            WHERE tenant=%s AND cache_key=%s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (tenant, cache_key),
        )
        spec_id = str((row or {}).get("spec_id") or "")

    if not spec_id:
        return {"ok": False, "status": "missing_spec_id"}

    success = _is_success(data)
    if success and object_ref:
        db.execute(
            """
            INSERT INTO avomap_assets (
                spec_id, tenant, cache_key, object_ref, mime_type, duration_sec, external_id, status, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'ready', NOW())
            ON CONFLICT (external_id)
            DO UPDATE SET
                spec_id = EXCLUDED.spec_id,
                tenant = EXCLUDED.tenant,
                cache_key = EXCLUDED.cache_key,
                object_ref = EXCLUDED.object_ref,
                mime_type = EXCLUDED.mime_type,
                duration_sec = EXCLUDED.duration_sec,
                status = 'ready',
                updated_at = NOW()
            """,
            (spec_id, tenant, cache_key, object_ref, mime_type, duration_sec, external_id),
        )
        db.execute(
            """
            UPDATE avomap_jobs
            SET status='completed', external_job_id=%s, last_error=NULL, updated_at=NOW()
            WHERE spec_id=%s
            """,
            (external_id, spec_id),
        )
        db.execute(
            """
            UPDATE travel_video_specs
            SET status='completed', last_error=NULL, updated_at=NOW()
            WHERE spec_id=%s
            """,
            (spec_id,),
        )
        spec_row = db.fetchone(
            """
            SELECT person_id, route_json
            FROM travel_video_specs
            WHERE spec_id=%s
            """,
            (spec_id,),
        ) or {}
        person_id = str((spec_row or {}).get("person_id") or "").strip()
        route_json = (spec_row or {}).get("route_json") or {}
        if isinstance(route_json, str):
            try:
                route_json = json.loads(route_json)
            except Exception:
                route_json = {}
        route_stops = route_json.get("stops") if isinstance(route_json, dict) else []
        if person_id and isinstance(route_stops, list) and route_stops:
            _record_places(db, tenant=tenant, person_id=person_id, route_stops=route_stops)
        return {"ok": True, "status": "completed", "spec_id": spec_id, "external_id": external_id}

    err = str(_pick(data, ("error",), ("message",), ("result", "error"), ("data", "error")) or "render_failed")
    db.execute(
        """
        UPDATE avomap_jobs
        SET status='failed', last_error=%s, updated_at=NOW()
        WHERE spec_id=%s
        """,
        (err[:500], spec_id),
    )
    db.execute(
        """
        UPDATE travel_video_specs
        SET status='failed', last_error=%s, updated_at=NOW()
        WHERE spec_id=%s
        """,
        (err[:500], spec_id),
    )
    return {"ok": True, "status": "failed", "spec_id": spec_id}
