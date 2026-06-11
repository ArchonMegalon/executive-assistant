from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from typing import Any


PROPERTYQUARRY_TEABLE_TABLE_NAMES = (
    "propertyquarry_tenants",
    "propertyquarry_users",
    "propertyquarry_subscriptions",
    "propertyquarry_preferences",
    "propertyquarry_search_runs",
    "propertyquarry_provider_sources",
    "propertyquarry_properties",
    "propertyquarry_property_evaluations",
    "propertyquarry_review_artifacts",
    "propertyquarry_research_tasks",
)


PROPERTYQUARRY_TEABLE_TABLE_FIELDS: dict[str, list[dict[str, object]]] = {
    "propertyquarry_tenants": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "tenant_name", "type": "singleLineText"},
        {"name": "source_system", "type": "singleLineText"},
        {"name": "privacy_scope", "type": "singleLineText"},
        {"name": "sync_version", "type": "singleLineText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_users": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "workspace_name", "type": "singleLineText"},
        {"name": "workspace_mode", "type": "singleLineText"},
        {"name": "region", "type": "singleLineText"},
        {"name": "language", "type": "singleLineText"},
        {"name": "timezone", "type": "singleLineText"},
        {"name": "selected_channels_json", "type": "longText"},
        {"name": "current_plan_key", "type": "singleLineText"},
        {"name": "subscription_status", "type": "singleLineText"},
        {"name": "is_paid", "type": "checkbox"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_subscriptions": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "current_plan_key", "type": "singleLineText"},
        {"name": "current_plan_label", "type": "singleLineText"},
        {"name": "status", "type": "singleLineText"},
        {"name": "active_until", "type": "singleLineText"},
        {"name": "is_paid", "type": "checkbox"},
        {"name": "pending_plan_key", "type": "singleLineText"},
        {"name": "plan_source", "type": "singleLineText"},
        {"name": "last_order_id", "type": "singleLineText"},
        {"name": "last_capture_id", "type": "singleLineText"},
        {"name": "last_payment_status", "type": "singleLineText"},
        {"name": "last_payment_amount_eur", "type": "singleLineText"},
        {"name": "captured_at", "type": "singleLineText"},
        {"name": "commercial_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_preferences": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "preference_person_id", "type": "singleLineText"},
        {"name": "country_code", "type": "singleLineText"},
        {"name": "language_code", "type": "singleLineText"},
        {"name": "listing_mode", "type": "singleLineText"},
        {"name": "property_type", "type": "singleLineText"},
        {"name": "location_query", "type": "singleLineText"},
        {"name": "keywords", "type": "singleLineText"},
        {"name": "selected_platforms_json", "type": "longText"},
        {"name": "max_price_eur", "type": "number"},
        {"name": "min_rooms", "type": "number"},
        {"name": "min_area_m2", "type": "number"},
        {"name": "max_results_per_source", "type": "number"},
        {"name": "use_stored_feedback_preferences", "type": "checkbox"},
        {"name": "alert_frequency", "type": "singleLineText"},
        {"name": "preferences_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_search_runs": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "run_id", "type": "singleLineText"},
        {"name": "status", "type": "singleLineText"},
        {"name": "status_url", "type": "singleLineText"},
        {"name": "selected_platforms_json", "type": "longText"},
        {"name": "preferences_json", "type": "longText"},
        {"name": "created_at", "type": "singleLineText"},
        {"name": "updated_at", "type": "singleLineText"},
        {"name": "generated_at", "type": "singleLineText"},
        {"name": "sources_total", "type": "number"},
        {"name": "listing_total", "type": "number"},
        {"name": "high_fit_total", "type": "number"},
        {"name": "review_created_total", "type": "number"},
        {"name": "review_existing_total", "type": "number"},
        {"name": "tour_created_total", "type": "number"},
        {"name": "tour_existing_total", "type": "number"},
        {"name": "provider_cache_hit_total", "type": "number"},
        {"name": "provider_cache_refresh_total", "type": "number"},
        {"name": "filtered_area_total", "type": "number"},
        {"name": "filtered_low_fit_total", "type": "number"},
        {"name": "research_task_total", "type": "number"},
        {"name": "open_research_task_total", "type": "number"},
        {"name": "summary_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_provider_sources": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "run_id", "type": "singleLineText"},
        {"name": "source_ref", "type": "singleLineText"},
        {"name": "source_label", "type": "singleLineText"},
        {"name": "source_url", "type": "longText"},
        {"name": "platform", "type": "singleLineText"},
        {"name": "preference_person_id", "type": "singleLineText"},
        {"name": "provider_cache_key", "type": "singleLineText"},
        {"name": "provider_cache_status", "type": "singleLineText"},
        {"name": "provider_cache_stale", "type": "checkbox"},
        {"name": "raw_listing_total", "type": "number"},
        {"name": "scanned_listing_total", "type": "number"},
        {"name": "listing_total", "type": "number"},
        {"name": "duplicate_listing_total", "type": "number"},
        {"name": "filtered_area_total", "type": "number"},
        {"name": "filtered_low_fit_total", "type": "number"},
        {"name": "filtered_floorplan_total", "type": "number"},
        {"name": "high_fit_total", "type": "number"},
        {"name": "top_fit_score", "type": "number"},
        {"name": "scan_truncated", "type": "checkbox"},
        {"name": "min_area_m2", "type": "number"},
        {"name": "max_price_eur", "type": "number"},
        {"name": "min_rooms", "type": "number"},
        {"name": "provider_filter_pushdown_json", "type": "longText"},
        {"name": "provider_cache_json", "type": "longText"},
        {"name": "source_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_properties": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "property_url", "type": "longText"},
        {"name": "listing_id", "type": "singleLineText"},
        {"name": "title", "type": "singleLineText"},
        {"name": "source_label", "type": "singleLineText"},
        {"name": "area_sqm", "type": "number"},
        {"name": "rooms", "type": "number"},
        {"name": "total_rent_eur", "type": "number"},
        {"name": "purchase_price_eur", "type": "number"},
        {"name": "postal_name", "type": "singleLineText"},
        {"name": "property_type", "type": "singleLineText"},
        {"name": "facts_json", "type": "longText"},
        {"name": "last_seen_run_id", "type": "singleLineText"},
        {"name": "last_seen_at", "type": "singleLineText"},
    ],
    "propertyquarry_property_evaluations": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "run_id", "type": "singleLineText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "property_url", "type": "longText"},
        {"name": "source_ref", "type": "singleLineText"},
        {"name": "source_label", "type": "singleLineText"},
        {"name": "fit_score", "type": "number"},
        {"name": "recommendation", "type": "singleLineText"},
        {"name": "fit_summary", "type": "singleLineText"},
        {"name": "review_url", "type": "longText"},
        {"name": "tour_url", "type": "longText"},
        {"name": "tour_status", "type": "singleLineText"},
        {"name": "match_reasons_json", "type": "longText"},
        {"name": "mismatch_reasons_json", "type": "longText"},
        {"name": "assessment_json", "type": "longText"},
        {"name": "facts_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_review_artifacts": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "run_id", "type": "singleLineText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "property_url", "type": "longText"},
        {"name": "source_ref", "type": "singleLineText"},
        {"name": "source_label", "type": "singleLineText"},
        {"name": "review_url", "type": "longText"},
        {"name": "review_status", "type": "singleLineText"},
        {"name": "review_task_id", "type": "singleLineText"},
        {"name": "review_task_status", "type": "singleLineText"},
        {"name": "review_reused", "type": "checkbox"},
        {"name": "queue_item_ref", "type": "singleLineText"},
        {"name": "recommended_task_key", "type": "singleLineText"},
        {"name": "tour_url", "type": "longText"},
        {"name": "tour_status", "type": "singleLineText"},
        {"name": "tour_blocked_reason", "type": "singleLineText"},
        {"name": "fit_score", "type": "number"},
        {"name": "recommendation", "type": "singleLineText"},
        {"name": "preference_person_id", "type": "singleLineText"},
        {"name": "artifact_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_research_tasks": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "run_id", "type": "singleLineText"},
        {"name": "task_id", "type": "singleLineText"},
        {"name": "status", "type": "singleLineText"},
        {"name": "field_key", "type": "singleLineText"},
        {"name": "label", "type": "singleLineText"},
        {"name": "question", "type": "longText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "property_url", "type": "longText"},
        {"name": "value", "type": "singleLineText"},
        {"name": "note", "type": "longText"},
        {"name": "task_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
}


def propertyquarry_teable_tenant_key() -> str:
    return str(os.environ.get("PROPERTYQUARRY_TEABLE_TENANT_KEY") or "propertyquarry").strip() or "propertyquarry"


def propertyquarry_teable_tenant_name() -> str:
    return str(os.environ.get("PROPERTYQUARRY_TEABLE_TENANT_NAME") or "PropertyQuarry").strip() or "PropertyQuarry"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_commercial_json(payload: dict[str, Any] | None) -> dict[str, Any]:
    blocked_exact = {"last_payer_email", "payer_email", "email", "billing_email"}
    blocked_markers = ("token", "secret", "cookie", "session", "oauth", "internal")
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        normalized = str(key or "").strip()
        lowered = normalized.lower()
        if normalized in blocked_exact:
            continue
        if any(marker in lowered for marker in blocked_markers):
            continue
        result[normalized] = value
    return result


def _safe_teable_facts(payload: dict[str, Any] | None) -> dict[str, Any]:
    blocked_exact = {"exact_address", "street_address", "house_number", "map_lat", "map_lng", "lat", "lng"}
    blocked_markers = ("token", "secret", "cookie", "session", "oauth", "internal")
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        normalized = str(key or "").strip()
        lowered = normalized.lower()
        if normalized in blocked_exact:
            continue
        if any(marker in lowered for marker in blocked_markers):
            continue
        result[normalized] = value
    return result


def _safe_teable_preferences(payload: dict[str, Any] | None) -> dict[str, Any]:
    blocked_exact = {
        "property_commercial",
        "payer_email",
        "billing_email",
        "email",
        "raw_notes",
        "notes",
        "consent_note",
    }
    blocked_markers = ("token", "secret", "cookie", "session", "oauth", "internal", "debug", "credential")
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        normalized = str(key or "").strip()
        lowered = normalized.lower()
        if normalized in blocked_exact:
            continue
        if any(marker in lowered for marker in blocked_markers):
            continue
        if "email" in lowered:
            continue
        if isinstance(value, dict):
            result[normalized] = _safe_teable_preferences(value)
            continue
        if isinstance(value, list):
            items: list[Any] = []
            for item in value[:50]:
                if isinstance(item, dict):
                    items.append(_safe_teable_preferences(item))
                else:
                    items.append(item)
            result[normalized] = items
            continue
        result[normalized] = value
    return result


def _safe_review_artifact(candidate: dict[str, Any] | None, *, safe_facts: dict[str, Any]) -> dict[str, Any]:
    payload = dict(candidate or {})
    return {
        "property_url": _text(payload.get("property_url"), limit=1000),
        "listing_id": _text(payload.get("listing_id"), limit=200),
        "title": _text(payload.get("title"), limit=240),
        "fit_score": _number(payload.get("fit_score")),
        "recommendation": _text(payload.get("recommendation"), limit=160),
        "review_status": _text(payload.get("review_status"), limit=80),
        "review_task_status": _text(payload.get("review_task_status"), limit=80),
        "review_reused": bool(payload.get("review_reused")),
        "tour_status": _text(payload.get("tour_status"), limit=80),
        "facts_json": dict(safe_facts),
    }


def _safe_source_summary(source: dict[str, Any] | None, *, source_label: str, platform: str, source_url: str) -> dict[str, Any]:
    payload = dict(source or {})
    return {
        "source_label": source_label,
        "platform": platform,
        "source_url": source_url,
        "raw_listing_total": payload.get("raw_listing_total"),
        "scanned_listing_total": payload.get("scanned_listing_total"),
        "listing_total": payload.get("listing_total"),
        "duplicate_listing_total": payload.get("duplicate_listing_total"),
        "filtered_area_total": payload.get("filtered_area_total"),
        "filtered_low_fit_total": payload.get("filtered_low_fit_total"),
        "filtered_floorplan_total": payload.get("filtered_floorplan_total"),
        "high_fit_total": payload.get("high_fit_total"),
        "top_fit_score": payload.get("top_fit_score"),
        "scan_truncated": bool(payload.get("scan_truncated")),
    }


def _text(value: object, *, limit: int = 500) -> str:
    text = str(value or "").strip()
    if limit > 0 and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "..."
    return text


def _number(value: object) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if number.is_integer():
        return int(number)
    return round(number, 4)


def _stable_ref(value: object, *, prefix: str) -> str:
    raw = str(value or "").strip()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


def _property_commercial_snapshot(preferences: dict[str, object]) -> dict[str, object]:
    try:
        from app.services.property_billing import property_commercial_snapshot

        return dict(property_commercial_snapshot(preferences))
    except Exception:
        commercial = dict(preferences.get("property_commercial") or {}) if isinstance(preferences.get("property_commercial"), dict) else {}
        plan_key = _text(commercial.get("active_plan_key") or commercial.get("plan_key") or "free", limit=80) or "free"
        status = _text(commercial.get("status") or ("free" if plan_key == "free" else "active"), limit=80)
        return {
            "current_plan_key": plan_key,
            "current_plan_label": plan_key.title(),
            "status": status,
            "active_until": _text(commercial.get("active_until"), limit=120),
            "is_paid": plan_key != "free",
            "pending_plan_key": _text(commercial.get("pending_plan_key"), limit=80),
            "property_commercial": commercial,
        }


def _table_rows(rows_by_id: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    return [dict(rows_by_id[key]) for key in sorted(rows_by_id)]


def _candidate_rows_from_run(run: dict[str, object]) -> list[dict[str, object]]:
    summary = dict(run.get("summary") or {})
    rows: list[dict[str, object]] = []
    for source in list(summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        source_label = _text(source.get("source_label"), limit=160)
        for candidate in list(source.get("top_candidates") or []):
            if not isinstance(candidate, dict):
                continue
            item = dict(candidate)
            item.setdefault("source_label", source_label)
            rows.append(item)
    return rows


def _source_rows_from_run(run: dict[str, object]) -> list[dict[str, object]]:
    summary = dict(run.get("summary") or {})
    rows: list[dict[str, object]] = []
    for source in list(summary.get("sources") or []):
        if isinstance(source, dict):
            rows.append(dict(source))
    return rows


def build_propertyquarry_teable_projection_records(
    *,
    principal_id: str,
    onboarding_status: dict[str, object] | None = None,
    search_runs: tuple[dict[str, object], ...] = (),
    tenant_key: str = "",
    tenant_name: str = "",
) -> dict[str, list[dict[str, object]]]:
    normalized_principal = _text(principal_id, limit=240)
    normalized_tenant = _text(tenant_key or propertyquarry_teable_tenant_key(), limit=120)
    normalized_tenant_name = _text(tenant_name or propertyquarry_teable_tenant_name(), limit=200)
    projected_at = _now_iso()
    status = dict(onboarding_status or {})
    workspace = dict(status.get("workspace") or {})
    preferences = dict(status.get("property_search_preferences") or {})
    raw_preferences = dict(preferences.get("raw_preferences") or {}) if isinstance(preferences.get("raw_preferences"), dict) else {}
    effective_preferences = raw_preferences or preferences
    safe_preferences = _safe_teable_preferences(effective_preferences)
    commercial = _property_commercial_snapshot(effective_preferences)
    commercial_json = dict(commercial.get("property_commercial") or {})
    safe_commercial_json = _safe_commercial_json(commercial_json)
    preference_person_id = _text(effective_preferences.get("preference_person_id") or "self", limit=120) or "self"

    tenants: dict[str, dict[str, object]] = {
        f"tenant:{normalized_tenant}": {
            "projection_id": f"tenant:{normalized_tenant}",
            "tenant_key": normalized_tenant,
            "tenant_name": normalized_tenant_name,
            "source_system": "propertyquarry",
            "privacy_scope": "operator_private",
            "sync_version": "propertyquarry_teable_projection_v1",
            "last_projected_at": projected_at,
        }
    }
    users: dict[str, dict[str, object]] = {}
    subscriptions: dict[str, dict[str, object]] = {}
    preference_rows: dict[str, dict[str, object]] = {}
    search_run_rows: dict[str, dict[str, object]] = {}
    provider_source_rows: dict[str, dict[str, object]] = {}
    property_rows: dict[str, dict[str, object]] = {}
    evaluation_rows: dict[str, dict[str, object]] = {}
    review_artifact_rows: dict[str, dict[str, object]] = {}
    research_task_rows: dict[str, dict[str, object]] = {}

    if normalized_principal:
        users[f"user:{normalized_tenant}:{normalized_principal}"] = {
            "projection_id": f"user:{normalized_tenant}:{normalized_principal}",
            "tenant_key": normalized_tenant,
            "principal_id": normalized_principal,
            "workspace_name": _text(workspace.get("name"), limit=200),
            "workspace_mode": _text(status.get("workspace_mode") or workspace.get("mode"), limit=80),
            "region": _text(status.get("region") or workspace.get("region"), limit=80),
            "language": _text(status.get("language") or workspace.get("language"), limit=80),
            "timezone": _text(status.get("timezone") or workspace.get("timezone"), limit=80),
            "selected_channels_json": list(status.get("selected_channels") or []),
            "current_plan_key": _text(commercial.get("current_plan_key"), limit=80),
            "subscription_status": _text(commercial.get("status"), limit=80),
            "is_paid": bool(commercial.get("is_paid")),
            "last_projected_at": projected_at,
        }
        subscriptions[f"subscription:{normalized_tenant}:{normalized_principal}"] = {
            "projection_id": f"subscription:{normalized_tenant}:{normalized_principal}",
            "tenant_key": normalized_tenant,
            "principal_id": normalized_principal,
            "current_plan_key": _text(commercial.get("current_plan_key"), limit=80),
            "current_plan_label": _text(commercial.get("current_plan_label"), limit=120),
            "status": _text(commercial.get("status"), limit=80),
            "active_until": _text(commercial.get("active_until"), limit=120),
            "is_paid": bool(commercial.get("is_paid")),
            "pending_plan_key": _text(commercial.get("pending_plan_key"), limit=80),
            "plan_source": _text(safe_commercial_json.get("plan_source"), limit=120),
            "last_order_id": _text(safe_commercial_json.get("last_order_id"), limit=160),
            "last_capture_id": _text(safe_commercial_json.get("last_capture_id"), limit=160),
            "last_payment_status": _text(safe_commercial_json.get("last_payment_status"), limit=120),
            "last_payment_amount_eur": _text(safe_commercial_json.get("last_payment_amount_eur"), limit=80),
            "captured_at": _text(safe_commercial_json.get("captured_at"), limit=120),
            "commercial_json": safe_commercial_json,
            "last_projected_at": projected_at,
        }
        preference_rows[f"preferences:{normalized_tenant}:{normalized_principal}:{preference_person_id}"] = {
            "projection_id": f"preferences:{normalized_tenant}:{normalized_principal}:{preference_person_id}",
            "tenant_key": normalized_tenant,
            "principal_id": normalized_principal,
            "preference_person_id": preference_person_id,
            "country_code": _text(effective_preferences.get("country_code"), limit=20),
            "language_code": _text(effective_preferences.get("language_code"), limit=20),
            "listing_mode": _text(effective_preferences.get("listing_mode"), limit=40),
            "property_type": _text(effective_preferences.get("property_type"), limit=80),
            "location_query": _text(effective_preferences.get("location_query"), limit=240),
            "keywords": _text(effective_preferences.get("keywords"), limit=240),
            "selected_platforms_json": list(effective_preferences.get("selected_platforms") or []),
            "max_price_eur": _number(effective_preferences.get("max_price_eur")),
            "min_rooms": _number(effective_preferences.get("min_rooms")),
            "min_area_m2": _number(effective_preferences.get("min_area_m2")),
            "max_results_per_source": _number(effective_preferences.get("max_results_per_source")),
            "use_stored_feedback_preferences": bool(effective_preferences.get("use_stored_feedback_preferences", True)),
            "alert_frequency": _text(effective_preferences.get("alert_frequency"), limit=80),
            "preferences_json": safe_preferences,
            "last_projected_at": projected_at,
        }

    for run in search_runs:
        if not isinstance(run, dict):
            continue
        run_id = _text(run.get("run_id"), limit=180)
        if not run_id:
            continue
        run_principal = _text(run.get("principal_id") or normalized_principal, limit=240)
        if normalized_principal and run_principal != normalized_principal:
            continue
        summary = dict(run.get("summary") or {})
        run_preferences = dict(run.get("property_search_preferences") or {})
        safe_run_preferences = _safe_teable_preferences(run_preferences)
        search_run_rows[f"search_run:{run_id}"] = {
            "projection_id": f"search_run:{run_id}",
            "tenant_key": normalized_tenant,
            "principal_id": run_principal,
            "run_id": run_id,
            "status": _text(run.get("status"), limit=80),
            "status_url": _text(run.get("status_url"), limit=240),
            "selected_platforms_json": list(run.get("selected_platforms") or []),
            "preferences_json": safe_run_preferences,
            "created_at": _text(run.get("created_at"), limit=120),
            "updated_at": _text(run.get("updated_at"), limit=120),
            "generated_at": _text(run.get("generated_at"), limit=120),
            "sources_total": _number(summary.get("sources_total")),
            "listing_total": _number(summary.get("listing_total")),
            "high_fit_total": _number(summary.get("high_fit_total")),
            "review_created_total": _number(summary.get("review_created_total")),
            "review_existing_total": _number(summary.get("review_existing_total")),
            "tour_created_total": _number(summary.get("tour_created_total")),
            "tour_existing_total": _number(summary.get("tour_existing_total")),
            "provider_cache_hit_total": _number(summary.get("provider_cache_hit_total")),
            "provider_cache_refresh_total": _number(summary.get("provider_cache_refresh_total")),
            "filtered_area_total": _number(summary.get("filtered_area_total")),
            "filtered_low_fit_total": _number(summary.get("filtered_low_fit_total")),
            "research_task_total": _number(run.get("research_task_total") or summary.get("research_task_total")),
            "open_research_task_total": _number(run.get("open_research_task_total") or summary.get("open_research_task_total")),
            "summary_json": summary,
            "last_projected_at": projected_at,
        }
        for source_index, source in enumerate(_source_rows_from_run(run), start=1):
            source_url = _text(source.get("source_url"), limit=1000)
            source_label = _text(source.get("source_label"), limit=200)
            source_ref = _stable_ref(source_url or f"{run_id}:{source_label}:{source_index}", prefix="source")
            provider_filter_pushdown = (
                dict(source.get("provider_filter_pushdown") or {})
                if isinstance(source.get("provider_filter_pushdown"), dict)
                else {}
            )
            provider_cache = dict(source.get("provider_cache") or {}) if isinstance(source.get("provider_cache"), dict) else {}
            applied_pushdown = (
                dict(provider_filter_pushdown.get("applied") or {})
                if isinstance(provider_filter_pushdown.get("applied"), dict)
                else {}
            )
            cache_key = _text(
                source.get("provider_cache_key")
                or provider_cache.get("cache_key")
                or provider_filter_pushdown.get("cache_key"),
                limit=240,
            )
            platform = _text(source.get("platform"), limit=120)
            if not platform and ":" in cache_key:
                platform = _text(cache_key.split(":", 1)[0], limit=120)
            provider_source_rows[f"provider_source:{run_id}:{source_ref}"] = {
                "projection_id": f"provider_source:{run_id}:{source_ref}",
                "tenant_key": normalized_tenant,
                "principal_id": run_principal,
                "run_id": run_id,
                "source_ref": source_ref,
                "source_label": source_label,
                "source_url": source_url,
                "platform": platform,
                "preference_person_id": _text(source.get("preference_person_id") or preference_person_id, limit=120),
                "provider_cache_key": cache_key,
                "provider_cache_status": _text(provider_cache.get("status"), limit=80),
                "provider_cache_stale": bool(provider_cache.get("stale") or provider_cache.get("status") == "stale_fallback"),
                "raw_listing_total": _number(source.get("raw_listing_total")),
                "scanned_listing_total": _number(source.get("scanned_listing_total")),
                "listing_total": _number(source.get("listing_total")),
                "duplicate_listing_total": _number(source.get("duplicate_listing_total")),
                "filtered_area_total": _number(source.get("filtered_area_total")),
                "filtered_low_fit_total": _number(source.get("filtered_low_fit_total")),
                "filtered_floorplan_total": _number(source.get("filtered_floorplan_total")),
                "high_fit_total": _number(source.get("high_fit_total")),
                "top_fit_score": _number(source.get("top_fit_score")),
                "scan_truncated": bool(source.get("scan_truncated")),
                "min_area_m2": _number(source.get("min_area_m2") or applied_pushdown.get("min_area_m2")),
                "max_price_eur": _number(applied_pushdown.get("max_price_eur")),
                "min_rooms": _number(applied_pushdown.get("min_rooms")),
                "provider_filter_pushdown_json": provider_filter_pushdown,
                "provider_cache_json": provider_cache,
                "source_json": _safe_source_summary(
                    source,
                    source_label=source_label,
                    platform=platform,
                    source_url=source_url,
                ),
                "last_projected_at": projected_at,
            }
        for candidate in _candidate_rows_from_run(run):
            property_url = _text(candidate.get("property_url"), limit=1000)
            if not property_url:
                continue
            property_ref = _stable_ref(property_url, prefix="property")
            facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
            safe_facts = _safe_teable_facts(facts)
            property_rows[property_ref] = {
                "projection_id": property_ref,
                "tenant_key": normalized_tenant,
                "property_ref": property_ref,
                "property_url": property_url,
                "listing_id": _text(candidate.get("listing_id") or property_url, limit=200),
                "title": _text(candidate.get("title"), limit=240),
                "source_label": _text(candidate.get("source_label"), limit=200),
                "area_sqm": _number(safe_facts.get("area_sqm") or safe_facts.get("living_area_sqm")),
                "rooms": _number(safe_facts.get("rooms") or safe_facts.get("room_count")),
                "total_rent_eur": _number(safe_facts.get("total_rent_eur") or safe_facts.get("rent_eur")),
                "purchase_price_eur": _number(safe_facts.get("purchase_price_eur") or safe_facts.get("price_eur")),
                "postal_name": _text(safe_facts.get("postal_name") or safe_facts.get("district") or safe_facts.get("location"), limit=160),
                "property_type": _text(safe_facts.get("property_type"), limit=120),
                "facts_json": safe_facts,
                "last_seen_run_id": run_id,
                "last_seen_at": _text(run.get("updated_at") or run.get("generated_at") or projected_at, limit=120),
            }
            evaluation_id = f"evaluation:{run_principal}:{run_id}:{property_ref}"
            evaluation_rows[evaluation_id] = {
                "projection_id": evaluation_id,
                "tenant_key": normalized_tenant,
                "principal_id": run_principal,
                "run_id": run_id,
                "property_ref": property_ref,
                "property_url": property_url,
                "source_ref": _text(candidate.get("source_ref"), limit=240),
                "source_label": _text(candidate.get("source_label"), limit=200),
                "fit_score": _number(candidate.get("fit_score")),
                "recommendation": _text(candidate.get("recommendation"), limit=160),
                "fit_summary": _text(candidate.get("fit_summary"), limit=240),
                "review_url": _text(candidate.get("review_url"), limit=1000),
                "tour_url": _text(candidate.get("tour_url"), limit=1000),
                "tour_status": _text(candidate.get("tour_status"), limit=80),
                "match_reasons_json": list(candidate.get("match_reasons") or []),
                "mismatch_reasons_json": list(candidate.get("mismatch_reasons") or []),
                "assessment_json": dict(candidate.get("assessment") or {}) if isinstance(candidate.get("assessment"), dict) else {},
                "facts_json": safe_facts,
                "last_projected_at": projected_at,
            }
            review_url = _text(candidate.get("review_url"), limit=1000)
            tour_url = _text(candidate.get("tour_url"), limit=1000)
            review_task_id = _text(candidate.get("review_task_id") or candidate.get("human_task_id"), limit=240)
            if review_url or tour_url or review_task_id:
                review_status = _text(candidate.get("review_status"), limit=80)
                if not review_status and review_url:
                    review_status = "ready"
                review_artifact_id = f"review_artifact:{run_principal}:{run_id}:{property_ref}"
                review_artifact_rows[review_artifact_id] = {
                    "projection_id": review_artifact_id,
                    "tenant_key": normalized_tenant,
                    "principal_id": run_principal,
                    "run_id": run_id,
                    "property_ref": property_ref,
                    "property_url": property_url,
                    "source_ref": _text(candidate.get("source_ref"), limit=240),
                    "source_label": _text(candidate.get("source_label"), limit=200),
                    "review_url": review_url,
                    "review_status": review_status,
                    "review_task_id": review_task_id,
                    "review_task_status": _text(candidate.get("review_task_status"), limit=80),
                    "review_reused": bool(candidate.get("review_reused")),
                    "queue_item_ref": _text(candidate.get("queue_item_ref"), limit=240),
                    "recommended_task_key": _text(candidate.get("recommended_task_key"), limit=240),
                    "tour_url": tour_url,
                    "tour_status": _text(candidate.get("tour_status"), limit=80),
                    "tour_blocked_reason": _text(candidate.get("blocked_reason") or candidate.get("tour_blocked_reason"), limit=240),
                    "fit_score": _number(candidate.get("fit_score")),
                    "recommendation": _text(candidate.get("recommendation"), limit=160),
                    "preference_person_id": _text(candidate.get("preference_person_id") or preference_person_id, limit=120),
                    "artifact_json": _safe_review_artifact(candidate, safe_facts=safe_facts),
                    "last_projected_at": projected_at,
                }
        for task in list(run.get("research_tasks") or summary.get("research_tasks") or []):
            if not isinstance(task, dict):
                continue
            task_id = _text(task.get("task_id") or task.get("id"), limit=240)
            if not task_id:
                continue
            property_url = _text(task.get("property_url"), limit=1000)
            property_ref = _stable_ref(property_url or f"{run_id}:{task_id}", prefix="property")
            research_task_rows[f"research_task:{run_id}:{task_id}"] = {
                "projection_id": f"research_task:{run_id}:{task_id}",
                "tenant_key": normalized_tenant,
                "principal_id": run_principal,
                "run_id": run_id,
                "task_id": task_id,
                "status": _text(task.get("status"), limit=80),
                "field_key": _text(task.get("field_key") or task.get("key"), limit=160),
                "label": _text(task.get("label"), limit=240),
                "question": _text(task.get("question"), limit=1000),
                "property_ref": property_ref,
                "property_url": property_url,
                "value": _text(task.get("value"), limit=240),
                "note": _text(task.get("note"), limit=1000),
                "task_json": task,
                "last_projected_at": projected_at,
            }

    return {
        "propertyquarry_tenants": _table_rows(tenants),
        "propertyquarry_users": _table_rows(users),
        "propertyquarry_subscriptions": _table_rows(subscriptions),
        "propertyquarry_preferences": _table_rows(preference_rows),
        "propertyquarry_search_runs": _table_rows(search_run_rows),
        "propertyquarry_provider_sources": _table_rows(provider_source_rows),
        "propertyquarry_properties": _table_rows(property_rows),
        "propertyquarry_property_evaluations": _table_rows(evaluation_rows),
        "propertyquarry_review_artifacts": _table_rows(review_artifact_rows),
        "propertyquarry_research_tasks": _table_rows(research_task_rows),
    }


def build_propertyquarry_teable_projection_summary(records: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    return {
        "projection_scope": "propertyquarry",
        "tenant_key": propertyquarry_teable_tenant_key(),
        "api_key_present": bool(str(os.environ.get("TEABLE_API_KEY") or "").strip()),
        "tables": [
            {
                "table_name": table_name,
                "record_count": len(records.get(table_name) or []),
                "sample_keys": sorted((records.get(table_name) or [{}])[0].keys()) if records.get(table_name) else [],
            }
            for table_name in PROPERTYQUARRY_TEABLE_TABLE_NAMES
        ],
    }
