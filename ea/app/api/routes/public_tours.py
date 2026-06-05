from __future__ import annotations

from functools import lru_cache
import html
import json
import mimetypes
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.api.dependencies import get_container
from app.container import AppContainer
from app.api.routes.landing import _anonymous_onboarding_status, _public_context, templates as public_templates
from app.product.service import _property_feedback_reason_map, build_product_service
from app.services.public_clickrank import clickrank_head_snippet, request_hostname

router = APIRouter(tags=["public-tours"])


def _fact_value_is_weak(value: object) -> bool:
    if value is None:
        return True
    if value is False:
        return True
    if isinstance(value, (int, float)):
        return float(value) <= 0.0
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple)):
        if not value:
            return True
        return all(_fact_value_is_weak(item) for item in value)
    if isinstance(value, dict):
        return not value
    return False


def _tour_dir() -> Path:
    return Path(str(os.getenv("EA_PUBLIC_TOUR_DIR") or "/docker/fleet/state/public_property_tours")).expanduser()


def _resolved_tour_root() -> Path:
    return _tour_dir().resolve()


def _resolved_tour_bundle(slug: str) -> Path:
    safe = str(slug or "").strip()
    if not safe or "/" in safe or ".." in safe:
        raise HTTPException(status_code=404, detail="tour_not_found")
    root = _resolved_tour_root()
    bundle_dir = (root / safe).resolve()
    if bundle_dir != root and root not in bundle_dir.parents:
        raise HTTPException(status_code=404, detail="tour_not_found")
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        raise HTTPException(status_code=404, detail="tour_not_found")
    return bundle_dir


def _tour_path(slug: str) -> Path:
    safe = str(slug or "").strip()
    if not safe or "/" in safe or ".." in safe:
        raise HTTPException(status_code=404, detail="tour_not_found")
    try:
        bundle_dir = _resolved_tour_bundle(slug)
    except HTTPException:
        bundle_dir = None
    if bundle_dir is not None:
        bundle_manifest = bundle_dir / "tour.json"
        if bundle_manifest.exists():
            return bundle_manifest
    root = _resolved_tour_root()
    candidate = (root / f"{safe}.json").resolve()
    if root not in candidate.parents:
        raise HTTPException(status_code=404, detail="tour_not_found")
    return candidate


def _tour_bundle_dir(slug: str) -> Path | None:
    try:
        return _resolved_tour_bundle(slug)
    except HTTPException:
        return None


def _load_tour(slug: str) -> dict[str, object]:
    path = _tour_path(slug)
    if not path.exists():
        raise HTTPException(status_code=404, detail="tour_not_found")
    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail="tour_payload_invalid") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="tour_payload_invalid")
    return payload


def _asset_file(slug: str, asset_path: str) -> Path:
    bundle_dir = _tour_bundle_dir(slug)
    if bundle_dir is None:
        raise HTTPException(status_code=404, detail="tour_file_not_found")
    candidate = (bundle_dir / str(asset_path or "")).resolve()
    if bundle_dir.resolve() not in candidate.parents:
        raise HTTPException(status_code=404, detail="tour_file_not_found")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="tour_file_not_found")
    return candidate


def _money(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"EUR {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "EUR ?"


def _safe_live_360_url(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return normalized


def _embedded_live_360_url(payload: dict[str, object]) -> str:
    normalized = dict(payload or {})
    return _safe_live_360_url(
        normalized.get("source_virtual_tour_url")
        or normalized.get("source_virtual_tour_origin")
    )


def _haversine_distance_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> int:
    from math import atan2, cos, radians, sin, sqrt

    earth_radius_m = 6_371_000.0
    phi_a = radians(lat_a)
    phi_b = radians(lat_b)
    delta_phi = radians(lat_b - lat_a)
    delta_lambda = radians(lon_b - lon_a)
    arc = sin(delta_phi / 2.0) ** 2 + cos(phi_a) * cos(phi_b) * sin(delta_lambda / 2.0) ** 2
    return int(round(2.0 * earth_radius_m * atan2(sqrt(arc), sqrt(max(1.0 - arc, 0.0)))))


@lru_cache(maxsize=128)
def _reverse_geocode(lat: float, lon: float) -> dict[str, object]:
    url = (
        "https://nominatim.openstreetmap.org/reverse?"
        f"format=jsonv2&lat={lat:.8f}&lon={lon:.8f}&zoom=18&addressdetails=1"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "EA/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=6.0) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=128)
def _fetch_nearby_poi_research(lat: float, lon: float) -> dict[str, object]:
    query = f"""
[out:json][timeout:20];
(
  node["shop"="supermarket"](around:5000,{lat:.8f},{lon:.8f});
  way["shop"="supermarket"](around:5000,{lat:.8f},{lon:.8f});
  node["amenity"="pharmacy"](around:5000,{lat:.8f},{lon:.8f});
  way["amenity"="pharmacy"](around:5000,{lat:.8f},{lon:.8f});
  node["leisure"="playground"](around:5000,{lat:.8f},{lon:.8f});
  way["leisure"="playground"](around:5000,{lat:.8f},{lon:.8f});
  node["railway"="subway_entrance"](around:7000,{lat:.8f},{lon:.8f});
  way["railway"="subway_entrance"](around:7000,{lat:.8f},{lon:.8f});
);
out center tags;
"""
    request = urllib.request.Request(
        "https://overpass-api.de/api/interpreter",
        data=query.encode("utf-8"),
        headers={"User-Agent": "EA/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15.0) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return {}
    elements = list(payload.get("elements") or []) if isinstance(payload, dict) else []
    if not elements:
        return {}
    closest: dict[str, tuple[int, str]] = {}
    for row in elements:
        if not isinstance(row, dict):
            continue
        tags = dict(row.get("tags") or {})
        point_lat = row.get("lat")
        point_lon = row.get("lon")
        if point_lat is None or point_lon is None:
            center = dict(row.get("center") or {})
            point_lat = center.get("lat")
            point_lon = center.get("lon")
        if not isinstance(point_lat, (int, float)) or not isinstance(point_lon, (int, float)):
            continue
        distance_m = _haversine_distance_m(lat, lon, float(point_lat), float(point_lon))
        if tags.get("shop") == "supermarket":
            key = "nearest_supermarket_m"
            name_key = "nearest_supermarket_name"
        elif tags.get("amenity") == "pharmacy":
            key = "nearest_pharmacy_m"
            name_key = "nearest_pharmacy_name"
        elif tags.get("leisure") == "playground":
            key = "nearest_playground_m"
            name_key = "nearest_playground_name"
        elif tags.get("railway") == "subway_entrance":
            key = "nearest_subway_m"
            name_key = "nearest_subway_name"
        else:
            continue
        current = closest.get(key)
        if current is None or distance_m < current[0]:
            closest[key] = (distance_m, str(tags.get("name") or "").strip())
            closest[name_key] = (distance_m, str(tags.get("name") or "").strip())
    result: dict[str, object] = {}
    for key, value in closest.items():
        if key.endswith("_name"):
            result[key] = value[1]
        else:
            result[key] = value[0]
    return result


@lru_cache(maxsize=128)
def _fetch_listing_research(url: str) -> dict[str, object]:
    normalized = str(url or "").strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {}
    request = urllib.request.Request(
        normalized,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=4.0) as response:
            raw_html = response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return {}
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw_html))
    lowered = " ".join(text.split()).lower()
    findings: dict[str, object] = {}
    raw_lower = raw_html.lower()

    lat_match = re.search(r'data-map-lat="([0-9.]+)"', raw_html)
    lon_match = re.search(r'data-map-lng="([0-9.]+)"', raw_html)
    if lat_match and lon_match:
        try:
            map_lat = float(lat_match.group(1))
            map_lon = float(lon_match.group(1))
            findings["map_lat"] = map_lat
            findings["map_lng"] = map_lon
            reverse = _reverse_geocode(map_lat, map_lon)
            display_name = str(reverse.get("display_name") or "").strip()
            if display_name:
                findings["exact_address"] = display_name
            address = dict(reverse.get("address") or {}) if isinstance(reverse.get("address"), dict) else {}
            road = str(address.get("road") or "").strip()
            house_number = str(address.get("house_number") or "").strip()
            postcode = str(address.get("postcode") or "").strip()
            city = str(address.get("city") or address.get("town") or address.get("village") or "").strip()
            if road and house_number:
                findings["street_address"] = f"{road} {house_number}"
                findings["address_lines"] = [f"{road} {house_number}", " ".join(part for part in (postcode, city) if part).strip()]
            poi = _fetch_nearby_poi_research(map_lat, map_lon)
            if poi:
                findings.update(poi)
        except ValueError:
            pass

    if any(token in lowered for token in ("personenaufzug", "aufzug", "lift")):
        findings["lift"] = True
    if any(token in lowered for token in ("plan_top", "plan top", "raumskizze", "grundriss", "floor plan")):
        findings["has_floorplan"] = True
    if "beziehbar sofort" in lowered:
        findings["availability"] = "Sofort"
    if "hauszentralheizung (gas)" in lowered or "house central heating (by gas)" in lowered:
        findings["heating_type"] = "Hauszentralheizung (Gas)"
    elif "gasheizung" in lowered or " gas " in lowered:
        findings["heating_type"] = "Gasheizung"
    if "8 wohneinheiten" in lowered or "8 residential units" in lowered:
        findings["building_units"] = 8
    if "tiefgaragenstellplatz" in lowered or "underground parking space" in lowered:
        findings["garage"] = True
    if "mietverhältnis" in lowered or "lease agreement" in lowered:
        findings["limited_lease"] = True
    if "5 jahre befristetes mietverhältnis" in lowered or "up to 5 years duration" in lowered:
        findings["lease_term_years_max"] = 5
    elif "max. mietdauer" in lowered:
        findings["lease_term_years_max"] = 10
    if "neuwertig" in lowered:
        findings["state"] = "neuwertig"

    bus_match = re.search(r"Bus</span>\s*<span[^>]*>\s*(\d+)\s*m", raw_html, flags=re.IGNORECASE)
    tram_bus_match = re.search(r"Straßenbahn / Bus</span>\s*<span[^>]*>\s*(\d+)\s*m", raw_html, flags=re.IGNORECASE)
    subway_match = re.search(r"U-Bahn</span>\s*<span[^>]*>\s*(\d+)\s*m", raw_html, flags=re.IGNORECASE)
    pharmacy_match = re.search(r"Apotheke</span>\s*<span[^>]*>\s*(\d+)\s*m", raw_html, flags=re.IGNORECASE)
    clinic_match = re.search(r"Klinik</span>\s*<span[^>]*>\s*(\d+)\s*m", raw_html, flags=re.IGNORECASE)
    hospital_match = re.search(r"Krankenhaus</span>\s*<span[^>]*>\s*(\d+)\s*m", raw_html, flags=re.IGNORECASE)
    if bus_match:
        findings["nearest_transit_m"] = int(bus_match.group(1))
    elif tram_bus_match:
        findings["nearest_transit_m"] = int(tram_bus_match.group(1))
    if tram_bus_match:
        findings["nearest_tram_bus_m"] = int(tram_bus_match.group(1))
    if subway_match:
        findings["nearest_subway_m"] = int(subway_match.group(1))
    if pharmacy_match:
        findings["nearest_pharmacy_m"] = int(pharmacy_match.group(1))
    if clinic_match:
        findings["nearest_clinic_m"] = int(clinic_match.group(1))
    if hospital_match:
        findings["nearest_hospital_m"] = int(hospital_match.group(1))

    rooms_match = re.search(r"zimmer\s+(\d+(?:[.,]\d+)?)", text, flags=re.IGNORECASE)
    if rooms_match:
        try:
            findings["rooms"] = float(rooms_match.group(1).replace(",", "."))
        except ValueError:
            pass
    area_match = re.search(r"Wohnfl[aä]che\s+ca\.\s*(\d+(?:[.,]\d+)?)\s*m", text, flags=re.IGNORECASE)
    if area_match:
        try:
            findings["area_sqm"] = float(area_match.group(1).replace(",", "."))
        except ValueError:
            pass
    terrace_area_match = re.search(r"Terrassenfl[aä]che\s+ca\.\s*(\d+(?:[.,]\d+)?)\s*m", text, flags=re.IGNORECASE)
    if terrace_area_match:
        try:
            findings["terrace_area_sqm"] = float(terrace_area_match.group(1).replace(",", "."))
        except ValueError:
            pass
    price_match = re.search(r"Gesamtmiete:\s*(\d[\d\.,]*)\s*€", text, flags=re.IGNORECASE)
    if price_match:
        normalized_price = price_match.group(1).replace(".", "").replace(",", ".")
        try:
            findings["total_rent_eur"] = float(normalized_price)
        except ValueError:
            pass
    parking_match = re.search(r"Euro\s*120,00", text, flags=re.IGNORECASE)
    if parking_match:
        findings["parking_monthly_eur"] = 120.0
    district_match = re.search(r"\b(1\d{3}\s+Wien)\b", text, flags=re.IGNORECASE)
    if district_match:
        findings["postal_name"] = district_match.group(1)
    if "salmannsdorf" in lowered:
        findings["district"] = "Salmannsdorf"
    return findings


def _merged_facts_with_listing_research(payload: dict[str, object], facts: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    merged = dict(facts)
    stored_research = dict(facts.get("listing_research_snapshot") or {}) if isinstance(facts.get("listing_research_snapshot"), dict) else {}
    research = stored_research
    if not research and str(os.getenv("EA_PUBLIC_TOUR_ENABLE_RENDER_RESEARCH_FALLBACK") or "").strip().lower() in {"1", "true", "yes", "on"}:
        listing_url = str(payload.get("listing_url") or payload.get("property_url") or "").strip()
        research = _fetch_listing_research(listing_url) if listing_url else {}
    if not research:
        return merged, {}
    for key, value in research.items():
        existing = merged.get(key)
        if _fact_value_is_weak(existing):
            merged[key] = value
    return merged, research


def _tour_payload_is_disabled_fallback(payload: dict[str, object]) -> bool:
    normalized = dict(payload or {})
    if str(normalized.get("scene_strategy") or "").strip() == "generated_listing_summary":
        return True
    if str(normalized.get("creation_mode") or "").strip() == "hosted_listing_fallback":
        return True
    scenes = [dict(row) for row in (normalized.get("scenes") or []) if isinstance(row, dict)]
    if any(str(scene.get("role") or "").strip() == "generated_overview" for scene in scenes):
        return True
    return False


def _feedback_reason_label(reason_key: object) -> str:
    reason_map = _property_feedback_reason_map()
    row = dict(reason_map.get(str(reason_key or "").strip(), {}))
    return str(row.get("label") or reason_key or "").strip()


def _preference_snapshot_nodes(facts: dict[str, object]) -> list[dict[str, object]]:
    snapshot = dict(facts.get("public_preference_snapshot") or {}) if isinstance(facts.get("public_preference_snapshot"), dict) else {}
    return [dict(row) for row in list(snapshot.get("preference_nodes") or []) if isinstance(row, dict)]


def _filter_node_active(nodes: list[dict[str, object]], *, key: str, category: str) -> bool:
    for row in nodes:
        if str(row.get("key") or "").strip().lower() != key.lower():
            continue
        if str(row.get("category") or "").strip().lower() != category.lower():
            continue
        if str(row.get("status") or "active").strip().lower() == "inactive":
            continue
        value = row.get("value_json")
        if isinstance(value, bool):
            return bool(value)
        if isinstance(value, list):
            return any(str(item or "").strip() for item in value)
        return value not in (None, "", 0, 0.0)
    return False


def _public_filter_specs(*, facts: dict[str, object]) -> list[dict[str, object]]:
    district_value = str(facts.get("postal_name") or facts.get("district") or "").strip()
    filters: list[dict[str, object]] = [
        {
            "key": "avoid_gas_heating",
            "label": "Avoid gas heating",
            "summary": "Suppress listings with gas-based heating.",
            "domain": "willhaben",
            "category": "aversion",
            "node_key": "avoid_heating_types",
            "value_json": ["Gasheizung", "Hauszentralheizung (Gas)"],
            "strength": "high",
            "confidence": 0.95,
        },
        {
            "key": "require_lift",
            "label": "Require lift",
            "summary": "Rank lift-access properties higher.",
            "domain": "willhaben",
            "category": "soft_preference",
            "node_key": "prefer_lift",
            "value_json": True,
            "strength": "high",
            "confidence": 0.92,
        },
        {
            "key": "require_floorplan",
            "label": "Require floor plan",
            "summary": "Prefer listings with a usable layout plan.",
            "domain": "willhaben",
            "category": "soft_preference",
            "node_key": "requires_floorplan_for_remote_review",
            "value_json": True,
            "strength": "high",
            "confidence": 0.9,
        },
        {
            "key": "prefer_subway_nearby",
            "label": "Prefer underground nearby",
            "summary": "Bias ranking toward strong underground access.",
            "domain": "willhaben",
            "category": "soft_preference",
            "node_key": "prefer_subway_nearby",
            "value_json": True,
            "strength": "medium",
            "confidence": 0.84,
        },
        {
            "key": "prefer_supermarket_nearby",
            "label": "Prefer supermarket nearby",
            "summary": "Bias ranking toward easier daily shopping.",
            "domain": "willhaben",
            "category": "soft_preference",
            "node_key": "prefer_supermarket_nearby",
            "value_json": True,
            "strength": "medium",
            "confidence": 0.82,
        },
        {
            "key": "prefer_playgrounds_nearby",
            "label": "Prefer playground nearby",
            "summary": "Bias ranking toward family-oriented micro-locations.",
            "domain": "willhaben",
            "category": "soft_preference",
            "node_key": "prefer_playgrounds_nearby",
            "value_json": True,
            "strength": "medium",
            "confidence": 0.82,
        },
        {
            "key": "prefer_unlimited_lease",
            "label": "Prefer unlimited lease",
            "summary": "Penalize limited-term leases.",
            "domain": "willhaben",
            "category": "soft_preference",
            "node_key": "prefer_unlimited_lease",
            "value_json": True,
            "strength": "high",
            "confidence": 0.9,
        },
        {
            "key": "prefer_balcony",
            "label": "Prefer balcony or terrace",
            "summary": "Bias ranking toward private outdoor space.",
            "domain": "willhaben",
            "category": "soft_preference",
            "node_key": "prefer_balcony",
            "value_json": True,
            "strength": "medium",
            "confidence": 0.8,
        },
    ]
    if district_value:
        filters.append(
            {
                "key": "prefer_this_district",
                "label": f"Prefer {district_value}",
                "summary": "Bias future ranking toward this district.",
                "domain": "willhaben",
                "category": "soft_preference",
                "node_key": "preferred_districts",
                "value_json": [district_value],
                "strength": "medium",
                "confidence": 0.88,
            }
        )
    return filters


def _filter_panel_context(*, facts: dict[str, object]) -> dict[str, object]:
    nodes = _preference_snapshot_nodes(facts)
    filters: list[dict[str, object]] = []
    active_labels: list[str] = []
    hard_filters: list[dict[str, object]] = []
    soft_filters: list[dict[str, object]] = []
    for spec in _public_filter_specs(facts=facts):
        active = _filter_node_active(nodes, key=str(spec.get("node_key") or ""), category=str(spec.get("category") or ""))
        enriched = {**spec, "active": active}
        filters.append(enriched)
        if str(spec.get("category") or "").strip().lower() == "aversion" or str(spec.get("strength") or "").strip().lower() == "high":
            hard_filters.append(enriched)
        else:
            soft_filters.append(enriched)
        if active:
            active_labels.append(str(spec.get("label") or "").strip())
    return {
        "filters": filters,
        "hard_filters": hard_filters,
        "soft_filters": soft_filters,
        "active_labels": active_labels[:8],
    }


def _shortlist_normalized_ref_tokens(value: object) -> tuple[str, ...]:
    raw = str(value or "").strip()
    if not raw:
        return ()
    normalized = raw.lower().strip()
    tokens: set[str] = {normalized}
    if "://" in normalized:
        normalized_url = str(urllib.parse.urldefrag(normalized)[0]).strip()
        if normalized_url:
            tokens.add(normalized_url)
            tokens.add(normalized_url.rstrip("/"))
            parsed = urllib.parse.urlparse(normalized_url)
            path = (parsed.path or "").rstrip("/")
            if path:
                tokens.add(path.rsplit("/", 1)[-1].lower())
    if ":" in normalized and not normalized.startswith("http"):
        tokens.add(normalized.split(":", 1)[-1].strip())
    maybe_id_match = re.search(r"(\d{4,})", normalized)
    if maybe_id_match:
        tokens.add(maybe_id_match.group(1))
    tail = normalized.rsplit("/", 1)[-1]
    if tail:
        tokens.add(tail)
    return tuple(sorted(token for token in tokens if token and token.lower() not in {"http", "https", "www"}))


def _shortlist_as_float(value: object) -> float | None:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        normalized = (
            str(value)
            .replace("€", "")
            .replace("EUR", "")
            .replace("eur", "")
            .replace(" ", "")
            .replace("m²", "")
            .replace("sqm", "")
            .replace("m", "")
        )
        normalized = re.sub(r"[^0-9.,\-]", "", normalized)
        if not normalized or normalized in {"-", "+", ".", ","}:
            return None
        if "," in normalized and "." in normalized:
            if normalized.rfind(",") > normalized.rfind("."):
                normalized = normalized.replace(".", "").replace(",", ".")
            else:
                normalized = normalized.replace(",", "")
            return float(normalized)
        if "," in normalized:
            before, after = normalized.rsplit(",", 1)
            if before and after and len(after) in {1, 2}:
                normalized = f"{before}.{after}"
            else:
                normalized = normalized.replace(",", "")
            return float(normalized)
        if "." in normalized:
            before, after = normalized.rsplit(".", 1)
            if before and after and len(after) == 3:
                normalized = normalized.replace(".", "")
            else:
                normalized = normalized
            return float(normalized)
        return float(normalized)
    except Exception:
        return None


def _shortlist_safe_http_url(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return normalized


def _shortlist_as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized in {"1", "true", "yes", "y", "ja", "on", "enabled", "present"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", "disabled", "missing", "none", "n/a"}:
        return False
    return None


def _public_tour_normalize_reason_keys(value: object, *, allowed: set[str]) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise HTTPException(status_code=422, detail="invalid_tour_feedback_reason_keys")
    keys: list[str] = []
    seen: set[str] = set()
    for row in value:
        key = str(row or "").strip().lower()
        if not key:
            continue
        if key not in allowed:
            raise HTTPException(status_code=422, detail="invalid_tour_feedback_reason_key")
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return tuple(keys)


@lru_cache(maxsize=8)
def _shortlist_tour_manifest_index(root: str) -> tuple[dict[str, object], ...]:
    root_dir = Path(root).expanduser()
    if not root_dir.exists() or not root_dir.is_dir():
        return ()
    rows: list[dict[str, object]] = []
    for candidate in sorted((entry for entry in root_dir.iterdir() if entry.is_dir()), key=lambda entry: entry.name):
        payload_path = candidate / "tour.json"
        if not payload_path.exists() or not payload_path.is_file():
            continue
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(dict(payload))
    return tuple(rows)


def _shortlist_tour_match_tokens(payload: dict[str, object]) -> tuple[str, ...]:
    tokens: set[str] = set()
    facts = dict(payload.get("facts") or {})
    runtime_inputs = dict(payload.get("runtime_inputs_json") or {})
    for candidate in (
        payload.get("listing_url"),
        payload.get("property_url"),
        payload.get("source_ref"),
        payload.get("external_id"),
        payload.get("tour_slug"),
        payload.get("slug"),
        runtime_inputs.get("listing_id"),
        facts.get("listing_id"),
    ):
        tokens.update(_shortlist_normalized_ref_tokens(candidate))
    return tuple(sorted(tokens))


def _shortlist_find_tour_payload_for_refs(*, refs: tuple[str, ...]) -> dict[str, object] | None:
    if not refs:
        return None
    ref_set = set(refs)
    for candidate in _shortlist_tour_manifest_index(str(_tour_dir())):
        candidate_tokens = set(_shortlist_tour_match_tokens(candidate))
        if ref_set & candidate_tokens:
            return dict(candidate)
    return None


def _shortlist_tour_row_metrics(payload: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {
            "total_rent_eur": None,
            "area_sqm": None,
            "rooms": None,
            "heating_type": "",
            "lift": None,
            "has_floorplan": None,
            "has_balcony": None,
            "nearest_subway_m": None,
            "nearest_supermarket_m": None,
            "nearest_playground_m": None,
        }
    facts = dict(payload.get("facts") or {})
    rent_keys = ("total_rent_eur", "rent_eur", "price_eur", "price", "base_rent_eur")
    area_keys = ("area_sqm", "area", "living_area", "living_area_sqm", "floor_area")
    room_keys = ("rooms", "room_count", "zimmer")
    lift_keys = ("lift", "has_lift", "elevator")
    floorplan_keys = ("has_floorplan", "requires_floorplan_for_remote_review", "floorplan_available", "floor_plan")
    balcony_keys = ("has_balcony", "has_terrace", "balcony", "terrace", "outdoor_space")
    distance_specs = (
        ("nearest_subway_m", ("nearest_subway_m", "distance_to_subway_m", "subway_distance_m")),
        ("nearest_supermarket_m", ("nearest_supermarket_m", "distance_to_supermarket_m", "supermarket_distance_m")),
        (
            "nearest_playground_m",
            ("nearest_playground_m", "distance_to_playground_m", "playground_distance_m"),
        ),
    )

    def _first_numeric(candidate_keys: tuple[str, ...]) -> float | None:
        for key in candidate_keys:
            value = _shortlist_as_float(facts.get(key))
            if value is not None and value > 0:
                return value
        return None

    def _first_bool(candidate_keys: tuple[str, ...]) -> bool | None:
        for key in candidate_keys:
            value = _shortlist_as_bool(facts.get(key))
            if value is not None:
                return value
        return None

    rent_value = _first_numeric(rent_keys)
    area_value = _first_numeric(area_keys)
    room_value = _first_numeric(room_keys)
    heating_value = str(facts.get("heating_type") or facts.get("heating") or "").strip()
    metrics = {
        "total_rent_eur": rent_value,
        "area_sqm": area_value,
        "rooms": int(room_value) if room_value is not None and room_value > 0 else None,
        "heating_type": heating_value,
        "lift": _first_bool(lift_keys),
        "has_floorplan": _first_bool(floorplan_keys),
        "has_balcony": _first_bool(balcony_keys),
    }
    for metric_key, options in distance_specs:
        metrics[metric_key] = _first_numeric(options)
    return metrics


def _shortlist_metric_labels() -> tuple[tuple[str, str, str], ...]:
    return (
        ("total_rent_eur", "Rent", "higher_is_worse"),
        ("area_sqm", "Area", "higher_is_better"),
        ("rooms", "Rooms", "higher_is_better"),
        ("heating_type", "Heating", "compare_text"),
        ("lift", "Lift", "higher_is_better"),
        ("has_floorplan", "Floor plan", "higher_is_better"),
        ("has_balcony", "Balcony/Terrace", "higher_is_better"),
        ("nearest_subway_m", "Underground", "higher_is_worse"),
        ("nearest_supermarket_m", "Supermarket", "higher_is_worse"),
        ("nearest_playground_m", "Playground", "higher_is_worse"),
    )


def _shortlist_metric_display(metric_key: str, value: object) -> str:
    if value is None:
        return "Not available"
    if metric_key == "total_rent_eur":
        if isinstance(value, (int, float)):
            return f"EUR {value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return str(value)
    if metric_key == "area_sqm":
        if isinstance(value, (int, float)):
            return f"{int(round(float(value)))} m²"
    if metric_key == "rooms":
        if isinstance(value, (int, float)):
            return f"{int(round(float(value)))}"
    if metric_key.endswith("_m"):
        if isinstance(value, (int, float)) and value >= 0:
            return f"about {int(round(value))} m"
    if metric_key in {"lift", "has_floorplan", "has_balcony"}:
        return "Yes" if bool(value) else "No"
    return str(value or "Not available")


def _shortlist_metric_delta(metric_key: str, *, baseline: object, candidate: object) -> tuple[str, str]:
    if candidate is None or baseline is None:
        return "No comparison", "neutral"
    if metric_key.endswith("_m") or metric_key in {"total_rent_eur", "area_sqm", "rooms"}:
        if not isinstance(baseline, (int, float)) or not isinstance(candidate, (int, float)):
            return "No comparison", "neutral"
        base_value = float(baseline)
        cand_value = float(candidate)
        if base_value == 0:
            return "No comparison", "neutral"
        difference = cand_value - base_value
        if abs(difference) < 0.0001:
            return "No change", "neutral"
        ratio = int(round((difference / base_value) * 100.0)) if base_value else 0
        prefix = "+" if difference > 0 else "-"
        delta = abs(difference)
        if metric_key == "total_rent_eur":
            delta_text = f"{prefix}EUR {delta:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        elif metric_key in {"area_sqm", "rooms"}:
            delta_text = f"{prefix}{abs(difference):.0f}"
        else:
            delta_text = f"{prefix}{int(round(abs(difference)))} m"
        metric_is_lower_better = metric_key in {"total_rent_eur", "nearest_subway_m", "nearest_supermarket_m", "nearest_playground_m"}
        if (metric_is_lower_better and difference < 0) or (not metric_is_lower_better and difference > 0):
            return f"{delta_text} ({abs(ratio)}%)", "better"
        return f"{delta_text} ({abs(ratio)}%)", "worse"
    if metric_key in {"lift", "has_floorplan", "has_balcony"}:
        if bool(baseline) == bool(candidate):
            return "Same", "neutral"
        if bool(candidate) and not bool(baseline):
            return "Better", "better"
        return "Worse", "worse"
    baseline_text = str(baseline or "").strip().lower()
    candidate_text = str(candidate or "").strip().lower()
    if baseline_text == candidate_text:
        return "Same", "neutral"
    if candidate_text:
        return "Different", "neutral"
    return "No comparison", "neutral"


def _live_property_feedback_context(
    *,
    container: AppContainer,
    payload: dict[str, object],
    slug: str,
) -> dict[str, object]:
    def _merge_snapshot_nodes(
        stored_snapshot: dict[str, object],
        profile_bundle: dict[str, object],
    ) -> list[dict[str, object]]:
        merged: list[dict[str, object]] = []
        seen: set[tuple[str, str, str]] = set()
        for source in (
            list(dict(stored_snapshot or {}).get("preference_nodes") or []),
            list(dict(profile_bundle or {}).get("preference_nodes") or []),
        ):
            for row in source:
                if not isinstance(row, dict):
                    continue
                key = str(row.get("key") or "").strip().lower()
                category = str(row.get("category") or "").strip().lower()
                value_marker = json.dumps(row.get("value_json"), sort_keys=True, ensure_ascii=False, default=str)
                marker = (key, category, value_marker)
                if not key or marker in seen:
                    continue
                seen.add(marker)
                merged.append(dict(row))
        return merged

    principal_id = str(payload.get("principal_id") or "").strip()
    facts = dict(payload.get("facts") or {})
    facts, _ = _merged_facts_with_listing_research(payload, facts)
    stored_snapshot = dict(facts.get("public_preference_snapshot") or {}) if isinstance(facts.get("public_preference_snapshot"), dict) else {}
    if not principal_id:
        return {"facts": facts, "feedback_suggestions": {"negative": [], "positive": []}, "learning_summary": {}}
    service = build_product_service(container)
    profile_bundle = service.get_preference_profile(principal_id=principal_id, person_id="self")
    listing_object_id = str(payload.get("listing_id") or payload.get("property_url") or payload.get("listing_url") or slug).strip() or slug
    existing_assessment = dict(facts.get("personal_fit_assessment") or {}) if isinstance(facts.get("personal_fit_assessment"), dict) else {}
    live_assessment = service.preview_preference_candidate(
        principal_id=principal_id,
        person_id="self",
        domain="willhaben",
        object_type="listing",
        object_id=listing_object_id,
        object_payload=facts,
        require_existing_profile=False,
    )
    if isinstance(live_assessment, dict):
        merged_assessment = dict(existing_assessment)
        merged_assessment.update(dict(live_assessment))
        existing_livability = dict(existing_assessment.get("livability_snapshot") or {}) if isinstance(existing_assessment.get("livability_snapshot"), dict) else {}
        live_livability = dict(live_assessment.get("livability_snapshot") or {}) if isinstance(live_assessment.get("livability_snapshot"), dict) else {}
        if existing_livability or live_livability:
            merged_livability = dict(existing_livability)
            merged_livability.update(live_livability)
            merged_assessment["livability_snapshot"] = merged_livability
        facts["personal_fit_assessment"] = merged_assessment
    facts["public_preference_snapshot"] = {
        "profile": dict(profile_bundle.get("profile") or stored_snapshot.get("profile") or {}),
        "preference_nodes": _merge_snapshot_nodes(stored_snapshot, profile_bundle),
    }
    return {
        "facts": facts,
        "feedback_suggestions": service.property_feedback_suggestions(
            property_facts=facts,
            assessment=dict(live_assessment or {}) if isinstance(live_assessment, dict) else None,
        ),
        "learning_summary": service.property_feedback_learning_summary(
            principal_id=principal_id,
            person_id="self",
            domain="willhaben",
        ),
        "live_assessment": dict(live_assessment or {}) if isinstance(live_assessment, dict) else {},
        "profile_bundle": profile_bundle,
    }


def _public_shortlist_comparison_context(
    *,
    container: AppContainer,
    payload: dict[str, object],
    slug: str,
    facts: dict[str, object],
) -> dict[str, object]:
    principal_id = str(payload.get("principal_id") or "").strip()
    if not principal_id:
        return {
            "current": {},
            "items": [],
            "metric_specs": list(_shortlist_metric_labels()),
        }
    metric_specs = list(_shortlist_metric_labels())
    current_refs = {
        str(payload.get("listing_id") or "").strip(),
        str(payload.get("property_url") or "").strip(),
        str(payload.get("listing_url") or "").strip(),
        str(slug or "").strip(),
    }
    current_payload = {
        "facts": dict(facts),
        "listing_url": payload.get("listing_url"),
        "property_url": payload.get("property_url"),
        "source_ref": payload.get("source_ref"),
        "external_id": payload.get("external_id"),
    }
    current_metrics = _shortlist_tour_row_metrics(current_payload)
    current_score_value = dict(facts.get("personal_fit_assessment") or {}).get("fit_score")
    current_score = float(current_score_value or 0.0) if isinstance(current_score_value, (int, float)) else 0.0
    current_title = str(payload.get("display_title") or payload.get("title") or slug).strip() or slug
    try:
        service = build_product_service(container)
        brief_items = list(service.list_brief_items(principal_id=principal_id, limit=8))
    except Exception:
        return {
            "current": {
                "title": current_title,
                "score": current_score,
                "object_ref": str(payload.get("listing_url") or payload.get("property_url") or slug).strip(),
                "listing_url": str(payload.get("listing_url") or payload.get("property_url") or "").strip(),
                "score_label": "Fit",
                "why_now": "",
                "recommended_action": "review current property",
                "metrics": current_metrics,
            },
            "items": [],
            "metric_specs": metric_specs,
        }
    items: list[dict[str, object]] = []
    if tuple(current_refs):
        normalized_current_refs = tuple(
            token
            for ref in current_refs
            for token in _shortlist_normalized_ref_tokens(ref)
            if token
        )
    else:
        normalized_current_refs = ()
    for row in brief_items:
        object_ref = str(getattr(row, "object_ref", "") or "").strip()
        object_ref_tokens = tuple(_shortlist_normalized_ref_tokens(object_ref))
        if any(token in object_ref_tokens for token in normalized_current_refs):
            continue
        if not object_ref_tokens:
            continue
        candidate_payload = _shortlist_find_tour_payload_for_refs(refs=object_ref_tokens)
        candidate_metrics = _shortlist_tour_row_metrics(candidate_payload)
        candidate_listing_url = str(
            (candidate_payload.get("listing_url") if isinstance(candidate_payload, dict) else "")
            or (candidate_payload.get("property_url") if isinstance(candidate_payload, dict) else "")
        ) if isinstance(candidate_payload, dict) else ""
        if not candidate_listing_url and object_ref.startswith("http"):
            candidate_listing_url = object_ref
        candidate_listing_url = _shortlist_safe_http_url(candidate_listing_url)
        items.append(
            {
                "title": str(getattr(row, "title", "") or "").strip() or "Shortlist property",
                "score": float(getattr(row, "score", 0.0) or 0.0),
                "why_now": str(getattr(row, "why_now", "") or "").strip(),
                "recommended_action": str(getattr(row, "recommended_action", "") or "").strip(),
                "object_ref": object_ref,
                "listing_url": candidate_listing_url,
                "metrics": candidate_metrics,
            }
        )
    current_reason = ""
    assessment = dict(facts.get("personal_fit_assessment") or {})
    for source in (list(assessment.get("good_fit_reasons") or []), list(assessment.get("match_reasons_json") or [])):
        for value in source:
            text = str(value or "").strip()
            if text:
                current_reason = text
                break
        if current_reason:
            break
    return {
        "current": {
            "title": current_title,
            "score": current_score,
            "why_now": current_reason or "Current hosted property under review.",
            "score_label": "Fit",
            "metrics": current_metrics,
            "recommended_action": "review current property",
            "object_ref": str(payload.get("listing_url") or payload.get("property_url") or slug).strip(),
            "listing_url": str(payload.get("listing_url") or payload.get("property_url") or "").strip(),
        },
        "items": items[:2],
        "metric_specs": metric_specs,
    }


def _public_tour_host_brand_label(hostname: str, *, fallback: str = "this domain") -> str:
    host = str(hostname or "").strip().lower().rstrip(".")
    if host.endswith("propertyquarry.com"):
        return "PropertyQuarry"
    if host.endswith("myexternalbrain.com"):
        return "My External Brain"
    return str(fallback or "this domain").strip() or "this domain"


def _tour_html(payload: dict[str, object], *, hostname: str = "") -> str:
    scenes = [dict(row) for row in (payload.get("scenes") or []) if isinstance(row, dict)]
    if not scenes:
        raise HTTPException(status_code=500, detail="tour_scenes_missing")
    facts, researched_facts = _merged_facts_with_listing_research(payload, dict(payload.get("facts") or {}))
    feedback_suggestions = dict(payload.get("_feedback_suggestions") or {}) if isinstance(payload.get("_feedback_suggestions"), dict) else {}
    learning_summary = dict(payload.get("_learning_summary") or {}) if isinstance(payload.get("_learning_summary"), dict) else {}
    filter_context = _filter_panel_context(facts=facts)
    shortlist_compare = dict(payload.get("_shortlist_compare") or {}) if isinstance(payload.get("_shortlist_compare"), dict) else {}
    brief = dict(payload.get("brief") or {})
    title = str(payload.get("title") or payload.get("tour_title") or payload.get("slug") or "Property Tour").strip()
    display_title = str(payload.get("display_title") or title).strip() or title
    listing_url = str(payload.get("listing_url") or "").strip()
    hosted_url = str(payload.get("hosted_url") or "").strip()
    source_virtual_tour_url = _embedded_live_360_url(payload)
    is_pure_360_cube = str(payload.get("scene_strategy") or "").strip() == "pure_360_cube"
    brand_name = str(payload.get("brand_name") or "Pioche Lecombe").strip() or "Pioche Lecombe"
    hosted_brand_name = _public_tour_host_brand_label(hostname, fallback=brand_name)
    hosted_brand_html = html.escape(hosted_brand_name)
    slug = str(payload.get("slug") or "").strip()
    video_relpath = str(payload.get("video_relpath") or "").strip()
    video_fallback_relpath = str(payload.get("video_fallback_relpath") or "").strip()
    video_url = f"/tours/files/{slug}/{video_relpath}" if slug and video_relpath else ""
    video_fallback_url = f"/tours/files/{slug}/{video_fallback_relpath}" if slug and video_fallback_relpath else ""

    def _trim_text(value: object) -> str:
        return str(value or "").strip()

    def _collect_scene_refs(value: object) -> list[str]:
        if value is None:
            return []
        refs: list[str] = []
        if isinstance(value, (str, int)):
            trimmed = _trim_text(value)
            if trimmed:
                refs.append(trimmed)
            return refs
        if isinstance(value, float):
            if value.is_integer():
                refs.append(_trim_text(int(value)))
            else:
                refs.append(_trim_text(value))
            return refs
        if isinstance(value, (list, tuple)):
            for item in value:
                refs.extend(_collect_scene_refs(item))
            return refs
        if isinstance(value, dict):
            for candidate_key in ("id", "location_id", "scene_id", "next", "to", "target"):
                refs.extend(_collect_scene_refs(value.get(candidate_key)))
            return refs
        return []

    def _text_list(value: object) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return [str(item or "").strip() for item in value if str(item or "").strip()]

    def _json_attr(value: object) -> str:
        return html.escape(json.dumps(value, ensure_ascii=False), quote=True)

    def _distance_rows(snapshot: dict[str, object]) -> list[tuple[str, str]]:
        labels = (
            ("nearest_transit_m", "Transit"),
            ("nearest_subway_m", "Underground"),
            ("nearest_supermarket_m", "Supermarket"),
            ("nearest_pharmacy_m", "Pharmacy"),
            ("nearest_bakery_m", "Bakery"),
            ("nearest_bicycle_parking_m", "Bicycle parking"),
            ("nearest_cycleway_m", "Cycleway"),
            ("nearest_playground_m", "Playground"),
            ("nearest_school_m", "School"),
            ("nearest_running_m", "Run or green space"),
        )
        rows: list[tuple[str, str]] = []
        for key, label in labels:
            value = snapshot.get(key)
            if isinstance(value, (int, float)) and value > 0:
                rows.append((label, f"about {int(value):d} m"))
        return rows[:6]

    def _fact_text(*keys: str) -> str:
        for key in keys:
            value = facts.get(key)
            text = str(value or "").strip()
            if text and text not in {"?", "None"}:
                return text
        return ""

    def _fact_bool(*keys: str) -> bool:
        for key in keys:
            value = facts.get(key)
            if isinstance(value, bool):
                return value
        return False

    def _normalized_token(value: object) -> str:
        text = str(value or "").strip().lower()
        return (
            text.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )

    def _feature_highlights() -> list[str]:
        rows: list[str] = []
        terrace_area_value = facts.get("terrace_area_sqm")
        if _fact_bool("lift") and _fact_bool("has_floorplan"):
            rows.append("Lift and floor plan materially reduce remote-viewing uncertainty.")
        elif _fact_bool("has_floorplan"):
            rows.append("A floor plan is available for layout validation.")
        elif _fact_bool("lift"):
            rows.append("The building has a passenger lift.")
        if isinstance(terrace_area_value, (int, float)) and terrace_area_value > 0:
            rows.append(f"{terrace_area_value:g} m² of terrace area adds meaningful private outdoor space.")
        elif _fact_bool("terrace"):
            rows.append("Multiple terraces materially improve usable outdoor space.")
        building_units = facts.get("building_units")
        if isinstance(building_units, (int, float)) and building_units > 0:
            rows.append(f"The building has only {int(building_units)} residential units, which should keep internal traffic lower.")
        state = _fact_text("state")
        renovation_year = facts.get("last_renovation_year")
        if state and isinstance(renovation_year, (int, float)) and renovation_year > 0:
            rows.append(f"The listing describes the condition as {state} and notes renovation in {int(renovation_year)}.")
        availability = _fact_text("availability")
        if availability:
            rows.append(f"Availability is listed as {availability}.")
        if _fact_bool("furnished", "is_furnished"):
            rows.append("The furnished setup lowers move-in friction.")
        elif _fact_bool("balcony"):
            rows.append("Includes a balcony.")
        if _fact_bool("garden"):
            rows.append("Includes outdoor garden space.")
        heating = _fact_text("heating", "heating_type")
        if heating and "gas" not in heating.lower():
            rows.append(f"Heating: {heating}.")
        deduped: list[str] = []
        seen: set[str] = set()
        for row in rows:
            normalized = row.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(row)
        return deduped[:5]

    def _feature_concerns() -> list[str]:
        rows: list[str] = []
        heating = _fact_text("heating", "heating_type")
        if heating and "gas" in heating.lower():
            rows.append("Gas heating may increase running-cost risk.")
        lease_term = facts.get("lease_term_years_max")
        if isinstance(lease_term, (int, float)) and lease_term > 0:
            rows.append(f"The lease is limited to about {int(lease_term)} years, which matters if long-term stability is important.")
        parking_monthly = facts.get("parking_monthly_eur")
        if isinstance(parking_monthly, (int, float)) and parking_monthly > 0:
            rows.append(f"The garage space is optional but adds about EUR {int(parking_monthly):d} per month.")
        if not _fact_bool("has_floorplan") and not rows:
            rows.append("No floor plan is stored yet.")
        if not _fact_bool("lift") and not rows:
            rows.append("Lift access is not confirmed.")
        return rows[:4]

    def _personalized_priority_rows() -> tuple[list[str], list[str], list[str]]:
        snapshot = dict(facts.get("public_preference_snapshot") or {}) if isinstance(facts.get("public_preference_snapshot"), dict) else {}
        nodes = [dict(row) for row in list(snapshot.get("preference_nodes") or []) if isinstance(row, dict)]
        positive: list[str] = []
        caution: list[str] = []
        open_questions: list[str] = []
        district_value = _normalized_token(_fact_text("postal_name", "district", "location"))
        heating_value = _fact_text("heating", "heating_type")
        heating_lower = heating_value.lower()
        has_floorplan = _fact_bool("has_floorplan")
        has_360 = _fact_bool("has_360")
        has_lift = _fact_bool("lift")
        has_balcony = _fact_bool("balcony") or _fact_bool("terrace")
        nearest_playground = livability_snapshot.get("nearest_playground_m")
        nearest_cycleway = livability_snapshot.get("nearest_cycleway_m")
        nearest_bicycle_parking = livability_snapshot.get("nearest_bicycle_parking_m")
        nearest_running = livability_snapshot.get("nearest_running_m")
        for row in nodes:
            key = str(row.get("key") or "").strip().lower()
            value = row.get("value_json")
            if key == "preferred_districts" and isinstance(value, list):
                preferred = [_normalized_token(item) for item in value if str(item or "").strip()]
                if district_value and any(item in district_value for item in preferred):
                    positive.append(f"The district matches your preferred areas ({_fact_text('postal_name', 'district', 'location')}).")
                elif preferred:
                    caution.append(f"The district is outside your stated preferred areas ({', '.join(str(item or '') for item in value if str(item or '').strip())}).")
            elif key == "avoid_heating_types" and isinstance(value, list):
                avoided = [str(item or "").strip().lower() for item in value if str(item or "").strip()]
                if heating_lower and any(item in heating_lower for item in avoided):
                    caution.append(f"{heating_value} conflicts with your heating preferences.")
                elif heating_value and avoided:
                    positive.append(f"{heating_value} avoids your excluded heating types.")
                elif avoided:
                    open_questions.append("The heating type should be confirmed against your exclusions.")
            elif key in {"require_floorplan", "requires_floorplan_for_remote_review"}:
                if has_floorplan:
                    positive.append("A floor plan is available, which supports your remote review workflow.")
                else:
                    caution.append("No floor plan is stored, although you prefer one for review.")
            elif key == "prefer_360_for_remote_review":
                if not has_360:
                    caution.append("A 360 tour is missing, even though you prefer one for remote review.")
            elif key == "prefer_lift":
                if has_lift:
                    positive.append("Lift access matches your stated preference.")
                else:
                    caution.append("Lift access is not confirmed, although you prefer it.")
            elif key == "prefer_balcony":
                if has_balcony:
                    positive.append("Outdoor space is available, which matches your balcony or terrace preference.")
                else:
                    caution.append("Balcony or terrace space is not confirmed.")
            elif "playground" in key:
                if isinstance(nearest_playground, (int, float)) and nearest_playground > 0:
                    positive.append(f"The nearest playground is about {int(nearest_playground):d} m away.")
                else:
                    open_questions.append("Playground distance is not stored yet.")
            elif "bike" in key:
                if isinstance(nearest_cycleway, (int, float)) and nearest_cycleway > 0:
                    positive.append(f"Cycleway access is about {int(nearest_cycleway):d} m away.")
                elif isinstance(nearest_bicycle_parking, (int, float)) and nearest_bicycle_parking > 0:
                    positive.append(f"Bicycle parking is about {int(nearest_bicycle_parking):d} m away.")
                else:
                    open_questions.append("Bike infrastructure distance is not stored yet.")
            elif "green" in key or "park" in key or "running" in key:
                if isinstance(nearest_running, (int, float)) and nearest_running > 0:
                    positive.append(f"Green-space or running access is about {int(nearest_running):d} m away.")
                else:
                    open_questions.append("Green-space distance is not stored yet.")
        return positive[:4], caution[:4], open_questions[:4]

    def _decision_rows() -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        exact_address_value = _fact_text("street_address", "exact_address")
        if exact_address_value:
            rows.append(("Address", exact_address_value))
        district_value = _fact_text("postal_name", "district", "location")
        if district_value:
            rows.append(("District", district_value))
        price_value = facts.get("total_rent_eur")
        if isinstance(price_value, (int, float)):
            rows.append(("Price", _money(price_value)))
        elif rent != "EUR ?":
            rows.append(("Price", rent))
        area_value = _fact_text("area_label")
        if not area_value:
            area_sqm_value = facts.get("area_sqm")
            if isinstance(area_sqm_value, (int, float)):
                area_value = f"{int(area_sqm_value) if float(area_sqm_value).is_integer() else area_sqm_value} m²"
        if area_value:
            rows.append(("Area", area_value))
        rooms_value = _fact_text("rooms_label")
        if not rooms_value:
            rooms_raw = facts.get("rooms")
            if isinstance(rooms_raw, (int, float)):
                rooms_value = f"{int(rooms_raw) if float(rooms_raw).is_integer() else rooms_raw} rooms"
        if rooms_value:
            rows.append(("Rooms", rooms_value))
        availability_value = _fact_text("availability")
        if availability_value:
            rows.append(("Availability", availability_value))
        heating_value = _fact_text("heating", "heating_type")
        if heating_value:
            rows.append(("Heating", heating_value))
        if _fact_bool("lift"):
            rows.append(("Access", "Lift available"))
        elif "lift" in facts:
            rows.append(("Access", "Lift not confirmed"))
        return rows[:6]

    scene_data = []
    for index, scene in enumerate(scenes):
        scene_id = _trim_text(
            scene.get("scene_id") or scene.get("location_id") or scene.get("id") or scene.get("scene")
        )
        if not scene_id:
            scene_id = str(index + 1)
        next_scene_refs = (
            _collect_scene_refs(scene.get("next_scene_id"))
            + _collect_scene_refs(scene.get("next_scene"))
            + _collect_scene_refs(scene.get("next_location_id"))
            + _collect_scene_refs(scene.get("next"))
        )
        prev_scene_refs = (
            _collect_scene_refs(scene.get("prev_scene_id"))
            + _collect_scene_refs(scene.get("prev_scene"))
            + _collect_scene_refs(scene.get("prev_location_id"))
            + _collect_scene_refs(scene.get("prev"))
        )
        scene_data.append(
            {
                "name": str(scene.get("name") or "").strip(),
                "scene_id": scene_id,
                "next_scene_id": _trim_text(next_scene_refs[0]) if next_scene_refs else "",
                "prev_scene_id": _trim_text(prev_scene_refs[0]) if prev_scene_refs else "",
                "next_scene_index": scene.get("next_scene_index"),
                "prev_scene_index": scene.get("prev_scene_index"),
                "image_url": (
                    f"/tours/files/{slug}/{str(scene.get('asset_relpath') or '').strip()}"
                    if slug and str(scene.get("asset_relpath") or "").strip()
                    else str(scene.get("image_url") or "").strip()
                ),
                "role": str(scene.get("role") or "photo").strip(),
                "source_url": "" if is_pure_360_cube else str(scene.get("source_url") or "").strip(),
                "cube_faces": {
                    key: f"/tours/files/{slug}/{str(value or '').strip()}"
                    for key, value in dict(scene.get("cube_faces") or {}).items()
                    if slug and str(value or "").strip()
                },
            }
        )

    if is_pure_360_cube and len(scene_data) > 1:
        scene_id_to_index = {
            scene_entry["scene_id"]: index for index, scene_entry in enumerate(scene_data) if scene_entry.get("scene_id")
        }

        def _resolve_scene_index(raw_ref: object, fallback: int) -> int:
            for ref in _collect_scene_refs(raw_ref):
                if ref in scene_id_to_index:
                    return scene_id_to_index[ref]
            return fallback

        for index, entry in enumerate(scene_data):
            next_index_raw = _collect_scene_refs(entry.get("next_scene_id") or entry.get("next_scene_index") or entry.get("next"))
            prev_index_raw = _collect_scene_refs(entry.get("prev_scene_id") or entry.get("prev_scene_index") or entry.get("prev"))
            next_index = _resolve_scene_index(next_index_raw, (index + 1) % len(scene_data))
            prev_index = _resolve_scene_index(prev_index_raw, (index - 1) % len(scene_data))
            entry["next_scene_index"] = next_index
            entry["prev_scene_index"] = prev_index
    data_json = json.dumps(scene_data, ensure_ascii=False).replace("</", "<\\/")
    title_html = html.escape(title)
    display_html = html.escape(display_title)
    variant_label = html.escape(str(payload.get("variant_label") or payload.get("variant_key") or "").strip())
    rooms = html.escape(str(facts.get("rooms") or "?"))
    area = html.escape(str(facts.get("area_sqm") or "?"))
    rent = html.escape(_money(facts.get("total_rent_eur")))
    availability = html.escape(str(facts.get("availability") or "?"))
    address = "<br>".join(html.escape(str(value)) for value in (facts.get("address_lines") or []))
    teaser = " · ".join(html.escape(str(value)) for value in (facts.get("teaser_attributes") or []))
    creative_brief = html.escape(str(brief.get("creative_brief") or "").strip())
    theme_name = html.escape(str(brief.get("theme_name") or "").strip())
    tour_style = html.escape(str(brief.get("tour_style") or "").strip())
    audience = html.escape(str(brief.get("audience") or "").strip())
    cta = html.escape(str(brief.get("call_to_action") or "").strip())
    brand_html = html.escape(brand_name)
    listing_link = f'<a class="ghost" href="{html.escape(listing_url)}" target="_blank" rel="noreferrer">Open Listing</a>' if listing_url else ""
    hosted_link = f'<a class="ghost" href="{html.escape(hosted_url)}">Permalink</a>' if hosted_url else ""
    primary_cta = "Open Live 360" if source_virtual_tour_url else "Open Tour"
    primary_cta_href = "#live-360" if source_virtual_tour_url else "#viewer"
    assessment = dict(facts.get("personal_fit_assessment") or {}) if isinstance(facts.get("personal_fit_assessment"), dict) else {}
    if not assessment and isinstance(facts.get("decision_summary"), dict):
        assessment = dict(facts.get("decision_summary") or {})
    recommendation = html.escape(str(assessment.get("recommendation") or "").strip().replace("_", " "))
    fit_score_value = assessment.get("fit_score")
    fit_score = int(round(float(fit_score_value))) if isinstance(fit_score_value, (int, float)) else None
    good_fit_reasons = _text_list(assessment.get("good_fit_reasons") or assessment.get("match_reasons_json"))
    bad_fit_reasons = _text_list(assessment.get("bad_fit_reasons") or assessment.get("mismatch_reasons_json"))
    unknowns = _text_list(assessment.get("unknowns") or assessment.get("unknowns_json"))
    livability_snapshot = dict(assessment.get("livability_snapshot") or {}) if isinstance(assessment.get("livability_snapshot"), dict) else {}
    for livability_key in (
        "nearest_transit_m",
        "nearest_subway_m",
        "nearest_supermarket_m",
        "nearest_pharmacy_m",
        "nearest_bakery_m",
        "nearest_bicycle_parking_m",
        "nearest_cycleway_m",
        "nearest_playground_m",
        "nearest_school_m",
        "nearest_running_m",
    ):
        if livability_key not in livability_snapshot and isinstance(facts.get(livability_key), (int, float)):
            livability_snapshot[livability_key] = facts.get(livability_key)
    location_fit_value = assessment.get("location_fit_score")
    location_fit = int(round(float(location_fit_value))) if isinstance(location_fit_value, (int, float)) else None
    distance_rows = _distance_rows(livability_snapshot)
    has_floorplan = _fact_bool("has_floorplan")
    has_lift = _fact_bool("lift")
    has_balcony = _fact_bool("balcony") or _fact_bool("terrace")
    nearest_playground = livability_snapshot.get("nearest_playground_m")
    district = html.escape(str(facts.get("postal_name") or facts.get("district") or "").strip())
    source_tour_link = ""
    rooms_chip = rooms if rooms != "?" else ""
    area_chip = area if area != "?" else ""
    rent_chip = rent if rent != "EUR ?" else ""
    availability_chip = availability if availability != "?" else ""
    decision_rows = _decision_rows()
    personalized_positive, personalized_caution, personalized_unknowns = _personalized_priority_rows()
    highlight_lines = personalized_positive or good_fit_reasons[:4] or _feature_highlights()
    concern_lines = personalized_caution or bad_fit_reasons[:4] or _feature_concerns()
    unknown_lines = personalized_unknowns or unknowns[:4]
    completed_research_line = ""
    if researched_facts:
        research_fragments: list[str] = []
        if _fact_text("street_address", "exact_address"):
            research_fragments.append("address")
        if _fact_bool("lift"):
            research_fragments.append("lift")
        if _fact_bool("has_floorplan"):
            research_fragments.append("floor plan")
        availability_value = _fact_text("availability")
        if availability_value:
            research_fragments.append(f"availability ({availability_value})")
        if isinstance(facts.get("nearest_supermarket_m"), (int, float)):
            research_fragments.append("supermarket distance")
        if isinstance(facts.get("nearest_pharmacy_m"), (int, float)):
            research_fragments.append("pharmacy distance")
        if isinstance(facts.get("nearest_playground_m"), (int, float)):
            research_fragments.append("playground distance")
        if isinstance(facts.get("nearest_subway_m"), (int, float)):
            research_fragments.append("underground distance")
        if research_fragments:
            completed_research_line = f"Source research already filled: {', '.join(research_fragments)}."
    if is_pure_360_cube and source_virtual_tour_url:
        fit_score_chip = f'<div class="chip">Fit {fit_score}/100</div>' if fit_score is not None else ""
        recommendation_chip = f'<div class="chip">{recommendation}</div>' if recommendation else ""
        location_chip = f'<div class="chip">Area fit {location_fit}/10</div>' if location_fit is not None else ""
        district_chip = f'<div class="chip">{district}</div>' if district else ""
        rooms_chip_html = f'<div class="chip">{html.escape(rooms_chip)}</div>' if rooms_chip else ""
        area_chip_html = f'<div class="chip">{html.escape(area_chip)}</div>' if area_chip else ""
        rent_chip_html = f'<div class="chip">{html.escape(rent_chip)}</div>' if rent_chip else ""
        availability_chip_html = f'<div class="chip">{html.escape(availability_chip)}</div>' if availability_chip else ""
        reasons_html = "".join(f"<li>{html.escape(item)}</li>" for item in highlight_lines)
        risks_html = "".join(f"<li>{html.escape(item)}</li>" for item in concern_lines)
        unknowns_html = "".join(f"<li>{html.escape(item)}</li>" for item in unknown_lines)
        decision_html = "".join(
            f'<div class="stat"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'
            for label, value in decision_rows
        )
        distance_html = "".join(
            f'<div class="stat"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'
            for label, value in distance_rows
        )
        recommendation_label = "Conditional match"
        if fit_score is not None and fit_score >= 78:
            recommendation_label = "Strong match"
        elif fit_score is not None and fit_score <= 49:
            recommendation_label = "Low match"
        recommendation_note = (
            highlight_lines[0]
            if highlight_lines
            else "The decision should be driven by constraints, neighborhood fit, and cost risk rather than the tour itself."
        )
        requirement_rows: list[tuple[str, str, str, str]] = []
        snapshot = dict(facts.get("public_preference_snapshot") or {}) if isinstance(facts.get("public_preference_snapshot"), dict) else {}
        nodes = [dict(row) for row in list(snapshot.get("preference_nodes") or []) if isinstance(row, dict)]
        for row in nodes:
            key = str(row.get("key") or "").strip().lower()
            value = row.get("value_json")
            if key == "avoid_heating_types" and isinstance(value, list):
                heating_value = _fact_text("heating", "heating_type") or "Unknown"
                avoided = ", ".join(str(item or "").strip() for item in value if str(item or "").strip())
                status = "Conflict" if "gas" in heating_value.lower() and any("gas" in str(item).lower() for item in value) else "Match"
                note = f"Preference excludes {avoided}." if avoided else "Heating preference stored."
                requirement_rows.append(("Heating", heating_value, status, note))
            elif key in {"require_floorplan", "requires_floorplan_for_remote_review"}:
                requirement_rows.append(("Floor plan", "Available" if has_floorplan else "Missing", "Match" if has_floorplan else "Unknown", "Remote layout review depends on this."))
            elif key == "prefer_lift":
                requirement_rows.append(("Lift", "Present" if has_lift else "Not confirmed", "Match" if has_lift else "Unknown", "Building access preference."))
            elif key == "prefer_balcony":
                requirement_rows.append(("Outdoor space", "Present" if has_balcony else "Not confirmed", "Match" if has_balcony else "Unknown", "Balcony or terrace preference."))
            elif "playground" in key:
                playground_value = f"{int(nearest_playground):d} m" if isinstance(nearest_playground, (int, float)) and nearest_playground > 0 else "Unknown"
                requirement_rows.append(("Playground access", playground_value, "Match" if playground_value != "Unknown" else "Unknown", "Family-fit proximity check."))
        if not requirement_rows:
            requirement_rows.extend(
                [
                    ("Heating", _fact_text("heating", "heating_type") or "Unknown", "Conflict" if "gas" in _fact_text("heating", "heating_type").lower() else "Check", "Operating-cost and preference fit."),
                    ("Floor plan", "Available" if has_floorplan else "Missing", "Match" if has_floorplan else "Unknown", "Layout validation."),
                    ("Lift", "Present" if has_lift else "Not confirmed", "Match" if has_lift else "Unknown", "Access convenience."),
                ]
            )
        requirement_table = "".join(
            f'<tr><td data-label="Requirement">{html.escape(label)}</td><td data-label="Property answer">{html.escape(answer)}</td><td data-label="Status"><span class="status status-{status.lower().replace(" ", "-")}">{html.escape(status)}</span></td><td data-label="Why it matters">{html.escape(note)}</td></tr>'
            for label, answer, status, note in requirement_rows[:8]
        )
        cost_rows: list[tuple[str, str]] = []
        if rent_chip:
            cost_rows.append(("Base rent", rent_chip))
        if isinstance(facts.get("parking_monthly_eur"), (int, float)) and float(facts.get("parking_monthly_eur") or 0.0) > 0:
            cost_rows.append(("Parking option", f"EUR {int(float(facts.get('parking_monthly_eur') or 0.0))}/month"))
        heating_value = _fact_text("heating", "heating_type")
        if heating_value:
            cost_rows.append(("Heating system", heating_value))
        lease_term_value = facts.get("lease_term_years_max")
        if isinstance(lease_term_value, (int, float)) and lease_term_value > 0:
            cost_rows.append(("Lease term", f"About {int(lease_term_value)} years"))
        cost_html = "".join(
            f'<div class="stat"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'
            for label, value in cost_rows
        )
        evidence_rows: list[tuple[str, str, str]] = []
        evidence_specs = (
            ("street_address", "Address"),
            ("lift", "Lift"),
            ("has_floorplan", "Floor plan"),
            ("availability", "Availability"),
            ("nearest_supermarket_m", "Supermarket"),
            ("nearest_pharmacy_m", "Pharmacy"),
            ("nearest_playground_m", "Playground"),
            ("nearest_subway_m", "Underground"),
        )
        for key, label in evidence_specs:
            raw_value = facts.get(key)
            if _fact_value_is_weak(raw_value):
                continue
            if isinstance(raw_value, bool):
                value = "Confirmed" if raw_value else "Not confirmed"
            elif isinstance(raw_value, (int, float)) and key.endswith("_m"):
                value = f"about {int(raw_value)} m"
            else:
                value = str(raw_value)
            provenance = "Researched" if key in researched_facts else "Listing"
            if key in {"street_address", "exact_address"} and "map_lat" in researched_facts:
                provenance = "Inferred"
            evidence_rows.append((label, value, provenance))
        evidence_html = "".join(
            f'<div class="evidence-row"><div><b>{html.escape(label)}</b><span>{html.escape(value)}</span></div><em class="provenance provenance-{provenance.lower()}">{html.escape(provenance)}</em></div>'
            for label, value, provenance in evidence_rows
        )
        feedback_negative = [dict(row) for row in list(feedback_suggestions.get("negative") or []) if isinstance(row, dict)]
        feedback_positive = [dict(row) for row in list(feedback_suggestions.get("positive") or []) if isinstance(row, dict)]
        feedback_negative_html = "".join(
            f'<button class="reason-chip reason-chip-negative" type="button" data-reason-key="{html.escape(str(row.get("key") or ""))}" data-sentiment="negative">{html.escape(str(row.get("label") or ""))}</button>'
            for row in feedback_negative
        )
        feedback_positive_html = "".join(
            f'<button class="reason-chip reason-chip-positive" type="button" data-reason-key="{html.escape(str(row.get("key") or ""))}" data-sentiment="positive">{html.escape(str(row.get("label") or ""))}</button>'
            for row in feedback_positive
        )
        learned_likes = _text_list(learning_summary.get("likes"))
        learned_dislikes = _text_list(learning_summary.get("dislikes"))
        learned_hard_rules = _text_list(learning_summary.get("hard_rules"))
        recent_feedback_rows = [dict(row) for row in list(learning_summary.get("recent_feedback") or []) if isinstance(row, dict)]
        learned_likes_html = "".join(f"<li>{html.escape(item)}</li>" for item in learned_likes[:6])
        learned_dislikes_html = "".join(f"<li>{html.escape(item)}</li>" for item in learned_dislikes[:6])
        learned_hard_rules_html = "".join(f"<li>{html.escape(item)}</li>" for item in learned_hard_rules[:4])
        recent_feedback_html = "".join(
            (
                '<div class="feedback-log-row">'
                f'<b>{html.escape(str(row.get("reaction") or "").title() or "Feedback")}</b>'
                f'<span>{html.escape(", ".join(_feedback_reason_label(item) for item in list(row.get("reasons") or []) if str(item or "").strip()) or "No structured reasons yet")}</span>'
                f'<em>{html.escape(str(row.get("recorded_at") or "")[:16].replace("T", " "))}</em>'
                '</div>'
            )
            for row in recent_feedback_rows[:6]
        )
        comparison_positive = (personalized_positive or good_fit_reasons or highlight_lines)[:3]
        comparison_conflicts = (personalized_caution or bad_fit_reasons or concern_lines)[:3]
        comparison_hard = learned_hard_rules[:3]
        comparison_panel = (
            '<section class="panel">'
            '<div class="eyebrow">Pattern Compare</div>'
            '<h2>How this compares to your learned pattern</h2>'
            '<div class="summary-grid" style="margin-top:0;">'
            '<div class="summary-card"><h3>Matches your pattern</h3><ul>'
            f'{"".join(f"<li>{html.escape(item)}</li>" for item in comparison_positive) or "<li>No strong positive pattern match is clear yet.</li>"}'
            '</ul></div>'
            '<div class="summary-card"><h3>Breaks your pattern</h3><ul>'
            f'{"".join(f"<li>{html.escape(item)}</li>" for item in comparison_conflicts) or "<li>No strong learned conflict is visible yet.</li>"}'
            '</ul></div>'
            '<div class="summary-card"><h3>Hard-rule pressure</h3><ul>'
            f'{"".join(f"<li>{html.escape(item)}</li>" for item in comparison_hard) or "<li>No hard-rule pressure is stored yet.</li>"}'
            '</ul></div>'
            '</div>'
            '</section>'
        )
        shortlist_items = [dict(row) for row in list(shortlist_compare.get("items") or []) if isinstance(row, dict)]
        shortlist_current = dict(shortlist_compare.get("current") or {}) if isinstance(shortlist_compare.get("current"), dict) else {}
        shortlist_metric_specs = shortlist_compare.get("metric_specs")
        shortlist_columns: list[tuple[str, str, str]] = [
            (str(key).strip(), str(label).strip(), str(direction).strip())
            for key, label, direction in (
                tuple(shortlist_metric_specs)
                if isinstance(shortlist_metric_specs, tuple)
                else list(shortlist_metric_specs) if isinstance(shortlist_metric_specs, list) else []
            )
            if isinstance(key, str) and isinstance(label, str) and isinstance(direction, str)
        ]
        if not shortlist_columns:
            shortlist_columns = list(_shortlist_metric_labels())
        shortlist_rows: list[dict[str, object]] = []
        if shortlist_current:
            shortlist_rows.append(shortlist_current)
        shortlist_rows.extend(shortlist_items)

        shortlist_cards = ""
        if shortlist_rows:
            shortlist_cards = "".join(
                (
                    '<div class="summary-card">'
                    f'<h3>{html.escape(str(card.get("title") or "Property").strip())}</h3>'
                    f'<div class="subtle">{html.escape(str(card.get("score_label") or "Fit").strip())} '
                    f'{int(round(float(card.get("score") or 0.0))):d}/100</div>'
                    f'<p class="sub">{html.escape(str(card.get("why_now") or "No comparison note stored.").strip())}</p>'
                    f'<a class="chip compare-chip" href="{html.escape(str(card.get("listing_url") or "#").strip())}"'
                    f'{"" if str(card.get("listing_url") or "").strip() else " aria-disabled=\"true\""}>{html.escape(str(card.get("recommended_action") or "review").strip())}</a>'
                    '</div>'
                )
                for card in shortlist_rows[:3]
            )

        shortlist_matrix_rows: list[str] = []
        if shortlist_rows and len(shortlist_rows) > 1:
            baseline = dict(shortlist_rows[0].get("metrics") or {})
            header_cells = [
                "<th>Metric</th>",
                f'<th>{html.escape(str(shortlist_rows[0].get("title") or "Current property"))}</th>',
            ]
            for candidate in shortlist_rows[1:]:
                candidate_title = str(candidate.get("title") or "Shortlist property").strip() or "Shortlist property"
                candidate_url = str(candidate.get("listing_url") or "").strip()
                if candidate_url:
                    header_cells.append(
                        f'<th><a class="shortlist-header-link" href="{html.escape(candidate_url)}" '
                        f'target="_blank" rel="noreferrer">{html.escape(candidate_title)}</a></th>'
                    )
                else:
                    header_cells.append(f"<th>{html.escape(candidate_title)}</th>")
            shortlist_matrix_rows.append(f"<tr>{''.join(header_cells)}</tr>")
            for metric_key, metric_label, _metric_direction in shortlist_columns:
                row_cells: list[str] = [f"<th class=\"shortlist-metric-label\">{html.escape(metric_label)}</th>"]
                for index, row in enumerate(shortlist_rows):
                    metrics = dict(row.get("metrics") or {})
                    value = _shortlist_metric_display(metric_key, metrics.get(metric_key))
                    if index == 0:
                        row_cells.append(f"<td><span class=\"shortlist-value\">{html.escape(value)}</span></td>")
                        continue
                    delta_text, delta_tone = _shortlist_metric_delta(
                        metric_key,
                        baseline=baseline.get(metric_key),
                        candidate=metrics.get(metric_key),
                    )
                    row_cells.append(
                        "<td>"
                        f"<span class=\"shortlist-value\">{html.escape(value)}</span>"
                        f"<span class=\"shortlist-delta shortlist-delta-{html.escape(delta_tone)}\">{html.escape(str(delta_text))}</span>"
                        "</td>"
                    )
                shortlist_matrix_rows.append(f"<tr>{''.join(row_cells)}</tr>")

        shortlist_matrix = (
            '<div class="shortlist-matrix-wrap">'
            '<table class="shortlist-table">'
            f'<tbody>{"".join(shortlist_matrix_rows)}</tbody>'
            "</table>"
            "</div>"
        ) if shortlist_matrix_rows else (
            '<div class="summary-card shortlist-empty">No shortlist comparison matrix is available yet.</div>'
        )

        shortlist_panel = (
            '<section class="panel">'
            '<div class="eyebrow">Shortlist Compare</div>'
            '<h2>Current property against active shortlist items</h2>'
            '<div class="summary-grid" style="margin-top:0;">'
            f'{shortlist_cards or "<div class=\"summary-card\"><h3>No shortlist loaded</h3><p class=\"sub\">No other active shortlist property is currently available for side-by-side comparison.</p></div>"}'
            '</div>'
            f'{shortlist_matrix}'
            '</section>'
        )
        detail_request_button = ""
        if str(payload.get("principal_id") or "").strip() and str(payload.get("property_url") or listing_url).strip():
            detail_request_button = (
                '<div class="request-row">'
                '<button id="request-details-btn" class="request-btn" type="button">Request deeper research</button>'
                '<span id="request-details-status" class="request-status"></span>'
                '</div>'
            )
        active_filter_labels = [str(item or "").strip() for item in list(filter_context.get("active_labels") or []) if str(item or "").strip()]
        hard_filter_button_html = "".join(
            (
                f'<button class="reason-chip filter-chip{" active" if bool(spec.get("active")) else ""}" '
                f'type="button" data-filter-key="{html.escape(str(spec.get("key") or ""))}" '
                f'data-enabled="{html.escape("false" if bool(spec.get("active")) else "true")}">'
                f'{html.escape(str(spec.get("label") or ""))}'
                '</button>'
            )
            for spec in list(filter_context.get("hard_filters") or [])
            if isinstance(spec, dict)
        )
        soft_filter_button_html = "".join(
            (
                f'<button class="reason-chip filter-chip{" active" if bool(spec.get("active")) else ""}" '
                f'type="button" data-filter-key="{html.escape(str(spec.get("key") or ""))}" '
                f'data-enabled="{html.escape("false" if bool(spec.get("active")) else "true")}">'
                f'{html.escape(str(spec.get("label") or ""))}'
                '</button>'
            )
            for spec in list(filter_context.get("soft_filters") or [])
            if isinstance(spec, dict)
        )
        active_filter_html = "".join(f"<li>{html.escape(label)}</li>" for label in active_filter_labels[:8])
        filters_panel = ""
        if str(payload.get("principal_id") or "").strip():
            filters_panel = (
                '<section id="filters" class="panel">'
                '<div class="eyebrow">Search Filters</div>'
                '<h2>Tune what future properties should pass</h2>'
                '<p class="sub">These are real ranking and suppression rules for future alerts, not just notes on this listing.</p>'
                '<div class="summary-grid filter-summary-grid" style="margin-top:16px;">'
                '<div class="summary-card"><h3>Active filters</h3><ul>'
                f'{active_filter_html or "<li>No explicit property filters are active yet.</li>"}'
                '</ul></div>'
                '<div class="summary-card"><h3>Quick toggles</h3>'
                '<div class="filter-group"><b>Hard blocks and must-haves</b>'
                f'<div class="reason-chip-row filter-chip-row">{hard_filter_button_html or "<span class=\"subtle\">No hard filters available here.</span>"}</div></div>'
                '<div class="filter-group"><b>Soft ranking signals</b>'
                f'<div class="reason-chip-row filter-chip-row">{soft_filter_button_html or "<span class=\"subtle\">No soft filters available here.</span>"}</div></div>'
                '</div></div>'
                '<div class="request-row"><span id="filter-status" class="request-status"></span></div>'
                '</section>'
            )
        feedback_panel = ""
        if str(payload.get("principal_id") or "").strip():
            feedback_panel = (
                '<section id="feedback" class="panel">'
                '<div class="eyebrow">Preference Feedback</div>'
                '<h2>Teach the system what to rank higher or lower</h2>'
                '<p class="sub">Give a quick reaction and mark the concrete reasons. Future property scoring and Telegram selection will use this feedback.</p>'
                '<div class="feedback-reaction-row">'
                '<button class="reaction-btn" type="button" data-reaction="like">Like</button>'
                '<button class="reaction-btn" type="button" data-reaction="maybe">Maybe</button>'
                '<button class="reaction-btn" type="button" data-reaction="dislike">Dislike</button>'
                '<button class="reaction-btn" type="button" data-reaction="hide">Hide</button>'
                '</div>'
                '<div class="feedback-groups">'
                '<div><h3>What hurts this property</h3><div class="reason-chip-row">'
                f'{feedback_negative_html or "<span class=\"subtle\">No structured negatives suggested yet.</span>"}'
                '</div></div>'
                '<div><h3>What works well</h3><div class="reason-chip-row">'
                f'{feedback_positive_html or "<span class=\"subtle\">No structured positives suggested yet.</span>"}'
                '</div></div>'
                '</div>'
                '<label class="feedback-note-label" for="feedback-note">Optional note</label>'
                '<textarea id="feedback-note" class="feedback-note" rows="3" placeholder="Anything subtle that the chips missed."></textarea>'
                '<div class="request-row">'
                '<button id="feedback-submit-btn" class="request-btn" type="button">Save feedback</button>'
                '<span id="feedback-status" class="request-status"></span>'
                '</div>'
                '</section>'
            )
        learned_panel = (
            '<section class="panel">'
            '<div class="eyebrow">Learning Loop</div>'
            '<h2>What the system has learned from you</h2>'
            '<div class="summary-grid" style="margin-top:0;">'
            '<div class="summary-card"><h3>Likes</h3><ul>'
            f'{learned_likes_html or "<li>No strong positive preference learned yet.</li>"}'
            '</ul></div>'
            '<div class="summary-card"><h3>Dislikes</h3><ul>'
            f'{learned_dislikes_html or "<li>No strong aversion learned yet.</li>"}'
            '</ul></div>'
            '<div class="summary-card"><h3>Hard rules</h3><ul>'
            f'{learned_hard_rules_html or "<li>No hard constraint has been locked in yet.</li>"}'
            '</ul></div>'
            '</div>'
            '<div class="feedback-log">'
            f'{recent_feedback_html or "<p class=\"sub\">No recent structured property feedback has been recorded yet.</p>"}'
            '</div>'
            '</section>'
        )
        return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title_html}</title>
    {clickrank_head_snippet(hostname)}
    <style>
      :root {{
        --bg: #f5f2ec;
        --panel: #ffffff;
        --panel-soft: #f7f6f3;
        --ink: #171717;
        --muted: #646464;
        --accent: #8d3f1f;
        --edge: #e6e0d6;
        --good: #166534;
        --warn: #9a6700;
        --risk: #991b1b;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--ink);
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: var(--bg);
      }}
      .shell {{ max-width: 1340px; margin: 0 auto; padding: 22px; }}
      .topbar, .panel, .live-shell, .hero, .section-band {{
        background: var(--panel);
        border: 1px solid var(--edge);
        border-radius: 18px;
        box-shadow: 0 8px 28px rgba(17, 17, 17, 0.05);
      }}
      .topbar, .panel, .live-shell, .hero, .section-band {{ padding: 20px; }}
      .topbar {{ position: sticky; top: 0; z-index: 20; display: flex; gap: 10px; align-items: center; justify-content: space-between; margin-bottom: 16px; flex-wrap: wrap; backdrop-filter: blur(12px); }}
      .section-nav {{ display: flex; gap: 8px; flex-wrap: wrap; }}
      .eyebrow {{ display: inline-flex; gap: 8px; align-items: center; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); }}
      h1 {{ margin: 10px 0 10px; font-size: clamp(2rem, 3vw, 3.2rem); line-height: 1.02; }}
      h2 {{ margin: 0 0 14px; font-size: 1.05rem; }}
      h3 {{ margin: 0 0 10px; font-size: 0.95rem; }}
      .sub {{ margin: 0; color: var(--muted); font-size: 0.98rem; line-height: 1.55; max-width: 72ch; }}
      .hero {{ display: grid; grid-template-columns: 1.25fr 0.75fr; gap: 18px; align-items: start; margin-bottom: 18px; }}
      .summary-grid, .section-grid {{ display: grid; gap: 18px; }}
      .summary-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 18px; }}
      .section-grid {{ grid-template-columns: 1.05fr 0.95fr; margin-top: 18px; }}
      .facts, .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }}
      .chip, .ghost, .cta {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 38px;
        padding: 0 14px;
        border-radius: 999px;
        background: var(--panel-soft);
        border: 1px solid var(--edge);
        color: inherit;
        text-decoration: none;
        font-size: 0.92rem;
      }}
      .cta {{ background: var(--ink); color: #fff; border-color: var(--ink); }}
      .kicker {{
        display: inline-flex;
        align-items: center;
        gap: 10px;
        min-height: 34px;
        padding: 0 12px;
        border-radius: 999px;
        background: #f0ebe4;
        color: var(--accent);
        font-size: 0.86rem;
      }}
      .summary-card, .panel, .live-shell {{
        background: var(--panel);
      }}
      .summary-card {{
        padding: 16px;
        border-radius: 16px;
        border: 1px solid var(--edge);
        background: var(--panel-soft);
      }}
      .filter-summary-grid {{ grid-template-columns: minmax(0, 0.75fr) minmax(0, 1.25fr); }}
      .summary-card ul, .panel ul {{ margin: 0; padding-left: 18px; }}
      .summary-card li + li, .panel li + li {{ margin-top: 8px; }}
      .compare-chip {{ margin-top: 12px; }}
      .stat-grid {{
        display: grid;
        gap: 10px;
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .stat {{
        padding: 12px 14px;
        border-radius: 14px;
        background: var(--panel-soft);
        border: 1px solid var(--edge);
        display: grid;
        gap: 4px;
      }}
      .stat span {{
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
      }}
      .stat strong {{ font-size: 1rem; font-weight: 600; }}
      .workspace-grid {{
        display: grid;
        grid-template-columns: 1.05fr 0.95fr;
        gap: 18px;
        align-items: start;
      }}
      .workspace-stack {{ display: grid; gap: 18px; }}
      .requirement-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.94rem;
      }}
      .requirement-table th, .requirement-table td {{
        padding: 12px 10px;
        border-bottom: 1px solid var(--edge);
        vertical-align: top;
        text-align: left;
      }}
      .requirement-table th {{
        font-size: 0.74rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
      }}
      .status {{
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        padding: 0 10px;
        border-radius: 999px;
        font-size: 0.82rem;
        border: 1px solid transparent;
      }}
      .status-match {{ background: rgba(22,101,52,0.10); color: var(--good); border-color: rgba(22,101,52,0.18); }}
      .status-conflict {{ background: rgba(153,27,27,0.10); color: var(--risk); border-color: rgba(153,27,27,0.18); }}
      .status-unknown, .status-check {{ background: rgba(154,103,0,0.10); color: var(--warn); border-color: rgba(154,103,0,0.18); }}
      details.research-card {{
        padding: 12px 14px;
        border-radius: 14px;
        background: var(--panel-soft);
        border: 1px solid var(--edge);
      }}
      details.research-card + details.research-card {{ margin-top: 12px; }}
      details.research-card > summary {{ cursor: pointer; font-weight: 600; }}
      .evidence-stack {{ display: grid; gap: 10px; }}
      .evidence-row {{
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: center;
        padding: 12px 14px;
        border-radius: 14px;
        background: var(--panel-soft);
        border: 1px solid var(--edge);
      }}
      .evidence-row b, .evidence-row span {{
        display: block;
      }}
      .evidence-row b {{ margin-bottom: 4px; font-size: 0.86rem; }}
      .evidence-row span {{ color: var(--muted); font-size: 0.92rem; }}
      .shortlist-matrix-wrap {{
        margin-top: 14px;
        overflow-x: auto;
        border: 1px solid var(--edge);
        border-radius: 14px;
        background: var(--panel-soft);
      }}
      .shortlist-table {{
        width: 100%;
        border-collapse: collapse;
        min-width: 780px;
      }}
      .shortlist-table th,
      .shortlist-table td {{
        padding: 12px 10px;
        border-bottom: 1px solid var(--edge);
        border-right: 1px solid var(--edge);
        text-align: left;
        vertical-align: top;
      }}
      .shortlist-table th:last-child,
      .shortlist-table td:last-child {{ border-right: 0; }}
      .shortlist-table th {{
        background: #f0ebe4;
        color: var(--muted);
        font-size: 0.74rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }}
      .shortlist-metric-label {{
        width: 170px;
        white-space: nowrap;
      }}
      .shortlist-table tbody tr:last-child th,
      .shortlist-table tbody tr:last-child td {{
        border-bottom: 0;
      }}
      .shortlist-header-link {{
        color: inherit;
        font-weight: 600;
        text-decoration: none;
        display: inline-flex;
      }}
      .shortlist-header-link:hover {{
        text-decoration: underline;
      }}
      .shortlist-value {{
        display: block;
        font-weight: 600;
      }}
      .shortlist-delta {{
        display: inline-flex;
        margin-top: 6px;
        font-size: 0.76rem;
        font-weight: 600;
      }}
      .shortlist-delta-better {{ color: var(--good); }}
      .shortlist-delta-worse {{ color: var(--risk); }}
      .shortlist-delta-neutral {{ color: var(--muted); }}
      .shortlist-empty {{
        margin-top: 12px;
      }}
      .provenance {{
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        padding: 0 10px;
        border-radius: 999px;
        font-size: 0.8rem;
        font-style: normal;
        border: 1px solid var(--edge);
        background: #fff;
      }}
      .request-row {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-top: 14px; }}
      .request-btn {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 40px;
        padding: 0 16px;
        border-radius: 999px;
        border: 1px solid var(--edge);
        background: var(--panel-soft);
        color: inherit;
        cursor: pointer;
      }}
      .request-status {{ color: var(--muted); font-size: 0.95rem; }}
      .feedback-reaction-row, .reason-chip-row, .feedback-groups {{
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
      }}
      .filter-chip-row {{ align-items: stretch; }}
      .filter-group {{ display: grid; gap: 10px; margin-top: 12px; }}
      .filter-group b {{ font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }}
      .feedback-groups {{ flex-direction: column; margin-top: 14px; }}
      .reaction-btn, .reason-chip {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 38px;
        padding: 0 14px;
        border-radius: 999px;
        border: 1px solid var(--edge);
        background: var(--panel-soft);
        color: inherit;
        cursor: pointer;
      }}
      .filter-chip {{ min-height: 44px; font-weight: 600; text-align: center; }}
      .reaction-btn.active {{ background: var(--ink); color: #fff; border-color: var(--ink); }}
      .reason-chip.active {{ border-color: var(--accent); color: var(--accent); background: #fff8f3; }}
      .reason-chip-negative {{ background: #fbf5f3; }}
      .reason-chip-positive {{ background: #f3f8f3; }}
      .feedback-note-label {{ display: block; margin: 16px 0 8px; font-size: 0.85rem; color: var(--muted); }}
      .feedback-note {{
        width: 100%;
        border-radius: 14px;
        border: 1px solid var(--edge);
        background: var(--panel-soft);
        padding: 12px 14px;
        resize: vertical;
        font: inherit;
        color: inherit;
      }}
      .feedback-log {{ display: grid; gap: 10px; margin-top: 16px; }}
      .feedback-log-row {{
        display: grid;
        gap: 4px;
        padding: 12px 14px;
        border-radius: 14px;
        border: 1px solid var(--edge);
        background: var(--panel-soft);
      }}
      .feedback-log-row span, .subtle {{ color: var(--muted); font-size: 0.92rem; }}
      .ooda-grid {{
        display: grid;
        gap: 10px;
      }}
      .ooda-cell {{
        padding: 12px 14px;
        border-radius: 14px;
        background: var(--panel-soft);
        border: 1px solid var(--edge);
      }}
      .ooda-cell b {{
        display: block;
        margin-bottom: 4px;
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
      }}
      .live-frame-wrap {{
        overflow: hidden;
        border-radius: 16px;
        background: rgba(18,17,16,0.94);
        border: 1px solid var(--edge);
        min-height: 540px;
      }}
      .live-frame {{
        display: block;
        width: 100%;
        height: 78vh;
        min-height: 540px;
        border: 0;
        background: #111;
      }}
      a {{ color: inherit; text-decoration: none; }}
      @media (max-width: 1000px) {{
        .hero, .section-grid, .workspace-grid, .summary-grid {{ grid-template-columns: 1fr; }}
        .stat-grid {{ grid-template-columns: 1fr; }}
        .filter-summary-grid {{ grid-template-columns: 1fr; }}
      }}
      @media (max-width: 720px) {{
        .section-nav {{
          flex-wrap: nowrap;
          overflow-x: auto;
          padding-bottom: 4px;
          width: 100%;
          scrollbar-width: none;
        }}
        .section-nav::-webkit-scrollbar {{ display: none; }}
        .section-nav .ghost {{ flex: 0 0 auto; min-height: 40px; padding: 0 12px; }}
        .facts {{
          flex-wrap: nowrap;
          overflow-x: auto;
          padding-bottom: 4px;
          scrollbar-width: none;
        }}
        .facts::-webkit-scrollbar {{ display: none; }}
        .facts .chip {{ flex: 0 0 auto; }}
        .requirement-table, .requirement-table thead, .requirement-table tbody, .requirement-table tr, .requirement-table td {{
          display: block;
          width: 100%;
        }}
        .requirement-table thead {{
          position: absolute;
          width: 1px;
          height: 1px;
          padding: 0;
          margin: -1px;
          overflow: hidden;
          clip: rect(0, 0, 0, 0);
          white-space: nowrap;
          border: 0;
        }}
        .requirement-table tbody {{ display: grid; gap: 12px; }}
        .requirement-table tr {{
          border: 1px solid var(--edge);
          border-radius: 14px;
          background: var(--panel-soft);
          padding: 12px;
        }}
        .requirement-table td {{ border: 0; padding: 8px 0 0; }}
        .requirement-table td:first-child {{ padding-top: 0; }}
        .requirement-table td::before {{
          content: attr(data-label);
          display: block;
          margin-bottom: 4px;
          font-size: 0.72rem;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          color: var(--muted);
        }}
        .evidence-row {{ display: grid; justify-content: start; }}
        .request-row {{ align-items: stretch; }}
        .request-btn, .reaction-btn {{ width: 100%; }}
      }}
      @media (max-width: 640px) {{
        .shell {{ padding: 14px; }}
        .topbar, .panel, .live-shell, .hero, .section-band {{ padding: 16px; border-radius: 16px; }}
        h1 {{ font-size: clamp(1.85rem, 10vw, 2.5rem); line-height: 1; }}
        .sub {{ max-width: none; font-size: 0.95rem; }}
        .actions {{ display: grid; grid-template-columns: 1fr; }}
        .actions .cta, .actions .ghost {{ width: 100%; }}
        .feedback-reaction-row {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        .reason-chip-row {{ display: grid; grid-template-columns: 1fr; }}
        .live-frame-wrap {{ min-height: 380px; }}
        .live-frame {{ min-height: 380px; height: 60vh; }}
      }}
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="topbar">
        <div class="eyebrow">Property Decision Workstation <span>•</span> personalized review</div>
        <nav class="section-nav">
          <a class="ghost" href="#decision">Decision</a>
          <a class="ghost" href="#match">Match</a>
          <a class="ghost" href="#location">Location</a>
          <a class="ghost" href="#costs">Costs</a>
          <a class="ghost" href="#filters">Filters</a>
          <a class="ghost" href="#feedback">Feedback</a>
          <a class="ghost" href="#risks">Risks</a>
          <a class="ghost" href="#research">Research</a>
          <a class="ghost" href="#tour">3D Tour</a>
        </nav>
      </div>
      <section id="decision" class="hero">
        <div>
          <div class="kicker">{html.escape(recommendation_label)}</div>
          <h1>{title_html}</h1>
          <p class="sub">{display_html}</p>
          <div class="facts">
            {rooms_chip_html}
            {area_chip_html}
            {rent_chip_html}
            {availability_chip_html}
            {fit_score_chip}
            {recommendation_chip}
            {location_chip}
            {district_chip}
            <div class="chip">{html.escape(str(payload.get("scene_count") or len(scenes)))} tour scenes</div>
          </div>
          <p class="sub">{html.escape(recommendation_note)}</p>
          <div class="actions">
            <a class="cta" href="#tour">Open 3D Tour</a>
            {listing_link}
            {hosted_link}
          </div>
          <div class="summary-grid">
            <div class="summary-card">
              <h3>Why it fits</h3>
              <ul>{reasons_html}</ul>
            </div>
            <div class="summary-card">
              <h3>Decision pressure</h3>
              <ul>{risks_html}</ul>
            </div>
            <div class="summary-card">
              <h3>Still missing</h3>
              <ul>{unknowns_html}</ul>
            </div>
          </div>
        </div>
        <aside class="panel">
          <h2>Decision Summary</h2>
          <div class="stat-grid">{decision_html}</div>
          <div class="ooda-grid" style="margin-top:16px;">
            <div class="ooda-cell"><b>Observe</b>{html.escape(highlight_lines[0]) if highlight_lines else 'Current facts are still incomplete.'}</div>
            <div class="ooda-cell"><b>Orient</b>{html.escape((personalized_positive or good_fit_reasons or ['The current fit is driven by the stored constraints and research pass.'])[0])}</div>
            <div class="ooda-cell"><b>Decide</b>{html.escape((personalized_caution or bad_fit_reasons or ['Shortlist only if the open questions are acceptable.'])[0])}</div>
            <div class="ooda-cell"><b>Act</b>{html.escape((personalized_unknowns or unknowns or ['Trigger deeper research before deciding.'])[0])}</div>
          </div>
        </aside>
      </section>
      <div class="workspace-grid">
        <div class="workspace-stack">
          <section id="match" class="panel">
            <div class="eyebrow">Requirement Match</div>
            <h2>Preference-to-Property Matrix</h2>
            <table class="requirement-table">
              <thead>
                <tr><th>Requirement</th><th>Property answer</th><th>Status</th><th>Why it matters</th></tr>
              </thead>
              <tbody>{requirement_table}</tbody>
            </table>
          </section>
          <section id="location" class="panel">
            <div class="eyebrow">Location Fit</div>
            <h2>Daily-life access</h2>
            <div class="stat-grid">{distance_html}</div>
          </section>
          <section id="costs" class="panel">
            <div class="eyebrow">Cost Picture</div>
            <h2>Monthly and structural costs</h2>
            <div class="stat-grid">{cost_html}</div>
          </section>
          {filters_panel}
          {feedback_panel}
          <section id="tour" class="live-shell">
            <div class="eyebrow">{brand_html} <span>•</span> 3D Evidence</div>
            <h2>Inspect layout, light, and finish quality</h2>
            <p class="sub">Use the original interactive 360 experience as evidence after reviewing the decision brief, not as the decision brief itself.</p>
            <div class="live-frame-wrap">
              <iframe
                class="live-frame"
                src="{html.escape(source_virtual_tour_url)}"
                title="{title_html}"
                allowfullscreen
                loading="eager"
                referrerpolicy="no-referrer-when-downgrade"
              ></iframe>
            </div>
          </section>
        </div>
        <div class="workspace-stack">
          <section id="risks" class="panel">
            <div class="eyebrow">Risk Register</div>
            <h2>What can still break the decision</h2>
            <ul>{risks_html}</ul>
          </section>
          {shortlist_panel}
          {comparison_panel}
          <section id="research" class="panel">
            <div class="eyebrow">Research Log</div>
            <h2>Confirmed, inferred, and open</h2>
            <details class="research-card" open>
              <summary>Completed checks</summary>
              <p class="sub">{html.escape(completed_research_line) if completed_research_line else 'No completed enrichment checks are stored yet.'}</p>
            </details>
            <details class="research-card">
              <summary>Evidence and provenance</summary>
              <div class="evidence-stack" style="margin-top:12px;">{evidence_html}</div>
            </details>
            <details class="research-card">
              <summary>Open questions</summary>
              <ul>{unknowns_html}</ul>
            </details>
            {detail_request_button}
          </section>
          {learned_panel}
          <section class="panel">
            <div class="eyebrow">Executive Brief</div>
            <h2>What this means</h2>
            <div class="ooda-grid">
              <div class="ooda-cell"><b>Strongest practical upside</b>{html.escape((highlight_lines or ['No clear upside has been stored yet.'])[0])}</div>
              <div class="ooda-cell"><b>Hardest practical downside</b>{html.escape((concern_lines or ['No concrete downside has been stored yet.'])[0])}</div>
              <div class="ooda-cell"><b>Most important next check</b>{html.escape((unknown_lines or ['No explicit follow-up question is stored yet.'])[0])}</div>
            </div>
          </section>
        </div>
      </div>
    </div>
    <script>
      const requestButton = document.getElementById("request-details-btn");
      const requestStatus = document.getElementById("request-details-status");
      let selectedReaction = "";
      const selectedReasons = new Set();
      const reactionButtons = [...document.querySelectorAll(".reaction-btn")];
      const reasonButtons = [...document.querySelectorAll(".reason-chip[data-reason-key]")];
      const filterButtons = [...document.querySelectorAll(".filter-chip[data-filter-key]")];
      const feedbackSubmitButton = document.getElementById("feedback-submit-btn");
      const feedbackStatus = document.getElementById("feedback-status");
      const feedbackNote = document.getElementById("feedback-note");
      const filterStatus = document.getElementById("filter-status");
      reactionButtons.forEach((button) => {{
        button.addEventListener("click", () => {{
          selectedReaction = String(button.dataset.reaction || "");
          reactionButtons.forEach((candidate) => candidate.classList.toggle("active", candidate === button));
        }});
      }});
      reasonButtons.forEach((button) => {{
        button.addEventListener("click", () => {{
          const reasonKey = String(button.dataset.reasonKey || "");
          if (!reasonKey) return;
          if (selectedReasons.has(reasonKey)) {{
            selectedReasons.delete(reasonKey);
            button.classList.remove("active");
          }} else {{
            selectedReasons.add(reasonKey);
            button.classList.add("active");
          }}
        }});
      }});
      if (feedbackSubmitButton && feedbackStatus) {{
        feedbackSubmitButton.addEventListener("click", async () => {{
          if (!selectedReaction) {{
            feedbackStatus.textContent = "Choose a reaction first.";
            return;
          }}
          feedbackSubmitButton.disabled = true;
          feedbackStatus.textContent = "Saving feedback...";
          try {{
            const response = await fetch(window.location.pathname + "/feedback", {{
              method: "POST",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{
                reaction: selectedReaction,
                reason_keys: [...selectedReasons],
                note: feedbackNote ? feedbackNote.value : "",
              }}),
            }});
            const payload = await response.json();
            if (!response.ok) throw new Error((payload.error && payload.error.code) || "feedback_failed");
            feedbackStatus.textContent = "Saved. Reloading the brief with updated preferences...";
            window.setTimeout(() => window.location.reload(), 800);
          }} catch (error) {{
            feedbackSubmitButton.disabled = false;
            feedbackStatus.textContent = "Could not save feedback right now.";
          }}
        }});
      }}
      filterButtons.forEach((button) => {{
        button.addEventListener("click", async () => {{
          const filterKey = String(button.dataset.filterKey || "");
          const enabled = String(button.dataset.enabled || "true") === "true";
          if (!filterKey || !filterStatus) return;
          button.disabled = true;
          filterStatus.textContent = enabled ? "Saving filter..." : "Removing filter...";
          try {{
            const response = await fetch(window.location.pathname + "/filters", {{
              method: "POST",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ filter_key: filterKey, enabled }}),
            }});
            const payload = await response.json();
            if (!response.ok) throw new Error((payload.error && payload.error.code) || "filter_update_failed");
            filterStatus.textContent = enabled ? "Filter saved. Reloading..." : "Filter removed. Reloading...";
            window.setTimeout(() => window.location.reload(), 700);
          }} catch (error) {{
            button.disabled = false;
            filterStatus.textContent = "Could not update the filter right now.";
          }}
        }});
      }});
      if (requestButton && requestStatus) {{
        requestButton.addEventListener("click", async () => {{
          requestButton.disabled = true;
          requestStatus.textContent = "Requesting deeper research...";
          try {{
            const response = await fetch(window.location.pathname + "/request-details", {{
              method: "POST",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{}}),
            }});
            const payload = await response.json();
            if (!response.ok) throw new Error((payload.error && payload.error.code) || "request_failed");
            requestStatus.textContent = "Deeper research requested. A follow-up task has been opened.";
          }} catch (error) {{
            requestButton.disabled = false;
            requestStatus.textContent = "Could not request deeper research right now.";
          }}
        }});
      }}
    </script>
  </body>
</html>"""
    if is_pure_360_cube:
        return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title_html}</title>
    {clickrank_head_snippet(hostname)}
    <style>
      html, body {{ margin: 0; height: 100%; overflow: hidden; background: #111; color: #f8f4eb; font-family: Inter, Arial, sans-serif; }}
      .topbar {{ position: fixed; z-index: 5; top: 0; left: 0; right: 0; display: flex; gap: 12px; align-items: center; justify-content: space-between; padding: 14px 16px; background: linear-gradient(rgba(0,0,0,.72), rgba(0,0,0,0)); }}
      .title {{ min-width: 0; }}
      .title b {{ display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 72vw; }}
      .title span {{ display: block; margin-top: 3px; color: rgba(248,244,235,.72); font-size: 12px; }}
      .controls {{ display: flex; gap: 8px; align-items: center; }}
      button, a.btn {{ min-height: 38px; border: 1px solid rgba(255,255,255,.2); border-radius: 999px; color: #fff; background: rgba(255,255,255,.12); padding: 0 13px; cursor: pointer; text-decoration: none; }}
      .viewer {{ position: fixed; inset: 0; perspective: 900px; cursor: grab; overflow: hidden; touch-action: none; }}
      .viewer.dragging {{ cursor: grabbing; }}
      .cube {{ position: absolute; left: 50%; top: 50%; width: 1024px; height: 1024px; margin-left: -512px; margin-top: -512px; transform-style: preserve-3d; }}
      .face {{ position: absolute; width: 1024px; height: 1024px; background-size: cover; background-position: center; backface-visibility: hidden; }}
      .f {{ transform: translateZ(-512px) rotateY(180deg); }}
      .b {{ transform: translateZ(512px); }}
      .r {{ transform: rotateY(-90deg) translateZ(512px); }}
      .l {{ transform: rotateY(90deg) translateZ(512px); }}
      .u {{ transform: rotateX(-90deg) translateZ(512px); }}
      .d {{ transform: rotateX(90deg) translateZ(512px); }}
      .scene-links {{ position: absolute; inset: 0; z-index: 4; pointer-events: none; }}
      .scene-link {{ position: absolute; top: 50%; transform: translateY(-50%); min-width: 114px; padding: 10px 14px; border-radius: 999px; border: 1px solid rgba(255,255,255,.25); background: rgba(0,0,0,.64); color: #fffaf2; font: 600 14px/1.2 Inter, Arial, sans-serif; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; gap: 8px; pointer-events: auto; }}
      .scene-link.prev {{ left: 14px; }}
      .scene-link.next {{ right: 14px; }}
      .scene-link.disabled {{ opacity: .45; pointer-events: none; }}
      .filmstrip {{ position: fixed; z-index: 6; left: 0; right: 0; bottom: 0; display: flex; gap: 8px; padding: 12px; overflow-x: auto; background: linear-gradient(rgba(0,0,0,0), rgba(0,0,0,.78)); }}
      .thumb {{ flex: 0 0 112px; height: 70px; border: 2px solid transparent; border-radius: 8px; background-size: cover; background-position: center; opacity: .78; }}
      .thumb.active {{ border-color: #fff; opacity: 1; }}
      @media (max-width: 720px) {{ .cube {{ transform-origin: center center; }} .title b {{ max-width: 56vw; }} .thumb {{ flex-basis: 92px; height: 58px; }} }}
    </style>
  </head>
  <body>
    <div class="topbar">
      <div class="title"><b>{title_html}</b><span>Pure 360 hosted on {hosted_brand_html} · {html.escape(str(payload.get("scene_count") or len(scene_data)))} locations</span></div>
      <div class="controls">
        <button id="prev" type="button">Prev</button>
        <button id="next" type="button">Next</button>
        {listing_link}
      </div>
    </div>
    <div id="viewer" class="viewer">
      <div id="cube" class="cube">
        <div class="face f"></div><div class="face b"></div><div class="face r"></div>
        <div class="face l"></div><div class="face u"></div><div class="face d"></div>
      </div>
      <div id="scene-links" class="scene-links">
        <a id="prev-link" class="scene-link prev" href="#"></a>
        <a id="next-link" class="scene-link next" href="#"></a>
      </div>
    </div>
    <div id="filmstrip" class="filmstrip"></div>
    <script id="scene-data" type="application/json">{data_json}</script>
    <script>
      const scenes = JSON.parse(document.getElementById("scene-data").textContent).filter(s => s.cube_faces && s.cube_faces.f);
      const viewer = document.getElementById("viewer");
      const cube = document.getElementById("cube");
      const filmstrip = document.getElementById("filmstrip");
      const prevLink = document.getElementById("prev-link");
      const nextLink = document.getElementById("next-link");
      let active = 0, yaw = 0, pitch = 0, dragging = false, lastX = 0, lastY = 0;
      const clampSceneIndex = (value) => ((value % scenes.length) + scenes.length) % scenes.length;
      function clamp(value, min, max) {{ return Math.max(min, Math.min(max, value)); }}
      function applyRotation() {{ cube.style.transform = `rotateX(${{pitch}}deg) rotateY(${{yaw}}deg)`; }}
      function resolveSceneIndex(rawIndex, fallback) {{
        const index = Number.parseInt(String(rawIndex), 10);
        if (Number.isInteger(index)) return clampSceneIndex(index);
        return fallback;
      }}
      function makeSceneHref(index) {{
        const target = new URL(window.location.href);
        const sceneId = scenes[index]?.scene_id || "";
        if (sceneId && sceneId !== "1") {{
          target.searchParams.set("scene", sceneId);
        }} else {{
          target.searchParams.delete("scene");
        }}
        target.hash = "";
        return target.pathname + (target.search || "");
      }}
      function setLinkState(link, index, labelSuffix) {{
        if (!link || scenes.length === 0) return;
        if (index < 0 || index >= scenes.length) {{
          link.classList.add("disabled");
          link.removeAttribute("href");
          link.textContent = "";
          return;
        }}
        link.classList.remove("disabled");
        link.dataset.index = String(index);
        link.href = makeSceneHref(index);
        const label = scenes[index].name || `Location ${{index + 1}}`;
        link.textContent = `${{labelSuffix}}${{label}}`;
      }}
      function setScene(index) {{
        if (!scenes.length) return;
        active = clampSceneIndex(index);
        const faces = scenes[active].cube_faces;
        for (const key of ["f","b","r","l","u","d"]) {{
          const node = cube.querySelector("." + key);
          node.style.backgroundImage = `url("${{faces[key]}}")`;
        }}
        [...filmstrip.children].forEach((node, i) => node.classList.toggle("active", i === active));
        const prevIndex = resolveSceneIndex(scenes[active].prev_scene_index, clampSceneIndex(active - 1));
        const nextIndex = resolveSceneIndex(scenes[active].next_scene_index, clampSceneIndex(active + 1));
        setLinkState(prevLink, prevIndex, "◀ ");
        setLinkState(nextLink, nextIndex, "");
        const currentUrl = new URL(window.location.href);
        const sceneId = scenes[active].scene_id || String(active + 1);
        if (sceneId && sceneId !== "1") currentUrl.searchParams.set("scene", sceneId);
        else currentUrl.searchParams.delete("scene");
        currentUrl.hash = "";
        history.replaceState({{}}, "", currentUrl.pathname + (currentUrl.search || ""));
      }}
      scenes.forEach((scene, index) => {{
        const button = document.createElement("button");
        button.type = "button";
        button.className = "thumb";
        button.style.backgroundImage = `url("${{scene.image_url || scene.cube_faces.f}}")`;
        button.title = scene.name || `Location ${{index + 1}}`;
        button.addEventListener("click", () => setScene(index));
        filmstrip.appendChild(button);
      }});
      viewer.addEventListener("pointerdown", (event) => {{ dragging = true; lastX = event.clientX; lastY = event.clientY; viewer.classList.add("dragging"); viewer.setPointerCapture(event.pointerId); }});
      viewer.addEventListener("pointermove", (event) => {{ if (!dragging) return; yaw += (event.clientX - lastX) * .12; pitch = clamp(pitch - (event.clientY - lastY) * .12, -80, 80); lastX = event.clientX; lastY = event.clientY; applyRotation(); }});
      viewer.addEventListener("pointerup", () => {{ dragging = false; viewer.classList.remove("dragging"); }});
      viewer.addEventListener("pointercancel", () => {{ dragging = false; viewer.classList.remove("dragging"); }});
      prevLink.addEventListener("click", (event) => {{ event.preventDefault(); const index = Number.parseInt(String(prevLink.dataset.index || ""), 10); if (Number.isInteger(index)) setScene(index); }});
      nextLink.addEventListener("click", (event) => {{ event.preventDefault(); const index = Number.parseInt(String(nextLink.dataset.index || ""), 10); if (Number.isInteger(index)) setScene(index); }});
      document.getElementById("prev").addEventListener("click", () => setScene(active - 1));
      document.getElementById("next").addEventListener("click", () => setScene(active + 1));
      window.addEventListener("keydown", (event) => {{ if (event.key === "ArrowLeft") setScene(active - 1); if (event.key === "ArrowRight") setScene(active + 1); }});
      const initialScene = new URLSearchParams(window.location.search).get("scene");
      const initialSceneIndex = scenes.findIndex((scene) => String(scene.scene_id || "").trim() === String(initialScene || "").trim());
      setScene(initialSceneIndex >= 0 ? initialSceneIndex : 0);
      applyRotation();
    </script>
  </body>
</html>"""
    live_shell = (
        f'''
        <section id="live-360" class="live-shell">
          <div class="live-head">
            <div>
              <div class="eyebrow">{brand_html} <span>•</span> Live 360</div>
              <h2>Live Panorama Viewer</h2>
              <p class="sub">The live browser view below stays entirely inside the {brand_html} public tour surface on this page.</p>
            </div>
            <div class="stack">
              <div class="kv"><b>Brand</b>{brand_html}</div>
              <div class="kv"><b>Experience</b>Hosted on {html.escape(hostname or 'this domain')}</div>
            </div>
          </div>
          <div class="live-frame-wrap">
            <iframe
              class="live-frame"
              src="{html.escape(source_virtual_tour_url)}"
              title="{title_html} live 360 viewer"
              loading="lazy"
              allowfullscreen
              referrerpolicy="no-referrer-when-downgrade"
            ></iframe>
          </div>
        </section>'''
        if source_virtual_tour_url
        else ""
    )
    clickrank_html = clickrank_head_snippet(hostname)
    return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title_html}</title>
    {clickrank_html}
    <style>
      :root {{
        --bg: #f3eee3;
        --panel: rgba(255,255,255,0.76);
        --ink: #1d1c1a;
        --muted: #6e6658;
        --accent: #9f2f22;
        --edge: rgba(29,28,26,0.12);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--ink);
        font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
        background:
          radial-gradient(circle at top left, rgba(159,47,34,0.18), transparent 34%),
          radial-gradient(circle at bottom right, rgba(29,28,26,0.10), transparent 30%),
          linear-gradient(160deg, #f8f4eb 0%, #ece5d8 100%);
      }}
      .shell {{
        max-width: 1220px;
        margin: 0 auto;
        padding: 24px;
      }}
      .hero {{
        display: grid;
        grid-template-columns: 1.2fr 0.8fr;
        gap: 22px;
        align-items: start;
      }}
      .mast, .panel {{
        background: var(--panel);
        backdrop-filter: blur(14px);
        border: 1px solid var(--edge);
        border-radius: 28px;
        box-shadow: 0 18px 50px rgba(29,28,26,0.08);
      }}
      .mast {{
        padding: 28px;
      }}
      .eyebrow {{
        display: inline-flex;
        gap: 10px;
        align-items: center;
        font-size: 12px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      h1 {{
        margin: 16px 0 10px;
        font-size: clamp(2rem, 4vw, 4.2rem);
        line-height: 0.95;
      }}
      .sub {{
        margin: 0;
        color: var(--muted);
        font-size: 1rem;
        line-height: 1.55;
        max-width: 65ch;
      }}
      .facts {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin: 20px 0 22px;
      }}
      .chip {{
        padding: 10px 14px;
        border-radius: 999px;
        background: rgba(255,255,255,0.72);
        border: 1px solid rgba(29,28,26,0.09);
        font-size: 14px;
      }}
      .actions {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 18px;
      }}
      a {{
        color: inherit;
        text-decoration: none;
      }}
      .ghost, .cta {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 44px;
        padding: 0 18px;
        border-radius: 999px;
        border: 1px solid var(--edge);
      }}
      .cta {{
        background: var(--ink);
        color: #fff9f1;
        border-color: transparent;
      }}
      .panel {{
        padding: 22px;
      }}
      .panel h2 {{
        margin: 0 0 10px;
        font-size: 1.1rem;
      }}
      .stack {{
        display: grid;
        gap: 12px;
      }}
      .kv {{
        padding: 12px 14px;
        border-radius: 18px;
        background: rgba(255,255,255,0.7);
        border: 1px solid rgba(29,28,26,0.07);
      }}
      .kv b {{
        display: block;
        margin-bottom: 4px;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        color: var(--muted);
      }}
      .stage {{
        margin-top: 22px;
        display: grid;
        gap: 18px;
      }}
      .live-shell {{
        display: grid;
        gap: 16px;
        padding: 22px;
        border-radius: 30px;
        background: rgba(255,255,255,0.76);
        border: 1px solid rgba(29,28,26,0.12);
        box-shadow: 0 18px 50px rgba(29,28,26,0.08);
      }}
      .live-head {{
        display: grid;
        grid-template-columns: 1.2fr 0.8fr;
        gap: 18px;
        align-items: start;
      }}
      .live-head h2 {{
        margin: 8px 0 10px;
        font-size: 1.6rem;
      }}
      .live-frame-wrap {{
        overflow: hidden;
        border-radius: 30px;
        background: rgba(18,17,16,0.94);
        border: 1px solid rgba(29,28,26,0.15);
        min-height: 540px;
      }}
      .live-frame {{
        display: block;
        width: 100%;
        height: 78vh;
        min-height: 540px;
        border: 0;
        background: #111;
      }}
      .hero-video {{
        overflow: hidden;
        border-radius: 30px;
        background: rgba(18,17,16,0.94);
        border: 1px solid rgba(29,28,26,0.15);
        box-shadow: 0 18px 50px rgba(29,28,26,0.08);
      }}
      .hero-video video {{
        display: block;
        width: 100%;
        min-height: 360px;
        max-height: 78vh;
        background: #111;
      }}
      .tour-toolbar {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }}
      .toggle {{
        display: inline-flex;
        gap: 8px;
        flex-wrap: wrap;
      }}
      .toggle button {{
        min-height: 42px;
        padding: 0 14px;
        border-radius: 999px;
        border: 1px solid rgba(29,28,26,0.10);
        background: rgba(255,255,255,0.72);
        color: var(--ink);
        cursor: pointer;
      }}
      .toggle button.active {{
        background: var(--ink);
        color: #fff8ef;
        border-color: var(--ink);
      }}
      .viewer {{
        position: relative;
        overflow: hidden;
        border-radius: 30px;
        background: rgba(18,17,16,0.94);
        min-height: 420px;
        border: 1px solid rgba(29,28,26,0.15);
      }}
      .viewer img {{
        width: 100%;
        height: 72vh;
        max-height: 760px;
        min-height: 420px;
        object-fit: contain;
        display: block;
      }}
      .caption {{
        position: absolute;
        left: 18px;
        bottom: 18px;
        padding: 12px 16px;
        max-width: min(90%, 520px);
        border-radius: 18px;
        background: rgba(11,11,10,0.64);
        color: #fffaf2;
      }}
      .caption small {{
        display: block;
        opacity: 0.72;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }}
      .nav {{
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 14px;
        pointer-events: none;
      }}
      .nav button {{
        pointer-events: auto;
        width: 52px;
        height: 52px;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.18);
        background: rgba(255,255,255,0.08);
        color: #fffaf2;
        font-size: 20px;
        cursor: pointer;
      }}
      .thumbs {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
        gap: 10px;
      }}
      .thumb {{
        position: relative;
        overflow: hidden;
        border-radius: 18px;
        border: 2px solid transparent;
        background: rgba(255,255,255,0.6);
        cursor: pointer;
      }}
      .thumb.active {{
        border-color: var(--accent);
      }}
      .thumb.hidden {{
        display: none;
      }}
      .thumb img {{
        width: 100%;
        height: 104px;
        object-fit: cover;
        display: block;
      }}
      .badge {{
        position: absolute;
        left: 8px;
        top: 8px;
        padding: 4px 8px;
        border-radius: 999px;
        background: rgba(11,11,10,0.72);
        color: #fffaf2;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }}
      @media (max-width: 900px) {{
        .hero {{ grid-template-columns: 1fr; }}
        .live-head {{ grid-template-columns: 1fr; }}
      }}
      @media (max-width: 640px) {{
        .shell {{ padding: 14px; }}
        .mast, .panel {{ border-radius: 22px; }}
        .viewer img {{ min-height: 320px; height: 52vh; }}
        .live-frame-wrap, .live-shell {{ border-radius: 22px; }}
        .live-frame {{ min-height: 380px; height: 60vh; }}
      }}
    </style>
  </head>
  <body>
    <div class="shell">
      <section class="hero">
        <div class="mast">
          <div class="eyebrow">Property Tour <span>•</span> {variant_label}</div>
          <h1>{title_html}</h1>
          <p class="sub">{display_html}</p>
          <div class="facts">
            <div class="chip">{rooms} Zimmer</div>
            <div class="chip">{area} m²</div>
            <div class="chip">{rent}</div>
            <div class="chip">Verfügbar: {availability}</div>
            <div class="chip">{html.escape(str(payload.get("scene_count") or len(scenes)))} Szenen</div>
          </div>
          <p class="sub">{teaser}</p>
          <div class="actions">
            <a class="cta" href="{primary_cta_href}">{primary_cta}</a>
            {listing_link}
            {hosted_link}
          </div>
        </div>
        <aside class="panel">
          <h2>Tour Brief</h2>
          <div class="stack">
            <div class="kv"><b>Theme</b>{theme_name}</div>
            <div class="kv"><b>Style</b>{tour_style}</div>
            <div class="kv"><b>Audience</b>{audience}</div>
            <div class="kv"><b>Creative Brief</b>{creative_brief}</div>
            <div class="kv"><b>CTA</b>{cta}</div>
            <div class="kv"><b>Adresse</b>{address}</div>
          </div>
        </aside>
      </section>
      <section class="stage">
        {live_shell}
        {(
            f'''<div class="hero-video">
              <video id="tour-video" controls playsinline preload="metadata" poster="{html.escape(scene_data[0]["image_url"])}">
                <source src="{html.escape(video_url)}" type="video/webm">
                {f'<source src="{html.escape(video_fallback_url)}" type="video/mp4">' if video_fallback_url else ''}
              </video>
            </div>'''
        ) if video_url else ''}
        <div class="tour-toolbar">
          <div class="toggle" id="role-filter">
            <button type="button" class="active" data-role="all">All Scenes</button>
            <button type="button" data-role="photo">Photos</button>
            <button type="button" data-role="floorplan">Floorplans</button>
          </div>
          <div class="toggle">
            <button type="button" id="autoplay-btn">Autoplay Scenes</button>
          </div>
        </div>
        <div id="viewer" class="viewer">
          <img id="stage-image" src="{html.escape(scene_data[0]['image_url'])}" alt="{html.escape(scene_data[0]['name'])}">
          <div class="caption">
            <small id="stage-role">{html.escape(scene_data[0]['role'])}</small>
            <div id="stage-name">{html.escape(scene_data[0]['name'])}</div>
          </div>
          <div class="nav">
            <button id="prev-btn" aria-label="Previous scene">‹</button>
            <button id="next-btn" aria-label="Next scene">›</button>
          </div>
        </div>
        <div id="thumbs" class="thumbs"></div>
      </section>
    </div>
    <script id="scene-data" type="application/json">{data_json}</script>
    <script>
      const scenes = JSON.parse(document.getElementById("scene-data").textContent);
      let activeIndex = 0;
      const stageImage = document.getElementById("stage-image");
      const stageName = document.getElementById("stage-name");
      const stageRole = document.getElementById("stage-role");
      const thumbs = document.getElementById("thumbs");
      const autoplayButton = document.getElementById("autoplay-btn");
      let autoplayHandle = null;
      let activeRoleFilter = "all";
      function visibleSceneIndexes() {{
        return scenes
          .map((scene, index) => (activeRoleFilter === "all" || scene.role === activeRoleFilter ? index : -1))
          .filter((index) => index >= 0);
      }}
      function renderThumbs() {{
        thumbs.innerHTML = "";
        scenes.forEach((scene, index) => {{
          const button = document.createElement("button");
          button.className = "thumb" + (index === activeIndex ? " active" : "");
          button.type = "button";
          if (activeRoleFilter !== "all" && scene.role !== activeRoleFilter) button.classList.add("hidden");
          button.innerHTML = `<span class="badge">${{scene.role}}</span><img src="${{scene.image_url}}" alt="${{scene.name}}">`;
          button.addEventListener("click", () => setActive(index));
          thumbs.appendChild(button);
        }});
      }}
      function setActive(index) {{
        activeIndex = (index + scenes.length) % scenes.length;
        const scene = scenes[activeIndex];
        stageImage.src = scene.image_url;
        stageImage.alt = scene.name;
        stageName.textContent = scene.name;
        stageRole.textContent = scene.role;
        renderThumbs();
      }}
      function shiftVisible(delta) {{
        const visible = visibleSceneIndexes();
        if (!visible.length) return;
        const currentSlot = Math.max(0, visible.indexOf(activeIndex));
        const nextSlot = (currentSlot + delta + visible.length) % visible.length;
        setActive(visible[nextSlot]);
      }}
      document.getElementById("prev-btn").addEventListener("click", () => shiftVisible(-1));
      document.getElementById("next-btn").addEventListener("click", () => shiftVisible(1));
      window.addEventListener("keydown", (event) => {{
        if (event.key === "ArrowLeft") shiftVisible(-1);
        if (event.key === "ArrowRight") shiftVisible(1);
      }});
      document.querySelectorAll("#role-filter button").forEach((button) => {{
        button.addEventListener("click", () => {{
          activeRoleFilter = button.dataset.role || "all";
          document.querySelectorAll("#role-filter button").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
          const visible = visibleSceneIndexes();
          if (visible.length && !visible.includes(activeIndex)) activeIndex = visible[0];
          renderThumbs();
          setActive(activeIndex);
        }});
      }});
      autoplayButton.addEventListener("click", () => {{
        if (autoplayHandle) {{
          clearInterval(autoplayHandle);
          autoplayHandle = null;
          autoplayButton.textContent = "Autoplay Scenes";
          return;
        }}
        autoplayButton.textContent = "Stop Autoplay";
        autoplayHandle = setInterval(() => shiftVisible(1), 2600);
      }});
      renderThumbs();
    </script>
  </body>
</html>"""


def _render_tour_unavailable_page(
    request: Request,
    *,
    status_code: int,
    title: str,
    summary: str,
    status_label: str,
    rows: list[dict[str, str]],
) -> HTMLResponse:
    response = public_templates.TemplateResponse(
        request,
        "workspace_link.html",
        _public_context(
            request=request,
            current_nav="product",
            page_title=title,
            principal_id="",
            status=_anonymous_onboarding_status(),
            access_identity=None,
            extra={
                "link_kicker": "Tour link unavailable",
                "link_title": title,
                "link_summary": summary,
                "link_detail_title": "What happened",
                "link_status_label": status_label,
                "link_rows": rows,
                "primary_action_href": "/sign-in",
                "primary_action_label": "Return to sign in",
                "secondary_action_href": "/register",
                "secondary_action_label": "Create personal workspace",
            },
        ),
    )
    response.status_code = status_code
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


@router.get("/tours/{slug}.json", response_class=JSONResponse)
def public_tour_payload(slug: str) -> JSONResponse:
    payload = _load_tour(slug)
    if _tour_payload_is_disabled_fallback(payload):
        raise HTTPException(status_code=404, detail="tour_disabled_fallback")
    return JSONResponse(payload)


@router.get("/tours/files/{slug}/{asset_path:path}")
def public_tour_file(slug: str, asset_path: str) -> FileResponse:
    file_path = _asset_file(slug, asset_path)
    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type)


@router.post("/tours/{slug}/request-details", response_class=JSONResponse)
def public_tour_request_details(
    slug: str,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> JSONResponse:
    payload = _load_tour(slug)
    if _tour_payload_is_disabled_fallback(payload):
        raise HTTPException(status_code=404, detail="tour_disabled_fallback")
    principal_id = str(payload.get("principal_id") or "").strip()
    property_url = str(payload.get("property_url") or payload.get("listing_url") or "").strip()
    if not principal_id or not property_url:
        raise HTTPException(status_code=409, detail="tour_detail_request_unavailable")
    result = build_product_service(container).request_property_tour_detail_refresh(
        principal_id=principal_id,
        property_url=property_url,
        title=str(payload.get("display_title") or payload.get("title") or "").strip(),
        variant_key=str(payload.get("variant_key") or "layout_first").strip() or "layout_first",
        recipient_email=str(payload.get("recipient_email") or "").strip(),
        source_ref=str(payload.get("source_ref") or "").strip(),
        external_id=str(payload.get("external_id") or "").strip(),
        actor=f"public_tour:{request_hostname(request)}",
    )
    return JSONResponse(result)


@router.post("/tours/{slug}/feedback", response_class=JSONResponse)
async def public_tour_feedback(
    slug: str,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> JSONResponse:
    payload = _load_tour(slug)
    if _tour_payload_is_disabled_fallback(payload):
        raise HTTPException(status_code=404, detail="tour_disabled_fallback")
    principal_id = str(payload.get("principal_id") or "").strip()
    if not principal_id:
        raise HTTPException(status_code=409, detail="tour_feedback_unavailable")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid_tour_feedback_payload")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="invalid_tour_feedback_payload")
    reaction = str(body.get("reaction") or "").strip().lower()
    if reaction not in {"like", "dislike", "maybe", "hide"}:
        raise HTTPException(status_code=422, detail="invalid_tour_feedback_reaction")
    reason_map = _property_feedback_reason_map()
    reason_keys = _public_tour_normalize_reason_keys(
        body.get("reason_keys"),
        allowed=set(reason_map.keys()),
    )
    note = str(body.get("note") or "").strip()
    facts = _live_property_feedback_context(container=container, payload=payload, slug=slug).get("facts") or dict(payload.get("facts") or {})
    result = build_product_service(container).record_property_feedback(
        principal_id=principal_id,
        property_slug=slug,
        property_url=str(payload.get("property_url") or payload.get("listing_url") or "").strip(),
        property_title=str(payload.get("display_title") or payload.get("title") or "").strip(),
        property_facts=dict(facts) if isinstance(facts, dict) else {},
        reaction=reaction,
        reason_keys=reason_keys,
        note=note,
        actor=f"public_tour:{request_hostname(request)}",
    )
    return JSONResponse(result)


@router.post("/tours/{slug}/filters", response_class=JSONResponse)
async def public_tour_filter_update(
    slug: str,
    body: dict[str, object] = Body(default_factory=dict),
    container: AppContainer = Depends(get_container),
) -> JSONResponse:
    payload = _load_tour(slug)
    if _tour_payload_is_disabled_fallback(payload):
        raise HTTPException(status_code=404, detail="tour_disabled_fallback")
    principal_id = str(payload.get("principal_id") or "").strip()
    if not principal_id:
        raise HTTPException(status_code=409, detail="tour_filter_update_unavailable")
    live_context = _live_property_feedback_context(container=container, payload=payload, slug=slug)
    facts = dict(live_context.get("facts") or payload.get("facts") or {})
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="invalid_tour_filter_payload")
    filter_key = str(body.get("filter_key") or "").strip()
    if not filter_key:
        raise HTTPException(status_code=422, detail="invalid_tour_filter_key")
    enabled = _shortlist_as_bool(body.get("enabled"))
    if enabled is None:
        raise HTTPException(status_code=422, detail="invalid_tour_filter_enabled")
    spec = next((row for row in _public_filter_specs(facts=facts) if str(row.get("key") or "").strip() == filter_key), None)
    if spec is None:
        raise HTTPException(status_code=422, detail="invalid_tour_filter_key")
    service = build_product_service(container)
    service.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        learning_enabled=True,
    )
    updated_node = service.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain=str(spec.get("domain") or "willhaben"),
        category=str(spec.get("category") or "soft_preference"),
        key=str(spec.get("node_key") or ""),
        value_json=spec.get("value_json"),
        strength=str(spec.get("strength") or "medium"),
        confidence=float(spec.get("confidence") or 0.8),
        source_mode="explicit",
        status="active" if enabled else "inactive",
        decay_policy="reinforce_only",
    )
    return JSONResponse(
        {
            "status": "updated",
            "filter_key": filter_key,
            "enabled": enabled,
            "node": updated_node,
        }
    )


@router.api_route("/tours/{slug}", methods=["GET", "HEAD"], response_class=HTMLResponse)
def public_tour_page(
    slug: str,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> HTMLResponse:
    hostname = request_hostname(request)
    try:
        payload = _load_tour(slug)
        if _tour_payload_is_disabled_fallback(payload):
            raise HTTPException(status_code=404, detail="tour_disabled_fallback")
        live_context = _live_property_feedback_context(container=container, payload=payload, slug=slug)
        rendered_payload = dict(payload)
        rendered_payload["facts"] = dict(live_context.get("facts") or {})
        rendered_payload["_feedback_suggestions"] = dict(live_context.get("feedback_suggestions") or {})
        rendered_payload["_learning_summary"] = dict(live_context.get("learning_summary") or {})
        rendered_payload["_shortlist_compare"] = _public_shortlist_comparison_context(
            container=container,
            payload=payload,
            slug=slug,
            facts=dict(rendered_payload["facts"] or {}),
        )
        return HTMLResponse(_tour_html(rendered_payload, hostname=hostname))
    except HTTPException as exc:
        detail = str(exc.detail or "").strip().lower()
        if exc.status_code == 404 and detail == "tour_disabled_fallback":
            return _render_tour_unavailable_page(
                request,
                status_code=404,
                title="This tour link is no longer available.",
                summary="Fallback listing-summary tours are disabled. Ask the sender for a real 360 tour or a fresh live-tour link.",
                status_label="Tour unavailable",
                rows=[
                    {
                        "label": "Tour state",
                        "value": "Disabled fallback",
                        "detail": "This link pointed to a generated fallback page rather than a real tour.",
                    },
                    {
                        "label": "Next step",
                        "value": "Request a real 360 tour",
                        "detail": "Only hosted pure-360 or live panorama tours remain available on this surface.",
                    },
                ],
            )
        if exc.status_code == 404 and detail == "tour_not_found":
            return _render_tour_unavailable_page(
                request,
                status_code=404,
                title="This tour link is no longer available.",
                summary="Ask the sender to share a fresh apartment-tour link or return to the workspace for the latest queue and evidence.",
                status_label="Tour unavailable",
                rows=[
                    {
                        "label": "Tour state",
                        "value": "Unavailable",
                        "detail": "The share bundle may have been replaced, removed, or never finished publishing.",
                    },
                    {
                        "label": "Next step",
                        "value": "Request a fresh tour",
                        "detail": f"A current link will open the branded {_public_tour_host_brand_label(hostname, fallback='this domain')} view when the bundle is ready.",
                    },
                ],
            )
        return _render_tour_unavailable_page(
            request,
            status_code=max(int(exc.status_code), 500) if int(exc.status_code) >= 500 else 500,
            title="This tour is temporarily unavailable.",
            summary="The tour link exists, but the published bundle is not ready to render right now. Return to the workspace or ask the sender to republish it.",
            status_label="Tour unavailable",
            rows=[
                {
                    "label": "Tour state",
                    "value": "Publish problem",
                    "detail": "The hosted tour bundle is missing required scenes or metadata.",
                },
                {
                    "label": "Recovery",
                    "value": "Reopen the workspace",
                    "detail": "The office can regenerate or resend the latest branded link from the queue.",
                },
            ],
        )
