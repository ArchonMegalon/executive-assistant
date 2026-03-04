from __future__ import annotations

from datetime import date, datetime, timezone
import os
import re
from typing import Any

from app.db import get_db
from app.integrations.avomap.browseract_payloads import build_browseract_payload
from app.integrations.avomap.detector import detect_new_place
from app.integrations.avomap.sanitizer import sanitize_route_for_export
from app.integrations.avomap.security import issue_job_token
from app.integrations.avomap.specs import TravelVideoSpec, build_cache_key, validate_spec
from app.integrations.routing.service import resolve_route_stops
from app.settings import settings


def _extract_city(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    # Prefer comma/semicolon separated geo parts and walk from the end to avoid
    # venue names like "Hilton Vienna Park, Vienna, Austria".
    parts = [p.strip() for p in re.split(r"[;,|]", raw) if p.strip()]
    country_like = {
        "austria",
        "germany",
        "switzerland",
        "france",
        "italy",
        "spain",
        "united kingdom",
        "uk",
        "england",
        "usa",
        "united states",
        "netherlands",
        "belgium",
        "portugal",
        "ireland",
        "poland",
        "czech republic",
        "slovakia",
        "hungary",
        "slovenia",
        "croatia",
        "romania",
        "bulgaria",
        "greece",
        "norway",
        "sweden",
        "finland",
        "denmark",
        "at",
        "de",
        "ch",
        "fr",
        "it",
        "es",
        "nl",
        "be",
        "pt",
        "ie",
        "pl",
        "cz",
        "sk",
        "hu",
        "si",
        "hr",
        "ro",
        "bg",
        "gr",
        "no",
        "se",
        "fi",
        "dk",
    }
    venue_tokens = (
        "hotel",
        "airport",
        "station",
        "bahnhof",
        "terminal",
        "gate",
        "hq",
        "office",
        "campus",
        "center",
        "centre",
        "conference",
        "meeting",
    )
    for part in reversed(parts):
        cleaned = re.sub(r"\s+", " ", re.sub(r"[^A-Za-zÀ-ÿ0-9 .'\-]", " ", part)).strip()
        if not cleaned:
            continue
        cleaned = re.sub(r"(?i)^(flight|train|trip|offsite|conference|meeting|hotel|stay|arrival|departure)\s+(to|at|in)\s+", "", cleaned).strip()
        if not cleaned:
            continue
        low = cleaned.lower()
        if low in country_like:
            continue
        if len(cleaned) <= 3 and low in {"at", "de", "ch", "fr", "it", "uk", "us", "eu"}:
            continue
        if any(tok in low for tok in venue_tokens):
            # Try to salvage city-like prefix in tokens such as "Zurich Airport".
            stripped = cleaned
            for tok in venue_tokens:
                stripped = re.sub(rf"(?i)\b{re.escape(tok)}\b", "", stripped).strip(" -_,")
            stripped = re.sub(r"(?i)^(flight|train|trip|offsite|conference|meeting|hotel|stay|arrival|departure)\s+(to|at|in)\s+", "", stripped).strip()
            if stripped and stripped.lower() != low:
                return stripped[:64]
            continue
        return cleaned[:64]
    # Fallback: best-effort first token-like phrase
    first = parts[0] if parts else raw
    first = re.sub(r"\s+", " ", re.sub(r"[^A-Za-zÀ-ÿ0-9 .'\-]", " ", first)).strip()
    return first[:64]


def _has_travel_signal(text: str) -> bool:
    low = str(text or "").lower()
    for kw in (
        "flight",
        "hotel",
        "airport",
        "rail",
        "train",
        "trip",
        "offsite",
        "conference",
        "itinerary",
        "boarding",
        "check-in",
        "departure",
        "arrival",
        "layover",
        "shuttle",
    ):
        if kw in low:
            return True
    return False


def build_day_context(*, calendar_events: list[dict] | None, travel_emails: list[dict] | None) -> dict[str, Any]:
    events = calendar_events or []
    emails = travel_emails or []

    stops: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        location_field = str(ev.get("location") or "").strip()
        summary = str(ev.get("summary") or ev.get("title") or "").strip()
        # Prefer explicit location. Only derive location from summary/title for
        # travel-like events to avoid generic meeting-title false positives.
        location = location_field
        if not location and summary and _has_travel_signal(summary):
            location = summary
        if not location:
            continue
        stops.append(
            {
                "label": location[:120],
                "city": _extract_city(location),
                "country": "",
            }
        )

    hints: list[str] = []
    for m in emails:
        if not isinstance(m, dict):
            continue
        text = " ".join(
            str(x or "")
            for x in (
                m.get("subject"),
                m.get("sender"),
                m.get("snippet"),
                m.get("preview"),
            )
        ).strip()
        if text and _has_travel_signal(text):
            hints.append(text[:220])
    # Calendar events can also carry strong travel intent signals.
    for ev in events:
        if not isinstance(ev, dict):
            continue
        text = " ".join(
            str(x or "")
            for x in (
                ev.get("title"),
                ev.get("summary"),
                ev.get("location"),
            )
        ).strip()
        if text and _has_travel_signal(text):
            hints.append(text[:220])

    base = {}
    try:
        if os.environ.get("EA_HOME_LAT") and os.environ.get("EA_HOME_LON"):
            base = {"lat": float(os.environ["EA_HOME_LAT"]), "lon": float(os.environ["EA_HOME_LON"])}
    except Exception:
        base = {}

    return {
        "route_stops": stops,
        "travel_email_hints": hints,
        "home_base": base,
    }


class AvoMapService:
    def __init__(self, db=None, *, enabled: bool | None = None):
        self.db = db or get_db()
        self.enabled = settings.avomap_enabled if enabled is None else bool(enabled)

    def _date_key(self, value: str | None = None) -> str:
        if value:
            return str(value)
        return date.today().isoformat()

    def _load_recent_place_keys(self, tenant: str, person_id: str) -> set[str]:
        rows = self.db.fetchall(
            """
            SELECT place_key
            FROM travel_place_history
            WHERE tenant=%s
              AND person_id=%s
              AND last_seen >= NOW() - (%s * INTERVAL '1 day')
            """,
            (tenant, person_id, int(settings.avomap_recent_place_days)),
        ) or []
        keys: set[str] = set()
        for r in rows:
            key = str((r or {}).get("place_key") or "").strip().lower()
            if key:
                keys.add(key)
        return keys

    def _inc_ledger_used(self, tenant: str, person_id: str, date_key: str) -> None:
        self.db.execute(
            """
            INSERT INTO avomap_credit_ledger (tenant, person_id, date_key, renders_used, renders_cached, updated_at)
            VALUES (%s, %s, %s, 1, 0, NOW())
            ON CONFLICT (tenant, person_id, date_key)
            DO UPDATE SET renders_used = avomap_credit_ledger.renders_used + 1,
                          updated_at = NOW()
            """,
            (tenant, person_id, date_key),
        )

    def _inc_ledger_cached(self, tenant: str, person_id: str, date_key: str) -> None:
        self.db.execute(
            """
            INSERT INTO avomap_credit_ledger (tenant, person_id, date_key, renders_used, renders_cached, updated_at)
            VALUES (%s, %s, %s, 0, 1, NOW())
            ON CONFLICT (tenant, person_id, date_key)
            DO UPDATE SET renders_cached = avomap_credit_ledger.renders_cached + 1,
                          updated_at = NOW()
            """,
            (tenant, person_id, date_key),
        )

    def _budget_allows(self, tenant: str, person_id: str, date_key: str) -> bool:
        row_person = self.db.fetchone(
            """
            SELECT renders_used
            FROM avomap_credit_ledger
            WHERE tenant=%s AND person_id=%s AND date_key=%s
            """,
            (tenant, person_id, date_key),
        ) or {}
        if int(row_person.get("renders_used") or 0) >= int(settings.avomap_max_per_person_per_day):
            return False

        row_tenant = self.db.fetchone(
            """
            SELECT COALESCE(SUM(renders_used), 0) AS total_used
            FROM avomap_credit_ledger
            WHERE tenant=%s AND date_key=%s
            """,
            (tenant, date_key),
        ) or {}
        if int(row_tenant.get("total_used") or 0) >= int(settings.avomap_daily_render_budget):
            return False
        return True

    def _record_places(self, tenant: str, person_id: str, route_stops: list[dict[str, Any]]) -> None:
        for stop in route_stops[:10]:
            place_key = str(
                stop.get("place_key")
                or f"{str(stop.get('city') or '').strip().lower()}|{str(stop.get('country') or '').strip().lower()}"
            ).strip()
            if not place_key:
                continue
            self.db.execute(
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

    def get_ready_asset(self, *, tenant: str, person_id: str, date_key: str | None = None) -> dict[str, Any] | None:
        day = self._date_key(date_key)
        return self.db.fetchone(
            """
            SELECT a.asset_id, a.object_ref, a.cache_key, a.mime_type, a.duration_sec,
                   s.mode, s.date_key
            FROM travel_video_specs s
            JOIN avomap_assets a
              ON a.tenant = s.tenant
             AND a.cache_key = s.cache_key
             AND a.status='ready'
            WHERE s.tenant=%s
              AND s.person_id=%s
              AND s.date_key=%s
            ORDER BY s.updated_at DESC, a.updated_at DESC
            LIMIT 1
            """,
            (tenant, person_id, day),
        )

    def plan_for_briefing(
        self,
        *,
        tenant: str,
        person_id: str,
        day_context: dict[str, Any],
        date_key: str | None = None,
    ) -> dict[str, Any]:
        day = self._date_key(date_key)
        if not self.enabled:
            return {"status": "disabled", "date_key": day}

        recent_place_keys = self._load_recent_place_keys(tenant, person_id)
        decision = detect_new_place(
            day_context,
            recent_place_keys,
            min_distance_km=int(settings.avomap_min_novelty_distance_km),
        )
        mode = str(decision.get("mode") or "none")
        if mode == "none":
            return {"status": "no_candidate", "date_key": day, "decision": decision}

        raw_route_stops = [s for s in (day_context.get("route_stops") or []) if isinstance(s, dict)]
        resolved_stops = resolve_route_stops(raw_route_stops, home_base=day_context.get("home_base"))
        route_stops = sanitize_route_for_export(resolved_stops, home_base=day_context.get("home_base"))
        markers = route_stops[:8]
        route_json = {"stops": route_stops[:8], "date_key": day}
        cache_key = build_cache_key(
            route_json=route_json,
            markers_json=markers,
            mode=mode,
            orientation=settings.avomap_default_orientation,
            duration_target_sec=int(settings.avomap_duration_target_sec),
        )
        spec = TravelVideoSpec(
            tenant=tenant,
            person_id=person_id,
            date_key=day,
            mode=mode,
            orientation=settings.avomap_default_orientation,
            duration_target_sec=int(settings.avomap_duration_target_sec),
            route_json=route_json,
            markers_json=markers,
            signal_json={
                "decision": decision,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "opsec_sanitized": True,
            },
            cache_key=cache_key,
        )
        errs = validate_spec(spec)
        if errs:
            return {"status": "invalid_spec", "errors": errs, "date_key": day}

        cached = self.db.fetchone(
            """
            SELECT asset_id, object_ref
            FROM avomap_assets
            WHERE tenant=%s AND cache_key=%s AND status='ready'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (tenant, cache_key),
        )
        if cached:
            row = self.db.fetchone(
                """
                INSERT INTO travel_video_specs (
                    tenant, person_id, date_key, mode, orientation, duration_target_sec,
                    route_json, markers_json, signal_json, cache_key, status, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, 'completed', NOW())
                ON CONFLICT (tenant, person_id, date_key, cache_key)
                DO UPDATE SET status='completed', updated_at=NOW()
                RETURNING spec_id
                """,
                (
                    spec.tenant,
                    spec.person_id,
                    spec.date_key,
                    spec.mode,
                    spec.orientation,
                    spec.duration_target_sec,
                    __import__("json").dumps(spec.route_json),
                    __import__("json").dumps(spec.markers_json),
                    __import__("json").dumps(spec.signal_json),
                    spec.cache_key,
                ),
            )
            spec_id = str((row or {}).get("spec_id") or "")
            self._inc_ledger_cached(tenant, person_id, day)
            return {
                "status": "cache_hit",
                "spec_id": spec_id,
                "asset_id": str((cached or {}).get("asset_id") or ""),
                "object_ref": str((cached or {}).get("object_ref") or ""),
                "mode": mode,
                "date_key": day,
            }

        existing = self.db.fetchone(
            """
            SELECT spec_id, status
            FROM travel_video_specs
            WHERE tenant=%s AND person_id=%s AND date_key=%s AND cache_key=%s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (tenant, person_id, day, cache_key),
        )
        if existing and str(existing.get("status") or "") in ("dispatched", "pending", "completed"):
            return {
                "status": "existing_spec",
                "spec_id": str(existing.get("spec_id") or ""),
                "mode": mode,
                "date_key": day,
            }

        if not self._budget_allows(tenant, person_id, day):
            self.db.execute(
                """
                INSERT INTO travel_video_specs (
                    tenant, person_id, date_key, mode, orientation, duration_target_sec,
                    route_json, markers_json, signal_json, cache_key, status, last_error, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, 'skipped_budget', 'budget_exhausted', NOW())
                ON CONFLICT (tenant, person_id, date_key, cache_key)
                DO UPDATE SET status='skipped_budget', last_error='budget_exhausted', updated_at=NOW()
                """,
                (
                    spec.tenant,
                    spec.person_id,
                    spec.date_key,
                    spec.mode,
                    spec.orientation,
                    spec.duration_target_sec,
                    __import__("json").dumps(spec.route_json),
                    __import__("json").dumps(spec.markers_json),
                    __import__("json").dumps(spec.signal_json),
                    spec.cache_key,
                ),
            )
            return {"status": "budget_exhausted", "mode": mode, "date_key": day}

        row = self.db.fetchone(
            """
            INSERT INTO travel_video_specs (
                tenant, person_id, date_key, mode, orientation, duration_target_sec,
                route_json, markers_json, signal_json, cache_key, status, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, 'pending', NOW())
            ON CONFLICT (tenant, person_id, date_key, cache_key)
            DO UPDATE SET
                mode=EXCLUDED.mode,
                orientation=EXCLUDED.orientation,
                duration_target_sec=EXCLUDED.duration_target_sec,
                route_json=EXCLUDED.route_json,
                markers_json=EXCLUDED.markers_json,
                signal_json=EXCLUDED.signal_json,
                status='pending',
                updated_at=NOW()
            RETURNING spec_id
            """,
            (
                spec.tenant,
                spec.person_id,
                spec.date_key,
                spec.mode,
                spec.orientation,
                spec.duration_target_sec,
                __import__("json").dumps(spec.route_json),
                __import__("json").dumps(spec.markers_json),
                __import__("json").dumps(spec.signal_json),
                spec.cache_key,
            ),
        )
        spec_id = str((row or {}).get("spec_id") or "")
        if not spec_id:
            return {"status": "spec_insert_failed", "mode": mode, "date_key": day}

        job = self.db.fetchone(
            """
            INSERT INTO avomap_jobs (spec_id, tenant, workflow_name, status, dedupe_key, updated_at)
            VALUES (%s, %s, %s, 'queued', %s, NOW())
            ON CONFLICT (tenant, dedupe_key)
            DO UPDATE SET updated_at=NOW()
            RETURNING job_id
            """,
            (spec_id, tenant, settings.avomap_browseract_workflow, f"{tenant}:{person_id}:{day}:{cache_key}"),
        )
        job_id = str((job or {}).get("job_id") or "")
        job_token = issue_job_token(
            settings.avomap_webhook_secret,
            tenant=tenant,
            job_id=job_id,
            spec_id=spec_id,
        )
        payload = build_browseract_payload(
            spec,
            settings.avomap_browseract_workflow,
            spec_id=spec_id,
            cache_key=cache_key,
            job_id=job_id,
            job_token=job_token,
        )

        self.db.execute(
            """
            INSERT INTO browser_jobs (tenant, target_ltd, script_payload_json, status)
            VALUES (%s, 'avomap', %s::jsonb, 'queued')
            """,
            (tenant, __import__("json").dumps(payload)),
        )
        self.db.execute(
            """
            UPDATE travel_video_specs
            SET status='dispatched', updated_at=NOW()
            WHERE spec_id=%s
            """,
            (spec_id,),
        )
        self._inc_ledger_used(tenant, person_id, day)
        return {
            "status": "dispatched",
            "spec_id": spec_id,
            "job_id": job_id,
            "cache_key": cache_key,
            "mode": mode,
            "date_key": day,
        }
