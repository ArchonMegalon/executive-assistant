from __future__ import annotations

import copy
import os
import urllib.parse
from dataclasses import dataclass

from app.domain.models import now_utc_iso
from app.services.fliplink.models import PacketPrivacyMode, PropertyPacketKind


REDACTION_POLICY_VERSION = "property_packet_v2"

PRIVATE_KEY_MARKERS = {
    "principal",
    "recipient",
    "preference",
    "learning",
    "shortlist",
    "raw_signal",
    "authorization",
    "cookie",
    "session",
    "token",
    "secret",
    "oauth",
    "credential",
    "internal",
}

EXACT_ADDRESS_KEYS = {
    "exact_address",
    "street_address",
    "address_lines",
    "address_line",
    "house_number",
    "door_number",
    "map_lat",
    "map_lng",
    "latitude",
    "longitude",
    "lat",
    "lng",
}

FLOORPLAN_REF_KEYS = {"floorplan_refs", "floorplans", "floorplan_urls", "floorplan_url", "floorplan_pdf_url", "floorplan_urls_json"}
PHOTO_REF_KEYS = {"photo_refs", "photos", "image_urls", "images", "photo_urls", "primary_image_url", "media_urls_json", "panorama_media_urls_json"}
DEFAULT_MEDIA_ALLOWED_HOSTS = (
    "propertyquarry.com",
    "*.propertyquarry.com",
    "storage.justimmo.at",
    "*.justimmo.at",
    "kalandra.at",
    "*.kalandra.at",
    "willhaben.at",
    "*.willhaben.at",
    "immobilienscout24.at",
    "*.immobilienscout24.at",
    "immobilienscout24.de",
    "*.immobilienscout24.de",
    "immowelt.de",
    "*.immowelt.de",
)
SENSITIVE_MEDIA_QUERY_MARKERS = ("token=", "secret=", "session=", "cookie=", "signature=", "signed=")
PHOTO_MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
FLOORPLAN_MEDIA_HINTS = ("floorplan", "floor-plan", "grundriss", "plan", "layout", "pdf")

BASE_PUBLIC_FACT_KEYS = {
    "rooms",
    "room_count",
    "area_sqm",
    "area_m2",
    "living_area_m2",
    "total_rent_eur",
    "rent_eur",
    "purchase_price_eur",
    "price_eur",
    "price_display",
    "rent_display",
    "district",
    "postal_name",
    "city",
    "country",
    "has_floorplan",
    "floorplan_count",
    "lift",
    "has_lift",
    "balcony",
    "terrace",
    "garden",
    "outdoor_space",
    "heating_type",
    "parking_monthly_eur",
    "availability",
    "building_type",
    "building_style",
    "building_year",
    "year_built",
    "construction_year",
    "nearest_library_m",
    "nearest_library_name",
    "nearest_tram_bus_m",
    "nearest_tram_bus_name",
    "nearest_running_m",
    "nearest_running_name",
    "nearest_medical_care_m",
    "nearest_medical_care_name",
    "nearest_hospital_m",
    "nearest_hospital_name",
    "nearest_cycleway_m",
    "nearest_cycleway_name",
    "nearest_bicycle_parking_m",
    "nearest_bicycle_parking_name",
    "nearest_school_m",
    "nearest_school_name",
    "air_quality_risk",
    "crime_risk",
    "parking_pressure_risk",
    "flood_risk",
    "official_risk_evidence",
    "future_change_research",
    "school_atlas_quality_summary",
    "school_atlas_progression_summary",
    "school_atlas_gymnasium_progression_pct",
    "school_atlas_top_secondary_destinations",
    "school_atlas_nearby_schools",
    "school_atlas_selected_school",
    "school_atlas_evidence_type",
    "school_atlas_source_url",
}

PAID_MARKET_REPORT_FACT_KEYS = {
    "market_scope",
    "market_scope_label",
    "district",
    "city",
    "country",
    "freshness_date",
    "coverage_window",
    "data_coverage",
    "source_coverage",
    "data_sources",
    "methodology",
    "listing_count",
    "sample_size",
    "market_buy_per_sqm_eur",
    "market_rent_per_sqm_eur",
    "median_price_eur",
    "median_rent_eur",
    "median_price_per_sqm_eur",
    "median_rent_per_sqm_eur",
    "price_per_sqm_range_eur",
    "rent_per_sqm_range_eur",
    "gross_yield_pct",
    "payback_years",
    "market_examples",
    "exclusions",
    "accuracy_notes",
    "legal_disclaimer",
}

PUBLIC_FACT_ALLOWLIST_BY_MODE: dict[PacketPrivacyMode, set[str]] = {
    PacketPrivacyMode.ANONYMOUS_PUBLIC: {
        *BASE_PUBLIC_FACT_KEYS,
    },
    PacketPrivacyMode.PAID_CUSTOMER: {
        *BASE_PUBLIC_FACT_KEYS,
        "market_buy_per_sqm_eur",
        "market_rent_per_sqm_eur",
        "gross_yield_pct",
        "payback_years",
        "methodology",
        "freshness_date",
    },
    PacketPrivacyMode.AGENT_SHARE: {
        *BASE_PUBLIC_FACT_KEYS,
        "nearest_supermarket_m",
        "nearest_pharmacy_m",
        "nearest_subway_m",
        "nearest_playground_m",
        "nearest_supermarket_name",
        "nearest_pharmacy_name",
        "nearest_subway_name",
        "nearest_playground_name",
    },
    PacketPrivacyMode.FAMILY_REVIEW: {
        *BASE_PUBLIC_FACT_KEYS,
        "nearest_supermarket_m",
        "nearest_pharmacy_m",
        "nearest_subway_m",
        "nearest_playground_m",
        "nearest_supermarket_name",
        "nearest_pharmacy_name",
        "nearest_subway_name",
        "nearest_playground_name",
    },
    PacketPrivacyMode.OWNER_PRIVATE: {
        *BASE_PUBLIC_FACT_KEYS,
        *EXACT_ADDRESS_KEYS,
        "source_listing_id",
        "provider_listing_id",
        "nearest_supermarket_m",
        "nearest_pharmacy_m",
        "nearest_subway_m",
        "nearest_playground_m",
        "nearest_supermarket_name",
        "nearest_pharmacy_name",
        "nearest_subway_name",
        "nearest_playground_name",
        "investment_snapshot",
        "market_buy_per_sqm_eur",
        "market_rent_per_sqm_eur",
        "gross_yield_pct",
        "payback_years",
    },
}


@dataclass(frozen=True)
class RedactionResult:
    payload: dict[str, object]
    receipt: dict[str, object]


def _key_private(key: object) -> bool:
    normalized = str(key or "").strip().lower()
    return any(marker in normalized for marker in PRIVATE_KEY_MARKERS)


def _redact_value(value: object, *, removed: list[str], path: str) -> object:
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, child in value.items():
            normalized_key = str(key or "").strip()
            child_path = f"{path}.{normalized_key}" if path else normalized_key
            if _key_private(normalized_key):
                removed.append(child_path)
                continue
            out[normalized_key] = _redact_value(child, removed=removed, path=child_path)
        return out
    if isinstance(value, list):
        return [
            _redact_value(child, removed=removed, path=f"{path}[{index}]")
            for index, child in enumerate(value[:100])
        ]
    return copy.deepcopy(value)


def _is_paid_market_report(packet_kind: object) -> bool:
    raw = packet_kind.value if isinstance(packet_kind, PropertyPacketKind) else str(packet_kind or "").strip().lower()
    return raw == PropertyPacketKind.PAID_MARKET_REPORT.value


def _fact_allowlist_for(
    privacy_mode: PacketPrivacyMode,
    *,
    include_exact_address: bool,
    packet_kind: object = None,
) -> set[str]:
    if _is_paid_market_report(packet_kind):
        return set(PAID_MARKET_REPORT_FACT_KEYS)
    allowed = set(PUBLIC_FACT_ALLOWLIST_BY_MODE.get(privacy_mode) or set())
    if include_exact_address and privacy_mode in {PacketPrivacyMode.AGENT_SHARE, PacketPrivacyMode.FAMILY_REVIEW, PacketPrivacyMode.OWNER_PRIVATE}:
        allowed.update(EXACT_ADDRESS_KEYS)
    if privacy_mode == PacketPrivacyMode.OWNER_PRIVATE:
        allowed.update(EXACT_ADDRESS_KEYS)
    return allowed


def _redact_facts(
    facts: dict[str, object],
    *,
    privacy_mode: PacketPrivacyMode,
    include_exact_address: bool,
    packet_kind: object = None,
    removed: list[str],
) -> dict[str, object]:
    allowed = _fact_allowlist_for(privacy_mode, include_exact_address=include_exact_address, packet_kind=packet_kind)
    out: dict[str, object] = {}
    for key, value in facts.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if normalized_key not in allowed or _key_private(normalized_key):
            removed.append(f"facts.{normalized_key}")
            continue
        if normalized_key in EXACT_ADDRESS_KEYS and normalized_key not in allowed:
            removed.append(f"facts.{normalized_key}")
            continue
        out[normalized_key] = _redact_value(value, removed=removed, path=f"facts.{normalized_key}")
    return out


def _list_text(value: object, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value[:limit] if str(item or "").strip()]


def _text(value: object, *, limit: int = 240) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _market_scope_label(source: dict[str, object], facts: dict[str, object]) -> str:
    for key in ("market_scope", "market_scope_label", "report_scope", "district", "city", "country"):
        value = _text(source.get(key) or facts.get(key), limit=180)
        if value:
            return value
    parts = [_text(facts.get(key), limit=80) for key in ("district", "city", "country")]
    return ", ".join(part for part in parts if part)


def _public_magic_fit_scene(source: dict[str, object], *, privacy_mode: PacketPrivacyMode, removed: list[str]) -> dict[str, object]:
    raw = dict(source.get("magic_fit_scene") or {}) if isinstance(source.get("magic_fit_scene"), dict) else {}
    if privacy_mode not in {PacketPrivacyMode.OWNER_PRIVATE, PacketPrivacyMode.FAMILY_REVIEW, PacketPrivacyMode.AGENT_SHARE}:
        if raw:
            removed.append("magic_fit_scene.privacy_mode_omitted")
        return {}
    if not raw or not bool(raw.get("share_with_packet_pdf")):
        return {}
    scene = {
        "scene_id": _text(raw.get("scene_id"), limit=120),
        "scene_type": _text(raw.get("scene_type"), limit=80),
        "room_hint": _text(raw.get("room_hint"), limit=160),
        "summary": _text(raw.get("summary"), limit=240),
        "image_url": _text(raw.get("image_url"), limit=2000),
        "reference_urls": _list_text(raw.get("reference_urls"), limit=3),
        "visual_simulation": bool(raw.get("visual_simulation", True)),
        "generated_at": _text(raw.get("generated_at"), limit=80),
    }
    if not scene["image_url"]:
        removed.append("magic_fit_scene.image_url_missing")
        return {}
    return scene


def _public_diorama_scene(source: dict[str, object], *, privacy_mode: PacketPrivacyMode, removed: list[str]) -> dict[str, object]:
    raw = dict(source.get("diorama_scene") or {}) if isinstance(source.get("diorama_scene"), dict) else {}
    if privacy_mode not in {PacketPrivacyMode.OWNER_PRIVATE, PacketPrivacyMode.FAMILY_REVIEW, PacketPrivacyMode.AGENT_SHARE}:
        if raw:
            removed.append("diorama_scene.privacy_mode_omitted")
        return {}
    if not raw or not bool(raw.get("share_with_packet_pdf", True)):
        return {}
    scene = {
        "scene_id": _text(raw.get("scene_id"), limit=120),
        "scene_type": _text(raw.get("scene_type"), limit=80),
        "summary": _text(raw.get("summary"), limit=240),
        "image_url": _text(raw.get("image_url"), limit=2000),
        "tour_url": _text(raw.get("tour_url"), limit=2000),
        "video_url": _text(raw.get("video_url"), limit=2000),
        "generated_at": _text(raw.get("generated_at"), limit=80),
    }
    if not scene["image_url"]:
        removed.append("diorama_scene.image_url_missing")
        return {}
    return scene


def _public_personal_reference_urls(source: dict[str, object], *, privacy_mode: PacketPrivacyMode, removed: list[str]) -> list[str]:
    if privacy_mode not in {PacketPrivacyMode.OWNER_PRIVATE, PacketPrivacyMode.FAMILY_REVIEW, PacketPrivacyMode.AGENT_SHARE}:
        if source.get("personal_reference_urls"):
            removed.append("personal_reference_urls.privacy_mode_omitted")
        return []
    return _list_text(source.get("personal_reference_urls"), limit=3)


def _media_allowed_hosts() -> set[str]:
    raw = str(os.getenv("FLIPLINK_PACKET_MEDIA_ALLOWED_HOSTS") or "").strip()
    values = raw.split(",") if raw else list(DEFAULT_MEDIA_ALLOWED_HOSTS)
    return {str(item or "").strip().lower().rstrip(".") for item in values if str(item or "").strip()}


def _media_host_allowed(host: str, allowed_hosts: set[str]) -> bool:
    normalized = str(host or "").strip().lower().rstrip(".")
    if not normalized:
        return False
    for allowed in allowed_hosts:
        if normalized == allowed:
            return True
        if allowed.startswith("*.") and normalized.endswith("." + allowed[2:]):
            return True
    return False


def _normalized_media_extension(parsed: urllib.parse.ParseResult) -> str:
    suffix = os.path.splitext(str(parsed.path or "").strip().lower())[1]
    return suffix


def _photo_media_ref_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    suffix = _normalized_media_extension(parsed)
    lowered = url.lower()
    basename = os.path.basename(str(parsed.path or "").strip().lower())
    if basename.startswith("magicfit-still-"):
        return suffix in PHOTO_MEDIA_EXTENSIONS
    path_parts = [part for part in str(parsed.path or "").strip().lower().split("/") if part]
    relevant_parts = [basename, *path_parts[-2:]]
    if any(marker in part for marker in FLOORPLAN_MEDIA_HINTS for part in relevant_parts if part):
        return False
    return suffix in PHOTO_MEDIA_EXTENSIONS


def _dedupe_media_key(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = str(parsed.hostname or "").strip().lower()
    path = str(parsed.path or "").strip().lower()
    if "/thumb/" in path:
        path = path.split("/thumb/", 1)[1]
    elif "/file/" in path:
        path = path.split("/file/", 1)[1]
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"{host}|{stem or path}"


def _public_media_refs(source: dict[str, object], keys: set[str], *, removed: list[str], limit: int = 16) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    allowed_hosts = _media_allowed_hosts()
    photo_mode = keys == PHOTO_REF_KEYS
    for key in keys:
        raw = source.get(key)
        values = raw if isinstance(raw, list) else ([raw] if raw else [])
        for index, value in enumerate(values):
            if isinstance(value, dict):
                value = value.get("url") or value.get("href") or value.get("src")
            text = str(value or "").strip()
            if not text:
                continue
            parsed = urllib.parse.urlparse(text)
            if parsed.scheme.lower() != "https" or not parsed.hostname:
                removed.append(f"{key}[{index}].non_https_media_ref")
                continue
            lowered = text.lower()
            if any(marker in lowered for marker in SENSITIVE_MEDIA_QUERY_MARKERS):
                removed.append(f"{key}[{index}].sensitive_media_query")
                continue
            if not _media_host_allowed(parsed.hostname, allowed_hosts):
                removed.append(f"{key}[{index}].host_not_allowed:{str(parsed.hostname or '').lower()}")
                continue
            if photo_mode and not _photo_media_ref_allowed(text):
                removed.append(f"{key}[{index}].non_photo_asset")
                continue
            dedupe_key = _dedupe_media_key(text)
            if dedupe_key in seen:
                removed.append(f"{key}[{index}].duplicate_media_ref")
                continue
            seen.add(dedupe_key)
            refs.append(text[:1000])
            if len(refs) >= limit:
                return refs
    return refs


def redact_property_packet(
    *,
    source: dict[str, object],
    privacy_mode: PacketPrivacyMode,
    packet_kind: object = None,
    include_exact_address: bool = False,
    include_floorplan: bool = True,
    include_photos: bool = True,
) -> RedactionResult:
    removed: list[str] = []
    paid_market_report = _is_paid_market_report(packet_kind)
    for key in source:
        if _key_private(key):
            removed.append(str(key or "").strip())
    fact_source = source.get("property_facts") or source.get("property_facts_json") or source.get("facts") or {}
    facts = dict(fact_source) if isinstance(fact_source, dict) else {}
    redacted_facts = _redact_facts(
        facts,
        privacy_mode=privacy_mode,
        include_exact_address=include_exact_address,
        packet_kind=packet_kind,
        removed=removed,
    )
    if paid_market_report:
        market_scope = _market_scope_label(source, {**facts, **redacted_facts})
        market_title = _text(source.get("market_report_title") or source.get("report_title"), limit=240)
        if not market_title:
            market_title = f"{market_scope} market report" if market_scope else "PropertyQuarry market report"
        payload = {
            "title": market_title,
            "market_scope": market_scope,
            "source_label": "PropertyQuarry market research",
            "fit_summary": _text(
                source.get("market_summary")
                or source.get("report_summary")
                or "Market-level report generated from redacted PropertyQuarry research.",
                limit=900,
            ),
            "recommendation": _text(source.get("market_recommendation") or "", limit=500),
            "market_observations": _list_text(
                source.get("market_observations")
                or source.get("market_highlights")
                or source.get("market_reasons"),
                limit=12,
            ),
            "market_examples": _list_text(source.get("market_examples") or redacted_facts.get("market_examples"), limit=10),
            "mismatch_reasons": _list_text(source.get("market_risks") or source.get("market_caveats"), limit=8),
            "unknowns": _list_text(source.get("market_exclusions") or source.get("exclusions") or source.get("accuracy_notes"), limit=8),
            "facts": redacted_facts,
        }
        for key in (
            "title",
            "property_title",
            "property_ref",
            "property_url",
            "source_url",
            "fit_summary",
            "summary",
            "recommendation",
            "match_reasons",
            "viewing_questions",
            "questions",
        ):
            if key in source:
                removed.append(key)
        for key in sorted(FLOORPLAN_REF_KEYS | PHOTO_REF_KEYS):
            if key in source:
                removed.append(f"{key}.paid_market_report_omitted")
    else:
        comparison_source = source.get("comparison_rows") or source.get("comparison_candidates")
        comparison_rows: list[dict[str, object]] = []
        if isinstance(comparison_source, list):
            for row in comparison_source[:6]:
                if not isinstance(row, dict):
                    continue
                item = {
                    "title": str(row.get("title") or row.get("property_title") or "").strip(),
                    "price": row.get("price") if isinstance(row.get("price"), (int, float)) else str(row.get("price") or "").strip(),
                    "rooms": row.get("rooms") if isinstance(row.get("rooms"), (int, float)) else str(row.get("rooms") or "").strip(),
                    "area_sqm": row.get("area_sqm") if isinstance(row.get("area_sqm"), (int, float)) else row.get("area"),
                    "recommendation": str(row.get("recommendation") or "").strip(),
                    "compare_reason": str(row.get("compare_reason") or "").strip(),
                    "property_url": str(row.get("property_url") or row.get("source_url") or "").strip(),
                }
                if item["title"]:
                    comparison_rows.append(item)
        payload = {
            "title": str(source.get("title") or source.get("property_title") or "PropertyQuarry packet").strip(),
            "property_ref": str(source.get("property_ref") or "").strip(),
            "property_url": str(source.get("property_url") or source.get("source_url") or "").strip(),
            "tour_url": str(source.get("tour_url") or "").strip(),
            "flythrough_url": str(source.get("flythrough_url") or "").strip(),
            "review_url": str(source.get("review_url") or "").strip(),
            "source_label": str(source.get("source_label") or "PropertyQuarry").strip(),
            "fit_summary": str(source.get("fit_summary") or source.get("summary") or "").strip(),
            "compare_reason": str(source.get("compare_reason") or "").strip(),
            "recommendation": str(source.get("recommendation") or "").strip(),
            "match_reasons": _list_text(source.get("match_reasons")),
            "mismatch_reasons": _list_text(source.get("mismatch_reasons")),
            "unknowns": _list_text(source.get("unknowns") or source.get("open_questions")),
            "viewing_questions": _list_text(source.get("viewing_questions") or source.get("questions")),
            "facts": redacted_facts,
        }
        if comparison_rows:
            payload["comparison_rows"] = comparison_rows
    if include_floorplan and not paid_market_report:
        floorplans = _public_media_refs(source, FLOORPLAN_REF_KEYS, removed=removed, limit=8)
        if floorplans:
            payload["floorplan_refs"] = floorplans
    elif not paid_market_report:
        removed.extend(sorted(key for key in FLOORPLAN_REF_KEYS if key in source))
    if include_photos and not paid_market_report:
        photos = _public_media_refs(source, PHOTO_REF_KEYS, removed=removed, limit=20)
        if photos:
            payload["photo_refs"] = photos
    elif not paid_market_report:
        removed.extend(sorted(key for key in PHOTO_REF_KEYS if key in source))
    if privacy_mode == PacketPrivacyMode.ANONYMOUS_PUBLIC:
        payload.pop("fit_summary", None)
        payload["recommendation"] = "public_summary"
    magic_fit_scene = _public_magic_fit_scene(source, privacy_mode=privacy_mode, removed=removed)
    if magic_fit_scene:
        payload["magic_fit_scene"] = magic_fit_scene
    personal_reference_urls = _public_personal_reference_urls(source, privacy_mode=privacy_mode, removed=removed)
    if personal_reference_urls:
        payload["personal_reference_urls"] = personal_reference_urls
    diorama_scene = _public_diorama_scene(source, privacy_mode=privacy_mode, removed=removed)
    if diorama_scene:
        payload["diorama_scene"] = diorama_scene
    payload = _redact_value(payload, removed=removed, path="")
    if not isinstance(payload, dict):
        payload = {}
    paid_source_refs = [str(source.get("search_run_id") or "").strip()] if paid_market_report else []
    receipt = {
        "redaction_policy_version": REDACTION_POLICY_VERSION,
        "packet_kind": PropertyPacketKind.PAID_MARKET_REPORT.value if paid_market_report else "",
        "privacy_mode": privacy_mode.value,
        "source_refs": [item for item in paid_source_refs if item] if paid_market_report else [
            str(source.get("property_ref") or "").strip(),
            str(source.get("search_run_id") or "").strip(),
        ],
        "removed_fields": sorted(set(item for item in removed if item)),
        "allowed_fact_keys": sorted(
            _fact_allowlist_for(privacy_mode, include_exact_address=include_exact_address, packet_kind=packet_kind)
        ),
        "media_allowed_hosts": sorted(_media_allowed_hosts()),
        "include_floorplan": bool(include_floorplan),
        "include_photos": bool(include_photos),
        "paid_market_report_market_level_only": bool(paid_market_report),
        "generated_at": now_utc_iso(),
    }
    assert_redacted_packet_safe(
        payload=payload,
        privacy_mode=privacy_mode,
        include_exact_address=include_exact_address,
        packet_kind=packet_kind,
    )
    return RedactionResult(payload=payload, receipt=receipt)


def _walk_forbidden(payload: object, *, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = str(key or "").strip()
            child_path = f"{path}.{normalized_key}" if path else normalized_key
            if _key_private(normalized_key):
                found.append(child_path)
            found.extend(_walk_forbidden(value, path=child_path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(_walk_forbidden(value, path=f"{path}[{index}]"))
    return found


def assert_redacted_packet_safe(
    *,
    payload: dict[str, object],
    privacy_mode: PacketPrivacyMode,
    include_exact_address: bool = False,
    packet_kind: object = None,
) -> None:
    forbidden = _walk_forbidden(payload)
    facts = dict(payload.get("facts") or {}) if isinstance(payload.get("facts"), dict) else {}
    if privacy_mode in {PacketPrivacyMode.ANONYMOUS_PUBLIC, PacketPrivacyMode.PAID_CUSTOMER} or not include_exact_address:
        for key in EXACT_ADDRESS_KEYS:
            if key in facts and privacy_mode != PacketPrivacyMode.OWNER_PRIVATE:
                forbidden.append(f"facts.{key}")
    if _is_paid_market_report(packet_kind):
        for key in ("property_ref", "property_url", "floorplan_refs", "photo_refs", "viewing_questions"):
            value = payload.get(key)
            if value:
                forbidden.append(key)
    if forbidden:
        raise ValueError("fliplink_packet_redaction_failed:" + ",".join(sorted(set(forbidden))[:20]))
