from __future__ import annotations

import copy
from dataclasses import dataclass

from app.domain.models import now_utc_iso
from app.services.fliplink.models import PacketPrivacyMode


REDACTION_POLICY_VERSION = "property_packet_v1"

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


def _fact_allowlist_for(privacy_mode: PacketPrivacyMode, *, include_exact_address: bool) -> set[str]:
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
    removed: list[str],
) -> dict[str, object]:
    allowed = _fact_allowlist_for(privacy_mode, include_exact_address=include_exact_address)
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


def redact_property_packet(
    *,
    source: dict[str, object],
    privacy_mode: PacketPrivacyMode,
    include_exact_address: bool = False,
) -> RedactionResult:
    removed: list[str] = []
    for key in source:
        if _key_private(key):
            removed.append(str(key or "").strip())
    facts = dict(source.get("property_facts") or source.get("facts") or {}) if isinstance(source.get("property_facts") or source.get("facts"), dict) else {}
    redacted_facts = _redact_facts(
        facts,
        privacy_mode=privacy_mode,
        include_exact_address=include_exact_address,
        removed=removed,
    )
    payload = {
        "title": str(source.get("title") or source.get("property_title") or "PropertyQuarry packet").strip(),
        "property_ref": str(source.get("property_ref") or "").strip(),
        "property_url": str(source.get("property_url") or source.get("source_url") or "").strip(),
        "source_label": str(source.get("source_label") or "PropertyQuarry").strip(),
        "fit_summary": str(source.get("fit_summary") or source.get("summary") or "").strip(),
        "recommendation": str(source.get("recommendation") or "").strip(),
        "match_reasons": _list_text(source.get("match_reasons")),
        "mismatch_reasons": _list_text(source.get("mismatch_reasons")),
        "unknowns": _list_text(source.get("unknowns") or source.get("open_questions")),
        "viewing_questions": _list_text(source.get("viewing_questions") or source.get("questions")),
        "facts": redacted_facts,
    }
    if privacy_mode == PacketPrivacyMode.ANONYMOUS_PUBLIC:
        payload.pop("fit_summary", None)
        payload["recommendation"] = "public_summary"
    payload = _redact_value(payload, removed=removed, path="")
    if not isinstance(payload, dict):
        payload = {}
    receipt = {
        "redaction_policy_version": REDACTION_POLICY_VERSION,
        "privacy_mode": privacy_mode.value,
        "source_refs": [
            str(source.get("property_ref") or "").strip(),
            str(source.get("search_run_id") or "").strip(),
        ],
        "removed_fields": sorted(set(item for item in removed if item)),
        "allowed_fact_keys": sorted(_fact_allowlist_for(privacy_mode, include_exact_address=include_exact_address)),
        "generated_at": now_utc_iso(),
    }
    assert_redacted_packet_safe(payload=payload, privacy_mode=privacy_mode, include_exact_address=include_exact_address)
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
) -> None:
    forbidden = _walk_forbidden(payload)
    facts = dict(payload.get("facts") or {}) if isinstance(payload.get("facts"), dict) else {}
    if privacy_mode in {PacketPrivacyMode.ANONYMOUS_PUBLIC, PacketPrivacyMode.PAID_CUSTOMER} or not include_exact_address:
        for key in EXACT_ADDRESS_KEYS:
            if key in facts and privacy_mode != PacketPrivacyMode.OWNER_PRIVATE:
                forbidden.append(f"facts.{key}")
    if forbidden:
        raise ValueError("fliplink_packet_redaction_failed:" + ",".join(sorted(set(forbidden))[:20]))
