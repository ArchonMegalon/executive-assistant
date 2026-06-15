from __future__ import annotations

import hmac
import json
import os
import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from markupsafe import Markup

from app.api.dependencies import (
    RequestContext,
    browser_principal_override_allowed,
    get_cloudflare_access_identity,
    get_container,
    get_request_context,
    require_operator_context,
)
from app.api.routes.landing_browser import (
    _browser_form_context,
    _form_value,
    _form_values,
    _normalize_browser_return_to,
    _shared_browser_fields,
    _workspace_session_cookie_kwargs,
)
from app.api.routes.landing_archive_support import (
    _archive_home_html,
    _archive_public_registry,
    _archive_publication_html_path,
    _is_archive_host,
)
from app.api.routes import landing_access_support as access_support
from app.api.routes.landing_content import (
    ADMIN_NAV_GROUPS,
    APP_NAV_GROUPS,
    app_nav_groups_for_brand,
    FEATURE_CARDS,
    HOW_STEPS,
    EA_DOC_LINKS,
    LANDING_FAQS,
    PROPERTY_DOC_LINKS,
    EA_LANDING_FAQS,
    PROPERTY_LANDING_FAQS,
    PERSONAS,
    PRICING_TIERS,
    PRODUCT_MODULES,
    PUBLIC_NAV,
    SIGN_IN_NOTES,
    TRUST_CARDS,
)
from app.api.routes.landing_object_support import (
    _evidence_detail_rows,
    _object_detail_row,
    _render_console_object_detail,
)
from app.api.routes import landing_public_pages_support as public_pages_support
from app.api.routes.landing_public_support import (
    _activation_preview_for_brand,
    _anonymous_onboarding_status,
    _console_shell_context,
    _load_status,
    _public_context,
    _public_page_context,
    _render_public_template,
    _render_secure_link_page,
    _today_activation_banner,
    templates,
)
from app.api.routes.landing_shared_support import (
    _app_live_feed,
    _default_operator_id_for_browser,
    _expected_api_token,
    _load_project_mode_payloads,
    _repo_root,
    _workspace_plan,
)
from app.api.routes.landing_view_models import (
    app_section_payload as _app_section_payload,
    humanize as _humanize,
    property_workspace_payload as _property_workspace_payload,
)
from app.api.routes.admin_view_models import build_admin_section_payload as _build_admin_section_payload
from app.api.routes.workspace_view_models import workspace_section_payload as _workspace_section_payload
from app.container import AppContainer
from app.product.service import build_product_service
from app.product.service import (
    _property_enrich_missing_fact_research,
    _property_investment_area_sqm,
    _property_investment_location_seed,
    _property_investment_price_eur,
    _property_investment_research_snapshot,
)
from app.services.cloudflare_access import CloudflareAccessIdentity
from app.services.google_oauth import complete_google_oauth_callback
from app.services.property_billing import payfunnels_configured, paypal_configured, property_commercial_snapshot
from app.services.property_market_catalog import (
    country_label as property_country_label,
    country_options as property_country_options,
    default_language_for_country,
    default_platforms_for_country,
    language_label as property_language_label,
    language_options as property_language_options,
    listing_mode_label as property_listing_mode_label,
    listing_mode_options as property_listing_mode_options,
    investment_research_mode_label as property_investment_research_mode_label,
    investment_research_mode_options as property_investment_research_mode_options,
    normalize_country_code,
    normalize_property_search_preferences,
    property_type_label as property_type_label_for_value,
    property_type_options as property_type_options_catalog,
    provider_options as property_provider_options,
)
from app.services.public_branding import request_brand
from app.services.registration_email import email_delivery_enabled

router = APIRouter(tags=["landing"])
archive_router = APIRouter(tags=["landing_archive"])


@router.get("/robots.txt", include_in_schema=False, response_class=PlainTextResponse)
def robots_txt(request: Request) -> PlainTextResponse:
    if _is_archive_host(request):
        response = PlainTextResponse("User-agent: *\nDisallow: /\n")
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
        return response
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /app",
        "Disallow: /admin",
        "Disallow: /api",
        "Disallow: /modes",
        "Disallow: /workspace-",
        "Disallow: /sign-in",
        "Disallow: /register",
        "Disallow: /get-started",
        "Disallow: /setup",
        "Disallow: /memorials",
    ]
    return PlainTextResponse("\n".join(lines) + "\n")
def _property_search_platform_catalog() -> tuple[dict[str, str], ...]:
    return tuple(property_provider_options(country_code="AT"))


def _property_console_context(
    *,
    container: AppContainer,
    principal_id: str,
    status: dict[str, object],
    run_id: str = "",
) -> dict[str, object]:
    product = build_product_service(container)
    raw_property_preferences = dict(status.get("property_search_preferences") or {})
    preferences = normalize_property_search_preferences(dict(raw_property_preferences.get("raw_preferences") or raw_property_preferences))
    selected_country = normalize_country_code(preferences.get("country_code"))
    commercial = property_commercial_snapshot(preferences)
    payfunnels_plus = payfunnels_configured(plan_key="plus")
    paypal_enabled = paypal_configured()
    selected_platforms = {
        str(value or "").strip().lower()
        for value in (preferences.get("selected_platforms") or [])
        if str(value or "").strip()
    }
    if not selected_platforms:
        selected_platforms = set(default_platforms_for_country(selected_country))
    country_provider_options = [dict(option) for option in property_provider_options(country_code=selected_country)]
    run_payload: dict[str, object] = {}
    normalized_run_id = str(run_id or "").strip()
    if normalized_run_id:
        try:
            run_payload = dict(
                product.get_property_search_run_status(
                    principal_id=principal_id,
                    run_id=normalized_run_id,
                )
                or {}
            )
        except Exception:
            run_payload = {}

    recent_matches: list[dict[str, object]] = []
    learning_summary: dict[str, object] = {}
    preference_bundle: dict[str, object] = {}
    preference_person_id = str(preferences.get("preference_person_id") or "self").strip() or "self"
    try:
        for handoff in product.list_handoffs(principal_id=principal_id, limit=12, status=None):
            task_type = str(getattr(handoff, "task_type", "") or "").strip()
            if task_type not in {"property_tour_followup", "property_alert_review"}:
                continue
            hosted_url = str(getattr(handoff, "tour_url", "") or "").strip()
            review_url = str(getattr(handoff, "editor_url", "") or "").strip()
            title = str(getattr(handoff, "summary", "") or "").strip() or str(getattr(handoff, "id", "") or "").strip() or "Property match"
            detail_parts = [
                str(getattr(handoff, "delivery_reason", "") or "").strip(),
                str(getattr(handoff, "counterparty", "") or "").strip(),
                str(getattr(handoff, "blocked_reason", "") or "").strip(),
            ]
            detail = " | ".join(part for part in detail_parts if part) or "Recent property follow-up."
            row: dict[str, object] = {
                "title": title,
                "detail": detail,
                "tag": "Hosted tour" if hosted_url else "Review",
            }
            if hosted_url:
                row["action_href"] = hosted_url
                row["action_method"] = "get"
                row["action_label"] = "Open 360"
            if review_url:
                if hosted_url:
                    row["secondary_action_href"] = review_url
                    row["secondary_action_method"] = "get"
                    row["secondary_action_label"] = "Review brief"
                else:
                    row["action_href"] = review_url
                    row["action_method"] = "get"
                    row["action_label"] = "Review brief"
            recent_matches.append(row)
            if len(recent_matches) >= 6:
                break
    except Exception:
        recent_matches = []
    try:
        preference_bundle = dict(
            product.get_preference_profile(
                principal_id=principal_id,
                person_id=preference_person_id,
            )
            or {}
        )
    except Exception:
        preference_bundle = {}
    try:
        learning_summary = dict(
            product.property_feedback_learning_summary(
                principal_id=principal_id,
                person_id=preference_person_id,
                domain="willhaben",
            )
            or {}
        )
    except Exception:
        learning_summary = {}

    return {
        "platform_options": country_provider_options,
        "platform_catalog_by_country": {
            str(option.get("value") or "").strip(): property_provider_options(country_code=str(option.get("value") or "").strip())
            for option in property_country_options()
        },
        "default_language_by_country": {
            str(option.get("value") or "").strip(): default_language_for_country(str(option.get("value") or "").strip())
            for option in property_country_options()
        },
        "country_options": property_country_options(),
        "language_options": property_language_options(),
        "listing_mode_options": property_listing_mode_options(),
        "investment_research_mode_options": property_investment_research_mode_options(),
        "property_type_options": property_type_options_catalog(),
        "country_label": property_country_label(selected_country),
        "language_label": property_language_label(preferences.get("language_code"), country_code=selected_country),
        "listing_mode_label": property_listing_mode_label(preferences.get("listing_mode")),
        "investment_research_mode_label": property_investment_research_mode_label(preferences.get("investment_research_mode")),
        "property_type_label": property_type_label_for_value(preferences.get("property_type")),
        "provider_total_for_country": len(country_provider_options),
        "preferences": preferences,
        "selected_platforms": list(selected_platforms),
        "run": run_payload,
        "recent_matches": recent_matches,
        "learning_summary": learning_summary,
        "preference_bundle": preference_bundle,
        "preference_person_id": preference_person_id,
        "start_endpoint": "/app/api/signals/property/search/run",
        "preferences_endpoint": "/v1/onboarding/property-search/preferences",
        "commercial": commercial,
        "billing_checkout_provider": ("payfunnels" if payfunnels_plus else ("paypal" if paypal_enabled else "")),
        "billing_checkout_provider_label": ("PayFunnels" if payfunnels_plus else ("PayPal" if paypal_enabled else "")),
        "billing_checkout_enabled": bool(payfunnels_plus or paypal_enabled),
        "billing_checkout_enabled_plans": (
            ["plus"]
            if payfunnels_plus
            else (["plus", "agent"] if paypal_enabled else [])
        ),
        "billing_order_endpoint": (
            "/app/api/signals/property/billing/payfunnels/order"
            if payfunnels_plus
            else "/app/api/signals/property/billing/paypal/order"
        ),
    }


@router.get("/", response_class=HTMLResponse)
def landing(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return public_pages_support.landing(request=request, container=container, access_identity=access_identity)


@archive_router.get("/{archive_slug}", response_class=HTMLResponse, include_in_schema=False)
def archive_publication_page(archive_slug: str, request: Request) -> HTMLResponse:
    return public_pages_support.archive_publication_page(archive_slug=archive_slug, request=request)


@router.get("/modes", response_class=HTMLResponse)
def project_modes_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
    _: None = Depends(require_operator_context),
) -> HTMLResponse:
    return public_pages_support.project_modes_page(request=request, container=container, access_identity=access_identity)


@router.get("/product", response_class=HTMLResponse)
def product_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return public_pages_support.product_page(request=request, container=container, access_identity=access_identity)


@router.get("/integrations", response_class=HTMLResponse)
def integrations_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return public_pages_support.integrations_page(request=request, container=container, access_identity=access_identity)


@router.get("/integrations/{channel_name}", response_class=HTMLResponse)
def integration_detail(
    channel_name: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return public_pages_support.integration_detail(channel_name=channel_name, request=request, container=container, access_identity=access_identity)


@router.get("/security", response_class=HTMLResponse)
def security_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return public_pages_support.security_page(request=request, container=container, access_identity=access_identity)


@router.get("/pricing", response_class=HTMLResponse)
def pricing_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return public_pages_support.pricing_page(request=request, container=container, access_identity=access_identity)


@router.get("/docs", response_class=HTMLResponse)
def docs_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return public_pages_support.docs_page(request=request, container=container, access_identity=access_identity)


@router.api_route("/sign-in", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def sign_in_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return access_support.sign_in_page(request=request, container=container, access_identity=access_identity)


@router.post("/sign-in/email-link")
async def sign_in_email_link(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> RedirectResponse:
    return await access_support.sign_in_email_link(request=request, container=container)


@router.post("/sign-in/google")
async def sign_in_google(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> RedirectResponse:
    return await access_support.sign_in_google(request=request, container=container)


@router.get("/register", response_class=HTMLResponse, response_model=None)
def register_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
):
    return access_support.register_page(request=request, container=container, access_identity=access_identity)


@router.api_route("/workspace-invites/{token}", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def workspace_invite_preview(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> HTMLResponse:
    return access_support.workspace_invite_preview(token=token, request=request, container=container)


@router.api_route("/workspace-access/{token}", methods=["GET", "HEAD"], response_model=None, include_in_schema=False)
def workspace_access_session(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
):
    return access_support.workspace_access_session(token=token, request=request, container=container)


@router.api_route("/workspace-invites/{token}/accept", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def workspace_invite_accept(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return access_support.workspace_invite_accept(token=token, request=request, container=container, access_identity=access_identity)


@router.get("/get-started", response_class=HTMLResponse)
def get_started(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return access_support.get_started(request=request, container=container, access_identity=access_identity)


@router.get("/app", response_class=HTMLResponse)
def app_root(request: Request) -> RedirectResponse:
    return RedirectResponse(str(request_brand(request).get("app_home") or "/app/today"), status_code=307)


def _property_candidate_ref(candidate: dict[str, object]) -> str:
    raw = "|".join(
        str(candidate.get(key) or "").strip()
        for key in ("title", "property_url", "review_url", "tour_url", "source_label")
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _property_shortlist_candidates_from_context(property_context: dict[str, object]) -> list[dict[str, object]]:
    run_payload = dict(property_context.get("run") or {})
    run_summary = dict(run_payload.get("summary") or {})
    run_id = str(run_payload.get("run_id") or "").strip()
    packet_candidates: list[dict[str, object]] = []
    for source in list(run_summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        source_label = str(source.get("source_label") or source.get("source_url") or "Source").strip()
        for candidate in list(source.get("top_candidates") or [])[:5]:
            if not isinstance(candidate, dict):
                continue
            candidate_row = dict(candidate)
            candidate_row.setdefault("source_label", source_label)
            candidate_row.setdefault("property_facts", dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {})
            packet_ref = _property_candidate_ref(
                {
                    "title": str(candidate_row.get("title") or "").strip(),
                    "property_url": str(candidate_row.get("property_url") or "").strip(),
                    "review_url": str(candidate_row.get("review_url") or "").strip(),
                    "tour_url": str(candidate_row.get("tour_url") or "").strip(),
                    "source_label": source_label,
                }
            )
            packet_url = f"/app/research/{packet_ref}"
            if run_id:
                packet_url = f"{packet_url}?run_id={urllib.parse.quote(run_id, safe='')}"
            candidate_row.setdefault("packet_url", packet_url)
            packet_candidates.append(candidate_row)
    return packet_candidates


def _property_lookup_candidate(
    *,
    property_context: dict[str, object],
    candidate_ref: str,
) -> dict[str, object] | None:
    summary = dict(dict(property_context.get("run") or {}).get("summary") or {})
    for source in list(summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        source_label = str(source.get("source_label") or source.get("source_url") or "Source").strip()
        for raw_candidate in list(source.get("top_candidates") or []):
            if not isinstance(raw_candidate, dict):
                continue
            candidate = dict(raw_candidate)
            candidate.setdefault("source_label", source_label)
            if _property_candidate_ref(candidate) == candidate_ref:
                return candidate
    return None


def _property_enriched_candidate_facts(*, candidate: dict[str, object]) -> dict[str, object]:
    facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
    title = str(candidate.get("title") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    text = " | ".join(part for part in (title, summary) if part)
    if text:
        if "price_eur" not in facts:
            price_match = re.search(r"(?:€|EUR)\s*([\d\.\s]+(?:,\d+)?)", text, flags=re.IGNORECASE)
            if price_match:
                raw_amount = str(price_match.group(1) or "").strip().replace(" ", "")
                normalized_amount = raw_amount.replace(".", "").replace(",", ".")
                try:
                    facts["price_eur"] = float(normalized_amount)
                    facts.setdefault("price_display", compact_text(price_match.group(0), fallback=f"EUR {facts['price_eur']:.0f}", limit=120))
                except Exception:
                    pass
        if "area_m2" not in facts and "living_area_m2" not in facts:
            area_match = re.search(r"(\d+(?:[.,]\d+)?)\s*m[²2]", text, flags=re.IGNORECASE)
            if area_match:
                try:
                    facts["area_m2"] = float(str(area_match.group(1) or "").replace(",", "."))
                except Exception:
                    pass
        if "rooms" not in facts and "room_count" not in facts:
            rooms_match = re.search(r"(\d+(?:[.,]\d+)?)\s*[- ]?Zimmer", text, flags=re.IGNORECASE)
            if rooms_match:
                try:
                    facts["rooms"] = float(str(rooms_match.group(1) or "").replace(",", "."))
                except Exception:
                    pass
        if "postal_name" not in facts and "address" not in facts and "district" not in facts:
            postal_match = re.search(r"\((\d{4}\s+[A-Za-zÄÖÜäöüß][^)]*)\)", text)
            if postal_match:
                postal_name = str(postal_match.group(1) or "").strip()[:160]
                if postal_name:
                    facts["postal_name"] = postal_name
                    facts.setdefault("address", postal_name)
    return _property_enrich_missing_fact_research(
        facts=facts,
        property_url=str(candidate.get("property_url") or "").strip(),
        title=title,
        summary=summary,
        source_label=str(candidate.get("source_label") or "").strip(),
    )


def _property_missing_fact_items(facts: dict[str, object]) -> list[dict[str, object]]:
    research = facts.get("missing_fact_research")
    if not isinstance(research, dict):
        return []
    items = research.get("items")
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)]


def _property_missing_fact_item(facts: dict[str, object], field: str) -> dict[str, object]:
    normalized = str(field or "").strip()
    for item in _property_missing_fact_items(facts):
        if str(item.get("field") or "").strip() == normalized:
            return item
    return {}


def _property_rooms_display(facts: dict[str, object]) -> str:
    label = str(facts.get("rooms_label") or "").strip()
    if label:
        return label
    raw_value = facts.get("rooms") or facts.get("room_count")
    if raw_value not in (None, "", []):
        return f"{raw_value} rooms"
    item = _property_missing_fact_item(facts, "rooms")
    if item:
        return str(item.get("display_value") or "Rooms under research").strip() or "Rooms under research"
    return ""


def _property_fact_rows(facts: dict[str, object]) -> list[dict[str, str]]:
    labels = {
        "price_eur": "Price",
        "warm_rent_eur": "Warm rent",
        "cold_rent_eur": "Cold rent",
        "area_m2": "Area",
        "rooms": "Rooms",
        "bedrooms": "Bedrooms",
        "bathrooms": "Bathrooms",
        "floor": "Floor",
        "has_lift": "Lift",
        "heating_type": "Heating",
        "energy_class": "Energy class",
        "distance_supermarket_m": "Supermarket",
        "distance_playground_m": "Playground",
        "nearest_playground_m": "Playground",
        "distance_pharmacy_m": "Pharmacy",
        "nearest_pharmacy_m": "Pharmacy",
        "distance_underground_m": "Underground",
        "nearest_subway_m": "Underground",
        "nearest_supermarket_m": "Supermarket",
        "address": "Address",
    }
    rows: list[dict[str, str]] = []
    for key, label in labels.items():
        value = facts.get(key)
        if value in (None, "", []):
            continue
        text = str(value).strip()
        if key.endswith("_eur"):
            text = f"{text} EUR"
        elif key.endswith("_m"):
            text = f"{text} m"
        elif key == "area_m2":
            text = f"{text} m2"
        elif isinstance(value, bool):
            text = "Yes" if value else "No"
        rows.append(_object_detail_row(label, text, "Fact"))
    return rows


def _property_distance_metric(facts: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        raw_value = facts.get(key)
        if raw_value in (None, "", []):
            continue
        try:
            meters = int(float(raw_value))
        except Exception:
            continue
        if meters > 0:
            return meters
    return None


def _property_bike_minutes_label(meters: int) -> str:
    minutes = max(1, int(round(float(meters) / 330.0)))
    return f"about {minutes} min by bike"


def _property_maps_directions_href(
    facts: dict[str, object],
    *,
    label: str,
    metric_key: str,
    travelmode: str = "walking",
) -> str:
    origin = ""
    try:
        lat = float(facts.get("map_lat"))
        lng = float(facts.get("map_lng"))
        origin = f"{lat:.7f},{lng:.7f}"
    except Exception:
        origin = str(
            facts.get("exact_address")
            or facts.get("street_address")
            or facts.get("address")
            or ""
        ).strip()
    prefix = metric_key[:-2] if metric_key.endswith("_m") else metric_key
    destination = ""
    try:
        destination_lat = float(facts.get(f"{prefix}_lat"))
        destination_lng = float(facts.get(f"{prefix}_lng"))
        destination = f"{destination_lat:.7f},{destination_lng:.7f}"
    except Exception:
        name = str(facts.get(f"{prefix}_name") or "").strip()
        if name and origin:
            destination = f"{name} near {origin}"
        elif origin:
            destination = f"{label} near {origin}"
    if not origin or not destination:
        return ""
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(
        {
            "api": "1",
            "origin": origin,
            "destination": destination,
            "travelmode": str(travelmode or "walking").strip().lower() or "walking",
        }
    )


def _property_distance_ooda_rows(facts: dict[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    distance_specs = (
        ("Playground", ("distance_playground_m", "nearest_playground_m"), "Neighbourhood", "walking"),
        ("Pharmacy", ("distance_pharmacy_m", "nearest_pharmacy_m"), "Errands", "walking"),
        ("Supermarket", ("distance_supermarket_m", "nearest_supermarket_m"), "Errands", "walking"),
        ("Underground", ("distance_underground_m", "nearest_subway_m"), "Transit", "bicycling"),
    )
    for label, keys, tag, travelmode in distance_specs:
        meters = _property_distance_metric(facts, *keys)
        if meters is None:
            continue
        available_keys = [key for key in keys if _property_distance_metric(facts, key) is not None]
        primary_metric_key = available_keys[0] if available_keys else keys[-1]
        for key in available_keys:
            prefix = key[:-2] if key.endswith("_m") else key
            if facts.get(f"{prefix}_lat") or facts.get(f"{prefix}_name"):
                primary_metric_key = key
                break
        maps_href = _property_maps_directions_href(
            facts,
            label=label,
            metric_key=primary_metric_key,
            travelmode=travelmode,
        )
        rows.append(
            _object_detail_row(
                f"Nearest {label.lower()}",
                f"{meters:,} m away | {_property_bike_minutes_label(meters)}".replace(",", " "),
                tag,
                href=maps_href,
                secondary_action_href=maps_href,
                secondary_action_label="Open navigation" if maps_href else "",
                secondary_action_method="get" if maps_href else "",
            )
        )
    return rows


def _property_tour_source_gap_detail(candidate: dict[str, object]) -> str:
    blocked_reason = str(candidate.get("blocked_reason") or "").strip()
    if blocked_reason:
        reason_map = {
            "listing_360_media_missing": "Floorplan or source 360 media missing: the listing does not expose usable tour material yet.",
            "pure_360_assets_unavailable": "Source 360 assets are not accessible enough to rebuild a hosted PropertyQuarry tour.",
            "property_tour_fallback_disabled": "Generated fallback tours are disabled until source floorplan or 360 material is available.",
        }
        return reason_map.get(blocked_reason, blocked_reason.replace("_", " "))
    facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}

    def _false_flag(value: object) -> bool:
        return str(value or "").strip().lower() in {"0", "false", "no", "none", "null"}

    def _zero_count(*keys: str) -> bool:
        for key in keys:
            raw_value = facts.get(key)
            if raw_value in (None, ""):
                continue
            try:
                return float(str(raw_value).strip()) <= 0.0
            except Exception:
                continue
        return False

    if _false_flag(facts.get("has_floorplan")) or _zero_count("floorplan_count", "floorplans_count"):
        return "Floorplan missing: this listing exposes no floorplan or source 360 media, so PropertyQuarry cannot generate a hosted tour yet."
    if _false_flag(facts.get("has_360")) or _zero_count("media_count", "image_count"):
        return "Tour source media missing: the source did not expose a 360, floorplan, or usable room media."
    return "Floorplan or source 360 media missing, so PropertyQuarry cannot generate a hosted tour yet."


def _property_tour_media_payload(candidate: dict[str, object]) -> dict[str, object]:
    tour_url = str(candidate.get("tour_url") or "").strip()
    vendor_tour_url = str(candidate.get("vendor_tour_url") or "").strip()
    review_url = str(candidate.get("review_url") or "").strip()
    status = str(candidate.get("tour_status") or "").strip().lower()
    eta_raw = str(candidate.get("tour_eta_minutes") or "").strip()
    eta_minutes = 0
    if eta_raw:
        try:
            eta_minutes = int(float(eta_raw))
        except Exception:
            eta_minutes = 0
    embed_href = tour_url or vendor_tour_url
    if tour_url:
        status_label = "Live 360 ready"
        status_detail = "Hosted 360 is ready on PropertyQuarry and should be reviewed before the raw listing."
    elif status in {"queued", "pending"}:
        status_label = "360 queued"
        status_detail = f"Tour generation is queued. ETA about {eta_minutes or 10} min."
    elif status in {"processing", "running", "in_progress", "started"}:
        status_label = "360 rendering"
        status_detail = f"Tour generation is running. ETA about {eta_minutes or 5} min."
    elif status in {"blocked", "failed", "skipped", "not_applicable"}:
        status_label = "360 unavailable"
        status_detail = _property_tour_source_gap_detail(candidate)
    elif vendor_tour_url:
        status_label = "External 360 available"
        status_detail = "A vendor-hosted 360 exists even if the internal hosted page is not ready yet."
    else:
        status_label = "360 unavailable"
        status_detail = _property_tour_source_gap_detail(candidate)
    return {
        "status_label": status_label,
        "status_detail": status_detail,
        "embed_href": embed_href,
        "primary_href": tour_url or vendor_tour_url or review_url,
        "primary_label": "Open 360" if (tour_url or vendor_tour_url) else ("Open packet" if review_url else ""),
        "secondary_href": review_url,
        "secondary_label": "Open hosted review" if review_url else "",
        "tertiary_href": vendor_tour_url if tour_url and vendor_tour_url and vendor_tour_url != tour_url else "",
        "tertiary_label": "Vendor 360" if tour_url and vendor_tour_url and vendor_tour_url != tour_url else "",
    }


def _property_packet_provenance_rows(facts: dict[str, object]) -> list[dict[str, str]]:
    labels = {
        "street_address": "Address",
        "exact_address": "Exact address",
        "address": "Address",
        "has_lift": "Lift",
        "heating_type": "Heating",
        "energy_class": "Energy class",
        "distance_supermarket_m": "Supermarket",
        "nearest_supermarket_m": "Supermarket",
        "distance_playground_m": "Playground",
        "nearest_playground_m": "Playground",
        "distance_pharmacy_m": "Pharmacy",
        "nearest_pharmacy_m": "Pharmacy",
        "distance_underground_m": "Underground",
        "nearest_subway_m": "Underground",
    }
    research_snapshot = dict(facts.get("listing_research_snapshot") or {}) if isinstance(facts.get("listing_research_snapshot"), dict) else {}
    research_meta = dict(facts.get("listing_research_meta") or {}) if isinstance(facts.get("listing_research_meta"), dict) else {}
    rows: list[dict[str, str]] = []
    for key, label in labels.items():
        raw_value = facts.get(key)
        if raw_value in (None, "", []):
            continue
        if isinstance(raw_value, bool):
            value = "Confirmed" if raw_value else "Not confirmed"
        elif isinstance(raw_value, (int, float)) and key.endswith("_m"):
            value = f"{int(raw_value)} m"
        else:
            value = str(raw_value).strip()
        if not value:
            continue
        provenance = "Researched" if key in research_snapshot else "Listing"
        if key in {"street_address", "exact_address", "address"} and ("map_lat" in research_snapshot or "map_lng" in research_snapshot):
            provenance = "Inferred"
        detail = value
        strategy = str(research_meta.get("strategy") or "").strip()
        if provenance == "Researched" and strategy:
            detail = f"{detail} | via {strategy.replace('_', ' ')}"
        rows.append(_object_detail_row(label, detail, provenance))
    return rows


def _property_packet_score_rows(
    *,
    facts: dict[str, object],
    preferences: dict[str, object],
    match_reasons: list[str],
    mismatch_reasons: list[str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    selected_locations = {str(value).strip().lower() for value in str(preferences.get("location_query") or "").split(",") if str(value).strip()}
    fact_address = str(facts.get("address") or facts.get("postal_name") or "").strip()
    if fact_address:
        fits_location = any(token in fact_address.lower() for token in selected_locations) if selected_locations else True
        rows.append(
            _object_detail_row(
                "Location fit",
                fact_address,
                "Strong" if fits_location else "Check",
            )
        )
    price_value = str(
        facts.get("price_display")
        or facts.get("rent_display")
        or facts.get("price")
        or facts.get("price_eur")
        or ""
    ).strip()
    if price_value:
        rows.append(_object_detail_row("Budget signal", price_value, "Budget"))
    area_value = str(facts.get("area_m2") or facts.get("living_area_m2") or "").strip()
    rooms_value = _property_rooms_display(facts)
    if area_value or rooms_value:
        detail = " | ".join(
            part for part in (
                rooms_value,
                f"{area_value} m2" if area_value else "",
            ) if part
        )
        rows.append(_object_detail_row("Layout signal", detail, "Layout"))
    if match_reasons:
        rows.append(_object_detail_row("Best fit signal", match_reasons[0], "Positive"))
    if mismatch_reasons:
        rows.append(_object_detail_row("Main caution", mismatch_reasons[0], "Risk"))
    return rows


def _property_packet_missing_rows(
    *,
    facts: dict[str, object],
    preferences: dict[str, object],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    missing_fact_specs = [
        ("address", "Exact address", "Needed for precise neighbourhood checks and revisit logistics."),
        ("heating_type", "Heating type", "Needed to confirm if the building avoids the wrong heating setup."),
        ("has_lift", "Lift status", "Needed because access and daily usability often decide the shortlist."),
        ("distance_supermarket_m", "Supermarket distance", "Needed to validate daily-errand convenience."),
        ("distance_playground_m", "Playground distance", "Needed if the search is family-oriented."),
        ("distance_pharmacy_m", "Pharmacy distance", "Needed to confirm basic services nearby."),
        ("distance_underground_m", "Underground distance", "Needed to validate fast transit access."),
    ]
    wanted_keywords = {str(value).strip().lower() for value in str(preferences.get("keywords") or "").split(",") if str(value).strip()}
    for key, title, detail in missing_fact_specs:
        if facts.get(key) not in (None, "", []):
            continue
        if key == "distance_playground_m" and "playground nearby" not in wanted_keywords and "family" not in wanted_keywords:
            continue
        if key == "distance_underground_m" and "underground nearby" not in wanted_keywords:
            continue
        if key == "heating_type" and not ({"no gas", "district heating"} & wanted_keywords):
            continue
        severity = "Critical" if key in {"address", "heating_type", "has_lift"} else "Important"
        rows.append(_object_detail_row(title, detail, severity))
    for item in _property_missing_fact_items(facts):
        if str(item.get("status") or "").strip().lower() == "filled":
            continue
        label = str(item.get("label") or item.get("field") or "Missing fact").strip()
        ooda = dict(item.get("ooda") or {}) if isinstance(item.get("ooda"), dict) else {}
        detail = str(ooda.get("act") or item.get("evidence") or "Missing-fact OODA queued.").strip()
        rows.append(_object_detail_row(label, detail, "OODA"))
    return rows


def _property_packet_decision_rows(
    *,
    candidate: dict[str, object],
    match_reasons: list[str],
    mismatch_reasons: list[str],
    missing_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    why_now = "; ".join(match_reasons[:2]) if match_reasons else "Enough positive fit signals are present to justify review now."
    why_not_now = "; ".join(mismatch_reasons[:2]) if mismatch_reasons else "No major blocking caution has been captured yet."
    critical_missing = sum(1 for row in missing_rows if str(row.get("tag") or "").strip().lower() == "critical")
    important_missing = sum(1 for row in missing_rows if str(row.get("tag") or "").strip().lower() == "important")
    if critical_missing:
        severity = "High"
        severity_detail = f"{critical_missing} critical fact(s) still missing before this should be trusted fully."
    elif important_missing >= 2:
        severity = "Medium"
        severity_detail = f"{important_missing} important fact(s) still missing. Keep this on the shortlist, but do not treat it as settled."
    elif important_missing == 1:
        severity = "Low"
        severity_detail = "One important fact is still missing. The packet is usable, but not fully closed."
    else:
        severity = "Low"
        severity_detail = "No major missing-data pressure remains in the current packet."
    recommendation = str(candidate.get("recommendation") or candidate.get("tag") or "candidate").replace("_", " ").strip().title() or "Candidate"
    return [
        _object_detail_row("Why now", why_now, "Now"),
        _object_detail_row("Why not now", why_not_now, "Risk"),
        _object_detail_row("Missing-data severity", severity_detail, severity),
        _object_detail_row("Current recommendation", recommendation, "Decision"),
    ]


def _property_packet_compare_rows(
    *,
    property_context: dict[str, object],
    current_candidate_ref: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    shortlist_candidates = _property_shortlist_candidates_from_context(property_context)
    for candidate in shortlist_candidates[:5]:
        if not isinstance(candidate, dict):
            continue
        candidate_ref = _property_candidate_ref(candidate)
        if candidate_ref == current_candidate_ref:
            continue
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        fact_line = " | ".join(
            part for part in (
                str(facts.get("price_display") or facts.get("rent_display") or facts.get("price") or "").strip(),
                _property_rooms_display(facts),
                f"{facts.get('area_m2')} m2" if facts.get("area_m2") else "",
            ) if part
        )
        rows.append(
            _object_detail_row(
                str(candidate.get("title") or "Shortlist candidate").strip() or "Shortlist candidate",
                " | ".join(
                    part for part in (
                        str(candidate.get("fit_summary") or candidate.get("detail") or "").strip(),
                        fact_line,
                    ) if part
                ) or "Open the packet to compare this candidate.",
                str(candidate.get("tag") or candidate.get("recommendation") or "Compare").strip() or "Compare",
                href=str(candidate.get("packet_url") or "").strip(),
                secondary_action_href=str(candidate.get("packet_url") or "").strip(),
                secondary_action_label="Open packet" if str(candidate.get("packet_url") or "").strip() else "",
                secondary_action_method="get" if str(candidate.get("packet_url") or "").strip() else "",
            )
        )
        if len(rows) >= 3:
            break
    return rows


def _property_investment_research_access_level(preferences: dict[str, object], commercial: dict[str, object], *, requested: bool) -> str:
    if str(preferences.get("listing_mode") or "").strip().lower() != "buy":
        return "off"
    if not requested and str(preferences.get("investment_research_mode") or "").strip().lower() != "auto":
        return "off"
    level = str(commercial.get("investment_research_level") or "none").strip().lower() or "none"
    return level


def _property_investment_risk_rows(facts: dict[str, object], snapshot: dict[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not str(facts.get("street_address") or "").strip():
        rows.append(_object_detail_row("Address confidence is low", "Exact address is still missing, so neighbourhood and comp confidence are reduced.", "High"))
    if not str(facts.get("heating_type") or "").strip():
        rows.append(_object_detail_row("Heating type still unknown", "Yield assumptions can be wrong if the heating setup drives renovation or tenant demand risk.", "Medium"))
    occupancy = str(facts.get("occupancy_status") or "").strip().lower()
    if occupancy:
        rows.append(_object_detail_row("Occupancy posture", str(facts.get("occupancy_status") or "").strip(), "Risk" if any(token in occupancy for token in ("occup", "vermiet", "bewohn", "uthyrd", "zamieszk")) else "Watch"))
    payback_years = snapshot.get("payback_years")
    if isinstance(payback_years, (int, float)) and float(payback_years) > 35.0:
        rows.append(_object_detail_row("Long payback horizon", f"Estimated payback is about {float(payback_years):.1f} years at current rent assumptions.", "Medium"))
    return rows


def _property_investment_context_rows(
    facts: dict[str, object],
    preferences: dict[str, object],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    risk_rows: list[dict[str, str]] = []
    listing_mode = str(preferences.get("listing_mode") or "").strip().lower()
    provider_group = str(facts.get("provider_group") or "").strip().lower()
    provider_channel = str(facts.get("provider_channel") or "").strip()
    marketing_type = str(facts.get("marketing_type") or "").strip()
    availability_label = str(facts.get("availability_label") or facts.get("move_in") or "").strip()
    court = str(facts.get("court") or "").strip()
    court_file_reference = str(facts.get("court_file_reference") or "").strip()
    valuation_display = str(facts.get("valuation_display") or "").strip()
    reserve_display = str(facts.get("reserve_price_display") or "").strip()
    occupancy = str(facts.get("occupancy_status") or "").strip()
    registration_count = 0
    try:
        registration_count = int(float(facts.get("registration_count") or 0))
    except Exception:
        registration_count = 0

    if provider_group == "genossenschaften_at":
        provider_label = provider_channel.replace("_", " ").strip().title() if provider_channel else "Genossenschaften"
        rows.append(_object_detail_row("Provider lane", f"{provider_label} cooperative supply lane.", "Source"))
        if marketing_type:
            rows.append(_object_detail_row("Offer posture", marketing_type, "Source"))
            if listing_mode == "buy" and marketing_type.lower().startswith("miet"):
                risk_rows.append(
                    _object_detail_row(
                        "Rental-led cooperative lane",
                        "This candidate is coming through a rental/cooperative supply lane while the brief is in buy mode. Treat the underwriting output as weak until the acquisition path is confirmed.",
                        "High",
                    )
                )
        if availability_label:
            rows.append(_object_detail_row("Delivery timing", availability_label, "Timing"))
        if registration_count > 0:
            rows.append(_object_detail_row("Applicant pressure", f"{registration_count:,} registrations or applicants were visible on the source lane.", "Demand"))
            if registration_count >= 10000:
                risk_rows.append(_object_detail_row("Extremely high applicant pressure", "Competition on this cooperative lane is already very high, so practical conversion odds may be weak even if the fit looks decent.", "High"))
            elif registration_count >= 1000:
                risk_rows.append(_object_detail_row("High applicant pressure", "Competition on this cooperative lane is already meaningful. Keep conversion risk in mind before overvaluing the headline fit.", "Medium"))

    if court or court_file_reference or valuation_display or reserve_display:
        if court:
            rows.append(_object_detail_row("Court process", court, "Auction"))
        if court_file_reference:
            rows.append(_object_detail_row("Case reference", court_file_reference, "Auction"))
        if valuation_display:
            rows.append(_object_detail_row("Judicial valuation", valuation_display, "Auction"))
        if reserve_display:
            rows.append(_object_detail_row("Reserve or deposit", reserve_display, "Auction"))
        risk_rows.append(
            _object_detail_row(
                "Judicial sale diligence",
                "This candidate is coming from a judicial or foreclosure lane. Underwriting should explicitly verify occupancy, legal encumbrances, and auction terms before treating the apparent discount as real.",
                "High",
            )
        )
        if occupancy:
            rows.append(_object_detail_row("Recorded occupancy", occupancy, "Auction"))

    return rows, risk_rows


def _property_investment_research_rows(
    *,
    property_url: str,
    facts: dict[str, object],
    preferences: dict[str, object],
    commercial: dict[str, object],
    requested: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    access_level = _property_investment_research_access_level(preferences, commercial, requested=requested)
    if access_level == "off":
        return [], []
    if access_level == "none":
        return [
            _object_detail_row(
                "Upgrade required",
                "Investment research is reserved for paid investment tiers. The current free tier does not run buy-side underwriting research.",
                "Locked",
            )
        ], []
    context_rows, context_risk_rows = _property_investment_context_rows(facts, preferences)
    current_price_eur = _property_investment_price_eur(facts)
    current_area_sqm = _property_investment_area_sqm(facts)
    location_seed = _property_investment_location_seed(facts, preferences)
    if not isinstance(current_price_eur, float) or not isinstance(current_area_sqm, float) or not location_seed:
        return context_rows + [
            _object_detail_row(
                "Investment research is waiting on core facts",
                "The packet still needs a credible buy price, area, and location before comp and yield work can run.",
                "Pending",
            )
        ], context_risk_rows
    selected_platforms = ",".join(str(value or "").strip() for value in (preferences.get("selected_platforms") or []) if str(value or "").strip())
    snapshot = _property_investment_research_snapshot(
        property_url=property_url,
        country_code=str(preferences.get("country_code") or "").strip() or "AT",
        location_query=location_seed,
        selected_platforms_csv=selected_platforms,
        current_price_eur=current_price_eur,
        current_area_sqm=current_area_sqm,
        research_level=access_level,
    )
    if not snapshot:
        return context_rows + [
            _object_detail_row(
                "Investment research could not build a benchmark yet",
                "No usable market samples were recovered from the current provider set for this location.",
                "Pending",
            )
        ], context_risk_rows
    rows: list[dict[str, str]] = context_rows + [
        _object_detail_row("Current underwriting base", f"EUR {current_price_eur:,.0f} over {current_area_sqm:.1f} m2 ({float(snapshot.get('current_price_per_sqm_eur') or 0.0):.2f} EUR/m2)", "Base"),
        _object_detail_row("Comparable buy samples", f"{int(snapshot.get('buy_sample_count') or 0)} listings", "Comps"),
        _object_detail_row("Comparable rent samples", f"{int(snapshot.get('rent_sample_count') or 0)} listings", "Comps"),
    ]
    market_buy = snapshot.get("market_buy_per_sqm_eur")
    delta_pct = snapshot.get("market_buy_delta_pct")
    if isinstance(market_buy, (int, float)):
        detail = f"Market buy benchmark is about {float(market_buy):.2f} EUR/m2."
        if isinstance(delta_pct, (int, float)):
            direction = "below" if float(delta_pct) < 0 else "above"
            detail = f"{detail} This listing sits {abs(float(delta_pct)):.1f}% {direction} that benchmark."
        rows.append(_object_detail_row("Buy-side benchmark", detail, "Value"))
    expected_rent = snapshot.get("expected_monthly_rent_eur")
    gross_yield = snapshot.get("gross_yield_pct")
    payback_years = snapshot.get("payback_years")
    if isinstance(expected_rent, (int, float)):
        rows.append(_object_detail_row("Expected monthly rent", f"About EUR {float(expected_rent):,.0f} ({float(snapshot.get('market_rent_per_sqm_eur') or 0.0):.2f} EUR/m2)", "Yield"))
    if isinstance(gross_yield, (int, float)):
        rows.append(_object_detail_row("Gross yield", f"About {float(gross_yield):.2f}% before vacancy, tax, and capex.", "Yield"))
    if isinstance(payback_years, (int, float)):
        rows.append(_object_detail_row("Payback horizon", f"About {float(payback_years):.1f} years on gross rent assumptions.", "Yield"))
    if access_level == "preview":
        rows.append(_object_detail_row("Preview tier limit", "Plus only returns the benchmark headline. Agent unlocks the fuller risk and diligence pass.", "Upgrade"))
        return rows, context_risk_rows
    risk_rows = context_risk_rows + _property_investment_risk_rows(facts, snapshot)
    if isinstance(snapshot.get("buy_samples"), list) and snapshot["buy_samples"]:
        top_buy = snapshot["buy_samples"][0]
        rows.append(_object_detail_row("Closest buy comp", f"{top_buy.get('title')} | {top_buy.get('per_sqm_eur')} EUR/m2 via {top_buy.get('source_label')}", "Comp"))
    if isinstance(snapshot.get("rent_samples"), list) and snapshot["rent_samples"]:
        top_rent = snapshot["rent_samples"][0]
        rows.append(_object_detail_row("Closest rent comp", f"{top_rent.get('title')} | {top_rent.get('per_sqm_eur')} EUR/m2 via {top_rent.get('source_label')}", "Comp"))
    return rows, risk_rows


def _property_packet_compare_table(
    *,
    property_context: dict[str, object],
    current_candidate: dict[str, object],
    current_candidate_ref: str,
) -> list[list[object]]:
    def _tour_state_for(candidate: dict[str, object]) -> str:
        if str(candidate.get("tour_url") or "").strip():
            return "Ready"
        status = str(candidate.get("tour_status") or "").strip().lower()
        eta_raw = str(candidate.get("tour_eta_minutes") or "").strip()
        if status in {"queued", "pending"}:
            return f"Queued | ETA about {eta_raw or '10'} min"
        if status in {"processing", "running", "in_progress", "started"}:
            return f"Rendering | ETA about {eta_raw or '5'} min"
        if status in {"blocked", "failed", "skipped", "not_applicable"}:
            return "Unavailable | " + _property_tour_source_gap_detail(candidate)
        return "Unavailable | " + _property_tour_source_gap_detail(candidate)

    def _row_for(candidate: dict[str, object], *, candidate_ref: str, current: bool) -> list[object]:
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        fit_summary = str(candidate.get("fit_summary") or candidate.get("detail") or "").strip() or "No fit summary"
        price_value = str(
            facts.get("price_display")
            or facts.get("rent_display")
            or facts.get("price")
            or facts.get("price_eur")
            or "Unknown"
        ).strip()
        layout_value = " | ".join(
            part for part in (
                _property_rooms_display(facts),
                f"{facts.get('area_m2')} m2" if facts.get("area_m2") else "",
            ) if part
        ) or "Layout under research"
        tour_state = _tour_state_for(candidate)
        return [
            {
                "title": (str(candidate.get("title") or "Shortlist candidate").strip() or "Shortlist candidate") + (" (Current)" if current else ""),
                "detail": str(candidate.get("source_label") or "").strip(),
                "href": str(candidate.get("packet_url") or "").strip(),
            },
            fit_summary,
            price_value,
            layout_value,
            tour_state,
            {
                "title": "Open packet",
                "detail": "Inspect this dossier",
                "href": str(candidate.get("packet_url") or "").strip(),
            },
        ]

    table_rows: list[list[object]] = [_row_for(current_candidate, candidate_ref=current_candidate_ref, current=True)]
    shortlist_candidates = _property_shortlist_candidates_from_context(property_context)
    for candidate in shortlist_candidates[:5]:
        if not isinstance(candidate, dict):
            continue
        candidate_ref = _property_candidate_ref(candidate)
        if candidate_ref == current_candidate_ref:
            continue
        table_rows.append(_row_for(candidate, candidate_ref=candidate_ref, current=False))
        if len(table_rows) >= 4:
            break
    return table_rows


@router.get("/app/research/{candidate_ref}", response_class=HTMLResponse)
def property_research_packet(
    candidate_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    run_id: str = Query(default=""),
    investment: int = Query(default=0),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    product = build_product_service(container)
    property_context = _property_console_context(
        container=container,
        principal_id=context.principal_id,
        status=status,
        run_id=run_id,
    )
    candidate = _property_lookup_candidate(property_context=property_context, candidate_ref=str(candidate_ref or "").strip())
    if candidate is None:
        raise HTTPException(status_code=404, detail="property_research_packet_not_found")
    workspace = dict(status.get("workspace") or {})
    assessment = dict(candidate.get("assessment") or {})
    facts = _property_enriched_candidate_facts(candidate=candidate)
    match_reasons = [str(item).strip() for item in list(candidate.get("match_reasons") or []) if str(item).strip()]
    mismatch_reasons = [str(item).strip() for item in list(candidate.get("mismatch_reasons") or []) if str(item).strip()]
    preferences = dict(property_context.get("preferences") or {})
    commercial = dict(property_context.get("commercial") or {})
    fit_summary = str(candidate.get("fit_summary") or candidate.get("detail") or "No fit summary captured.").strip()
    review_url = str(candidate.get("review_url") or "").strip()
    tour_url = str(candidate.get("tour_url") or "").strip()
    property_url = str(candidate.get("property_url") or "").strip()
    source_label = str(candidate.get("source_label") or "Property scout").strip() or "Property scout"
    title = str(candidate.get("title") or property_url or "Research packet").strip() or "Research packet"
    run_target = f"/app/research/{candidate_ref}" + (f"?run_id={urllib.parse.quote(run_id, safe='')}" if str(run_id or "").strip() else "")
    preference_person_id = str(preferences.get("preference_person_id") or "self").strip() or "self"
    packet_score_rows = _property_packet_score_rows(
        facts=facts,
        preferences=preferences,
        match_reasons=match_reasons,
        mismatch_reasons=mismatch_reasons,
    )
    missing_rows = _property_packet_missing_rows(
        facts=facts,
        preferences=preferences,
    )
    decision_rows = _property_packet_decision_rows(
        candidate=candidate,
        match_reasons=match_reasons,
        mismatch_reasons=mismatch_reasons,
        missing_rows=missing_rows,
    )
    provenance_rows = _property_packet_provenance_rows(facts)
    compare_rows = _property_packet_compare_rows(
        property_context=property_context,
        current_candidate_ref=str(candidate_ref or "").strip(),
    )
    compare_table_rows = _property_packet_compare_table(
        property_context=property_context,
        current_candidate=candidate,
        current_candidate_ref=str(candidate_ref or "").strip(),
    )
    investment_rows, investment_risk_rows = _property_investment_research_rows(
        property_url=property_url,
        facts=facts,
        preferences=preferences,
        commercial=commercial,
        requested=bool(int(investment or 0)),
    )
    ooda_summary_rows = [
        _object_detail_row("Why this was selected", match_reasons[0], "Match")
        if match_reasons
        else _object_detail_row("Why this was selected", fit_summary or "This candidate survived the shortlist ranking.", "Match"),
        _object_detail_row(
            "Best reason to act",
            str(decision_rows[0].get("detail") or fit_summary).strip()
            or "The current packet sees enough signal to keep this candidate open.",
            "OODA",
        ),
        _object_detail_row("Main concern", mismatch_reasons[0], "Risk")
        if mismatch_reasons
        else _object_detail_row("Main concern", "Some evidence is still missing, so this packet should be treated as a research view, not final diligence.", "Risk"),
        _object_detail_row("Current recommendation", str(candidate.get("tag") or candidate.get("recommendation") or "Candidate").strip() or "Candidate", "Decision"),
    ]
    for item in _property_missing_fact_items(facts):
        if str(item.get("status") or "").strip().lower() == "filled":
            continue
        ooda = dict(item.get("ooda") or {}) if isinstance(item.get("ooda"), dict) else {}
        ooda_summary_rows.append(
            _object_detail_row(
                str(item.get("label") or item.get("field") or "Missing fact").strip(),
                str(ooda.get("orient") or ooda.get("act") or item.get("evidence") or "Missing-fact research queued.").strip(),
                "Research",
            )
        )
    ooda_summary_rows.extend(_property_distance_ooda_rows(facts))
    investment_run_target = run_target + ("&investment=1" if "?" in run_target else "?investment=1")
    try:
        feedback_suggestions = dict(product.property_feedback_suggestions(property_facts=facts, assessment=assessment or candidate))
    except Exception:
        feedback_suggestions = {"negative": [], "positive": []}
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "PropertyQuarry Workspace"),
        page_title=f"PropertyQuarry {title}",
        current_nav="research",
        console_title="Review",
        console_summary="",
        object_kind="Research packet",
        object_title=title,
        object_summary=f"{fit_summary} · {source_label}",
        object_media=_property_tour_media_payload(candidate),
        object_meta=[
            {"label": "Source", "value": source_label},
            {"label": "Recommendation", "value": str(candidate.get("tag") or candidate.get("recommendation") or "Candidate").strip() or "Candidate"},
            {"label": "Run", "value": str(run_id or "latest").strip() or "latest"},
            {"label": "Packet", "value": str(candidate_ref)},
        ],
        object_ooda_title="OODA summary",
        object_ooda_copy="Start here. Why this candidate was selected, what makes it compelling now, what still argues against it, and what the immediate neighbourhood looks like.",
        object_ooda_rows=ooda_summary_rows,
        object_sidebar_title="Packet actions",
        object_sidebar_copy="Open the internal packet first. Raw portals and hosted tours stay secondary to the actual research decision surface.",
        object_sidebar_rows=[
            _object_detail_row("Fit summary", fit_summary, "Fit"),
            _object_detail_row(
                "Internal packet",
                "This page stays on PropertyQuarry and should remain the primary review surface.",
                "Primary",
                href=run_target,
            ),
            _object_detail_row(
                "Hosted review",
                review_url or "No hosted review page exists for this candidate yet.",
                "Review",
                href=review_url,
                secondary_action_href=review_url,
                secondary_action_label="Open hosted review" if review_url else "",
                secondary_action_method="get" if review_url else "",
            ),
            _object_detail_row(
                "Hosted 360",
                tour_url or _property_tour_source_gap_detail(candidate),
                "Tour",
                href=tour_url,
                secondary_action_href=tour_url,
                secondary_action_label="Open 360" if tour_url else "",
                secondary_action_method="get" if tour_url else "",
            ),
            _object_detail_row(
                "Original listing",
                property_url or "No raw listing URL was captured.",
                "Listing",
                href=property_url,
                secondary_action_href=property_url,
                secondary_action_label="Open source" if property_url else "",
                secondary_action_method="get" if property_url else "",
            ),
            _object_detail_row(
                "Investment research",
                (
                    "Agent can run the full buy-side investment pass."
                    if str(commercial.get("investment_research_level") or "") == "full"
                    else (
                        "Plus can run a shortened benchmark view."
                        if str(commercial.get("investment_research_level") or "") == "preview"
                        else "Upgrade to a paid investment tier to run buy-side underwriting research."
                    )
                ),
                "Research",
                href=investment_run_target if str(preferences.get("listing_mode") or "") == "buy" else "",
                secondary_action_href=investment_run_target if str(preferences.get("listing_mode") or "") == "buy" else "",
                secondary_action_label="Run investment research" if str(preferences.get("listing_mode") or "") == "buy" else "",
                secondary_action_method="get" if str(preferences.get("listing_mode") or "") == "buy" else "",
            ),
        ],
        object_sections=[
            {
                "eyebrow": "Decision call",
                "title": "The current recommendation in plain terms",
                "items": decision_rows,
            },
            {
                "eyebrow": "Decision scorecard",
                "title": "The first reasons to keep or reject this property",
                "items": packet_score_rows
                or [_object_detail_row("No scorecard yet", "The packet still needs enough facts to summarize the decision cleanly.", "Pending")],
            },
            {
                "eyebrow": "Fit reasoning",
                "title": "Why this candidate matched",
                "items": (
                    [_object_detail_row(item, "Positive signal used in ranking.", "Match") for item in match_reasons]
                    + [_object_detail_row(item, "Risk, mismatch, or still-open weakness.", "Risk") for item in mismatch_reasons]
                ) or [_object_detail_row("No explicit reasoning captured", "The packet has not yet received structured fit reasoning.", "Waiting")],
            },
            {
                "eyebrow": "Property facts",
                "title": "What the product currently knows",
                "items": _property_fact_rows(facts) or [_object_detail_row("No structured facts yet", "Run deeper enrichment or inspect the raw listing.", "Pending")],
            },
            {
                "eyebrow": "Evidence and provenance",
                "title": "Which facts came from the listing and which were researched",
                "items": provenance_rows
                or [_object_detail_row("No provenance rows yet", "Deeper enrichment will surface which facts were researched versus copied from the listing.", "Pending")],
            },
            {
                "eyebrow": "Investment research",
                "title": "Buy-side benchmark, rent thesis, and underwriting posture",
                "items": investment_rows
                or [_object_detail_row("Investment research is off", "Enable investment research in the search brief or request it explicitly from this packet on buy listings.", "Idle")],
            },
            {
                "eyebrow": "Open questions",
                "title": "What still needs verification before this is trustworthy",
                "items": missing_rows + investment_risk_rows + [
                    _object_detail_row(
                        "Review the hosted surfaces",
                        "Use the hosted review and 360 pages only after the internal packet already looks compelling.",
                        "Review",
                    ),
                    _object_detail_row(
                        "Record preference feedback",
                        "Like, dislike, or hide the candidate from the shortlist lane so the next run learns.",
                        "Learning",
                    ),
                ],
            },
            {
                "eyebrow": "Compare next",
                "title": "Keep the next-best shortlist candidates visible",
                "table_headers": ["Candidate", "Fit", "Price", "Layout", "360", "Packet"],
                "table_rows": compare_table_rows,
                "items": compare_rows
                or [_object_detail_row("No compare candidates yet", "Finish or widen the shortlist run to compare alternatives here.", "Waiting")],
            },
        ],
        object_feedback={
            "person_id": preference_person_id,
            "profile_href": f"/app/profile" + (f"?run_id={urllib.parse.quote(run_id, safe='')}" if str(run_id or "").strip() else ""),
            "suggestions": feedback_suggestions,
            "property_url": property_url,
            "property_title": title,
            "property_facts": facts,
            "assessment": assessment or candidate,
            "property_slug": str(candidate_ref or "").strip(),
            "save_endpoint": f"/app/api/people/{urllib.parse.quote(preference_person_id, safe='')}/preference-profile/property-feedback",
        },
    )


@router.get("/app/{section}", response_class=HTMLResponse)
def app_shell(
    section: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    run_id: str = Query(default=""),
) -> HTMLResponse:
    brand = request_brand(request)
    property_brand = brand["key"] == "propertyquarry"
    nav_groups = app_nav_groups_for_brand(brand["key"])
    allowed = {item["href"].rstrip("/").rsplit("/", 1)[-1] for group in nav_groups for item in group["items"]}
    if property_brand:
        allowed.update(
            {
                "properties",
                "shortlist",
                "research",
                "profile",
                "alerts",
                "billing",
                "settings",
                "briefing",
                "inbox",
                "follow-ups",
                "memory",
                "contacts",
                "activity",
                "channels",
                "automations",
            }
        )
    else:
        allowed.update(
            {
                "today",
                "queue",
                "commitments",
                "people",
                "evidence",
                "properties",
                "settings",
                "search",
                "channel-loop",
                "briefing",
                "inbox",
                "follow-ups",
                "memory",
                "contacts",
                "activity",
                "channels",
                "automations",
            }
        )
    if section not in allowed:
        raise HTTPException(status_code=404, detail="app_section_not_found")
    legacy_redirects = {
        "briefing": "/app/queue",
        "inbox": "/app/queue",
        "follow-ups": "/app/commitments",
        "memory": "/app/people",
        "contacts": "/app/evidence",
        "activity": "/admin/office",
        "channels": "/app/settings",
        "automations": "/app/settings",
    }
    if section in legacy_redirects:
        target = legacy_redirects[section]
        query = str(request.url.query or "").strip()
        if query:
            target = f"{target}?{query}"
        return RedirectResponse(target, status_code=307)
    resolved_section = section
    current_nav = section
    status = container.onboarding.status(principal_id=context.principal_id)
    if resolved_section == "channel-loop":
        workspace = dict(status.get("workspace") or {})
        product = build_product_service(container)
        pack = product.channel_loop_pack(
            principal_id=context.principal_id,
            operator_id=str(context.operator_id or "").strip(),
        )
        product.record_surface_event(
            principal_id=context.principal_id,
            event_type="channel_loop_opened",
            surface="channel_loop",
            actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
        )
        stats = [
            {"label": "Memo items", "value": str(int(dict(pack.get("stats") or {}).get("memo_items") or 0))},
            {"label": "Pending drafts", "value": str(int(dict(pack.get("stats") or {}).get("pending_drafts") or 0))},
            {"label": "Commitments", "value": str(int(dict(pack.get("stats") or {}).get("open_commitments") or 0))},
            {"label": "Handoffs", "value": str(int(dict(pack.get("stats") or {}).get("open_handoffs") or 0))},
            {"label": "Decisions", "value": str(int(dict(pack.get("stats") or {}).get("open_decisions") or 0))},
        ]
        return _render_public_template(
            request,
            "console_shell.html",
            **_console_shell_context(
                request=request,
                page_title=f"{request_brand(request)['name']} Inline Loop",
                current_nav="today",
                context=context,
                console_title=str(pack.get("headline") or "Inline loop"),
                console_summary=str(pack.get("summary") or "Clear the compact office loop."),
                nav_groups=nav_groups,
                workspace_label=str(workspace.get("name") or ("Executive Assistant Workspace" if request_brand(request)["key"] == "ea" else "PropertyQuarry Workspace")),
                cards=[
                    {
                        "eyebrow": "Inline loop",
                        "title": str(pack.get("headline") or "Inline loop"),
                        "body": str(pack.get("summary") or "Clear the compact office loop."),
                        "items": list(pack.get("items") or []),
                    },
                    *[
                        {
                            "eyebrow": "Channel digest",
                            "title": str(digest.get("headline") or "Channel digest"),
                            "body": " ".join(
                                part
                                for part in (
                                    str(digest.get("summary") or "").strip(),
                                    str(digest.get("preview_text") or "").strip(),
                                )
                                if part
                            ),
                            "items": list(digest.get("items") or []),
                        }
                        for digest in list(pack.get("digests") or [])
                    ],
                ],
                stats=stats,
            ),
        )
    property_sections = {"properties", "shortlist", "research", "profile", "alerts", "billing", "settings"} if property_brand else set()
    core_sections = {"today", "queue", "commitments", "people", "evidence", "activity", "settings"} - property_sections
    if resolved_section in core_sections:
        product = build_product_service(container)
        surface_event = {
            "today": "memo_opened",
            "queue": "queue_opened",
            "commitments": "commitment_ledger_opened",
            "people": "people_graph_opened",
            "evidence": "evidence_opened",
            "activity": "operator_queue_opened",
            "settings": "rules_opened",
        }.get(resolved_section)
        if surface_event:
            product.record_surface_event(
                principal_id=context.principal_id,
                event_type=surface_event,
                surface=resolved_section,
                actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
            )
        diagnostics = product.workspace_diagnostics(principal_id=context.principal_id)
        outcomes = product.workspace_outcomes(principal_id=context.principal_id) if resolved_section == "settings" else None
        payload = _workspace_section_payload(
            resolved_section,
            product.workspace_snapshot(
                principal_id=context.principal_id,
                operator_id=str(context.operator_id or "").strip(),
            ),
            diagnostics,
            outcomes,
            operator_id=str(context.operator_id or "").strip(),
            brand_key=request_brand(request)["key"],
        )
    else:
        property_context = (
            _property_console_context(
                container=container,
                principal_id=context.principal_id,
                status=status,
                run_id=run_id,
            )
            if resolved_section in property_sections or resolved_section == "properties"
            else None
        )
        if resolved_section in property_sections or resolved_section == "properties":
            build_product_service(container).record_surface_event(
                principal_id=context.principal_id,
                event_type=f"{resolved_section}_opened",
                surface=resolved_section,
                actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
            )
        if property_brand and resolved_section in property_sections:
            payload = _property_workspace_payload(
                resolved_section,
                status=status,
                property_state=property_context or {},
            )
        else:
            payload = _app_section_payload(
                resolved_section,
                status,
                live_feed=_app_live_feed(container, principal_id=context.principal_id),
                property_context=property_context,
            )
    workspace = dict(status.get("workspace") or {})
    if property_brand and resolved_section in property_sections:
        property_template = "app/property_decision_workbench.html" if resolved_section == "properties" else "app/property_workspace.html"
        return _render_public_template(
            request,
            property_template,
            **{
                **_console_shell_context(
                    request=request,
                    page_title=f"{request_brand(request)['name']} {payload['title']}",
                    current_nav=current_nav,
                    context=context,
                    console_title=str(payload["title"]),
                    console_summary=str(payload["summary"]),
                    nav_groups=nav_groups,
                    workspace_label=str(workspace.get("name") or "PropertyQuarry Workspace"),
                    cards=list(payload.get("cards") or []),
                    stats=list(payload["stats"]),
                    console_form=dict(payload.get("console_form") or {}),
                ),
                **payload,
            },
        )
    return _render_public_template(
        request,
        "console_shell.html",
        **_console_shell_context(
            request=request,
            page_title=f"{request_brand(request)['name']} {payload['title']}",
            current_nav=current_nav,
            context=context,
            console_title=str(payload["title"]),
            console_summary=str(payload["summary"]),
            nav_groups=nav_groups,
            workspace_label=str(workspace.get("name") or ("Executive Assistant Workspace" if request_brand(request)["key"] == "ea" else "PropertyQuarry Workspace")),
            cards=list(payload["cards"]),
            stats=list(payload["stats"]),
            console_form=dict(payload.get("console_form") or {}),
            activation_banner=_today_activation_banner(request=request, status=status) if current_nav == "today" else None,
        ),
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_root() -> RedirectResponse:
    return RedirectResponse("/admin/policies", status_code=307)


@router.get("/admin/{section}", response_class=HTMLResponse)
def admin_shell(
    section: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    _: None = Depends(require_operator_context),
) -> HTMLResponse:
    allowed = {row["key"] for group in ADMIN_NAV_GROUPS for row in group["items"]}
    if section not in allowed:
        raise HTTPException(status_code=404, detail="admin_section_not_found")
    operator_id = str(context.operator_id or "").strip()
    if not operator_id and context.auth_source == "loopback_no_auth":
        operator_id = _default_operator_id_for_browser(container, principal_id=context.principal_id)
    payload = _build_admin_section_payload(
        section,
        container=container,
        principal_id=context.principal_id,
        operator_id=operator_id,
    )
    return _render_public_template(
        request,
        "console_shell.html",
        **_console_shell_context(
            request=request,
            page_title=f"{request_brand(request)['name']} Admin {payload['title']}",
            current_nav=section,
            context=context,
            console_title=str(payload["title"]),
            console_summary=str(payload["summary"]),
            nav_groups=ADMIN_NAV_GROUPS,
            workspace_label="Operator Center",
            cards=list(payload["cards"]),
            stats=list(payload["stats"]),
        ),
    )


@router.get("/setup")
def legacy_setup_redirect() -> RedirectResponse:
    return RedirectResponse("/get-started", status_code=307)


@router.get("/privacy")
def legacy_privacy_redirect() -> RedirectResponse:
    return RedirectResponse("/security", status_code=307)


@router.get("/demo/brief")
def legacy_brief_redirect() -> RedirectResponse:
    return RedirectResponse("/app/queue", status_code=307)


@router.get("/channels/google")
def legacy_google_channel_redirect() -> RedirectResponse:
    return RedirectResponse("/integrations/google", status_code=307)


@router.get("/channels/telegram")
def legacy_telegram_channel_redirect() -> RedirectResponse:
    return RedirectResponse("/integrations/telegram", status_code=307)


@router.get("/channels/whatsapp")
def legacy_whatsapp_channel_redirect() -> RedirectResponse:
    return RedirectResponse("/integrations/whatsapp", status_code=307)


@router.get("/app/commitments/candidates/{candidate_id}", response_class=HTMLResponse)
def commitment_candidate_review(
    candidate_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    brand = request_brand(request)
    nav_groups = app_nav_groups_for_brand(brand["key"])
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    candidate = product.get_commitment_candidate(principal_id=context.principal_id, candidate_id=candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="commitment_candidate_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="commitment_candidate_opened",
        surface=f"candidate:{candidate_id}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_public_template(
        request,
        "app/commitment_candidate_review.html",
        **{
            **_console_shell_context(
                request=request,
                page_title=f"{brand['name']} Review {candidate.title}",
                current_nav="queue",
                context=context,
                console_title="Review extracted commitment",
                console_summary="Edit the wording, due date, or ownership before this enters the commitment ledger.",
                nav_groups=nav_groups,
                workspace_label=str(workspace.get("name") or brand["workspace_label"]),
                cards=[],
                stats=[
                    {"label": "Confidence", "value": f"{int(candidate.confidence * 100)}%"},
                    {"label": "Counterparty", "value": candidate.counterparty or "None"},
                    {"label": "Suggested due", "value": candidate.suggested_due_at[:10] if candidate.suggested_due_at else "Open"},
                    {"label": "Status", "value": candidate.status.title()},
                ],
            ),
            "candidate": candidate,
        },
    )
