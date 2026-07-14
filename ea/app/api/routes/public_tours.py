from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
import fcntl
import hashlib
import html
import ipaddress
import json
import logging
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import time
import unicodedata
import urllib.parse
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
import requests

from app.api.dependencies import get_container
from app.api.routes.landing_public_support import _anonymous_onboarding_status, _public_context, templates as public_templates
from app.container import AppContainer
from app.product.service import _property_feedback_reason_map, build_product_service
from app.services.public_artifact_paths import public_tour_dir
from app.services.public_clickrank import clickrank_head_snippet, request_hostname
from app.services.public_request import trust_forwarded_ip
from app.services.public_rybbit import request_hostname as rybbit_request_hostname
from app.services.public_rybbit import rybbit_head_snippet
from app.services.public_tour_release_policy import (
    GENERATED_RECONSTRUCTION_PROVIDER,
    PUBLIC_TOUR_VIDEO_RELEASE_CONTRACT,
    evaluate_public_tour_embed_release,
    evaluate_public_tour_generated_viewer_release,
    evaluate_public_tour_video_release,
    safe_public_navigation_url,
)

router = APIRouter(tags=["public-tours"])

_PUBLIC_TOUR_ACTIONS = frozenset({"request-details", "feedback", "filters"})
_PUBLIC_TOUR_FEEDBACK_RATE_LIMIT: OrderedDict[str, tuple[float, int]] = OrderedDict()
_PUBLIC_TOUR_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS = 60.0
_PUBLIC_TOUR_FEEDBACK_RATE_LIMIT_MAX = 12
_PUBLIC_TOUR_FEEDBACK_RATE_LIMIT_MAX_KEYS = 2048
log = logging.getLogger(__name__)

_PUBLIC_TOUR_QUARANTINED_SLUG_RE = re.compile(
    r"^(?:"
    r"runtime[-_.](?:reconstruction|service)|"
    r"debug[-_.](?:reconstruction|tour|viewer)|"
    r"probe[-_.](?:reconstruction|tour|viewer)|"
    r"private[-_.](?:showcase|fixture|tour)|"
    r"(?:test|pytest|fixture)[-_.](?:reconstruction|tour|viewer|property)|"
    r"bridge[-_.]direct[-_.]probe|"
    r"check[-_.]viewer|"
    r"generated[-_.]reconstruction(?:[-_.][a-z0-9]+)*[-_.]debug|"
    r"repro[-_.]tour|"
    r"(?:manual[-_.])?viewer[-_.](?:debug|probe)"
    r")(?:[-_.]|$)",
    re.IGNORECASE,
)
_PUBLIC_TOUR_EXACT_ADDRESS_KEY_RE = re.compile(
    r"^(?:streetaddress|exactaddress|geocodedaddress|addressline(?:s|\d+|one|two|three)?)$"
)
_PUBLIC_TOUR_NON_PROPERTY_ADDRESS_CONTEXT = frozenset(
    {"agent", "broker", "company", "contact", "office", "organisation", "organization", "recipient"}
)
_PUBLIC_TOUR_STREET_CUE_RE = re.compile(
    r"(?:"
    r"(?:straße|strasse|strae|gasse|allee|platz|ring|steig|weg)\b|"
    r"\b(?:avenida|avenue|boulevard|calle|chaussee|court|drive|lane|promenade|quai|road|"
    r"rue|square|street|terrace|ulica|via|way)\b"
    r")",
    re.IGNORECASE,
)
_PUBLIC_TOUR_NUMBER_FIRST_ABBREVIATED_STREET_RE = re.compile(
    r"\b\d{1,5}[a-z]?(?:[-/]\d{1,5}[a-z]?)?\s+[^,\n]{2,80}\s(?:ave|blvd|ct|dr|ln|rd|sq|st|terr)\b",
    re.IGNORECASE,
)
_PUBLIC_TOUR_LOCATION_URL_PREFIXES = (
    "continuity",
    "crezlo",
    "direct",
    "editor",
    "flythrough",
    "hosted",
    "krpano",
    "listing",
    "matterport",
    "pano",
    "premium",
    "property",
    "public",
    "source",
    "threedvista",
    "tour",
    "viewer",
)


def _public_tour_compact_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _public_tour_slug_is_quarantined(value: object) -> bool:
    return bool(_PUBLIC_TOUR_QUARANTINED_SLUG_RE.match(str(value or "").strip()))


def _public_tour_location_normalizations(value: object) -> set[str]:
    try:
        decoded = urllib.parse.unquote_plus(str(value or ""))
    except Exception:
        decoded = str(value or "")
    variants = {decoded.casefold(), decoded.lower().replace("ß", "")}
    normalized: set[str] = set()
    for variant in variants:
        ascii_variant = unicodedata.normalize("NFKD", variant).encode("ascii", "ignore").decode("ascii")
        compact = re.sub(r"[^a-z0-9]+", "", ascii_variant.lower())
        if compact:
            normalized.add(compact)
    return normalized


def _public_tour_exact_address_is_credible(value: object) -> bool:
    try:
        decoded = urllib.parse.unquote_plus(str(value or "")).strip()
    except Exception:
        decoded = str(value or "").strip()
    if len(decoded) < 8 or not re.search(r"\d", decoded):
        return False
    if not (
        _PUBLIC_TOUR_STREET_CUE_RE.search(decoded)
        or _PUBLIC_TOUR_NUMBER_FIRST_ABBREVIATED_STREET_RE.search(decoded)
    ):
        return False
    words = re.findall(r"[^\W\d_]{2,}", decoded, flags=re.UNICODE)
    return bool(words) and any(len(value) >= 8 for value in _public_tour_location_normalizations(decoded))


def _public_tour_exact_address_normalizations(value: object) -> set[str]:
    try:
        decoded = urllib.parse.unquote_plus(str(value or "")).strip()
    except Exception:
        decoded = str(value or "").strip()
    candidates = [decoded, *re.split(r"[\n,;|]+", decoded)]
    normalized: set[str] = set()
    for candidate in candidates:
        if _public_tour_exact_address_is_credible(candidate):
            normalized.update(_public_tour_location_normalizations(candidate))
    return normalized


def _public_tour_collect_exact_addresses(
    value: object,
    *,
    context: tuple[str, ...] = (),
) -> set[str]:
    collected: set[str] = set()
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = _public_tour_compact_key(raw_key)
            child_context = (*context, key)
            private_context = any(
                token in context_key
                for context_key in child_context
                for token in _PUBLIC_TOUR_NON_PROPERTY_ADDRESS_CONTEXT
            )
            if _PUBLIC_TOUR_EXACT_ADDRESS_KEY_RE.fullmatch(key) and not private_context:
                candidates = child if isinstance(child, (list, tuple, set)) else (child,)
                for candidate in candidates:
                    if _public_tour_exact_address_is_credible(candidate):
                        collected.update(_public_tour_exact_address_normalizations(candidate))
            collected.update(_public_tour_collect_exact_addresses(child, context=child_context))
    elif isinstance(value, (list, tuple)):
        for child in value:
            collected.update(_public_tour_collect_exact_addresses(child, context=context))
    return collected


def _public_tour_collect_location_surfaces(
    payload: dict[str, object],
    *,
    requested_slug: str,
) -> set[str]:
    values: list[object] = [
        requested_slug,
        payload.get("slug"),
        payload.get("display_title"),
        payload.get("title"),
        payload.get("tour_title"),
    ]
    for raw_key, child in payload.items():
        key = _public_tour_compact_key(raw_key)
        if key.endswith("url") and key.startswith(_PUBLIC_TOUR_LOCATION_URL_PREFIXES):
            values.append(child)

    def _collect_scene_values(value: object) -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = _public_tour_compact_key(raw_key)
                if key in {"href", "label", "name", "src", "title"} or key.endswith(("label", "url")):
                    values.append(child)
                _collect_scene_values(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                _collect_scene_values(child)

    _collect_scene_values(payload.get("scenes"))
    surfaces: set[str] = set()
    for value in values:
        if isinstance(value, (str, int, float)):
            surfaces.update(_public_tour_location_normalizations(value))
    return surfaces


def _public_tour_has_exact_location_conflict(
    payload: dict[str, object],
    *,
    requested_slug: str,
) -> bool:
    if payload.get("public_exact_location_allowed") is True:
        return False
    exact_addresses = _public_tour_collect_exact_addresses(payload)
    if not exact_addresses:
        return False
    surfaces = _public_tour_collect_location_surfaces(payload, requested_slug=requested_slug)
    return any(address in surface for address in exact_addresses for surface in surfaces)


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
    return public_tour_dir()


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
    if _public_tour_slug_is_quarantined(slug):
        raise HTTPException(status_code=404, detail="tour_not_found")
    path = _tour_path(slug)
    if not path.exists():
        raise HTTPException(status_code=404, detail="tour_not_found")
    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail="tour_payload_invalid") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="tour_payload_invalid")
    if _public_tour_slug_is_quarantined(payload.get("slug")):
        raise HTTPException(status_code=404, detail="tour_not_found")
    if _public_tour_has_exact_location_conflict(payload, requested_slug=str(slug or "")):
        raise HTTPException(status_code=404, detail="tour_not_found")
    return payload


_PUBLIC_TOUR_TOP_LEVEL_KEYS = frozenset(
    {
        "slug",
        "title",
        "tour_title",
        "display_title",
        "variant_key",
        "variant_label",
        "scene_count",
        "scene_strategy",
        "creation_mode",
        "brand_name",
        "listing_url",
        "property_url",
        "hosted_url",
        "public_url",
        "crezlo_public_url",
        "source_virtual_tour_url",
        "source_virtual_tour_origin",
        "panorama_source",
        "facts",
        "brief",
        "scenes",
        "video_relpath",
        "tour_privacy_mode",
        "privacy_mode",
    }
)
_PUBLIC_TOUR_SCENE_KEYS = frozenset(
    {
        "name",
        "role",
        "mime_type",
        "scene_id",
        "location_id",
        "id",
        "scene",
        "next_scene_id",
        "prev_scene_id",
        "next_scene",
        "prev_scene",
        "next_location_id",
        "prev_location_id",
        "next",
        "prev",
        "next_scene_index",
        "prev_scene_index",
        "image_url",
        "asset_relpath",
        "cube_faces",
    }
)
_PUBLIC_TOUR_PRIVATE_KEYS = frozenset(
    {
        "_feedback_suggestions",
        "_learning_summary",
        "_shortlist_compare",
        "actor",
        "api_key",
        "audit_rows",
        "auth_header",
        "authorization",
        "cookie",
        "cookies",
        "debug",
        "external_id",
        "headers",
        "internal_ref",
        "learning_summary",
        "owner_id",
        "person_id",
        "preference_nodes",
        "preference_profile",
        "principal_id",
        "private_recipient_email",
        "public_preference_snapshot",
        "raw_signal_json",
        "recipient",
        "recipient_email",
        "recipient_name",
        "recipient_phone",
        "refresh_token",
        "runtime_inputs_json",
        "session",
        "shortlist_context",
        "source_ref",
        "token",
    }
)
_PUBLIC_TOUR_PRIVATE_KEY_MARKERS = (
    "access_token",
    "api_key",
    "auth",
    "cookie",
    "credential",
    "debug",
    "internal",
    "learning",
    "oauth",
    "owner",
    "preference",
    "principal",
    "private",
    "recipient",
    "refresh_token",
    "secret",
    "session",
    "shortlist",
)
_PUBLIC_TOUR_ALLOWED_ASSET_EXTENSIONS = frozenset(
    {
        ".avif",
        ".gif",
        ".jpeg",
        ".jpg",
        ".m4v",
        ".mov",
        ".mp4",
        ".pdf",
        ".png",
        ".webm",
        ".webp",
    }
)
_PUBLIC_TOUR_PUBLIC_PDF_PRIVACY_CLASSES = frozenset(
    {
        "floorplan_pdf_public",
        "floorplan_public",
        "public_floorplan_pdf",
    }
)
_PUBLIC_TOUR_DENIED_ASSET_EXTENSIONS = frozenset(
    {
        ".conf",
        ".csv",
        ".db",
        ".env",
        ".gz",
        ".htm",
        ".html",
        ".ini",
        ".json",
        ".key",
        ".log",
        ".pem",
        ".sqlite",
        ".tar",
        ".txt",
        ".yaml",
        ".yml",
        ".zip",
    }
)
_PUBLIC_TOUR_PRIVACY_MODES = frozenset(
    {
        "anonymous_public",
        "viewer_only",
        "agent_share",
        "family_review",
        "owner_private",
    }
)
_PUBLIC_TOUR_ADDRESS_ALLOWED_MODES = frozenset({"viewer_only", "agent_share", "family_review"})
_PUBLIC_TOUR_EXACT_LOCATION_FACT_KEYS = frozenset(
    {
        "address",
        "address_line",
        "address_lines",
        "exact_address",
        "formatted_address",
        "geojson",
        "geocode",
        "geocoded_address",
        "house_number",
        "lat",
        "latitude",
        "lng",
        "lon",
        "longitude",
        "map_lat",
        "map_lng",
        "postcode",
        "postal_code",
        "reverse_geocode",
        "street",
        "street_address",
        "street_name",
    }
)
_PUBLIC_TOUR_ANONYMOUS_FACT_KEYS = frozenset(
    {
        "area_sqm",
        "availability",
        "balcony_sqm",
        "bathrooms",
        "bedrooms",
        "city",
        "country_code",
        "district",
        "district_name",
        "energy_class",
        "floor",
        "floor_plan",
        "floorplan_available",
        "floorplan_count",
        "garden_sqm",
        "has_360",
        "has_balcony",
        "has_floorplan",
        "has_garden",
        "has_lift",
        "has_loggia",
        "has_terrace",
        "heating_type",
        "lift",
        "elevator",
        "livability_snapshot",
        "municipality",
        "parking_monthly_eur",
        "personal_fit_assessment",
        "postal_name",
        "price_eur",
        "property_type",
        "purchase_price_eur",
        "rooms",
        "teaser_attributes",
        "terrace_sqm",
        "terrace_area_sqm",
        "total_rent_eur",
        "building_units",
        "year_built",
    }
)
_PUBLIC_TOUR_PUBLIC_ASSESSMENT_KEYS = frozenset(
    {
        "adjusted_fit_score",
        "decision_summary",
        "fit_score",
        "good_fit_reasons",
        "livability_snapshot",
        "location_fit_score",
        "match_reasons_json",
        "mismatch_reasons_json",
        "pros",
        "cons",
        "risk_flags",
        "summary",
        "unknowns_json",
    }
)
_PUBLIC_TOUR_RESEARCH_DEFAULT_HOST_SUFFIXES = (
    "willhaben.at",
    "immobilienscout24.at",
    "immowelt.at",
    "immonet.de",
    "matterport.com",
    "edikte2.justiz.gv.at",
    "sreal.at",
    "immobilien.derstandard.at",
    "derstandard.at",
)


def _public_tour_key_is_private(key: object) -> bool:
    normalized = str(key or "").strip().lower()
    if not normalized:
        return True
    if normalized in _PUBLIC_TOUR_PRIVATE_KEYS:
        return True
    return any(marker in normalized for marker in _PUBLIC_TOUR_PRIVATE_KEY_MARKERS)


def _public_tour_safe_asset_relpath(value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if (
        not raw
        or "\x00" in raw
        or "://" in raw
        or raw.startswith("/")
        or any(character in raw for character in "\"'`<>&")
    ):
        return ""
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return ""
    return "/".join(path.parts)


def _public_tour_safe_display_text(value: object, *, fallback: str = "", limit: int = 180) -> str:
    normalized = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    normalized = (
        normalized.replace("&", " and ")
        .replace("<", "‹")
        .replace(">", "›")
        .replace('"', "”")
        .replace("'", "’")
        .replace("`", "’")
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return (normalized or fallback)[: max(int(limit), 1)]


def _public_tour_env_truthy(raw: object) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _public_tour_prod_mode_enabled() -> bool:
    return str(os.getenv("EA_RUNTIME_MODE") or "").strip().lower() == "prod"


def _public_tour_privacy_mode(payload: dict[str, object]) -> str:
    raw = str(payload.get("tour_privacy_mode") or payload.get("privacy_mode") or "").strip().lower()
    return raw if raw in _PUBLIC_TOUR_PRIVACY_MODES else "anonymous_public"


def _require_public_tour_viewable(payload: dict[str, object]) -> None:
    if _public_tour_privacy_mode(payload) == "owner_private":
        raise HTTPException(status_code=404, detail="tour_not_found")


def _public_tour_exact_address_allowed(payload: dict[str, object], *, privacy_mode: str) -> bool:
    if privacy_mode not in _PUBLIC_TOUR_ADDRESS_ALLOWED_MODES:
        return False
    return _public_tour_env_truthy(
        payload.get("public_address_allowed")
        or payload.get("public_exact_location_allowed")
        or payload.get("share_exact_location")
    )


def _public_tour_asset_path_is_public(
    relpath: str,
    *,
    privacy_class: str = "",
    role: str = "",
    mime_type: str = "",
) -> bool:
    safe_relpath = _public_tour_safe_asset_relpath(relpath)
    if not safe_relpath:
        return False
    suffix = PurePosixPath(safe_relpath).suffix.lower()
    if suffix in _PUBLIC_TOUR_DENIED_ASSET_EXTENSIONS:
        return False
    if suffix not in _PUBLIC_TOUR_ALLOWED_ASSET_EXTENSIONS:
        return False
    if suffix == ".pdf" or "pdf" in str(mime_type or "").strip().lower():
        normalized_privacy = str(privacy_class or "").strip().lower()
        normalized_role = str(role or "").strip().lower().replace("-", "_")
        return normalized_privacy in _PUBLIC_TOUR_PUBLIC_PDF_PRIVACY_CLASSES and normalized_role in {
            "floorplan",
            "floor_plan",
            "layout",
            "valuation_floorplan",
        }
    return True


def _public_tour_collect_asset_refs(payload: dict[str, object]) -> set[str]:
    refs: set[str] = set()

    def _add(
        value: object,
        *,
        privacy_class: str = "",
        role: str = "",
        mime_type: str = "",
    ) -> None:
        relpath = _public_tour_safe_asset_relpath(value)
        if relpath and _public_tour_asset_path_is_public(
            relpath,
            privacy_class=privacy_class,
            role=role,
            mime_type=mime_type,
        ):
            refs.add(relpath)

    video_release = evaluate_public_tour_video_release(payload)
    if video_release.get("released"):
        _add(video_release.get("relpath"), role="video")
    for scene in list(payload.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        scene_privacy = str(scene.get("privacy_class") or scene.get("privacy") or "").strip()
        scene_role = str(scene.get("role") or "").strip()
        scene_mime = str(scene.get("mime_type") or "").strip()
        for key in ("asset_relpath", "thumbnail_relpath", "preview_relpath", "floorplan_relpath"):
            _add(scene.get(key), privacy_class=scene_privacy, role=scene_role, mime_type=scene_mime)
        cube_faces = scene.get("cube_faces")
        if isinstance(cube_faces, dict):
            for value in cube_faces.values():
                _add(value)
    public_assets = payload.get("public_assets")
    if isinstance(public_assets, list):
        for row in public_assets:
            if isinstance(row, str):
                _add(row)
                continue
            if not isinstance(row, dict):
                continue
            privacy_class = str(row.get("privacy_class") or row.get("privacy") or "public").strip().lower()
            if privacy_class in {"private", "internal", "debug", "restricted"}:
                continue
            role = str(row.get("role") or row.get("asset_role") or "").strip()
            normalized_role = role.lower().replace("-", "_")
            if normalized_role == "provider_sidecar":
                continue
            if normalized_role in {"video", "video_still"} and not video_release.get("released"):
                continue
            mime_type = str(row.get("mime_type") or row.get("content_type") or "").strip()
            for key in ("path", "relpath", "asset_relpath"):
                _add(row.get(key), privacy_class=privacy_class, role=role, mime_type=mime_type)
    return refs


def _public_tour_allowed_asset_paths(payload: dict[str, object]) -> set[str]:
    return set(_public_tour_collect_asset_refs(payload))


def _public_tour_asset_metadata(payload: dict[str, object]) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}

    def _record(
        value: object,
        *,
        privacy_class: str = "",
        role: str = "",
        mime_type: str = "",
    ) -> None:
        relpath = _public_tour_safe_asset_relpath(value)
        if not relpath or not _public_tour_asset_path_is_public(
            relpath,
            privacy_class=privacy_class,
            role=role,
            mime_type=mime_type,
        ):
            return
        row = metadata.setdefault(relpath, {})
        normalized_privacy = str(privacy_class or "").strip().lower()
        normalized_role = str(role or "").strip().lower().replace("-", "_")
        if normalized_privacy:
            row["privacy_class"] = normalized_privacy
        if normalized_role:
            row["role"] = normalized_role
        if mime_type:
            row["mime_type"] = str(mime_type).strip()

    video_release = evaluate_public_tour_video_release(payload)
    if video_release.get("released"):
        _record(video_release.get("relpath"), role="video")
    for scene in list(payload.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        scene_privacy = str(scene.get("privacy_class") or scene.get("privacy") or "").strip()
        scene_role = str(scene.get("role") or "").strip()
        scene_mime = str(scene.get("mime_type") or "").strip()
        for key in ("asset_relpath", "thumbnail_relpath", "preview_relpath", "floorplan_relpath"):
            _record(scene.get(key), privacy_class=scene_privacy, role=scene_role, mime_type=scene_mime)
        cube_faces = scene.get("cube_faces")
        if isinstance(cube_faces, dict):
            for value in cube_faces.values():
                _record(value, role="cube_face")
    public_assets = payload.get("public_assets")
    if isinstance(public_assets, list):
        for row in public_assets:
            if isinstance(row, str):
                _record(row)
                continue
            if not isinstance(row, dict):
                continue
            privacy_class = str(row.get("privacy_class") or row.get("privacy") or "public").strip().lower()
            if privacy_class in {"private", "internal", "debug", "restricted"}:
                continue
            role = str(row.get("role") or row.get("asset_role") or "").strip()
            normalized_role = role.lower().replace("-", "_")
            if normalized_role == "provider_sidecar":
                continue
            if normalized_role in {"video", "video_still"} and not video_release.get("released"):
                continue
            mime_type = str(row.get("mime_type") or row.get("content_type") or "").strip()
            for key in ("path", "relpath", "asset_relpath"):
                _record(row.get(key), privacy_class=privacy_class, role=role, mime_type=mime_type)
    return metadata


def _public_tour_manifest(payload: dict[str, object], *, only_relpath: str = "") -> dict[str, dict[str, object]]:
    slug = str(payload.get("slug") or "").strip()
    bundle_dir = _tour_bundle_dir(slug)
    only_safe_relpath = _public_tour_safe_asset_relpath(only_relpath)
    manifest: dict[str, dict[str, object]] = {}
    for relpath, metadata in sorted(_public_tour_asset_metadata(payload).items()):
        if only_safe_relpath and relpath != only_safe_relpath:
            continue
        row: dict[str, object] = {
            "path": relpath,
            "url": _public_tour_file_url(slug, relpath),
            "mime_type": metadata.get("mime_type") or mimetypes.guess_type(relpath)[0] or "application/octet-stream",
            "privacy_class": metadata.get("privacy_class") or "public",
        }
        if metadata.get("role"):
            row["role"] = metadata["role"]
        if bundle_dir is not None:
            candidate = (bundle_dir / relpath).resolve()
            try:
                if bundle_dir.resolve() in candidate.parents and candidate.exists() and candidate.is_file():
                    size_bytes = candidate.stat().st_size
                    row["size_bytes"] = size_bytes
                    mime_type = str(row.get("mime_type") or "").strip().lower()
                    should_hash = size_bytes <= (8 * 1024 * 1024) and not mime_type.startswith("video/")
                    if should_hash:
                        digest = hashlib.sha256()
                        with candidate.open("rb") as handle:
                            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                                digest.update(chunk)
                        row["sha256"] = digest.hexdigest()
            except OSError:
                pass
        manifest[relpath] = row
    return manifest


def _public_tour_file_url(slug: str, relpath: str) -> str:
    safe_relpath = _public_tour_safe_asset_relpath(relpath)
    if not slug or not safe_relpath:
        return ""
    return f"/tours/files/{slug}/{safe_relpath}"


def _public_tour_generated_viewer_url(slug: str, relpath: object) -> str:
    safe_slug = str(slug or "").strip()
    safe_relpath = _public_tour_safe_asset_relpath(relpath)
    if not safe_slug or "/" in safe_slug or ".." in safe_slug or not safe_relpath:
        return ""
    return f"/tours/viewer/{urllib.parse.quote(safe_slug, safe='')}/{urllib.parse.quote(safe_relpath, safe='/')}"


@lru_cache(maxsize=256)
def _public_tour_cached_file_sha256(
    path: str,
    *,
    size_bytes: int,
    mtime_ns: int,
    ctime_ns: int,
) -> str:
    del size_bytes, mtime_ns, ctime_ns
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _public_tour_path_contains_symlink(bundle_dir: Path, relpath: str) -> bool:
    cursor = bundle_dir
    for part in PurePosixPath(relpath).parts:
        cursor = cursor / part
        if not os.path.lexists(cursor):
            return False
        try:
            if stat.S_ISLNK(os.lstat(cursor).st_mode):
                return True
        except OSError:
            return True
    return False


def _public_tour_generated_source_path_is_unsafe(value: object) -> bool:
    normalized = str(value or "").strip().replace("\\", "/").lower()
    if not normalized:
        return True
    if normalized.startswith(("/tmp/", "/var/tmp/")) or "/tmp/" in normalized:
        return True
    return bool(re.search(r"(?:^|[/._-])(?:pytest(?:-of)?|debug|probe)(?:[/._-]|$)", normalized))


def _public_tour_generated_manifest_source_paths(value: object) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key or "").strip().lower().replace("-", "_")
            if normalized_key in {"source_path", "source_uri", "source_asset_ref", "source_asset_id"}:
                paths.append(str(child or "").strip())
            else:
                paths.extend(_public_tour_generated_manifest_source_paths(child))
    elif isinstance(value, list):
        for child in value:
            paths.extend(_public_tour_generated_manifest_source_paths(child))
    return paths


def _public_tour_generated_manifest_provenance_verified(
    bundle_dir: Path,
    *,
    relpath: object,
    expected_sha256: object,
) -> bool:
    safe_relpath = _public_tour_safe_asset_relpath(relpath)
    normalized_sha256 = str(expected_sha256 or "").strip().lower()
    if not safe_relpath or not re.fullmatch(r"[0-9a-f]{64}", normalized_sha256):
        return False
    if _public_tour_path_contains_symlink(bundle_dir, safe_relpath):
        return False
    candidate = (bundle_dir / safe_relpath).resolve()
    if bundle_dir.resolve() not in candidate.parents or not candidate.exists() or not candidate.is_file():
        return False
    try:
        candidate_stat = candidate.stat()
        if candidate_stat.st_size <= 0 or candidate_stat.st_size > 4 * 1024 * 1024:
            return False
        actual_sha256 = _public_tour_cached_file_sha256(
            str(candidate),
            size_bytes=int(candidate_stat.st_size),
            mtime_ns=int(candidate_stat.st_mtime_ns),
            ctime_ns=int(candidate_stat.st_ctime_ns),
        )
        if actual_sha256 != normalized_sha256:
            return False
        manifest = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, dict):
        return False
    source_paths = _public_tour_generated_manifest_source_paths(manifest)
    return bool(source_paths) and all(
        not _public_tour_generated_source_path_is_unsafe(source_path)
        for source_path in source_paths
    )


def _public_tour_generated_video_provenance_verified(
    bundle_dir: Path,
    release: dict[str, object],
) -> bool:
    return _public_tour_generated_manifest_provenance_verified(
        bundle_dir,
        relpath=release.get("source_manifest_relpath"),
        expected_sha256=release.get("source_manifest_sha256"),
    )


def _public_tour_safe_http_url(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return normalized


def _public_tour_external_media_url_allowed(value: object) -> bool:
    normalized = _public_tour_safe_http_url(value)
    if not normalized:
        return False
    return _public_tour_listing_research_url_allowed(normalized)


def _redact_public_tour_value(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            if _public_tour_key_is_private(key):
                continue
            redacted[str(key)] = _redact_public_tour_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_public_tour_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_public_tour_value(item) for item in value]
    return value


def _redacted_public_tour_facts(
    payload: dict[str, object],
    facts: dict[str, object],
    *,
    privacy_mode: str,
) -> dict[str, object]:
    redacted_value = _redact_public_tour_value(facts if isinstance(facts, dict) else {})
    redacted = dict(redacted_value) if isinstance(redacted_value, dict) else {}
    exact_address_allowed = _public_tour_exact_address_allowed(payload, privacy_mode=privacy_mode)
    for key in list(redacted.keys()):
        normalized_key = str(key or "").strip().lower()
        if normalized_key in _PUBLIC_TOUR_EXACT_LOCATION_FACT_KEYS and not exact_address_allowed:
            redacted.pop(key, None)
    if privacy_mode != "anonymous_public":
        return redacted

    def _redacted_public_livability(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        return {
            str(livability_key): _redact_public_tour_value(livability_value)
            for livability_key, livability_value in value.items()
            if str(livability_key or "").strip().lower().startswith("nearest_")
        }

    public_facts: dict[str, object] = {}
    for key, value in redacted.items():
        normalized_key = str(key or "").strip().lower()
        if normalized_key in _PUBLIC_TOUR_EXACT_LOCATION_FACT_KEYS:
            continue
        if normalized_key.startswith("nearest_") or normalized_key in _PUBLIC_TOUR_ANONYMOUS_FACT_KEYS:
            if normalized_key == "personal_fit_assessment" and isinstance(value, dict):
                assessment: dict[str, object] = {}
                for assessment_key, assessment_value in value.items():
                    normalized_assessment_key = str(assessment_key or "").strip().lower()
                    if normalized_assessment_key not in _PUBLIC_TOUR_PUBLIC_ASSESSMENT_KEYS:
                        continue
                    if normalized_assessment_key == "livability_snapshot":
                        assessment[str(assessment_key)] = _redacted_public_livability(assessment_value)
                    else:
                        assessment[str(assessment_key)] = _redact_public_tour_value(assessment_value)
                public_facts[str(key)] = assessment
            elif normalized_key == "livability_snapshot":
                public_facts[str(key)] = _redacted_public_livability(value)
            else:
                public_facts[str(key)] = value
    return public_facts


def _redacted_public_tour_scenes(
    payload: dict[str, object],
    *,
    expose_asset_relpaths: bool,
) -> list[dict[str, object]]:
    slug = str(payload.get("slug") or "").strip()
    allowed_assets = _public_tour_allowed_asset_paths(payload)
    rows: list[dict[str, object]] = []
    for scene in list(payload.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        rendered: dict[str, object] = {}
        for key, value in scene.items():
            if key not in _PUBLIC_TOUR_SCENE_KEYS or _public_tour_key_is_private(key):
                continue
            if key == "asset_relpath":
                relpath = _public_tour_safe_asset_relpath(value)
                if relpath not in allowed_assets:
                    continue
                if expose_asset_relpaths:
                    rendered[key] = relpath
                else:
                    rendered["image_url"] = _public_tour_file_url(slug, relpath)
                continue
            if key == "cube_faces":
                cube_faces: dict[str, object] = {}
                for face_key, face_value in dict(value or {}).items():
                    relpath = _public_tour_safe_asset_relpath(face_value)
                    if relpath not in allowed_assets:
                        continue
                    cube_faces[str(face_key)] = relpath if expose_asset_relpaths else _public_tour_file_url(slug, relpath)
                if cube_faces:
                    rendered[key] = cube_faces
                continue
            if key == "image_url":
                safe_url = _public_tour_external_media_url_allowed(value) and _public_tour_safe_http_url(value)
                if safe_url:
                    rendered[key] = safe_url
                continue
            rendered[str(key)] = _redact_public_tour_value(value)
        if rendered and ("image_url" in rendered or "asset_relpath" in rendered or "cube_faces" in rendered):
            rows.append(rendered)
    return rows


def _redacted_public_tour_payload(
    payload: dict[str, object],
    *,
    expose_asset_relpaths: bool = False,
) -> dict[str, object]:
    rendered: dict[str, object] = {}
    slug = str(payload.get("slug") or "").strip()
    privacy_mode = _public_tour_privacy_mode(payload)
    for key in _PUBLIC_TOUR_TOP_LEVEL_KEYS:
        if key not in payload or _public_tour_key_is_private(key):
            continue
        if key in {"facts", "brief"}:
            if key == "facts":
                rendered[key] = _redacted_public_tour_facts(
                    payload,
                    payload.get(key) if isinstance(payload.get(key), dict) else {},
                    privacy_mode=privacy_mode,
                )
            else:
                rendered[key] = _redact_public_tour_value(payload.get(key) if isinstance(payload.get(key), dict) else {})
            continue
        if key == "scenes":
            rendered[key] = _redacted_public_tour_scenes(payload, expose_asset_relpaths=expose_asset_relpaths)
            continue
        if key == "video_relpath":
            video_release = evaluate_public_tour_video_release(payload)
            relpath = _public_tour_safe_asset_relpath(video_release.get("relpath")) if video_release.get("released") else ""
            if not relpath or relpath not in _public_tour_allowed_asset_paths(payload):
                continue
            if expose_asset_relpaths:
                rendered[key] = relpath
            else:
                rendered[key.replace("_relpath", "_url")] = _public_tour_file_url(slug, relpath)
            continue
        if key in {"source_virtual_tour_url", "source_virtual_tour_origin"}:
            embed_release = evaluate_public_tour_embed_release(payload)
            if embed_release.get("released"):
                rendered[key] = str(embed_release.get("url") or "")
            continue
        rendered[key] = _redact_public_tour_value(payload.get(key))
    rendered["slug"] = slug
    rendered["tour_privacy_mode"] = privacy_mode
    rendered.setdefault("facts", {})
    rendered.setdefault("brief", {})
    rendered.setdefault("scenes", [])
    if not expose_asset_relpaths:
        rendered["public_assets"] = list(_public_tour_manifest(payload).values())
        video_release = evaluate_public_tour_video_release(payload)
        if video_release.get("released"):
            raw_release = payload.get("video_release")
            raw_release = dict(raw_release) if isinstance(raw_release, dict) else {}
            rendered["video_release"] = {
                "contract": PUBLIC_TOUR_VIDEO_RELEASE_CONTRACT,
                "status": "ready",
                "release_revision": str(video_release.get("release_revision") or ""),
                "asset_sha256": str(video_release.get("expected_sha256") or ""),
                "disclosure": str(video_release.get("disclosure") or ""),
                "synthetic": bool(video_release.get("synthetic") or raw_release.get("synthetic")),
                "verified_provider_capture": bool(
                    video_release.get("verified_provider_capture")
                    or raw_release.get("verified_provider_capture")
                ),
            }
        viewer_release = evaluate_public_tour_generated_viewer_release(payload)
        if viewer_release.get("released"):
            viewer_url = _public_tour_generated_viewer_url(slug, viewer_release.get("viewer_relpath"))
            if viewer_url:
                rendered["generated_viewer"] = {
                    "url": viewer_url,
                    "release_revision": str(viewer_release.get("release_revision") or ""),
                    "disclosure": str(viewer_release.get("disclosure") or ""),
                    "synthetic": True,
                    "verified_provider_capture": False,
                }
    return rendered


def _asset_file(slug: str, asset_path: str) -> Path:
    payload = _load_tour(slug)
    _require_public_tour_viewable(payload)
    safe_relpath = _public_tour_safe_asset_relpath(asset_path)
    configured_video_relpath = _public_tour_safe_asset_relpath(payload.get("video_relpath"))
    video_release = evaluate_public_tour_video_release(payload) if safe_relpath == configured_video_relpath else {}
    if safe_relpath and safe_relpath == configured_video_relpath:
        if not video_release.get("released"):
            status_code = 410 if video_release.get("terminal") else 404
            detail = "tour_media_no_longer_available" if status_code == 410 else "tour_file_not_found"
            raise HTTPException(status_code=status_code, detail=detail)
    manifest = _public_tour_manifest(payload, only_relpath=safe_relpath)
    bundle_dir = _tour_bundle_dir(slug)
    if not safe_relpath or bundle_dir is None:
        raise HTTPException(status_code=404, detail="tour_file_not_found")
    if safe_relpath not in manifest:
        raise HTTPException(status_code=404, detail="tour_file_not_found")
    if _public_tour_path_contains_symlink(bundle_dir, safe_relpath):
        raise HTTPException(status_code=404, detail="tour_file_not_found")
    candidate = (bundle_dir / safe_relpath).resolve()
    if bundle_dir.resolve() not in candidate.parents:
        raise HTTPException(status_code=404, detail="tour_file_not_found")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="tour_file_not_found")
    expected_sha256 = str(video_release.get("expected_sha256") or "").strip().lower()
    expected_size = video_release.get("expected_size_bytes")
    if expected_sha256 and isinstance(expected_size, int):
        try:
            candidate_stat = candidate.stat()
            digest = _public_tour_cached_file_sha256(
                str(candidate),
                size_bytes=int(candidate_stat.st_size),
                mtime_ns=int(candidate_stat.st_mtime_ns),
                ctime_ns=int(candidate_stat.st_ctime_ns),
            )
        except OSError as exc:
            raise HTTPException(status_code=404, detail="tour_file_not_found") from exc
        if candidate_stat.st_size != expected_size or digest != expected_sha256:
            raise HTTPException(status_code=410, detail="tour_media_no_longer_available")
    if (
        video_release.get("released")
        and video_release.get("provider") == GENERATED_RECONSTRUCTION_PROVIDER
        and not _public_tour_generated_video_provenance_verified(bundle_dir, video_release)
    ):
        raise HTTPException(status_code=410, detail="tour_media_no_longer_available")
    if candidate.suffix.lower() == ".pdf":
        max_bytes = max(int(os.getenv("PROPERTYQUARRY_PUBLIC_PDF_MAX_BYTES") or "15728640"), 1)
        try:
            if candidate.stat().st_size > max_bytes:
                raise HTTPException(status_code=404, detail="tour_file_not_found")
        except OSError as exc:
            raise HTTPException(status_code=404, detail="tour_file_not_found") from exc
    return candidate


def _generated_viewer_file(
    slug: str,
    asset_path: str,
) -> tuple[Path, dict[str, object], dict[str, object]]:
    payload = _load_tour(slug)
    _require_public_tour_viewable(payload)
    release = evaluate_public_tour_generated_viewer_release(payload)
    if not release.get("released"):
        status_code = 410 if release.get("terminal") else 404
        detail = "tour_viewer_no_longer_available" if status_code == 410 else "tour_viewer_not_found"
        raise HTTPException(status_code=status_code, detail=detail)

    safe_relpath = _public_tour_safe_asset_relpath(asset_path)
    bindings = release.get("bindings")
    binding = dict(bindings.get(safe_relpath) or {}) if isinstance(bindings, dict) and safe_relpath else {}
    role = str(binding.get("role") or "").strip().lower()
    mime_type = str(binding.get("mime_type") or "").strip().lower()
    allowed_mime_types = {
        "viewer_document": {"text/html"},
        "viewer_module": {"application/javascript", "text/javascript"},
        "floorplan_texture": {"image/jpeg", "image/png", "image/webp"},
        "photo_texture": {"image/jpeg", "image/png", "image/webp"},
    }
    if (
        not safe_relpath
        or role not in allowed_mime_types
        or mime_type not in allowed_mime_types[role]
        or (role == "viewer_document" and safe_relpath != release.get("viewer_relpath"))
    ):
        raise HTTPException(status_code=404, detail="tour_viewer_not_found")

    bundle_dir = _tour_bundle_dir(slug)
    if bundle_dir is None or _public_tour_path_contains_symlink(bundle_dir, safe_relpath):
        raise HTTPException(status_code=404, detail="tour_viewer_not_found")
    candidate = (bundle_dir / safe_relpath).resolve()
    if bundle_dir.resolve() not in candidate.parents or not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="tour_viewer_not_found")

    expected_sha256 = str(binding.get("sha256") or "").strip().lower()
    expected_size = binding.get("size_bytes")
    try:
        candidate_stat = candidate.stat()
        actual_sha256 = _public_tour_cached_file_sha256(
            str(candidate),
            size_bytes=int(candidate_stat.st_size),
            mtime_ns=int(candidate_stat.st_mtime_ns),
            ctime_ns=int(candidate_stat.st_ctime_ns),
        )
    except OSError as exc:
        raise HTTPException(status_code=404, detail="tour_viewer_not_found") from exc
    if not isinstance(expected_size, int) or candidate_stat.st_size != expected_size or actual_sha256 != expected_sha256:
        raise HTTPException(status_code=410, detail="tour_viewer_integrity_failed")
    proof_bindings = [
        row
        for row in dict(release.get("bindings") or {}).values()
        if isinstance(row, dict) and str(row.get("role") or "").strip().lower() == "reconstruction_manifest"
    ]
    if len(proof_bindings) != 1 or not _public_tour_generated_manifest_provenance_verified(
        bundle_dir,
        relpath=proof_bindings[0].get("path") if proof_bindings else "",
        expected_sha256=proof_bindings[0].get("sha256") if proof_bindings else "",
    ):
        raise HTTPException(status_code=410, detail="tour_viewer_integrity_failed")
    return candidate, binding, release


def _money(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"EUR {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "EUR ?"


def _safe_live_360_url(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    try:
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or port not in {None, 443}
    ):
        return ""
    return normalized


def _embedded_live_360_url(payload: dict[str, object]) -> str:
    release = evaluate_public_tour_embed_release(dict(payload or {}))
    return _safe_live_360_url(release.get("url")) if release.get("released") else ""


def _public_tour_has_complete_hosted_cube(payload: dict[str, object]) -> bool:
    if str(payload.get("scene_strategy") or "").strip().lower() != "pure_360_cube":
        return False
    slug = str(payload.get("slug") or "").strip()
    bundle_dir = _tour_bundle_dir(slug)
    if bundle_dir is None:
        return False
    required_faces = {"r", "l", "u", "d", "f", "b"}
    for scene in list(payload.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        cube_faces = scene.get("cube_faces")
        if not isinstance(cube_faces, dict) or not required_faces.issubset(cube_faces):
            continue
        complete = True
        for face in required_faces:
            relpath = _public_tour_safe_asset_relpath(cube_faces.get(face))
            if (
                not relpath
                or not _public_tour_asset_path_is_public(relpath, role="cube_face", mime_type="image/jpeg")
                or _public_tour_path_contains_symlink(bundle_dir, relpath)
            ):
                complete = False
                break
            candidate = (bundle_dir / relpath).resolve()
            if bundle_dir.resolve() not in candidate.parents or not candidate.exists() or not candidate.is_file():
                complete = False
                break
        if complete:
            return True
    return False


def _public_tour_listing_research_allowed_hosts() -> tuple[str, ...]:
    raw = str(os.getenv("PROPERTYQUARRY_PUBLIC_RESEARCH_ALLOWED_HOSTS") or "").strip()
    if not raw:
        return _PUBLIC_TOUR_RESEARCH_DEFAULT_HOST_SUFFIXES
    hosts = tuple(
        item.strip().lower().lstrip(".")
        for item in raw.split(",")
        if item.strip().lower().lstrip(".")
    )
    return hosts or _PUBLIC_TOUR_RESEARCH_DEFAULT_HOST_SUFFIXES


def _public_tour_hostname_matches_suffix(hostname: str, suffix: str) -> bool:
    normalized_host = str(hostname or "").strip().lower().rstrip(".")
    normalized_suffix = str(suffix or "").strip().lower().rstrip(".").lstrip(".")
    if not normalized_host or not normalized_suffix:
        return False
    return normalized_host == normalized_suffix or normalized_host.endswith(f".{normalized_suffix}")


def _public_tour_host_resolves_to_public_ips(hostname: str) -> bool:
    try:
        addresses = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    if not addresses:
        return False
    for row in addresses:
        try:
            ip_value = str(row[4][0])
            address = ipaddress.ip_address(ip_value)
        except (IndexError, TypeError, ValueError):
            return False
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            return False
    return True


def _public_tour_listing_research_url_allowed(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return False
    hostname = parsed.hostname.strip().lower().rstrip(".")
    if not any(
        _public_tour_hostname_matches_suffix(hostname, suffix)
        for suffix in _public_tour_listing_research_allowed_hosts()
    ):
        return False
    return _public_tour_host_resolves_to_public_ips(hostname)


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
    try:
        # Fixed OpenStreetMap reverse-geocode endpoint for map context.
        response = requests.get(url, headers={"User-Agent": "EA/1.0"}, timeout=6.0)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=128)
def _fetch_nearby_poi_research(lat: float, lon: float) -> dict[str, object]:
    query = f"""
[out:json][timeout:20];
(
  node["shop"="supermarket"](around:5000,{lat:.8f},{lon:.8f});
  way["shop"="supermarket"](around:5000,{lat:.8f},{lon:.8f});
  node["shop"="convenience"](around:5000,{lat:.8f},{lon:.8f});
  way["shop"="convenience"](around:5000,{lat:.8f},{lon:.8f});
  node["shop"="greengrocer"](around:5000,{lat:.8f},{lon:.8f});
  way["shop"="greengrocer"](around:5000,{lat:.8f},{lon:.8f});
  node["amenity"="pharmacy"](around:5000,{lat:.8f},{lon:.8f});
  way["amenity"="pharmacy"](around:5000,{lat:.8f},{lon:.8f});
  node["amenity"="library"](around:5000,{lat:.8f},{lon:.8f});
  way["amenity"="library"](around:5000,{lat:.8f},{lon:.8f});
  node["leisure"="playground"](around:5000,{lat:.8f},{lon:.8f});
  way["leisure"="playground"](around:5000,{lat:.8f},{lon:.8f});
  node["shop"="doityourself"](around:7000,{lat:.8f},{lon:.8f});
  way["shop"="doityourself"](around:7000,{lat:.8f},{lon:.8f});
  node["shop"="hardware"](around:7000,{lat:.8f},{lon:.8f});
  way["shop"="hardware"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="marketplace"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="marketplace"](around:7000,{lat:.8f},{lon:.8f});
  node["shop"="mall"](around:7000,{lat:.8f},{lon:.8f});
  way["shop"="mall"](around:7000,{lat:.8f},{lon:.8f});
  node["highway"="pedestrian"](around:7000,{lat:.8f},{lon:.8f});
  way["highway"="pedestrian"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="theatre"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="theatre"](around:7000,{lat:.8f},{lon:.8f});
  node["leisure"="swimming_pool"](around:7000,{lat:.8f},{lon:.8f});
  way["leisure"="swimming_pool"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="doctors"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="doctors"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="clinic"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="clinic"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="hospital"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="hospital"](around:7000,{lat:.8f},{lon:.8f});
  node["railway"="tram_stop"](around:7000,{lat:.8f},{lon:.8f});
  way["railway"="tram_stop"](around:7000,{lat:.8f},{lon:.8f});
  node["highway"="bus_stop"](around:7000,{lat:.8f},{lon:.8f});
  way["highway"="bus_stop"](around:7000,{lat:.8f},{lon:.8f});
  node["railway"="subway_entrance"](around:7000,{lat:.8f},{lon:.8f});
  way["railway"="subway_entrance"](around:7000,{lat:.8f},{lon:.8f});
);
out center tags;
"""
    try:
        # Fixed Overpass API endpoint for nearby POI context.
        response = requests.post(
            "https://overpass-api.de/api/interpreter",
            data=query.encode("utf-8"),
            headers={"User-Agent": "EA/1.0"},
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, json.JSONDecodeError):
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
        if tags.get("shop") in {"supermarket", "convenience", "greengrocer"}:
            key = "nearest_supermarket_m"
            name_key = "nearest_supermarket_name"
        elif tags.get("amenity") == "pharmacy":
            key = "nearest_pharmacy_m"
            name_key = "nearest_pharmacy_name"
        elif tags.get("amenity") == "library":
            key = "nearest_library_m"
            name_key = "nearest_library_name"
        elif tags.get("leisure") == "playground":
            key = "nearest_playground_m"
            name_key = "nearest_playground_name"
        elif tags.get("shop") in {"doityourself", "hardware"}:
            key = "nearest_hardware_store_m"
            name_key = "nearest_hardware_store_name"
        elif tags.get("amenity") == "marketplace":
            key = "nearest_market_m"
            name_key = "nearest_market_name"
        elif tags.get("shop") == "mall":
            key = "nearest_shopping_center_m"
            name_key = "nearest_shopping_center_name"
        elif tags.get("highway") == "pedestrian":
            key = "nearest_shopping_street_m"
            name_key = "nearest_shopping_street_name"
        elif tags.get("amenity") == "theatre":
            key = "nearest_theatre_m"
            name_key = "nearest_theatre_name"
        elif tags.get("leisure") == "swimming_pool":
            key = "nearest_public_pool_m"
            name_key = "nearest_public_pool_name"
        elif tags.get("amenity") in {"doctors", "clinic", "hospital"}:
            key = "nearest_medical_care_m"
            name_key = "nearest_medical_care_name"
        elif tags.get("railway") == "tram_stop" or tags.get("highway") == "bus_stop":
            key = "nearest_tram_bus_m"
            name_key = "nearest_tram_bus_name"
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
    if not _public_tour_listing_research_url_allowed(normalized):
        return {}
    try:
        # Listing URL fetch is guarded by host allowlist and public-IP checks above.
        response = requests.get(
            normalized,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
            },
            timeout=4.0,
        )
        response.raise_for_status()
        raw_html = response.text
    except (requests.RequestException, ValueError):
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


def _public_tour_rate_limit_dir() -> Path | None:
    raw = (
        os.environ.get("PROPERTYQUARRY_PUBLIC_RATE_LIMIT_DIR")
        or os.environ.get("EA_PUBLIC_RATE_LIMIT_DIR")
        or ""
    ).strip()
    if raw:
        return Path(raw).expanduser()
    ledger_dir = str(os.environ.get("EA_RESPONSES_PROVIDER_LEDGER_DIR") or "").strip()
    if ledger_dir:
        return Path(ledger_dir).expanduser() / "public-tour-rate-limits"
    return None


def _safe_public_tour_ip(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("[") and "]" in raw:
        raw = raw[1 : raw.find("]")]
    elif raw.count(":") == 1 and "." in raw:
        raw = raw.rsplit(":", 1)[0]
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return ""


def _public_tour_client_identity(request: Request) -> str:
    cf_ip = _safe_public_tour_ip(request.headers.get("cf-connecting-ip"))
    if trust_forwarded_ip() and cf_ip and str(request.headers.get("cf-ray") or "").strip():
        return f"cf:{cf_ip}"
    if trust_forwarded_ip():
        for part in str(request.headers.get("x-forwarded-for") or "").split(","):
            forwarded_ip = _safe_public_tour_ip(part)
            if forwarded_ip:
                return f"xff:{forwarded_ip}"
    client_ip = _safe_public_tour_ip(getattr(getattr(request, "client", None), "host", "") or "")
    return f"client:{client_ip or 'unknown'}"


def _public_tour_feedback_rate_limit_key(*, request: Request, slug: str, principal_id: str) -> str:
    identity = _public_tour_client_identity(request)
    identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    principal_hash = hashlib.sha256(str(principal_id or "").encode("utf-8")).hexdigest()[:16]
    slug_hash = hashlib.sha256(str(slug or "").encode("utf-8")).hexdigest()[:16]
    return f"{slug_hash}:{principal_hash}:{identity_hash}"


def _prune_public_tour_feedback_memory_rate_limit(now: float) -> None:
    expired = [
        key
        for key, (window_started, _count) in _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT.items()
        if now - float(window_started) > _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS
    ]
    for key in expired:
        _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT.pop(key, None)
    while len(_PUBLIC_TOUR_FEEDBACK_RATE_LIMIT) > _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT_MAX_KEYS:
        _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT.popitem(last=False)


def _enforce_public_tour_feedback_memory_rate_limit(*, key: str, now: float) -> None:
    _prune_public_tour_feedback_memory_rate_limit(now)
    window_started, count = _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT.get(key, (now, 0))
    if now - float(window_started) > _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS:
        _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT[key] = (now, 1)
        return
    if int(count) >= _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="public_tour_feedback_rate_limited")
    _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT[key] = (float(window_started), int(count) + 1)
    _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT.move_to_end(key)


def _prune_public_tour_feedback_file_rate_limit(rate_dir: Path, *, now: float) -> None:
    try:
        files = sorted(rate_dir.glob("*.json"), key=lambda item: item.stat().st_mtime)
    except OSError:
        return
    stale_before = now - (_PUBLIC_TOUR_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS * 4)
    for path in files:
        try:
            if path.stat().st_mtime < stale_before:
                path.unlink(missing_ok=True)
        except OSError:
            continue
    if len(files) <= _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT_MAX_KEYS:
        return
    for path in files[: max(0, len(files) - _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT_MAX_KEYS)]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue


def _enforce_public_tour_feedback_file_rate_limit(*, key: str, now: float) -> bool:
    rate_dir = _public_tour_rate_limit_dir()
    if rate_dir is None:
        return False
    try:
        rate_dir.mkdir(parents=True, exist_ok=True)
        lock_path = rate_dir / ".feedback-rate-limit.lock"
        state_path = rate_dir / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
            except Exception:
                state = {}
            try:
                window_started = float(state.get("window_started") or now)
            except Exception:
                window_started = now
            try:
                count = int(state.get("count") or 0)
            except Exception:
                count = 0
            if now - window_started > _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS:
                window_started = now
                count = 0
            if count >= _PUBLIC_TOUR_FEEDBACK_RATE_LIMIT_MAX:
                raise HTTPException(status_code=429, detail="public_tour_feedback_rate_limited")
            tmp_path = state_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps({"window_started": window_started, "count": count + 1}, sort_keys=True),
                encoding="utf-8",
            )
            tmp_path.replace(state_path)
            _prune_public_tour_feedback_file_rate_limit(rate_dir, now=now)
        return True
    except HTTPException:
        raise
    except Exception:
        log.exception("public tour feedback durable rate limit failed")
        if _public_tour_env_truthy(os.getenv("PROPERTYQUARRY_PUBLIC_RATE_LIMIT_FAIL_CLOSED")) or _public_tour_prod_mode_enabled():
            raise HTTPException(status_code=503, detail="public_tour_feedback_rate_limit_unavailable")
        return False


def _enforce_public_tour_feedback_rate_limit(*, request: Request, slug: str, principal_id: str) -> None:
    now = time.time()
    key = _public_tour_feedback_rate_limit_key(request=request, slug=slug, principal_id=principal_id)
    if _enforce_public_tour_feedback_file_rate_limit(key=key, now=now):
        return
    _enforce_public_tour_feedback_memory_rate_limit(key=key, now=now)


def _public_tour_authenticated_action_required(action: str) -> HTTPException:
    normalized_action = str(action or "").strip()
    if normalized_action not in _PUBLIC_TOUR_ACTIONS:
        normalized_action = "public-tour-action"
    return HTTPException(status_code=403, detail=f"{normalized_action}_requires_authenticated_workspace")


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
        except (OSError, ValueError, json.JSONDecodeError):
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


def _tour_no_released_scenes_html(
    payload: dict[str, object],
    *,
    hostname: str = "",
    rybbit_hostname: str = "",
) -> str:
    facts = dict(payload.get("facts") or {}) if isinstance(payload.get("facts"), dict) else {}
    title = _public_tour_safe_display_text(
        payload.get("title") or payload.get("tour_title") or payload.get("display_title") or payload.get("slug"),
        fallback="Property review",
    )
    display_title = _public_tour_safe_display_text(payload.get("display_title"), fallback=title, limit=260)
    brand = _public_tour_safe_display_text(
        payload.get("brand_name"),
        fallback=_public_tour_host_brand_label(hostname, fallback="PropertyQuarry"),
    )
    slug = str(payload.get("slug") or "").strip()
    listing_url = safe_public_navigation_url(
        payload.get("listing_url") or payload.get("property_url"),
        production=_public_tour_prod_mode_enabled(),
    )
    hosted_url = safe_public_navigation_url(
        payload.get("hosted_url") or payload.get("public_url"),
        production=_public_tour_prod_mode_enabled(),
    )
    viewer_url = safe_public_navigation_url(
        payload.get("_released_generated_viewer_url"),
        production=_public_tour_prod_mode_enabled(),
    )
    embed_url = _safe_live_360_url(payload.get("_released_embed_url"))
    video_relpath = _public_tour_safe_asset_relpath(payload.get("_released_video_relpath"))
    video_url = _public_tour_file_url(slug, video_relpath) if slug and video_relpath else ""

    fact_rows: list[tuple[str, str]] = []
    rooms = facts.get("rooms_label") or facts.get("rooms") or facts.get("room_count")
    if isinstance(rooms, (str, int, float)) and str(rooms).strip():
        fact_rows.append(("Rooms", _public_tour_safe_display_text(rooms, limit=80)))
    area = facts.get("area_label")
    if not area and isinstance(facts.get("area_sqm"), (int, float)):
        area = f"{facts['area_sqm']:g} m²"
    if isinstance(area, str) and area.strip():
        fact_rows.append(("Area", _public_tour_safe_display_text(area, limit=80)))
    rent = facts.get("total_rent_eur")
    if isinstance(rent, (int, float)) and float(rent) > 0:
        fact_rows.append(("Price", _money(rent)))
    availability = facts.get("availability")
    if isinstance(availability, str) and availability.strip():
        fact_rows.append(("Availability", _public_tour_safe_display_text(availability, limit=100)))
    fact_cards = "".join(
        '<div class="fact-card">'
        f'<span>{html.escape(label)}</span><strong>{html.escape(value)}</strong>'
        "</div>"
        for label, value in fact_rows[:4]
    )
    if not fact_cards:
        fact_cards = (
            '<div class="fact-card"><span>Listing facts</span>'
            "<strong>Review the source listing for confirmed dimensions and costs.</strong></div>"
        )

    media_state = "released"
    if viewer_url:
        media_title = "Released interactive reconstruction"
        media_summary = "Use the room route to inspect the reconstructed layout. Confirm dimensions and finishes in person."
        media_html = (
            '<iframe class="media-frame" '
            f'src="{html.escape(viewer_url)}" '
            f'title="{html.escape(title)} interactive generated reconstruction" '
            'sandbox="allow-scripts" loading="eager" allowfullscreen referrerpolicy="no-referrer"></iframe>'
        )
    elif video_url:
        media_title = "Released generated walkthrough"
        media_summary = "This reviewed synthetic walkthrough is a layout aid, not a captured provider scan."
        media_html = (
            f'<video class="media-frame" controls preload="metadata" src="{html.escape(video_url)}">'
            "Your browser does not support the reviewed walkthrough video.</video>"
        )
    elif embed_url:
        media_title = "Released external panorama"
        media_summary = "The reviewed provider panorama is isolated in a constrained frame."
        media_html = (
            '<iframe class="media-frame" '
            f'src="{html.escape(embed_url)}" title="{html.escape(title)} external panorama" '
            'sandbox="allow-scripts allow-same-origin allow-forms allow-presentation" '
            'allow="fullscreen; autoplay" loading="eager" allowfullscreen referrerpolicy="no-referrer"></iframe>'
        )
    else:
        media_state = "unreleased"
        media_title = "Tour media is awaiting release review"
        media_summary = (
            "No tour media has passed public release review for this listing. "
            "The page remains useful for approved listing facts without exposing private, test, or source artifacts."
        )
        media_html = (
            '<div class="media-empty" role="status">'
            '<span aria-hidden="true">360°</span>'
            "<strong>No released scenes</strong>"
            "<p>Ask the sender for a newly reviewed tour when the media package is ready.</p>"
            "</div>"
        )

    disclosure = _public_tour_safe_display_text(
        payload.get("_tour_media_disclosure"),
        fallback=media_summary,
        limit=360,
    )
    if media_state == "unreleased":
        disclosure = media_summary
    actions = ['<a class="primary" href="#media-review">Review media status</a>']
    if listing_url:
        actions.append(
            f'<a href="{html.escape(listing_url)}" target="_blank" rel="noreferrer noopener">Open listing</a>'
        )
    if hosted_url and hosted_url != listing_url:
        actions.append(f'<a href="{html.escape(hosted_url)}" rel="noreferrer">Permalink</a>')
    actions_html = "".join(actions)
    clickrank_html = clickrank_head_snippet(hostname)
    rybbit_html = rybbit_head_snippet(rybbit_hostname or hostname)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(title)}</title>
    {clickrank_html}
    {rybbit_html}
    <style>
      :root {{ --bg:#f4efe6; --panel:#fffdf8; --ink:#201d18; --muted:#6c6255; --accent:#8d3f1f; --edge:#dfd5c7; }}
      * {{ box-sizing:border-box; }}
      body {{ margin:0; color:var(--ink); background:radial-gradient(circle at 8% 0%, #ead9c8, transparent 34%), var(--bg); font-family:ui-sans-serif,system-ui,sans-serif; }}
      .shell {{ width:min(1120px,calc(100% - 32px)); margin:0 auto; padding:40px 0 56px; }}
      .hero,.panel {{ background:color-mix(in srgb,var(--panel) 94%,transparent); border:1px solid var(--edge); border-radius:24px; box-shadow:0 22px 70px rgba(56,42,26,.10); }}
      .hero {{ display:grid; grid-template-columns:minmax(0,1.1fr) minmax(280px,.9fr); gap:28px; padding:clamp(24px,5vw,54px); }}
      .eyebrow {{ color:var(--accent); font-size:.76rem; font-weight:850; letter-spacing:.13em; text-transform:uppercase; }}
      h1,h2,p {{ margin-top:0; }}
      h1 {{ margin-bottom:14px; font:700 clamp(2rem,5vw,4rem)/.98 Georgia,serif; letter-spacing:-.035em; }}
      h2 {{ margin-bottom:10px; font:700 clamp(1.45rem,3vw,2.2rem)/1.05 Georgia,serif; }}
      .lede,.summary {{ color:var(--muted); line-height:1.65; }}
      .facts {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:24px; }}
      .fact-card {{ min-height:86px; padding:14px; border:1px solid var(--edge); border-radius:16px; background:#fff; }}
      .fact-card span {{ display:block; margin-bottom:6px; color:var(--muted); font-size:.78rem; font-weight:750; text-transform:uppercase; }}
      .fact-card strong {{ line-height:1.35; }}
      .actions {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:24px; }}
      .actions a {{ padding:11px 16px; border:1px solid var(--edge); border-radius:999px; color:var(--ink); background:#fff; font-weight:750; text-decoration:none; }}
      .actions .primary {{ color:#fff; border-color:var(--accent); background:var(--accent); }}
      .status-card {{ display:flex; flex-direction:column; justify-content:center; padding:24px; border-radius:20px; background:#242019; color:#fff; }}
      .status-card .eyebrow,.status-card .summary {{ color:#ead8c1; }}
      .panel {{ margin-top:24px; padding:clamp(20px,4vw,38px); }}
      .media-wrap {{ overflow:hidden; min-height:360px; margin-top:22px; border:1px solid var(--edge); border-radius:18px; background:#171512; }}
      .media-frame {{ display:block; width:100%; min-height:520px; border:0; background:#171512; }}
      .media-empty {{ display:grid; min-height:360px; place-items:center; align-content:center; gap:8px; padding:36px; color:#f8f1e7; text-align:center; }}
      .media-empty > span {{ display:grid; width:84px; height:84px; place-items:center; border:1px solid rgba(255,255,255,.28); border-radius:50%; font:700 1.35rem Georgia,serif; }}
      .media-empty p {{ max-width:540px; margin-bottom:0; color:#cfc3b4; line-height:1.55; }}
      @media (max-width:760px) {{ .hero {{ grid-template-columns:1fr; }} .facts {{ grid-template-columns:1fr; }} .media-frame {{ min-height:420px; }} }}
      @media (prefers-reduced-motion:reduce) {{ * {{ scroll-behavior:auto!important; animation-duration:.01ms!important; transition-duration:.01ms!important; }} }}
    </style>
  </head>
  <body>
    <div class="shell" data-media-state="{media_state}">
      <section class="hero">
        <div>
          <div class="eyebrow">{html.escape(brand)} · public property review</div>
          <h1>{html.escape(title)}</h1>
          <p class="lede">{html.escape(display_title)}</p>
          <div class="facts">{fact_cards}</div>
          <div class="actions">{actions_html}</div>
        </div>
        <aside class="status-card">
          <div class="eyebrow">Evidence boundary</div>
          <h2>{html.escape(media_title)}</h2>
          <p class="summary">{html.escape(media_summary)}</p>
        </aside>
      </section>
      <section id="media-review" class="panel" aria-labelledby="media-review-title">
        <div class="eyebrow">Reviewed media lane</div>
        <h2 id="media-review-title">{html.escape(media_title)}</h2>
        <p class="summary">{html.escape(disclosure)}</p>
        <div class="media-wrap">{media_html}</div>
      </section>
    </div>
  </body>
</html>"""


def _tour_html(payload: dict[str, object], *, hostname: str = "", rybbit_hostname: str = "") -> str:
    scenes = [dict(row) for row in (payload.get("scenes") or []) if isinstance(row, dict)]
    if not scenes:
        return _tour_no_released_scenes_html(
            payload,
            hostname=hostname,
            rybbit_hostname=rybbit_hostname,
        )
    facts, researched_facts = _merged_facts_with_listing_research(payload, dict(payload.get("facts") or {}))
    facts.pop("public_preference_snapshot", None)
    feedback_suggestions = dict(payload.get("_feedback_suggestions") or {}) if isinstance(payload.get("_feedback_suggestions"), dict) else {}
    learning_summary = dict(payload.get("_learning_summary") or {}) if isinstance(payload.get("_learning_summary"), dict) else {}
    filter_context = _filter_panel_context(facts=facts)
    shortlist_compare = dict(payload.get("_shortlist_compare") or {}) if isinstance(payload.get("_shortlist_compare"), dict) else {}
    brief = dict(payload.get("brief") or {})
    title = str(payload.get("title") or payload.get("tour_title") or payload.get("slug") or "Property Tour").strip()
    display_title = str(payload.get("display_title") or title).strip() or title
    listing_url = str(payload.get("listing_url") or "").strip()
    hosted_url = str(payload.get("hosted_url") or "").strip()
    source_virtual_tour_url = _safe_live_360_url(payload.get("_released_embed_url"))
    is_pure_360_cube = bool(payload.get("_hosted_cube_ready"))
    brand_name = str(payload.get("brand_name") or "Pioche Lecombe").strip() or "Pioche Lecombe"
    hosted_brand_name = _public_tour_host_brand_label(hostname, fallback=brand_name)
    hosted_brand_html = html.escape(hosted_brand_name)
    slug = str(payload.get("slug") or "").strip()
    video_relpath = _public_tour_safe_asset_relpath(payload.get("_released_video_relpath"))
    video_url = f"/tours/files/{slug}/{video_relpath}" if slug and video_relpath else ""
    generated_viewer_url = safe_public_navigation_url(
        payload.get("_released_generated_viewer_url"),
        production=_public_tour_prod_mode_enabled(),
    )

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
            ("nearest_library_m", "Library"),
            ("nearest_medical_care_m", "Medical care"),
            ("nearest_market_m", "Market"),
            ("nearest_hardware_store_m", "Baumarkt"),
            ("nearest_shopping_street_m", "Flaniermeile"),
            ("nearest_shopping_center_m", "Shopping center"),
            ("nearest_theatre_m", "Theatre"),
            ("nearest_public_pool_m", "Public pool"),
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

    def _missing_fact_items() -> list[dict[str, object]]:
        research = facts.get("missing_fact_research")
        if not isinstance(research, dict):
            return []
        items = research.get("items")
        if not isinstance(items, list):
            return []
        return [dict(item) for item in items if isinstance(item, dict)]

    def _missing_fact_item(field: str) -> dict[str, object]:
        normalized = str(field or "").strip()
        for item in _missing_fact_items():
            if str(item.get("field") or "").strip() == normalized:
                return item
        return {}

    def _rooms_display() -> str:
        label = _fact_text("rooms_label")
        if label:
            return label
        raw_rooms = facts.get("rooms") or facts.get("room_count")
        if isinstance(raw_rooms, (int, float)) and float(raw_rooms) > 0:
            return f"{int(raw_rooms) if float(raw_rooms).is_integer() else raw_rooms} rooms"
        item = _missing_fact_item("rooms")
        if item:
            return str(item.get("display_value") or "Rooms under research").strip() or "Rooms under research"
        return ""

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
        if _fact_bool("air_quality_risk"):
            rows.append("Air quality still needs explicit validation for pollution burden and respiratory comfort.")
        if _fact_bool("crime_risk"):
            rows.append("Crime and safety burden still need explicit validation for this micro-location.")
        if _fact_bool("parking_pressure_risk"):
            rows.append("Parking pressure still needs clarification because no reliable garage fallback is confirmed.")
        if _fact_bool("drinking_water_risk"):
            rows.append("Drinking-water source and groundwater burden still need explicit validation.")
        if _fact_bool("cesspit_risk"):
            rows.append("Senkgrube or septic dependence still needs explicit validation for cost and smell burden.")
        if _fact_bool("winter_access_risk"):
            rows.append("Winter snow or slope access still needs explicit validation.")
        if _fact_bool("flood_risk"):
            rows.append("Flood and runoff exposure still need explicit validation.")
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
        nearest_library = livability_snapshot.get("nearest_library_m")
        nearest_medical_care = livability_snapshot.get("nearest_medical_care_m")
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
            elif "library" in key:
                if isinstance(nearest_library, (int, float)) and nearest_library > 0:
                    positive.append(f"The nearest library is about {int(nearest_library):d} m away.")
                else:
                    open_questions.append("Library distance is not stored yet.")
            elif "medical" in key or "doctor" in key or "hospital" in key:
                if isinstance(nearest_medical_care, (int, float)) and nearest_medical_care > 0:
                    positive.append(f"Medical care is about {int(nearest_medical_care):d} m away.")
                else:
                    open_questions.append("Medical-care distance is not stored yet.")
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
                "name": _public_tour_safe_display_text(scene.get("name"), fallback=f"Scene {index + 1}"),
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
                "role": re.sub(r"[^a-z0-9_-]+", "-", str(scene.get("role") or "photo").strip().lower()).strip("-") or "photo",
                "mime_type": str(scene.get("mime_type") or "").strip(),
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
    rooms = html.escape(_rooms_display())
    area_display = _fact_text("area_sqm", "area_m2", "living_area_m2")
    area = html.escape(area_display or "Area under research")
    rent_value = _money(facts.get("total_rent_eur") or facts.get("price_eur") or facts.get("purchase_price_eur"))
    rent = html.escape("" if rent_value == "EUR ?" else rent_value)
    availability = html.escape(_fact_text("availability", "availability_text") or "Availability under research")
    address = "<br>".join(html.escape(str(value)) for value in (facts.get("address_lines") or []))
    teaser = " · ".join(html.escape(str(value)) for value in (facts.get("teaser_attributes") or []))
    creative_brief = html.escape(str(brief.get("creative_brief") or "").strip())
    theme_name = html.escape(str(brief.get("theme_name") or "").strip())
    tour_style = html.escape(str(brief.get("tour_style") or "").strip())
    audience = html.escape(str(brief.get("audience") or "").strip())
    cta = html.escape(str(brief.get("call_to_action") or "").strip())
    brand_html = html.escape(brand_name)
    listing_url = safe_public_navigation_url(listing_url, production=_public_tour_prod_mode_enabled())
    hosted_url = safe_public_navigation_url(hosted_url, production=_public_tour_prod_mode_enabled())
    listing_link = f'<a class="ghost" href="{html.escape(listing_url)}" target="_blank" rel="noreferrer noopener">Open Listing</a>' if listing_url else ""
    hosted_link = f'<a class="ghost" href="{html.escape(hosted_url)}" rel="noreferrer">Permalink</a>' if hosted_url else ""
    primary_cta = "Open Live 360" if source_virtual_tour_url else "Open Tour"
    primary_cta_href = "#live-360" if source_virtual_tour_url else "#viewer"
    if generated_viewer_url:
        primary_cta = "Open interactive 3D reconstruction"
        primary_cta_href = "#generated-3d-viewer"
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
        "nearest_library_m",
        "nearest_medical_care_m",
        "nearest_market_m",
        "nearest_hardware_store_m",
        "nearest_shopping_street_m",
        "nearest_shopping_center_m",
        "nearest_theatre_m",
        "nearest_public_pool_m",
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
    rooms_chip = rooms
    area_chip = area
    rent_chip = rent
    availability_chip = availability
    rooms_legacy_chip_html = f'<div class="chip">{rooms}</div>' if rooms else '<div class="chip">Rooms under research</div>'
    area_legacy_chip_html = f'<div class="chip">{area} m²</div>' if area_display else f'<div class="chip">{area}</div>'
    rent_legacy_chip_html = f'<div class="chip">{rent}</div>' if rent else ""
    availability_legacy_chip_html = f'<div class="chip">Available: {availability}</div>' if availability else ""
    decision_rows = _decision_rows()
    personalized_positive, personalized_caution, personalized_unknowns = _personalized_priority_rows()
    highlight_lines = personalized_positive or good_fit_reasons[:4] or _feature_highlights()
    concern_lines = personalized_caution or bad_fit_reasons[:4] or _feature_concerns()
    missing_fact_lines = []
    for item in _missing_fact_items():
        if str(item.get("status") or "").strip().lower() == "filled":
            continue
        label = str(item.get("label") or item.get("field") or "Missing fact").strip()
        ooda = dict(item.get("ooda") or {}) if isinstance(item.get("ooda"), dict) else {}
        action = str(ooda.get("act") or item.get("evidence") or "Research queued.").strip()
        line = f"{label}: {action}".strip()
        missing_fact_lines.append(line[:180])
    unknown_lines = missing_fact_lines[:3] or personalized_unknowns or unknowns[:4]
    completed_research_line = ""
    if researched_facts or _public_tour_env_truthy(payload.get("_public_research_completed")):
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
            ("nearest_library_m", "Library"),
            ("nearest_medical_care_m", "Medical care"),
            ("nearest_market_m", "Market"),
            ("nearest_hardware_store_m", "Baumarkt"),
            ("nearest_shopping_street_m", "Flaniermeile"),
            ("nearest_shopping_center_m", "Shopping center"),
            ("nearest_theatre_m", "Theatre"),
            ("nearest_public_pool_m", "Public pool"),
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
        comparison_panel = (
            '<section class="panel">'
            '<div class="eyebrow">Fit Pattern</div>'
            '<h2>How this property compares to the current brief</h2>'
            '<div class="summary-grid" style="margin-top:0;">'
            '<div class="summary-card"><h3>Supports the brief</h3><ul>'
            f'{"".join(f"<li>{html.escape(item)}</li>" for item in comparison_positive) or "<li>No strong positive pattern match is clear yet.</li>"}'
            '</ul></div>'
            '<div class="summary-card"><h3>Needs caution</h3><ul>'
            f'{"".join(f"<li>{html.escape(item)}</li>" for item in comparison_conflicts) or "<li>No strong learned conflict is visible yet.</li>"}'
            '</ul></div>'
            '<div class="summary-card"><h3>Open questions</h3><ul>'
            f'{"".join(f"<li>{html.escape(item)}</li>" for item in (unknown_lines[:3] or ["No critical open question is stored yet."]))}'
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
        detail_request_button = (
            '<div class="request-row">'
            '<span id="request-details-status" class="request-status">'
            'Open the authenticated PropertyQuarry review packet to request deeper research.'
            '</span>'
            '</div>'
        )
        active_filter_labels = [str(item or "").strip() for item in list(filter_context.get("active_labels") or []) if str(item or "").strip()]
        hard_filter_button_html = "".join(
            (
                f'<button class="reason-chip filter-chip{" active" if bool(spec.get("active")) else ""}" '
                f'type="button" data-filter-key="{html.escape(str(spec.get("key") or ""))}" '
                f'data-enabled="{html.escape("false" if bool(spec.get("active")) else "true")}" '
                'disabled title="Open the authenticated PropertyQuarry workspace to change profile filters.">'
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
                f'data-enabled="{html.escape("false" if bool(spec.get("active")) else "true")}" '
                'disabled title="Open the authenticated PropertyQuarry workspace to change profile filters.">'
                f'{html.escape(str(spec.get("label") or ""))}'
                '</button>'
            )
            for spec in list(filter_context.get("soft_filters") or [])
            if isinstance(spec, dict)
        )
        active_filter_html = "".join(f"<li>{html.escape(label)}</li>" for label in active_filter_labels[:8])
        filters_panel = ""
        feedback_panel = ""
        if bool(payload.get("_feedback_enabled")) or str(payload.get("principal_id") or "").strip():
            feedback_panel = (
                '<section id="feedback" class="panel">'
                '<div class="eyebrow">Preference Feedback</div>'
                '<h2>Teach the system what to rank higher or lower</h2>'
                '<p class="sub">Give a quick reaction and mark concrete reasons. Public-link feedback is captured as an external signal; sign in to apply it to a ranking profile.</p>'
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
        learned_panel = ""
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
                sandbox="allow-scripts allow-same-origin allow-forms allow-presentation"
                allow="fullscreen; autoplay"
                allowfullscreen
                loading="eager"
                referrerpolicy="no-referrer"
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
            if (!response.ok) {{
              feedbackStatus.textContent = payload.status === "not_captured"
                ? "Feedback could not be saved. Please retry from the signed-in workspace."
                : "Could not save feedback right now.";
              return;
            }}
            feedbackStatus.textContent = payload.status === "captured_external"
              ? "Feedback captured as an external review signal. Sign in to make it part of your ranking profile."
              : "Feedback captured.";
          }} catch (error) {{
            feedbackSubmitButton.disabled = false;
            feedbackStatus.textContent = "Could not save feedback right now.";
          }}
        }});
      }}
      filterButtons.forEach((button) => {{
        button.addEventListener("click", async () => {{
          const filterKey = String(button.dataset.filterKey || "");
          if (!filterKey || !filterStatus) return;
          filterStatus.textContent = "Open the authenticated PropertyQuarry workspace to change profile filters.";
        }});
      }});
      if (requestButton && requestStatus) {{
        requestButton.addEventListener("click", async () => {{
          requestStatus.textContent = "Open the authenticated PropertyQuarry review packet to request deeper research.";
        }});
      }}
    </script>
  </body>
</html>"""
    pure_decision_rows_html = "".join(
        f'<div class="stat"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'
        for label, value in decision_rows
    )
    pure_reasons_html = "".join(f"<li>{html.escape(item)}</li>" for item in (highlight_lines or ["No strong positive pattern match is clear yet."]))
    pure_risks_html = "".join(f"<li>{html.escape(item)}</li>" for item in (concern_lines or ["No concrete downside has been stored yet."]))
    pure_unknowns_html = "".join(f"<li>{html.escape(item)}</li>" for item in (unknown_lines or ["No explicit follow-up question is stored yet."]))
    pure_feedback_panel = ""
    if bool(payload.get("_feedback_enabled")) or str(payload.get("principal_id") or "").strip():
        pure_feedback_panel = (
            '<section class="card decision-card">'
            '<div class="eyebrow">Preference Feedback</div>'
            '<h2>Teach the system what to rank higher or lower</h2>'
            '<p class="sub">Give a quick reaction and mark concrete reasons. Public-link feedback is captured as an external signal; sign in to apply it to a ranking profile.</p>'
            '<button class="btn" type="button">Save feedback</button>'
            '</section>'
        )
    pure_shortlist_items = [dict(row) for row in list(shortlist_compare.get("items") or []) if isinstance(row, dict)]
    pure_shortlist_current = dict(shortlist_compare.get("current") or {}) if isinstance(shortlist_compare.get("current"), dict) else {}
    pure_shortlist_rows = ([pure_shortlist_current] if pure_shortlist_current else []) + pure_shortlist_items
    pure_shortlist_cards = "".join(
        (
            '<div class="stat">'
            f'<span>Fit {int(round(float(row.get("score") or 0.0))):d}/100</span>'
            f'<strong>{html.escape(str(row.get("title") or "Property").strip())}</strong>'
            f'<p>{html.escape(str(row.get("why_now") or "No comparison note stored.").strip())}</p>'
            f'<p><span class="shortlist-delta-better">shortlist upside</span> <span class="shortlist-delta-worse">shortlist trade-off</span></p>'
            + ''.join(
                f'<p><b>{html.escape(label)}:</b> {html.escape(_shortlist_metric_display(key, dict(row.get("metrics") or {}).get(key)))}</p>'
                for key, label, _direction in _shortlist_metric_labels()
                if key in dict(row.get("metrics") or {})
            )
            + '</div>'
        )
        for row in pure_shortlist_rows[:3]
    )
    pure_shortlist_panel = (
        '<section class="card decision-card">'
        '<div class="eyebrow">Shortlist Compare</div>'
        '<h2>Current property against active shortlist items</h2>'
        f'<div class="stat-grid">{pure_shortlist_cards or "<div class=\"stat\"><span>Shortlist</span><strong>No shortlist loaded</strong></div>"}</div>'
        '</section>'
    )
    pure_distance_html = "".join(
        f'<div class="stat"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'
        for label, value in distance_rows
    )
    pure_decision_panel = (
        '<section class="card decision-card">'
        '<div class="eyebrow">Decision Summary</div>'
        '<h2>Decision Summary</h2>'
        f'<div class="stat-grid">{pure_decision_rows_html}</div>'
        '<div class="decision-grid">'
        '<div><h3>Why it fits</h3><ul>' + pure_reasons_html + '</ul></div>'
        '<div><h3>Decision pressure</h3><ul>' + pure_risks_html + '</ul></div>'
        '<div><h3>Still missing</h3><ul>' + pure_unknowns_html + '</ul></div>'
        '</div>'
        + (f'<h2>Daily-life access</h2><div class="stat-grid">{pure_distance_html}</div>' if pure_distance_html else '')
        + (f'<p class="sub">{html.escape(completed_research_line)}</p>' if completed_research_line else '')
        + '</section>'
    )
    if is_pure_360_cube:
        return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title_html}</title>
    {clickrank_head_snippet(hostname)}
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@photo-sphere-viewer/core/index.min.css">
    <style>
      :root {{
        --bg: #f5efe3;
        --panel: rgba(255,255,255,0.82);
        --ink: #1f1c18;
        --muted: #6f665a;
        --line: rgba(31,28,24,0.12);
        --accent: #1f5f51;
        --accent-soft: rgba(31,95,81,0.10);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--ink);
        font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
        background:
          radial-gradient(circle at top left, rgba(31,95,81,0.14), transparent 32%),
          radial-gradient(circle at bottom right, rgba(183,132,40,0.16), transparent 28%),
          linear-gradient(160deg, #f8f4ec 0%, #efe8db 100%);
      }}
      .shell {{
        max-width: 1380px;
        margin: 0 auto;
        padding: 24px;
      }}
      .hero {{
        display: grid;
        grid-template-columns: 1.25fr 0.75fr;
        gap: 18px;
        align-items: start;
      }}
      .card {{
        border-radius: 28px;
        border: 1px solid var(--line);
        background: var(--panel);
        backdrop-filter: blur(14px);
        box-shadow: 0 18px 48px rgba(31,28,24,0.08);
      }}
      .hero-main {{ padding: 28px; }}
      .hero-side {{ padding: 22px; }}
      .eyebrow {{
        display: inline-flex;
        gap: 10px;
        align-items: center;
        font-size: 12px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      h1 {{
        margin: 14px 0 10px;
        font-size: clamp(2rem, 4vw, 4rem);
        line-height: 0.95;
      }}
      .sub {{
        margin: 0;
        color: var(--muted);
        line-height: 1.55;
        max-width: 66ch;
      }}
      .actions {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 20px;
      }}
      .btn {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 44px;
        padding: 0 18px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: rgba(255,255,255,0.72);
        color: var(--ink);
        text-decoration: none;
        cursor: pointer;
      }}
      .btn.primary {{
        background: var(--ink);
        color: #fff9f0;
        border-color: transparent;
      }}
      .stack {{
        display: grid;
        gap: 12px;
      }}
      .kv {{
        padding: 12px 14px;
        border-radius: 18px;
        background: rgba(255,255,255,0.68);
        border: 1px solid rgba(31,28,24,0.08);
      }}
      .kv b {{
        display: block;
        margin-bottom: 4px;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        color: var(--muted);
      }}
      .stage {{
        margin-top: 18px;
        display: grid;
        gap: 18px;
      }}
      .decision-card {{
        padding: 22px;
      }}
      .decision-card h2 {{
        margin: 8px 0 14px;
      }}
      .decision-grid, .stat-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
      }}
      .decision-grid {{
        margin-top: 16px;
      }}
      .decision-grid h3 {{
        margin: 0 0 8px;
      }}
      .decision-grid ul {{
        margin: 0;
        padding-left: 18px;
        color: var(--muted);
        line-height: 1.5;
      }}
      .stat {{
        padding: 12px 14px;
        border-radius: 18px;
        background: rgba(255,255,255,0.68);
        border: 1px solid rgba(31,28,24,0.08);
      }}
      .stat span {{
        display: block;
        margin-bottom: 4px;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        color: var(--muted);
      }}
      .stat strong {{
        display: block;
      }}
      .stat p {{
        margin: 6px 0 0;
        color: var(--muted);
        line-height: 1.45;
      }}
      .toolbar {{
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
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
        border: 1px solid var(--line);
        background: rgba(255,255,255,0.74);
        color: var(--ink);
        cursor: pointer;
      }}
      .toggle button.active {{
        background: var(--ink);
        color: #fff8ef;
        border-color: var(--ink);
      }}
      .toggle button:disabled {{
        opacity: .4;
        cursor: not-allowed;
      }}
      .stage-grid {{
        display: grid;
        grid-template-columns: minmax(0, 1.22fr) minmax(320px, 0.78fr);
        gap: 18px;
      }}
      .viewer-shell {{
        padding: 16px;
      }}
      .pane {{ display: none; }}
      .pane.active {{ display: block; }}
      #cube {{
        min-height: 72vh;
        height: 72vh;
        border-radius: 24px;
        overflow: hidden;
        background: #111;
        border: 1px solid rgba(31,28,24,0.14);
      }}
      .viewer-empty {{
        min-height: 72vh;
        height: 72vh;
        display: grid;
        place-items: center;
        padding: 28px;
        text-align: center;
        color: #fff8ef;
        background: radial-gradient(circle at top, rgba(31,95,81,0.42), rgba(12,12,12,0.94));
      }}
      .viewer-empty strong {{
        display: block;
        margin-bottom: 10px;
        font-size: 1.1rem;
      }}
      .viewer-empty p {{
        max-width: 32rem;
        margin: 0 auto 16px;
        line-height: 1.55;
        color: rgba(255,248,239,0.82);
      }}
      .viewer-empty button {{
        min-height: 40px;
        padding: 0 14px;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.18);
        background: rgba(255,255,255,0.10);
        color: #fff8ef;
        cursor: pointer;
      }}
      .overview-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
      }}
      .overview-card {{
        padding: 16px;
        border-radius: 22px;
        border: 1px solid rgba(31,28,24,0.09);
        background: rgba(255,255,255,0.74);
      }}
      .overview-card strong {{
        display: block;
        margin-bottom: 8px;
      }}
      .overview-card p {{
        margin: 0 0 14px;
        color: var(--muted);
        line-height: 1.5;
      }}
      .overview-card button {{
        min-height: 38px;
        padding: 0 14px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: var(--accent-soft);
        color: var(--accent);
        cursor: pointer;
      }}
      .doc-stage {{
        border-radius: 24px;
        overflow: hidden;
        border: 1px solid rgba(31,28,24,0.12);
        background: rgba(255,255,255,0.88);
        min-height: 72vh;
      }}
      .video-stage {{
        border-radius: 24px;
        overflow: hidden;
        border: 1px solid rgba(31,28,24,0.12);
        background: #0f1012;
        min-height: 72vh;
      }}
      .video-stage video {{
        width: 100%;
        height: 72vh;
        min-height: 72vh;
        display: block;
        object-fit: cover;
        background: #0f1012;
      }}
      .doc-stage iframe,
      .doc-stage img {{
        width: 100%;
        height: 72vh;
        min-height: 72vh;
        display: block;
        border: 0;
        background: #fff;
      }}
      .doc-stage img {{
        object-fit: contain;
      }}
      .sidebar {{
        padding: 18px;
        display: grid;
        gap: 14px;
        align-content: start;
      }}
      .section-title {{
        margin: 0;
        font-size: 1rem;
      }}
      .note {{
        margin: 0;
        color: var(--muted);
        line-height: 1.5;
      }}
      .thumbs {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(124px, 1fr));
        gap: 10px;
      }}
      .thumb {{
        position: relative;
        overflow: hidden;
        border-radius: 18px;
        border: 2px solid transparent;
        background: rgba(255,255,255,0.62);
        cursor: pointer;
      }}
      .thumb.active {{ border-color: var(--accent); }}
      .thumb img {{
        width: 100%;
        height: 108px;
        object-fit: cover;
        display: block;
      }}
      .thumb-doc {{
        min-height: 108px;
        display: grid;
        place-items: center;
        background: linear-gradient(135deg, rgba(255,255,255,0.95), rgba(240,233,218,0.92));
        color: var(--ink);
        font-weight: 800;
        letter-spacing: 0.08em;
      }}
      .thumb-badge {{
        position: absolute;
        left: 8px;
        top: 8px;
        padding: 4px 8px;
        border-radius: 999px;
        background: rgba(14,14,13,0.72);
        color: #fffaf2;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }}
      .scene-list {{
        display: grid;
        gap: 8px;
      }}
      .brief-list {{
        margin: 0;
        padding-left: 18px;
        color: var(--muted);
        line-height: 1.5;
      }}
      .brief-list li + li {{
        margin-top: 6px;
      }}
      .scene-row {{
        display: flex;
        gap: 10px;
        align-items: center;
        justify-content: space-between;
        padding: 10px 12px;
        border-radius: 16px;
        border: 1px solid rgba(31,28,24,0.08);
        background: rgba(255,255,255,0.68);
      }}
      .scene-row.active {{
        background: rgba(31,95,81,0.10);
        border-color: rgba(31,95,81,0.28);
      }}
      .scene-row button {{
        min-height: 34px;
        padding: 0 12px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: #fff;
        cursor: pointer;
      }}
      .status-pill {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        border-radius: 999px;
        background: rgba(255,255,255,0.74);
        border: 1px solid var(--line);
        color: var(--muted);
      }}
      .plan-preview {{
        border-radius: 20px;
        overflow: hidden;
        border: 1px solid rgba(31,28,24,0.1);
        background: rgba(255,255,255,0.84);
      }}
      .plan-preview img {{
        width: 100%;
        height: 148px;
        object-fit: cover;
        display: block;
        background: #fff;
      }}
      .plan-preview-doc {{
        min-height: 148px;
        display: grid;
        place-items: center;
        background: linear-gradient(135deg, rgba(255,255,255,0.97), rgba(240,233,218,0.92));
        color: var(--ink);
        font-weight: 800;
        letter-spacing: 0.08em;
      }}
      .plan-preview-copy {{
        padding: 12px 14px 14px;
        display: grid;
        gap: 8px;
      }}
      .plan-preview-copy strong {{
        display: block;
      }}
      .plan-preview-copy button {{
        min-height: 38px;
        padding: 0 14px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: var(--accent-soft);
        color: var(--accent);
        cursor: pointer;
      }}
      @media (max-width: 1040px) {{
        .hero, .stage-grid {{ grid-template-columns: 1fr; }}
      }}
      @media (max-width: 640px) {{
        .shell {{ padding: 14px; }}
        .card {{ border-radius: 22px; }}
        #cube, .doc-stage, .doc-stage iframe, .doc-stage img, .video-stage, .video-stage video {{
          min-height: 56vh;
          height: 56vh;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="shell">
      <section class="hero">
        <div class="card hero-main">
          <div class="eyebrow">PropertyQuarry <span>•</span> Hosted 360</div>
          <h1>{title_html}</h1>
          <p class="sub">A white-label 360 review with an actual panorama viewer, a clear scene overview, and floorplan access on the same surface. Pure 360 hosted on {hosted_brand_html}.</p>
          <div class="actions">
            <a class="btn primary" href="#panorama-pane">Open panorama</a>
            {listing_link}
          </div>
        </div>
        <aside class="card hero-side">
          <div class="stack">
            <div class="kv"><b>Hosted by</b>{hosted_brand_html}</div>
            <div class="kv"><b>Location</b>{address or district or 'Location under review'}</div>
            <div class="kv"><b>Scenes</b>{html.escape(str(len([scene for scene in scene_data if scene.get('cube_faces')])))} panorama positions</div>
            <div class="kv"><b>Floorplans</b>{html.escape(str(len([scene for scene in scene_data if str(scene.get('role') or '') == 'floorplan'])))} attached documents</div>
            <div class="kv"><b>Review mode</b>Panorama first, then layout and packet review.</div>
          </div>
        </aside>
      </section>
      <section class="stage">
        {pure_decision_panel}
        {pure_feedback_panel}
        {pure_shortlist_panel}
      </section>
      <section class="stage">
        <div class="toolbar">
          <div class="toggle" id="mode-toggle">
            <button type="button" class="active" data-pane="panorama-pane">Panorama</button>
            <button type="button" data-pane="overview-pane">Overview</button>
            <button type="button" data-pane="floorplan-pane">Floorplans</button>
            {"<button type=\"button\" data-pane=\"flythrough-pane\">Flythrough</button>" if video_url else ""}
          </div>
          <div class="status-pill" id="tour-status">Hosted white-label 360 review</div>
        </div>
        <div class="stage-grid">
          <div class="card viewer-shell">
            <section id="panorama-pane" class="pane active">
              <div id="cube"></div>
            </section>
            <section id="overview-pane" class="pane">
              <div class="overview-grid" id="overview-grid"></div>
            </section>
            <section id="floorplan-pane" class="pane">
              <div class="doc-stage" id="floorplan-stage">
                <img id="floorplan-image" alt="Floorplan preview" hidden referrerpolicy="no-referrer">
                <iframe id="floorplan-frame" title="Floorplan document" hidden referrerpolicy="no-referrer"></iframe>
              </div>
            </section>
            {"<section id=\"flythrough-pane\" class=\"pane\"><div class=\"video-stage\"><video id=\"flythrough-video\" controls playsinline preload=\"metadata\"><source src=\"" + html.escape(video_url) + "\" type=\"video/mp4\"></video></div></section>" if video_url else ""}
          </div>
          <aside class="card sidebar">
            <h2 class="section-title">Scene navigation</h2>
            <p class="note">Move through the panorama for spatial feel, validate the circulation on the plan, then return to the packet with a cleaner room-by-room read.</p>
            <h2 class="section-title">Review route</h2>
            <ol class="brief-list">
              <li>Open the main panorama and get the room proportions.</li>
              <li>Switch to the floorplan to validate doors, walls, and usable edges.</li>
              <li>Return to the dossier for risks, questions, and decision context.</li>
            </ol>
            <div class="actions">
              <button class="btn" id="prev-link" type="button">Previous</button>
              <button class="btn" id="next-link" type="button">Next</button>
              {"<button class=\"btn\" id=\"open-flythrough\" type=\"button\">Play flythrough</button>" if video_url else ""}
            </div>
            <div class="scene-list" id="scene-list"></div>
            <h2 class="section-title">Layout preview</h2>
            <div id="layout-preview" class="plan-preview">
              <div class="plan-preview-doc">No plan</div>
              <div class="plan-preview-copy">
                <strong>Layout preview unavailable</strong>
                <p class="note">This tour currently has no stored floorplan document.</p>
              </div>
            </div>
            <h2 class="section-title">Media deck</h2>
            <div class="thumbs" id="thumbs"></div>
          </aside>
        </div>
      </section>
    </div>
    <script id="scene-data" type="application/json">{data_json}</script>
    <script type="importmap">
      {{
        "imports": {{
          "three": "https://cdn.jsdelivr.net/npm/three/build/three.module.js",
          "@photo-sphere-viewer/core": "https://cdn.jsdelivr.net/npm/@photo-sphere-viewer/core/index.module.js",
          "@photo-sphere-viewer/cubemap-adapter": "https://cdn.jsdelivr.net/npm/@photo-sphere-viewer/cubemap-adapter/index.module.js"
        }}
      }}
    </script>
    <script type="module">
      import {{ Viewer }} from '@photo-sphere-viewer/core';
      import {{ CubemapAdapter }} from '@photo-sphere-viewer/cubemap-adapter';

      const sceneData = JSON.parse(document.getElementById("scene-data").textContent);
      const panoramaScenes = sceneData.filter((scene) => scene.cube_faces && scene.cube_faces.f);
      const floorplanScenes = sceneData.filter((scene) => String(scene.role || "").trim() === "floorplan");
      const thumbs = document.getElementById("thumbs");
      const sceneList = document.getElementById("scene-list");
      const overviewGrid = document.getElementById("overview-grid");
      const floorplanImage = document.getElementById("floorplan-image");
      const floorplanFrame = document.getElementById("floorplan-frame");
      const layoutPreview = document.getElementById("layout-preview");
      const flythroughVideo = document.getElementById("flythrough-video");
      const modeButtons = [...document.querySelectorAll('#mode-toggle button[data-pane]')];
      const panes = [...document.querySelectorAll('.pane')];
      const floorplanButton = modeButtons.find((button) => button.dataset.pane === 'floorplan-pane');
      if (floorplanButton && floorplanScenes.length === 0) {{
        floorplanButton.disabled = true;
      }}
      let activePanorama = 0;
      let activeFloorplan = 0;
      const viewerContainer = document.querySelector('#cube');
      let viewer = null;

      function showPanoramaFallback(message) {{
        if (!viewerContainer) return;
        viewerContainer.innerHTML = `
          <div class="viewer-empty">
            <div>
              <strong>Panorama preview unavailable on this device right now</strong>
              <p>${{message || 'Use the overview and floorplan tabs to keep the layout review moving, then reopen the panorama after the connection or browser stabilizes.'}}</p>
              <button type="button" id="panorama-fallback-overview">Open overview instead</button>
            </div>
          </div>
        `;
        const fallbackButton = document.getElementById('panorama-fallback-overview');
        if (fallbackButton) {{
          fallbackButton.addEventListener('click', () => switchPane(floorplanScenes.length ? 'floorplan-pane' : 'overview-pane'));
        }}
        if (panoramaScenes.length) {{
          document.getElementById('tour-status').textContent = 'Panorama unavailable · using white-label fallback';
        }}
      }}

      if (panoramaScenes.length) {{
        try {{
          viewer = new Viewer({{
            container: viewerContainer,
            adapter: CubemapAdapter,
            navbar: ['zoom', 'move', 'fullscreen'],
            mousewheel: true,
            touchmoveTwoFingers: false,
            defaultZoomLvl: 42,
            panorama: {{
              left: panoramaScenes[0].cube_faces.l,
              front: panoramaScenes[0].cube_faces.f,
              right: panoramaScenes[0].cube_faces.r,
              back: panoramaScenes[0].cube_faces.b,
              top: panoramaScenes[0].cube_faces.u,
              bottom: panoramaScenes[0].cube_faces.d,
            }},
          }});
        }} catch (error) {{
          console.error('PropertyQuarry panorama init failed', error);
          showPanoramaFallback('The white-label panorama viewer could not initialize here. The overview and floorplan lanes stay available so the dossier remains usable on mobile.');
        }}
      }}

      function switchPane(name) {{
        panes.forEach((pane) => pane.classList.toggle('active', pane.id === name));
        modeButtons.forEach((button) => button.classList.toggle('active', button.dataset.pane === name));
        if (name === 'flythrough-pane') {{
          document.getElementById('tour-status').textContent = 'Flythrough · interior route';
        }} else if (name === 'floorplan-pane' && floorplanScenes.length) {{
          document.getElementById('tour-status').textContent = `Floorplan · ${{floorplanScenes[activeFloorplan]?.name || `Plan ${{activeFloorplan + 1}}`}}`;
        }}
      }}

      async function autoplayFlythrough() {{
        if (!flythroughVideo || typeof flythroughVideo.play !== 'function') return;
        flythroughVideo.muted = true;
        flythroughVideo.autoplay = true;
        try {{
          await flythroughVideo.play();
        }} catch (_error) {{
          flythroughVideo.controls = true;
        }}
      }}

      function setPanoramaScene(index) {{
        if (!panoramaScenes.length || !viewer) return;
        activePanorama = ((index % panoramaScenes.length) + panoramaScenes.length) % panoramaScenes.length;
        const scene = panoramaScenes[activePanorama];
        try {{
          viewer.setPanorama({{
            left: scene.cube_faces.l,
            front: scene.cube_faces.f,
            right: scene.cube_faces.r,
            back: scene.cube_faces.b,
            top: scene.cube_faces.u,
            bottom: scene.cube_faces.d,
          }});
        }} catch (error) {{
          console.error('PropertyQuarry panorama scene switch failed', error);
          showPanoramaFallback('This panorama scene could not be rendered cleanly on the current device. Use the scene overview or floorplan lane for the layout-first review.');
          switchPane(floorplanScenes.length ? 'floorplan-pane' : 'overview-pane');
          return;
        }}
        [...sceneList.children].forEach((node, sceneIndex) => node.classList.toggle('active', sceneIndex === activePanorama));
        [...thumbs.children].forEach((node) => {{
          const role = String(node.dataset.role || '');
          const sceneIndex = Number.parseInt(String(node.dataset.index || '-1'), 10);
          node.classList.toggle('active', role === 'pure_360' && sceneIndex === activePanorama);
        }});
        const target = new URL(window.location.href);
        const sceneId = scene.scene_id || String(activePanorama + 1);
        if (sceneId && sceneId !== '1') target.searchParams.set('scene', sceneId);
        else target.searchParams.delete('scene');
        target.hash = '';
        history.replaceState({{}}, '', target.pathname + (target.search || ''));
        document.getElementById('tour-status').textContent = `Panorama · ${{scene.name || `Scene ${{activePanorama + 1}}`}}`;
      }}

      function setFloorplan(index) {{
        if (!floorplanScenes.length) return;
        activeFloorplan = ((index % floorplanScenes.length) + floorplanScenes.length) % floorplanScenes.length;
        const scene = floorplanScenes[activeFloorplan];
        const url = String(scene.image_url || '');
        const isPdf = String(scene.mime_type || '').includes('pdf') || /\\.pdf(?:$|[?#])/i.test(url);
        if (isPdf) {{
          floorplanImage.hidden = true;
          floorplanFrame.hidden = false;
          floorplanFrame.src = url;
        }} else {{
          floorplanFrame.hidden = true;
          floorplanFrame.src = '';
          floorplanImage.hidden = false;
          floorplanImage.src = url;
        }}
        [...thumbs.children].forEach((node) => {{
          const role = String(node.dataset.role || '');
          const sceneIndex = Number.parseInt(String(node.dataset.index || '-1'), 10);
          node.classList.toggle('active', role === 'floorplan' && sceneIndex === activeFloorplan);
        }});
      }}

      function renderLayoutPreview() {{
        if (!layoutPreview) return;
        if (!floorplanScenes.length) {{
          layoutPreview.innerHTML = `
            <div class="plan-preview-doc">No plan</div>
            <div class="plan-preview-copy">
              <strong>Layout preview unavailable</strong>
              <p class="note">This tour currently has no stored floorplan document.</p>
            </div>
          `;
          return;
        }}
        const scene = floorplanScenes[0];
        const url = String(scene.image_url || '');
        const isPdf = String(scene.mime_type || '').includes('pdf') || /\\.pdf(?:$|[?#])/i.test(url);
        layoutPreview.innerHTML = isPdf
          ? `
              <div class="plan-preview-doc">PDF</div>
              <div class="plan-preview-copy">
                <strong>${{scene.name || 'Attached floorplan'}}</strong>
                <p class="note">Open the plan sheet to validate room flow, circulation, and usable edges.</p>
                <button type="button" id="layout-preview-open">Open floorplan</button>
              </div>
            `
          : `
              <img src="${{url}}" alt="${{scene.name || 'Floorplan preview'}}" referrerpolicy="no-referrer">
              <div class="plan-preview-copy">
                <strong>${{scene.name || 'Attached floorplan'}}</strong>
                <p class="note">Use the layout image as a quick map while reading the panorama.</p>
                <button type="button" id="layout-preview-open">Open floorplan</button>
              </div>
            `;
        const openButton = document.getElementById('layout-preview-open');
        if (openButton) {{
          openButton.addEventListener('click', () => {{
            switchPane('floorplan-pane');
            setFloorplan(0);
          }});
        }}
      }}

      modeButtons.forEach((button) => {{
        button.addEventListener('click', () => {{
          if (button.disabled) return;
          switchPane(String(button.dataset.pane || 'panorama-pane'));
        }});
      }});

      document.getElementById('prev-link').addEventListener('click', () => setPanoramaScene(activePanorama - 1));
      document.getElementById('next-link').addEventListener('click', () => setPanoramaScene(activePanorama + 1));
      const openFlythrough = document.getElementById('open-flythrough');
      if (openFlythrough) {{
        openFlythrough.addEventListener('click', () => {{
          switchPane('flythrough-pane');
          if (flythroughVideo && typeof flythroughVideo.play === 'function') {{
            flythroughVideo.play().catch(() => null);
          }}
        }});
      }}
      window.addEventListener('keydown', (event) => {{
        if (event.key === 'ArrowLeft') setPanoramaScene(activePanorama - 1);
        if (event.key === 'ArrowRight') setPanoramaScene(activePanorama + 1);
      }});

      panoramaScenes.forEach((scene, index) => {{
        const row = document.createElement('div');
        row.className = 'scene-row';
        row.innerHTML = `
          <div>
            <strong>${{scene.name || `Scene ${{index + 1}}`}}</strong>
            <div class="note">Panorama position ${{index + 1}}</div>
          </div>
          <button type="button">Open</button>
        `;
        row.querySelector('button').addEventListener('click', () => {{
          switchPane('panorama-pane');
          setPanoramaScene(index);
        }});
        sceneList.appendChild(row);

        const card = document.createElement('article');
        card.className = 'overview-card';
        card.innerHTML = `
          <strong>${{scene.name || `Scene ${{index + 1}}`}}</strong>
          <p>Use this viewpoint for the spatial read before switching into the packet and floorplan review.</p>
          <button type="button">View panorama</button>
        `;
        card.querySelector('button').addEventListener('click', () => {{
          switchPane('panorama-pane');
          setPanoramaScene(index);
        }});
        overviewGrid.appendChild(card);

        const thumb = document.createElement('button');
        thumb.type = 'button';
        thumb.className = 'thumb';
        thumb.dataset.role = 'pure_360';
        thumb.dataset.index = String(index);
        thumb.innerHTML = `<span class="thumb-badge">360</span><img src="${{scene.image_url || scene.cube_faces.f}}" alt="${{scene.name || `Scene ${{index + 1}}`}}" referrerpolicy="no-referrer">`;
        thumb.addEventListener('click', () => {{
          switchPane('panorama-pane');
          setPanoramaScene(index);
        }});
        thumbs.appendChild(thumb);
      }});

      floorplanScenes.forEach((scene, index) => {{
        const thumb = document.createElement('button');
        thumb.type = 'button';
        thumb.className = 'thumb';
        thumb.dataset.role = 'floorplan';
        thumb.dataset.index = String(index);
        const isPdf = String(scene.mime_type || '').includes('pdf') || /\\.pdf(?:$|[?#])/i.test(String(scene.image_url || ''));
        thumb.innerHTML = isPdf
          ? `<span class="thumb-badge">Plan</span><div class="thumb-doc">PDF</div>`
          : `<span class="thumb-badge">Plan</span><img src="${{scene.image_url || ''}}" alt="${{scene.name || `Floorplan ${{index + 1}}`}}" referrerpolicy="no-referrer">`;
        thumb.addEventListener('click', () => {{
          switchPane('floorplan-pane');
          setFloorplan(index);
        }});
        thumbs.appendChild(thumb);

        const card = document.createElement('article');
        card.className = 'overview-card';
        card.innerHTML = `
          <strong>${{scene.name || `Floorplan ${{index + 1}}`}}</strong>
          <p>Use the layout sheet to validate room flow, circulation, and usable edges before a viewing.</p>
          <button type="button">Open floorplan</button>
        `;
        card.querySelector('button').addEventListener('click', () => {{
          switchPane('floorplan-pane');
          setFloorplan(index);
        }});
        overviewGrid.appendChild(card);
      }});

      const initialParams = new URLSearchParams(window.location.search);
      const initialScene = initialParams.get('scene');
      const initialPane = initialParams.get('pane');
      const initialAutoplay = initialParams.get('autoplay');
      const initialSceneIndex = panoramaScenes.findIndex((scene) => String(scene.scene_id || '').trim() === String(initialScene || '').trim());
      if (panoramaScenes.length && viewer) {{
        setPanoramaScene(initialSceneIndex >= 0 ? initialSceneIndex : 0);
      }} else if (panoramaScenes.length) {{
        showPanoramaFallback('The white-label panorama viewer is currently unavailable here. Use the overview and floorplan lanes while the 3D scene is unavailable.');
      }} else {{
        document.getElementById('tour-status').textContent = 'No panorama scenes stored';
      }}
      if (floorplanScenes.length) {{
        setFloorplan(0);
      }}
      renderLayoutPreview();
      if (initialPane === 'flythrough-pane' && flythroughVideo) {{
        switchPane('flythrough-pane');
        if (initialAutoplay === '1') {{
          autoplayFlythrough();
        }}
      }} else if (initialPane === 'floorplan-pane' && floorplanScenes.length) {{
        switchPane('floorplan-pane');
      }} else if (initialPane === 'overview-pane') {{
        switchPane('overview-pane');
      }}
    </script>
  </body>
</html>"""
    generated_viewer_disclosure = _public_tour_safe_display_text(
        payload.get("_tour_media_disclosure"),
        fallback="Generated interactive reconstruction — not a provider-captured scan.",
        limit=360,
    )
    generated_viewer_shell = (
        f'''
        <section id="generated-3d-viewer" class="live-shell generated-viewer-shell">
          <div class="live-head">
            <div>
              <div class="eyebrow">{brand_html} <span>•</span> Released interactive reconstruction</div>
              <h2>Walk the reconstructed layout</h2>
              <p id="generated-viewer-disclosure" class="sub">{html.escape(generated_viewer_disclosure)}</p>
            </div>
            <div class="stack">
              <div class="kv"><b>Controls</b>Drag to orbit, scroll or pinch to zoom, and use the room route to move through the layout.</div>
              <div class="kv"><b>Evidence boundary</b>Use this spatial aid alongside the source photos and floorplan; confirm dimensions and finishes in person.</div>
            </div>
          </div>
          <div class="live-frame-wrap">
            <iframe
              id="generated-tour-viewer"
              class="live-frame"
              src="{html.escape(generated_viewer_url)}"
              title="{title_html} interactive generated 3D reconstruction"
              aria-describedby="generated-viewer-disclosure"
              sandbox="allow-scripts"
              loading="eager"
              allowfullscreen
              referrerpolicy="no-referrer"
            ></iframe>
          </div>
        </section>'''
        if generated_viewer_url
        else ""
    )
    live_shell = (
        f'''
        <section id="live-360" class="live-shell">
          <div class="live-head">
            <div>
              <div class="eyebrow">{brand_html} <span>•</span> Live 360</div>
              <h2>Live Panorama Viewer</h2>
              <p class="sub">This verified external panorama remains visibly framed by {brand_html}. Opening it shares normal browser request metadata with {html.escape(str(payload.get("_released_embed_origin") or "the reviewed provider origin"))}.</p>
            </div>
            <div class="stack">
              <div class="kv"><b>Brand</b>{brand_html}</div>
              <div class="kv"><b>Experience</b>External panorama in a constrained viewer</div>
            </div>
          </div>
          <div class="live-frame-wrap">
            <iframe
              class="live-frame"
              src="{html.escape(source_virtual_tour_url)}"
              title="{title_html} live 360 viewer"
              loading="lazy"
              sandbox="allow-scripts allow-same-origin allow-forms allow-presentation"
              allow="fullscreen; autoplay"
              allowfullscreen
              referrerpolicy="no-referrer"
            ></iframe>
          </div>
        </section>'''
        if source_virtual_tour_url
        else ""
    )
    legacy_decision_rows_html = "".join(
        f'<div class="kv"><b>{html.escape(label)}</b>{html.escape(value)}</div>'
        for label, value in decision_rows
    )
    legacy_reasons_html = "".join(f"<li>{html.escape(item)}</li>" for item in (highlight_lines or ["No strong positive pattern match is clear yet."]))
    legacy_risks_html = "".join(f"<li>{html.escape(item)}</li>" for item in (concern_lines or ["No concrete downside has been stored yet."]))
    legacy_unknowns_html = "".join(f"<li>{html.escape(item)}</li>" for item in (unknown_lines or ["No explicit follow-up question is stored yet."]))
    feedback_negative = [dict(row) for row in list(feedback_suggestions.get("negative") or []) if isinstance(row, dict)]
    feedback_positive = [dict(row) for row in list(feedback_suggestions.get("positive") or []) if isinstance(row, dict)]
    legacy_feedback_chips = "".join(
        f'<span class="chip">{html.escape(str(row.get("label") or row.get("key") or "").strip())}</span>'
        for row in [*feedback_negative[:4], *feedback_positive[:4]]
        if str(row.get("label") or row.get("key") or "").strip()
    )
    legacy_feedback_panel = ""
    if bool(payload.get("_feedback_enabled")) or str(payload.get("principal_id") or "").strip():
        legacy_feedback_panel = (
            '<section class="panel">'
            '<div class="eyebrow">Preference Feedback</div>'
            '<h2>Teach the system what to rank higher or lower</h2>'
            '<p class="sub">Give a quick reaction and mark concrete reasons. Public-link feedback is captured as an external signal; sign in to apply it to a ranking profile.</p>'
            f'<div class="facts">{legacy_feedback_chips or "<span class=\"chip\">No structured feedback chips yet</span>"}</div>'
            '</section>'
        )
    legacy_shortlist_items = [dict(row) for row in list(shortlist_compare.get("items") or []) if isinstance(row, dict)]
    legacy_shortlist_current = dict(shortlist_compare.get("current") or {}) if isinstance(shortlist_compare.get("current"), dict) else {}
    legacy_shortlist_rows = ([legacy_shortlist_current] if legacy_shortlist_current else []) + legacy_shortlist_items
    legacy_shortlist_cards = "".join(
        (
            '<div class="kv">'
            f'<b>{html.escape(str(row.get("title") or "Property").strip())}</b>'
            f'{html.escape(str(row.get("why_now") or row.get("score_label") or "No comparison note stored.").strip())}'
            '</div>'
        )
        for row in legacy_shortlist_rows[:3]
    )
    legacy_shortlist_panel = (
        '<section class="panel">'
        '<div class="eyebrow">Shortlist Compare</div>'
        '<h2>Current property against active shortlist items</h2>'
        f'<div class="stack">{legacy_shortlist_cards or "<div class=\"kv\"><b>No shortlist loaded</b>No other active shortlist property is currently available for side-by-side comparison.</div>"}</div>'
        '</section>'
    )
    legacy_decision_panel = (
        '<section class="panel">'
        '<div class="eyebrow">Decision Summary</div>'
        '<h2>Decision Summary</h2>'
        f'<div class="stack">{legacy_decision_rows_html}</div>'
        '<div class="stage">'
        '<div class="panel"><h2>Why it fits</h2><ul>' + legacy_reasons_html + '</ul></div>'
        '<div class="panel"><h2>Decision pressure</h2><ul>' + legacy_risks_html + '</ul></div>'
        '<div class="panel"><h2>Still missing</h2><ul>' + legacy_unknowns_html + '</ul></div>'
        '</div>'
        '</section>'
    )
    clickrank_html = clickrank_head_snippet(hostname)
    rybbit_html = rybbit_head_snippet(rybbit_hostname or hostname)
    return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title_html}</title>
    {clickrank_html}
    {rybbit_html}
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
      .viewer img,
      .viewer iframe {{
        width: 100%;
        height: 72vh;
        max-height: 760px;
        min-height: 420px;
        display: block;
        border: 0;
      }}
      .viewer img {{
        object-fit: contain;
      }}
      .viewer iframe {{
        background: #fff;
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
      .thumb-doc {{
        min-height: 104px;
        display: grid;
        place-items: center;
        color: var(--ink);
        font-weight: 800;
        letter-spacing: 0.08em;
        background: linear-gradient(135deg, rgba(255,255,255,0.94), rgba(241,231,214,0.86));
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
            {rooms_legacy_chip_html}
            {area_legacy_chip_html}
            {rent_legacy_chip_html}
            {availability_legacy_chip_html}
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
        {legacy_decision_panel}
        {legacy_feedback_panel}
        {legacy_shortlist_panel}
      </section>
      <section class="stage">
        {generated_viewer_shell}
        {live_shell}
        {(
            f'''<div class="hero-video">
              <video id="tour-video" controls playsinline preload="metadata" poster="{html.escape(scene_data[0]["image_url"])}">
                <source src="{html.escape(video_url)}" type="video/webm">
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
          <img id="stage-image" src="{html.escape(scene_data[0]['image_url'])}" alt="{html.escape(scene_data[0]['name'])}" referrerpolicy="no-referrer">
          <iframe id="stage-frame" src="" title="{html.escape(scene_data[0]['name'])}" referrerpolicy="no-referrer" hidden></iframe>
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
      const stageFrame = document.getElementById("stage-frame");
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
          const isPdf = String(scene.mime_type || "").includes("pdf") || /\\.pdf(?:$|[?#])/i.test(String(scene.image_url || ""));
          button.innerHTML = isPdf
            ? `<span class="badge">${{scene.role}}</span><span class="thumb-doc">PDF</span>`
            : `<span class="badge">${{scene.role}}</span><img src="${{scene.image_url}}" alt="${{scene.name}}" referrerpolicy="no-referrer">`;
          button.addEventListener("click", () => setActive(index));
          thumbs.appendChild(button);
        }});
      }}
      function setActive(index) {{
        activeIndex = (index + scenes.length) % scenes.length;
        const scene = scenes[activeIndex];
        const isPdf = String(scene.mime_type || "").includes("pdf") || /\\.pdf(?:$|[?#])/i.test(String(scene.image_url || ""));
        if (isPdf) {{
          stageFrame.src = scene.image_url;
          stageFrame.title = scene.name;
          stageFrame.hidden = false;
          stageImage.hidden = true;
        }} else {{
          stageImage.src = scene.image_url;
          stageImage.alt = scene.name;
          stageImage.hidden = false;
          stageFrame.hidden = true;
        }}
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
      setActive(0);
    </script>
  </body>
</html>"""


def _harden_public_tour_html(source: str, payload: dict[str, object]) -> str:
    rendered = str(source or "")
    rendered = rendered.replace('<html lang="de">', '<html lang="en">', 1)
    rendered = rendered.replace('src=""', 'src="about:blank" sandbox=""')
    rendered = rendered.replace(
        "if (initialAutoplay === '1') {",
        "if (initialAutoplay === '1' && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {",
    )
    keyboard_guard = (
        "if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || "
        "(event.target && event.target.closest('input, textarea, select, button, a, [contenteditable=\"true\"]'))) return;"
    )
    rendered = rendered.replace(
        'document.addEventListener("keydown", (event) => {',
        f'document.addEventListener("keydown", (event) => {{ {keyboard_guard}',
    )
    rendered = rendered.replace(
        "window.addEventListener('keydown', (event) => {",
        f"window.addEventListener('keydown', (event) => {{ {keyboard_guard}",
    )

    common_css = """
      [hidden] { display: none !important; }
      .tour-skip-link {
        position: fixed;
        z-index: 10000;
        left: 16px;
        top: 12px;
        transform: translateY(-160%);
        padding: 10px 14px;
        border-radius: 999px;
        background: #17130f;
        color: #fff;
        font: 700 14px/1.2 ui-sans-serif, system-ui, sans-serif;
      }
      .tour-skip-link:focus { transform: translateY(0); }
      .tour-release-header,
      .tour-release-footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 12px max(20px, calc((100vw - 1340px) / 2 + 22px));
        color: var(--ink);
        background: color-mix(in srgb, var(--panel, #fff) 94%, transparent);
        border-bottom: 1px solid var(--edge, var(--line, rgba(0,0,0,.14)));
        font: 650 13px/1.4 ui-sans-serif, system-ui, sans-serif;
      }
      .tour-release-header nav { display: flex; flex-wrap: wrap; gap: 14px; }
      .tour-release-header a { color: inherit; text-underline-offset: 3px; }
      .tour-release-footer {
        align-items: flex-start;
        border-top: 1px solid var(--edge, var(--line, rgba(0,0,0,.14)));
        border-bottom: 0;
        color: var(--muted, #625b52);
      }
      :where(a, button, textarea, summary, iframe, video, [tabindex]):focus-visible {
        outline: 3px solid var(--accent, #8d3f1f);
        outline-offset: 3px;
      }
      @media (max-width: 640px) {
        .tour-release-header, .tour-release-footer { align-items: flex-start; flex-direction: column; }
      }
      @media (prefers-reduced-motion: reduce) {
        html { scroll-behavior: auto !important; }
        *, *::before, *::after {
          animation-duration: .01ms !important;
          animation-iteration-count: 1 !important;
          transition-duration: .01ms !important;
          scroll-behavior: auto !important;
        }
      }
    """
    rendered = rendered.replace("</style>", f"{common_css}</style>", 1)

    brand = html.escape(str(payload.get("brand_name") or "PropertyQuarry").strip() or "PropertyQuarry")
    disclosure = _public_tour_safe_display_text(
        payload.get("_tour_media_disclosure"),
        fallback="Image and floorplan walkthrough. This surface does not claim a captured 3D scan.",
        limit=360,
    )
    disclosure_html = html.escape(disclosure)
    header = (
        '<a class="tour-skip-link" href="#main-content">Skip to tour</a>'
        '<header class="tour-release-header">'
        f'<strong>{brand}</strong>'
        '<nav aria-label="Tour navigation">'
        '<a href="#main-content">Tour</a>'
        '<a href="#tour-release-notice">Media disclosure</a>'
        '</nav>'
        '</header>'
        '<main id="main-content">'
    )
    rendered = rendered.replace("<body>", f"<body>{header}", 1)

    assistive_script = """
    <script>
      (() => {
        const selectable = '.reaction-btn, .reason-chip, .filter-chip, .toggle button, .thumb, [data-scene-index], [data-role]';
        const syncSelectionState = () => {
          document.querySelectorAll(selectable).forEach((button) => {
            if (!(button instanceof HTMLButtonElement)) return;
            const selected = button.classList.contains('active') || button.classList.contains('selected');
            button.setAttribute('aria-pressed', selected ? 'true' : 'false');
            if (button.classList.contains('thumb') || button.hasAttribute('data-scene-index')) {
              if (selected) button.setAttribute('aria-current', 'true');
              else button.removeAttribute('aria-current');
            }
          });
          document.querySelectorAll('#tour-status, #feedback-status, #filter-status, #request-details-status, .request-status')
            .forEach((node) => {
              node.setAttribute('role', 'status');
              node.setAttribute('aria-live', 'polite');
            });
        };
        syncSelectionState();
        new MutationObserver(syncSelectionState).observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['class']});
        document.addEventListener('visibilitychange', () => {
          if (document.hidden) document.querySelectorAll('video').forEach((video) => video.pause());
        });
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
          document.querySelectorAll('video[autoplay]').forEach((video) => {
            video.autoplay = false;
            video.pause();
          });
        }
      })();
    </script>
    """
    footer = (
        '</main>'
        '<footer id="tour-release-notice" class="tour-release-footer">'
        '<strong>Media disclosure</strong>'
        f'<span>{disclosure_html}</span>'
        '</footer>'
        f'{assistive_script}'
    )
    rendered = rendered.replace("</body>", f"{footer}</body>", 1)
    return rendered


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
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _public_tour_security_headers(
    *,
    cache_control: str = "no-store",
    frame_origins: tuple[str, ...] = (),
) -> dict[str, str]:
    approved_frame_origins: list[str] = []
    for value in frame_origins:
        normalized = str(value or "").strip().rstrip("/")
        parsed = urlparse(normalized)
        try:
            port = parsed.port
        except ValueError:
            continue
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and port in {None, 443}
            and not parsed.path
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
        ):
            approved_frame_origins.append(f"https://{parsed.hostname.lower().rstrip('.')}")
    frame_src = " ".join(["'self'", *sorted(set(approved_frame_origins))])
    return {
        "Cache-Control": cache_control,
        "Content-Security-Policy": (
            "default-src 'self'; "
            "base-uri 'none'; "
            "object-src 'none'; "
            "frame-ancestors 'self'; "
            "form-action 'self'; "
            "img-src 'self' data: https:; "
            "media-src 'self'; "
            f"frame-src {frame_src}; "
            "script-src 'self' 'unsafe-inline' https://js.clickrank.ai https://app.rybbit.io https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "connect-src 'self' https://app.rybbit.io https://cdn.jsdelivr.net"
        ),
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Robots-Tag": "noindex, nofollow, noarchive",
    }


def _public_tour_generated_viewer_headers(
    *,
    role: str,
    sha256: str,
    release_revision: str,
) -> dict[str, str]:
    is_document = role == "viewer_document"
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-store" if is_document else "public, max-age=86400, immutable",
        "Cross-Origin-Resource-Policy": "cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-PropertyQuarry-Asset-SHA256": sha256,
        "X-PropertyQuarry-Viewer-Revision": release_revision,
        "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
    }
    if is_document:
        headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "script-src 'unsafe-inline' 'self'; "
            "style-src 'unsafe-inline'; "
            "img-src 'self' data:; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "form-action 'none'; "
            "frame-ancestors 'self'"
        )
    return headers


@router.get("/tours/{slug}.json", response_class=JSONResponse)
@router.head("/tours/{slug}.json", response_class=JSONResponse)
def public_tour_payload(slug: str) -> JSONResponse:
    payload = _load_tour(slug)
    _require_public_tour_viewable(payload)
    if _tour_payload_is_disabled_fallback(payload):
        raise HTTPException(status_code=404, detail="tour_disabled_fallback")
    return JSONResponse(
        _redacted_public_tour_payload(payload, expose_asset_relpaths=False),
        headers=_public_tour_security_headers(),
    )


@router.get("/tours/files/{slug}/{asset_path:path}")
@router.head("/tours/files/{slug}/{asset_path:path}")
def public_tour_file(slug: str, asset_path: str) -> FileResponse:
    payload = _load_tour(slug)
    safe_relpath = _public_tour_safe_asset_relpath(asset_path)
    manifest_row = _public_tour_manifest(payload, only_relpath=safe_relpath).get(safe_relpath, {}) if safe_relpath else {}
    file_path = _asset_file(slug, asset_path)
    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    headers = _public_tour_security_headers(cache_control="public, max-age=86400, immutable")
    configured_video_relpath = _public_tour_safe_asset_relpath(payload.get("video_relpath"))
    video_release = evaluate_public_tour_video_release(payload) if safe_relpath == configured_video_relpath else {}
    release_sha256 = str(video_release.get("expected_sha256") or "").strip().lower()
    if release_sha256 or manifest_row.get("sha256"):
        headers["X-PropertyQuarry-Asset-SHA256"] = release_sha256 or str(manifest_row["sha256"])
    if video_release.get("release_revision"):
        headers["X-PropertyQuarry-Media-Revision"] = str(video_release["release_revision"])
    if manifest_row.get("privacy_class"):
        headers["X-PropertyQuarry-Asset-Privacy"] = str(manifest_row["privacy_class"])
    return FileResponse(
        file_path,
        media_type=media_type,
        headers=headers,
    )


@router.get("/tours/viewer/{slug}/{asset_path:path}")
@router.head("/tours/viewer/{slug}/{asset_path:path}")
def public_tour_generated_viewer_file(slug: str, asset_path: str) -> FileResponse:
    file_path, binding, release = _generated_viewer_file(slug, asset_path)
    role = str(binding.get("role") or "").strip().lower()
    sha256 = str(binding.get("sha256") or "").strip().lower()
    media_type = str(binding.get("mime_type") or "application/octet-stream").strip().lower()
    return FileResponse(
        file_path,
        media_type=media_type,
        headers=_public_tour_generated_viewer_headers(
            role=role,
            sha256=sha256,
            release_revision=str(release.get("release_revision") or ""),
        ),
    )


@router.post("/tours/{slug}/request-details", response_class=JSONResponse)
async def public_tour_request_details(
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
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raise _public_tour_authenticated_action_required("request-details")


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
    _enforce_public_tour_feedback_rate_limit(request=request, slug=slug, principal_id=principal_id)
    reaction = str(body.get("reaction") or "").strip().lower()
    if reaction not in {"like", "dislike", "maybe", "hide"}:
        raise HTTPException(status_code=422, detail="invalid_tour_feedback_reaction")
    reason_map = _property_feedback_reason_map()
    reason_keys = _public_tour_normalize_reason_keys(
        body.get("reason_keys"),
        allowed=set(reason_map.keys()),
    )
    note = str(body.get("note") or "").strip()
    facts, _ = _merged_facts_with_listing_research(payload, dict(payload.get("facts") or {}))
    facts.pop("public_preference_snapshot", None)
    observation_payload = {
        "slug": slug,
        "property_url": str(payload.get("property_url") or payload.get("listing_url") or "").strip(),
        "property_title": str(payload.get("display_title") or payload.get("title") or "").strip(),
        "reaction": reaction,
        "reason_keys": reason_keys,
        "reason_labels": [_feedback_reason_label(reason_key) for reason_key in reason_keys],
        "note": note[:500],
        "host": request_hostname(request),
        "source": "public_tour_external_feedback",
        "trust": "untrusted_external",
        "facts": dict(facts) if isinstance(facts, dict) else {},
    }
    try:
        container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel="propertyquarry",
            event_type="public_tour_external_feedback",
            payload=observation_payload,
            source_id=f"public-tour:{slug}",
            dedupe_key="",
        )
    except Exception as exc:
        log.exception(
            "public tour feedback persistence failed slug=%s principal_hash=%s reaction=%s",
            slug,
            hashlib.sha256(principal_id.encode("utf-8")).hexdigest()[:16],
            reaction,
        )
        return JSONResponse(
            {
                "status": "not_captured",
                "trust": "untrusted_external",
                "message": "Feedback could not be saved right now. Please retry from the signed-in workspace.",
                "retryable": True,
                "error": "public_tour_feedback_persistence_failed",
            },
            status_code=503,
        )
    return JSONResponse(
        {
            "status": "captured_external",
            "trust": "untrusted_external",
            "message": "Feedback was captured as an external review signal. Sign in to apply it to a ranking profile.",
            "reaction": reaction,
            "reason_keys": reason_keys,
        }
    )


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
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="invalid_tour_filter_payload")
    raise _public_tour_authenticated_action_required("filters")


@router.api_route("/tours/{slug}", methods=["GET", "HEAD"], response_class=HTMLResponse)
def public_tour_page(
    slug: str,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> HTMLResponse:
    hostname = request_hostname(request)
    rybbit_hostname = rybbit_request_hostname(request)
    try:
        payload = _load_tour(slug)
        _require_public_tour_viewable(payload)
        if _tour_payload_is_disabled_fallback(payload):
            raise HTTPException(status_code=404, detail="tour_disabled_fallback")
        rendered_payload = _redacted_public_tour_payload(payload, expose_asset_relpaths=True)
        rendered_facts, research_snapshot = _merged_facts_with_listing_research(payload, dict(payload.get("facts") or {}))
        rendered_facts.pop("public_preference_snapshot", None)
        feedback_context = _live_property_feedback_context(
            container=container,
            payload=payload,
            slug=slug,
        )
        live_feedback_facts = dict(feedback_context.get("facts") or {}) if isinstance(feedback_context.get("facts"), dict) else {}
        if live_feedback_facts:
            rendered_facts.update(live_feedback_facts)
        shortlist_compare = _public_shortlist_comparison_context(
            container=container,
            payload=payload,
            slug=slug,
            facts=rendered_facts,
        )
        rendered_payload["facts"] = _redacted_public_tour_facts(
            payload,
            rendered_facts,
            privacy_mode=str(rendered_payload.get("tour_privacy_mode") or "anonymous_public"),
        )
        rendered_payload["_public_research_completed"] = bool(research_snapshot)
        rendered_payload["_feedback_enabled"] = bool(str(payload.get("principal_id") or "").strip())
        rendered_payload["_feedback_suggestions"] = dict(feedback_context.get("feedback_suggestions") or {})
        rendered_payload["_learning_summary"] = dict(feedback_context.get("learning_summary") or {})
        rendered_payload["_shortlist_compare"] = dict(shortlist_compare or {})
        video_release = evaluate_public_tour_video_release(payload)
        embed_release = evaluate_public_tour_embed_release(payload)
        viewer_release = evaluate_public_tour_generated_viewer_release(payload)
        if video_release.get("released"):
            rendered_payload["_released_video_relpath"] = str(video_release.get("relpath") or "")
        if embed_release.get("released"):
            rendered_payload["_released_embed_url"] = str(embed_release.get("url") or "")
            rendered_payload["_released_embed_origin"] = str(embed_release.get("origin") or "")
        if viewer_release.get("released"):
            viewer_url = _public_tour_generated_viewer_url(slug, viewer_release.get("viewer_relpath"))
            if viewer_url:
                rendered_payload["_released_generated_viewer_url"] = viewer_url
        rendered_payload["_hosted_cube_ready"] = _public_tour_has_complete_hosted_cube(payload)
        if viewer_release.get("released"):
            rendered_payload["_tour_media_disclosure"] = str(viewer_release.get("disclosure") or "").strip()
        elif video_release.get("released"):
            rendered_payload["_tour_media_disclosure"] = str(video_release.get("disclosure") or "").strip()
        elif embed_release.get("released"):
            provider = str(embed_release.get("provider") or "external provider").strip()
            origin = str(embed_release.get("origin") or "").strip()
            rendered_payload["_tour_media_disclosure"] = (
                f"Verified external {provider} panorama from {origin}. The provider receives normal browser request metadata."
            )
        elif rendered_payload["_hosted_cube_ready"]:
            rendered_payload["_tour_media_disclosure"] = (
                "Hosted panorama assembled from the published six-face scene assets. Confirm dimensions and finishes in person."
            )
        else:
            if list(rendered_payload.get("scenes") or []):
                rendered_payload["_tour_media_disclosure"] = (
                    "Image and floorplan walkthrough. This surface does not claim a captured or provider-verified 3D scan."
                )
            else:
                rendered_payload["_tour_media_disclosure"] = (
                    "No tour media has passed public release review for this listing. "
                    "Approved listing facts remain available without exposing private, test, or source artifacts."
                )
        tour_html = _harden_public_tour_html(
            _tour_html(rendered_payload, hostname=hostname, rybbit_hostname=rybbit_hostname),
            rendered_payload,
        )
        frame_origin = str(embed_release.get("origin") or "").strip() if embed_release.get("released") else ""
        return HTMLResponse(
            tour_html,
            headers=_public_tour_security_headers(frame_origins=(frame_origin,) if frame_origin else ()),
        )
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
