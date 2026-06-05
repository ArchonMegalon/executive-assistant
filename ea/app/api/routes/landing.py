from __future__ import annotations

import html
import hmac
import os
import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.api.dependencies import (
    RequestContext,
    browser_principal_override_allowed,
    get_cloudflare_access_identity,
    get_container,
    get_request_context,
    require_operator_context,
)
from app.api.routes.landing_content import (
    ADMIN_NAV_GROUPS,
    APP_NAV_GROUPS,
    app_nav_groups_for_brand,
    DOC_LINKS,
    FEATURE_CARDS,
    HOW_STEPS,
    LANDING_FAQS,
    PERSONAS,
    PRICING_TIERS,
    PRODUCT_MODULES,
    PUBLIC_NAV,
    SIGN_IN_NOTES,
    TRUST_CARDS,
)
from app.api.routes.landing_view_models import (
    app_section_payload as _app_section_payload,
    channel_cards as _channel_cards,
    humanize as _humanize,
    list_rows as _list_rows,
    property_workspace_payload as _property_workspace_payload,
)
from app.api.routes.admin_view_models import build_admin_section_payload as _build_admin_section_payload
from app.api.routes.workspace_view_models import workspace_section_payload as _workspace_section_payload
from app.container import AppContainer
from app.product.commercial import workspace_plan_for_mode
from app.product.service import build_product_service
from app.product.service import (
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
from app.services.public_clickrank import clickrank_head_snippet as _clickrank_head_snippet, request_hostname as _request_hostname
from app.services.registration_email import email_delivery_enabled

router = APIRouter(tags=["landing"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))

templates.env.globals["clickrank_head_snippet"] = lambda request=None: Markup(_clickrank_head_snippet(_request_hostname(request)))


@router.get("/robots.txt", include_in_schema=False, response_class=PlainTextResponse)
def robots_txt() -> PlainTextResponse:
    response = PlainTextResponse("User-agent: *\nDisallow: /\n")
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response



def _expected_api_token(container: AppContainer) -> str:
    return str(container.settings.auth.api_token or "").strip()



def _default_principal_id(container: AppContainer) -> str:
    return str(container.settings.auth.default_principal_id or "").strip() or "local-user"



def _token_required(container: AppContainer) -> bool:
    mode = str(getattr(getattr(container.settings, "runtime", None), "mode", "dev") or "dev").strip().lower() or "dev"
    return mode == "prod" or bool(_expected_api_token(container))



def _form_value(form_data: dict[str, list[str]], key: str, default: str = "") -> str:
    values = form_data.get(key) or []
    return str(values[0] if values else default).strip()



def _form_values(form_data: dict[str, list[str]], key: str) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in (form_data.get(key) or []) if str(value).strip())



def _principal_for_page(
    *,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> str:
    if access_identity is not None:
        return access_identity.principal_id
    return ""



def _anonymous_onboarding_status() -> dict[str, object]:
    payfunnels_plus = payfunnels_configured(plan_key="plus")
    paypal_enabled = paypal_configured()
    return {
        "principal_id": "",
        "status": "anonymous",
        "workspace": {"name": "PropertyQuarry"},
        "selected_channels": [],
        "privacy": {},
        "assistant_modes": [],
        "featured_domains": [],
        "storage_posture": {},
        "channels": {},
        "brief_preview": {},
        "next_step": "Sign in to start a workspace or view the current one.",
        "onboarding_id": "",
    }



def _load_status(
    *,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> tuple[str, dict[str, object]]:
    principal_id = _principal_for_page(container=container, access_identity=access_identity)
    if not principal_id:
        return "", _anonymous_onboarding_status()
    return principal_id, container.onboarding.status(principal_id=principal_id)


def _public_app_base_url(request: Request) -> str:
    forwarded = str(request.headers.get("x-forwarded-host") or "").strip().lower().rstrip(".")
    request_host = str(request.url.hostname or "").strip().lower().rstrip(".")
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").strip() or request.url.scheme
    effective_host = forwarded or request_host
    if effective_host in {"propertyquarry.com", "www.propertyquarry.com"}:
        host = forwarded or request_host
        return f"https://{host}"
    explicit = str(os.environ.get("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    if forwarded:
        forwarded_proto = _first_forwarded_https_or_first_token(forwarded_proto)
    if forwarded:
        return f"{forwarded_proto}://{forwarded}"
    return str(request.base_url).rstrip("/")



def _normalize_browser_return_to(raw: str | None, *, default: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return default
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme or parsed.netloc or value.startswith("//") or not value.startswith("/"):
        return default
    return value


def _first_forwarded_https_or_first_token(raw: str) -> str:
    tokens = [token.strip().lower() for token in str(raw or "").split(",") if token.strip()]
    if "https" in tokens:
        return "https"
    if "wss" in tokens:
        return "wss"
    return tokens[0] if tokens else ""


def _browser_request_uses_secure_scheme(request: Request) -> bool:
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").strip().lower()
    normalized = _first_forwarded_https_or_first_token(forwarded_proto)
    if normalized:
        return normalized in {"https", "wss"}
    return str(request.url.scheme or "").strip().lower() == "https"


def _workspace_session_cookie_kwargs(request: Request, *, expires_at: str = "") -> dict[str, object]:
    kwargs: dict[str, object] = {
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": _browser_request_uses_secure_scheme(request),
    }
    normalized_expires_at = str(expires_at or "").strip()
    if not normalized_expires_at:
        return kwargs
    try:
        expires_dt = datetime.fromisoformat(normalized_expires_at)
    except ValueError:
        return kwargs
    if expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=timezone.utc)
    max_age = max(int((expires_dt - datetime.now(timezone.utc)).total_seconds()), 0)
    kwargs["expires"] = expires_dt
    kwargs["max_age"] = max_age
    return kwargs


def _shared_browser_fields(
    *,
    principal_id: str,
    access_identity: CloudflareAccessIdentity | None,
    container: AppContainer,
) -> str:
    token_field = ""
    if access_identity is None and _token_required(container):
        token_field = """
        <label for=\"api_token\">API token</label>
        <input id=\"api_token\" name=\"api_token\" type=\"password\" placeholder=\"required for browser setup on this host\">
        """
    if access_identity is not None:
        return f"""
        <input type=\"hidden\" name=\"principal_id\" value=\"{html.escape(principal_id)}\">
        {token_field}
        """
    if not browser_principal_override_allowed():
        return f"""
        {token_field}
        <p class=\"helper-note\">This browser can only finish setup for the default workspace on this deployment. Switching workspaces from the browser is disabled here.</p>
        """
    return f"""
    <label for=\"principal_id\">Workspace ID (advanced)</label>
    <input id=\"principal_id\" name=\"principal_id\" value=\"{html.escape(principal_id)}\" required>
    {token_field}
    """



def _browser_form_context(
    *,
    form_data: dict[str, list[str]],
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> str:
    expected = _expected_api_token(container)
    if access_identity is None and _token_required(container):
        api_token = _form_value(form_data, "api_token", "")
        if not expected or not hmac.compare_digest(api_token, expected):
            raise HTTPException(status_code=401, detail="auth_required")
    if access_identity is not None:
        requested = _form_value(form_data, "principal_id", access_identity.principal_id)
        if requested and requested != access_identity.principal_id:
            raise HTTPException(status_code=403, detail="principal_scope_mismatch")
        return access_identity.principal_id
    default_principal = _default_principal_id(container)
    requested = _form_value(form_data, "principal_id", "")
    if browser_principal_override_allowed():
        return requested or default_principal
    if requested and requested != default_principal:
        raise HTTPException(status_code=403, detail="principal_override_not_allowed")
    return default_principal



def _public_context(
    *,
    request: Request,
    current_nav: str,
    page_title: str,
    principal_id: str,
    status: dict[str, object],
    access_identity: CloudflareAccessIdentity | None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    brand = request_brand(request)
    workspace = dict(status.get("workspace") or {})
    channels = dict(status.get("channels") or {})
    preview = dict(status.get("brief_preview") or {})
    selected_channels = [str(row) for row in (status.get("selected_channels") or []) if str(row).strip()]
    context: dict[str, object] = {
        "page_title": page_title,
        "brand": brand,
        "public_nav": PUBLIC_NAV,
        "current_nav": current_nav,
        "access_identity": access_identity,
        "principal_id": principal_id,
        "status": status,
        "workspace": workspace,
        "privacy": dict(status.get("privacy") or {}),
        "channels": channels,
        "channel_cards": _channel_cards(channels),
        "selected_channels_label": ", ".join(selected_channels) if selected_channels else "Google sign-in recommended",
        "workspace_mode_label": _humanize(str(workspace.get("mode") or "personal")),
        "brief_headline": str(preview.get("headline") or "Turn your channels into a prioritized day."),
        "first_brief_items": _list_rows(
            preview.get("first_brief_preview") or preview.get("first_brief"),
            (
                "Connect Google sign-in if you want easier return access from the same account.",
                "Keep one reviewable property workflow before widening the channel footprint.",
                "Make approvals and memory rules explicit before automating actions.",
            ),
        ),
        "suggested_actions": _list_rows(
            preview.get("suggested_actions"),
            (
                "Turn the workspace posture into a useful shortlist and research loop.",
                "Add more channels only after the first loop already feels useful.",
            ),
        ),
        "trust_notes": _list_rows(
            preview.get("trust_notes"),
            (
                "Each channel says clearly what the assistant can actually do today.",
                "Approvals and workspace memory stay visible product features, not hidden implementation details.",
            ),
        ),
        "top_contacts": _list_rows(preview.get("top_contacts"), ("No contact memory yet.",)),
        "top_themes": _list_rows(preview.get("top_themes"), ("No themes yet.",)),
    }
    if extra:
        context.update(extra)
    return context


def _workspace_plan(container: AppContainer, *, principal_id: str):
    status = container.onboarding.status(principal_id=principal_id)
    workspace = dict(status.get("workspace") or {})
    return workspace_plan_for_mode(str(workspace.get("mode") or "personal"))



def _console_shell_context(
    *,
    request: Request,
    page_title: str,
    current_nav: str,
    context: RequestContext,
    console_title: str,
    console_summary: str,
    nav_groups: tuple[dict[str, object], ...],
    workspace_label: str,
    cards: list[dict[str, object]],
    stats: list[dict[str, str]],
    console_form: dict[str, object] | None = None,
) -> dict[str, object]:
    brand = request_brand(request)
    return {
        "page_title": page_title,
        "brand": brand,
        "current_nav": current_nav,
        "nav_groups": nav_groups,
        "console_title": console_title,
        "console_summary": console_summary,
        "workspace_label": workspace_label,
        "cards": cards,
        "stats": stats,
        "console_form": console_form or {},
        "principal_id": context.principal_id,
        "access_email": context.access_email,
        "operator_id": context.operator_id,
    }



def _render_public_template(request: Request, template_name: str, **context: Any) -> HTMLResponse:
    context.setdefault("request", request)
    context.setdefault("brand", request_brand(request))
    response = templates.TemplateResponse(request, template_name, context)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


def _render_secure_link_page(
    request: Request,
    *,
    page_title: str,
    current_nav: str,
    link_kicker: str,
    link_title: str,
    link_summary: str,
    link_detail_title: str,
    link_status_label: str,
    link_rows: list[dict[str, str]],
    primary_action_href: str,
    primary_action_label: str,
    primary_action_method: str = "get",
    primary_action_fields: dict[str, str] | None = None,
    secondary_action_href: str = "",
    secondary_action_label: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    response = _render_public_template(
        request,
        "workspace_link.html",
        **_public_context(
            request=request,
            current_nav=current_nav,
            page_title=page_title,
            principal_id="",
            status=_anonymous_onboarding_status(),
            access_identity=None,
            extra={
                "link_kicker": link_kicker,
                "link_title": link_title,
                "link_summary": link_summary,
                "link_detail_title": link_detail_title,
                "link_status_label": link_status_label,
                "link_rows": link_rows,
                "primary_action_href": primary_action_href,
                "primary_action_label": primary_action_label,
                "primary_action_method": str(primary_action_method or "get").strip().lower() or "get",
                "primary_action_fields": dict(primary_action_fields or {}),
                "secondary_action_href": secondary_action_href,
                "secondary_action_label": secondary_action_label,
            },
        ),
    )
    response.status_code = status_code
    return response


def _default_operator_id_for_browser(container: AppContainer, *, principal_id: str) -> str:
    operators = container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=1)
    if not operators:
        return ""
    return str(operators[0].operator_id or "").strip()


def _app_live_feed(container: AppContainer, *, principal_id: str) -> dict[str, object]:
    approvals = container.orchestrator.list_pending_approvals_for_principal(
        principal_id=principal_id,
        limit=6,
    )
    human_tasks = container.orchestrator.list_human_tasks(
        principal_id=principal_id,
        status="pending",
        limit=6,
    )
    pending_delivery = container.channel_runtime.list_pending_delivery(
        limit=6,
        principal_id=principal_id,
    )
    return {
        "approvals": approvals,
        "human_tasks": human_tasks,
        "pending_delivery": pending_delivery,
    }


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
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    brand = request_brand(request)
    return _render_public_template(
        request,
        "propertyquarry_home.html" if brand["key"] == "propertyquarry" else "marketing_home.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title=brand["name"],
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "feature_cards": FEATURE_CARDS,
                "how_steps": HOW_STEPS,
                "trust_cards": TRUST_CARDS,
                "landing_faqs": LANDING_FAQS,
                "doc_links": DOC_LINKS,
            },
        ),
    )


@router.get("/product", response_class=HTMLResponse)
def product_page() -> RedirectResponse:
    return RedirectResponse("/", status_code=307)


@router.get("/integrations", response_class=HTMLResponse)
def integrations_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "integrations_page.html",
        **_public_context(
            request=request,
            current_nav="integrations",
            page_title="PropertyQuarry Integrations",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
        ),
    )


@router.get("/integrations/{channel_name}", response_class=HTMLResponse)
def integration_detail(
    channel_name: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    channels = dict(status.get("channels") or {})
    mapping = {
        "google": {
            "title": "Google sign-in",
            "eyebrow": "Google",
            "detail_points": (
                "Start with Google sign-in unless you already know you need broader workspace actions.",
                "PropertyQuarry only needs Google identity by default so the same account can return cleanly.",
                "Broader Gmail or Drive context stays an explicit upgrade path instead of the default.",
            ),
            "body_points": (
                "Explain permissions in plain language first and raw scopes second.",
                "Show a real connected account and a real first success instead of treating consent as the finish line.",
                "Keep Google as optional account access, not as the center of the product story.",
            ),
        },
        "telegram": {
            "title": "Telegram",
            "eyebrow": "Telegram",
            "detail_points": (
                "Personal identity linking and official bot installation are separate decisions.",
                "Login alone does not imply generic history import.",
                "Future-only, import-later, and manual-forward are distinct promises and stay distinct in the UI.",
            ),
            "body_points": (
                "Ask first whether this is a personal Telegram setup or a bot rollout.",
                "Record where EA will operate: DM, groups, or channels.",
                "Treat the bot as the durable operating surface once installed and verified.",
            ),
        },
        "whatsapp": {
            "title": "WhatsApp",
            "eyebrow": "WhatsApp",
            "detail_points": (
                "Business onboarding and export intake are separate supported paths.",
                "The assistant does not promise generic automated history download outside those paths.",
                "Live messaging and manual history intake stay visibly distinct in the product contract.",
            ),
            "body_points": (
                "Use Business onboarding for the long-term live assistant path.",
                "Use export intake for personal or unsupported cases without pretending it is live sync.",
                "Keep media inclusion, history source, and future live sync as separate explicit choices.",
            ),
        },
    }
    current = mapping.get(channel_name)
    if current is None:
        raise HTTPException(status_code=404, detail="integration_not_found")
    channel = dict(channels.get(channel_name) or {})
    return _render_public_template(
        request,
        "channel_detail.html",
        **_public_context(
            request=request,
            current_nav="integrations",
            page_title=f"PropertyQuarry {current['title']}",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "channel": channel,
                "channel_title": current["title"],
                "channel_eyebrow": current["eyebrow"],
                "detail_points": current["detail_points"],
                "body_points": current["body_points"],
            },
        ),
    )


@router.get("/security", response_class=HTMLResponse)
def security_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "security_page.html",
        **_public_context(
            request=request,
            current_nav="security",
            page_title="PropertyQuarry Security",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={"trust_cards": TRUST_CARDS},
        ),
    )


@router.get("/pricing", response_class=HTMLResponse)
def pricing_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "pricing_page.html",
        **_public_context(
            request=request,
            current_nav="pricing",
            page_title="PropertyQuarry Pricing",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={"pricing_tiers": PRICING_TIERS},
        ),
    )


@router.get("/docs", response_class=HTMLResponse)
def docs_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "docs_page.html",
        **_public_context(
            request=request,
            current_nav="docs",
            page_title="PropertyQuarry Docs",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={"doc_links": DOC_LINKS},
        ),
    )


@router.api_route("/sign-in", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def sign_in_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    link_status = str(request.query_params.get("link_status") or "").strip()
    link_email = str(request.query_params.get("link_email") or "").strip()
    link_count = int(request.query_params.get("link_count") or 0)
    link_failed_total = int(request.query_params.get("link_failed_total") or 0)
    link_error = str(request.query_params.get("link_error") or "").strip()
    google_error = str(request.query_params.get("google_error") or "").strip()
    return _render_public_template(
        request,
        "sign_in.html",
        **_public_context(
            request=request,
            current_nav="sign-in",
            page_title=f"Sign in to {request_brand(request)['name']}",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "sign_in_notes": SIGN_IN_NOTES,
                "sign_in_link_enabled": email_delivery_enabled(),
                "sign_in_link_status": link_status,
                "sign_in_link_email": link_email,
                "sign_in_link_count": link_count,
                "sign_in_link_failed_total": link_failed_total,
                "sign_in_link_error": link_error,
                "sign_in_google_error": google_error,
            },
        ),
    )


@router.post("/sign-in/email-link")
async def sign_in_email_link(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    email = _form_value(form_data, "email", "").lower()
    product = build_product_service(container)
    try:
        result = product.request_workspace_sign_in_email_links(
            email=email,
            base_url=_public_app_base_url(request),
        )
    except ValueError as exc:
        return RedirectResponse(
            "/sign-in?"
            + urllib.parse.urlencode(
                {
                    "link_status": "invalid",
                    "link_email": email,
                    "link_error": str(exc or "workspace_sign_in_email_invalid"),
                }
            ),
            status_code=303,
        )
    except RuntimeError as exc:
        return RedirectResponse(
            "/sign-in?"
            + urllib.parse.urlencode(
                {
                    "link_status": "failed",
                    "link_email": email,
                    "link_error": str(exc or "workspace_sign_in_email_delivery_not_configured"),
                }
            ),
            status_code=303,
        )
    query = {
        "link_status": str(result.get("status") or "failed").strip() or "failed",
        "link_email": str(result.get("email") or email).strip().lower(),
        "link_count": str(int(result.get("sent_total") or 0)),
        "link_failed_total": str(int(result.get("failed_total") or 0)),
    }
    if str(query["link_status"]) == "failed":
        first_error = next(
            (
                str(item.get("error") or "").strip()
                for item in list(result.get("items") or [])
                if str(item.get("error") or "").strip()
            ),
            "",
        )
        if first_error:
            query["link_error"] = first_error
    return RedirectResponse("/sign-in?" + urllib.parse.urlencode(query), status_code=303)


@router.post("/sign-in/google")
async def sign_in_google(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> RedirectResponse:
    from app.services.google_oauth import build_google_oauth_start

    try:
        packet = build_google_oauth_start(
            principal_id="",
            scope_bundle="identity",
            redirect_uri_override=f"{_public_app_base_url(request)}/google/callback",
            return_to="/sign-in?google_connected=1",
            browser_source="sign_in",
        )
    except RuntimeError as exc:
        return RedirectResponse(
            "/sign-in?"
            + urllib.parse.urlencode(
                {
                    "google_error": str(exc or "google_oauth_not_ready"),
                }
            ),
            status_code=303,
        )
    return RedirectResponse(str(packet.auth_url), status_code=303)


@router.get("/register", response_class=HTMLResponse)
def register_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    if principal_id:
        build_product_service(container).record_surface_event(
            principal_id=principal_id,
            event_type="activation_opened",
            surface="register",
        )
    return _render_public_template(
        request,
        "register.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title="Create your property workspace" if request_brand(request)["key"] == "propertyquarry" else "Start your workspace",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
        ),
    )


@router.api_route("/workspace-invites/{token}", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def workspace_invite_preview(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> HTMLResponse:
    product = build_product_service(container)
    invite = product.preview_workspace_invitation(token=token)
    if invite is None:
        return _render_secure_link_page(
            request,
            page_title="Workspace invite unavailable",
            current_nav="sign-in",
            link_kicker="Invite unavailable",
            link_title="This workspace invite is no longer valid.",
            link_summary="Ask the workspace owner to send a fresh invitation or use a current sign-in link if you already have access.",
            link_detail_title="What happened",
            link_status_label="Invite unavailable",
            link_rows=[
                {"label": "Invite status", "value": "Unavailable", "detail": "The invite may be expired, revoked, or already replaced."},
                {"label": "Next step", "value": "Request a fresh invite", "detail": "Use sign in if you already have another secure link."},
            ],
            primary_action_href="/sign-in",
            primary_action_label="Request new sign-in link",
            secondary_action_href="/register",
            secondary_action_label="Create account",
            status_code=404,
        )
    access_url = str(invite.get("access_url") or "").strip()
    if access_url:
        response = RedirectResponse(access_url, status_code=303)
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
        return response
    return _render_secure_link_page(
        request,
        page_title="Review workspace invite",
        current_nav="sign-in",
        link_kicker="Workspace invitation",
        link_title="Review this workspace invite before you join.",
        link_summary="This secure invite opens one executive office. Accept it when you are ready to enter with the role below.",
        link_detail_title="Invite details",
        link_status_label=str(invite.get("status") or "pending").replace("_", " ").title(),
        link_rows=[
            {"label": "Email", "value": str(invite.get("email") or "Unknown"), "detail": ""},
            {"label": "Role", "value": str(invite.get("role") or "operator").replace("_", " ").title(), "detail": ""},
            {
                "label": "Expires",
                "value": str(invite.get("expires_at") or "Not recorded")[:19] or "Not recorded",
                "detail": "Accept before the invite expires so the workspace can issue access cleanly.",
            },
        ],
        primary_action_href=f"/workspace-invites/{urllib.parse.quote(token, safe='')}/accept",
        primary_action_label="Accept invitation",
        secondary_action_href="/sign-in",
        secondary_action_label="Return through existing access",
    )


@router.api_route("/workspace-access/{token}", methods=["GET", "HEAD"], response_model=None, include_in_schema=False)
def workspace_access_session(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
):
    product = build_product_service(container)
    brand = request_brand(request)
    actor = str(request.headers.get("X-EA-Operator-ID") or request.headers.get("X-EA-Principal-ID") or "").strip()
    session = product.open_workspace_access_session(token=token, actor=actor)
    if session is None:
        return _render_secure_link_page(
            request,
            page_title="Sign-in link unavailable",
            current_nav="sign-in",
            link_kicker="Secure link expired",
            link_title="This sign-in link is no longer valid.",
            link_summary="Request a fresh sign-in link or use another secure workspace path such as an invite, current session, or SSO.",
            link_detail_title="What to do next",
            link_status_label="Link expired",
            link_rows=[
                {"label": "Link state", "value": "Expired or revoked", "detail": "Secure workspace links rotate and eventually expire."},
                {"label": "Recovery", "value": "Request a new link", "detail": "Use the same inbox that already has workspace access."},
            ],
            primary_action_href="/sign-in",
            primary_action_label="Request new sign-in link",
            secondary_action_href="/register",
            secondary_action_label="Create account",
            status_code=404,
        )
    target = _normalize_browser_return_to(
        request.query_params.get("return_to") or str(session.get("default_target") or "").strip(),
        default=str(brand.get("app_home") or "/app/today"),
    )
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        "ea_workspace_session",
        str(session.get("access_token") or "").strip(),
        **_workspace_session_cookie_kwargs(request, expires_at=str(session.get("expires_at") or "").strip()),
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


@router.api_route("/workspace-invites/{token}/accept", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def workspace_invite_accept(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    product = build_product_service(container)
    actor = str(
        getattr(access_identity, "email", "")
        or request.headers.get("X-EA-Operator-ID")
        or request.headers.get("X-EA-Principal-ID")
        or "workspace_invite"
    ).strip() or "workspace_invite"
    try:
        invite = product.accept_workspace_invitation(token=token, accepted_by=actor)
    except ValueError as exc:
        if str(exc or "").strip() == "operator_seat_limit_reached":
            return _render_secure_link_page(
                request,
                page_title="Invite cannot be accepted",
                current_nav="sign-in",
                link_kicker="Workspace full",
                link_title="This workspace cannot add another operator right now.",
                link_summary="The office is at its current operator seat limit. Ask the workspace owner to free a seat or upgrade the plan before retrying.",
                link_detail_title="Why acceptance stopped",
                link_status_label="Seat limit reached",
                link_rows=[
                    {"label": "Invite status", "value": "Pending", "detail": "The invite is still valid, but the workspace needs room before it can be accepted."},
                    {"label": "Next step", "value": "Contact the workspace owner", "detail": "They can revoke an unused seat or expand the plan and resend access."},
                ],
                primary_action_href="/sign-in",
                primary_action_label="Return to sign in",
                secondary_action_href="/register",
                secondary_action_label="Create account",
                status_code=409,
            )
        raise
    if invite is None:
        return _render_secure_link_page(
            request,
            page_title="Workspace invite unavailable",
            current_nav="sign-in",
            link_kicker="Invite unavailable",
            link_title="This workspace invite is no longer valid.",
            link_summary="Ask the workspace owner to send a fresh invitation or use another secure workspace link if you already have access.",
            link_detail_title="What happened",
            link_status_label="Invite unavailable",
            link_rows=[
                {"label": "Invite state", "value": "Unavailable", "detail": "The invite may be expired, revoked, or already used."},
                {"label": "Next step", "value": "Request a fresh invite", "detail": "A new secure link will reopen the correct workspace."},
            ],
            primary_action_href="/sign-in",
            primary_action_label="Request new sign-in link",
            secondary_action_href="/register",
            secondary_action_label="Create account",
            status_code=404,
        )
    access_url = str(invite.get("access_url") or "").strip()
    if access_url:
        response = RedirectResponse(access_url, status_code=303)
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
        return response
    return _render_secure_link_page(
        request,
        page_title="Workspace invite accepted",
        current_nav="sign-in",
        link_kicker="Invitation accepted",
        link_title="Your workspace invite was accepted.",
        link_summary="Continue through sign in if you need another secure access link for this workspace.",
        link_detail_title="Accepted access",
        link_status_label=str(invite.get("status") or "accepted").replace("_", " ").title(),
        link_rows=[
            {"label": "Email", "value": str(invite.get("email") or "Workspace teammate"), "detail": ""},
            {"label": "Role", "value": str(invite.get("role") or "operator").replace("_", " ").title(), "detail": ""},
        ],
        primary_action_href="/sign-in",
        primary_action_label="Continue to sign in",
        secondary_action_href=str(request_brand(request).get("app_home") or "/app/today"),
        secondary_action_label="Open current session",
    )


@router.get("/get-started", response_class=HTMLResponse)
def get_started() -> RedirectResponse:
    return RedirectResponse("/register", status_code=307)


@router.get("/app", response_class=HTMLResponse)
def app_root(request: Request) -> RedirectResponse:
    return RedirectResponse(str(request_brand(request).get("app_home") or "/app/today"), status_code=307)


def _object_detail_row(
    title: str,
    detail: str,
    tag: str,
    href: str = "",
    action_href: str = "",
    action_label: str = "",
    action_value: str = "",
    action_method: str = "",
    return_to: str = "",
    secondary_action_href: str = "",
    secondary_action_label: str = "",
    secondary_action_value: str = "",
    secondary_action_method: str = "",
    secondary_return_to: str = "",
    tertiary_action_href: str = "",
    tertiary_action_label: str = "",
    tertiary_action_value: str = "",
    tertiary_action_method: str = "",
    tertiary_return_to: str = "",
    quaternary_action_href: str = "",
    quaternary_action_label: str = "",
    quaternary_action_value: str = "",
    quaternary_action_method: str = "",
    quaternary_return_to: str = "",
) -> dict[str, str]:
    row = {
        "title": str(title or "").strip(),
        "detail": str(detail or "").strip(),
        "tag": str(tag or "").strip(),
    }
    if href:
        row["href"] = href
    if action_href:
        row["action_href"] = action_href
    if action_label:
        row["action_label"] = action_label
    if action_value:
        row["action_value"] = action_value
    if action_method:
        row["action_method"] = action_method
    if return_to:
        row["return_to"] = return_to
    if secondary_action_href:
        row["secondary_action_href"] = secondary_action_href
    if secondary_action_label:
        row["secondary_action_label"] = secondary_action_label
    if secondary_action_value:
        row["secondary_action_value"] = secondary_action_value
    if secondary_action_method:
        row["secondary_action_method"] = secondary_action_method
    if secondary_return_to:
        row["secondary_return_to"] = secondary_return_to
    if tertiary_action_href:
        row["tertiary_action_href"] = tertiary_action_href
    if tertiary_action_label:
        row["tertiary_action_label"] = tertiary_action_label
    if tertiary_action_value:
        row["tertiary_action_value"] = tertiary_action_value
    if tertiary_action_method:
        row["tertiary_action_method"] = tertiary_action_method
    if tertiary_return_to:
        row["tertiary_return_to"] = tertiary_return_to
    if quaternary_action_href:
        row["quaternary_action_href"] = quaternary_action_href
    if quaternary_action_label:
        row["quaternary_action_label"] = quaternary_action_label
    if quaternary_action_value:
        row["quaternary_action_value"] = quaternary_action_value
    if quaternary_action_method:
        row["quaternary_action_method"] = quaternary_action_method
    if quaternary_return_to:
        row["quaternary_return_to"] = quaternary_return_to
    return row


def _evidence_detail_rows(items) -> list[dict[str, str]]:  # type: ignore[no-untyped-def]
    rows: list[dict[str, str]] = []
    for item in items or ():
        rows.append(
            _object_detail_row(
                str(getattr(item, "note", "") or getattr(item, "ref", "") or "Supporting evidence"),
                str(getattr(item, "ref", "") or "No external reference attached."),
                str(getattr(item, "source_type", "") or "Evidence"),
            )
        )
    if rows:
        return rows
    return [_object_detail_row("No supporting evidence yet", "This object has no attached evidence refs yet.", "Pending")]


def _render_console_object_detail(
    *,
    request: Request,
    context: RequestContext,
    workspace_label: str,
    page_title: str,
    current_nav: str,
    console_title: str,
    console_summary: str,
    object_kind: str,
    object_title: str,
    object_summary: str,
    object_meta: list[dict[str, str]],
    object_media: dict[str, object] | None = None,
    object_ooda_title: str = "",
    object_ooda_copy: str = "",
    object_ooda_rows: list[dict[str, str]] | None = None,
    object_sidebar_title: str,
    object_sidebar_copy: str,
    object_sidebar_rows: list[dict[str, str]],
    object_sections: list[dict[str, object]],
    object_sidebar_form: dict[str, object] | None = None,
    object_feedback: dict[str, object] | None = None,
) -> HTMLResponse:
    return _render_public_template(
        request,
        "app/object_detail.html",
        **{
            **_console_shell_context(
                request=request,
                page_title=page_title,
                current_nav=current_nav,
                context=context,
                console_title=console_title,
                console_summary=console_summary,
                nav_groups=app_nav_groups_for_brand(request_brand(request)["key"]),
                workspace_label=workspace_label,
                cards=[],
                stats=[{"label": item["label"], "value": item["value"]} for item in object_meta],
            ),
            "object_kind": object_kind,
            "object_title": object_title,
            "object_summary": object_summary,
            "object_meta": object_meta,
            "object_media": object_media or {},
            "object_ooda_title": object_ooda_title,
            "object_ooda_copy": object_ooda_copy,
            "object_ooda_rows": object_ooda_rows or [],
            "object_sidebar_title": object_sidebar_title,
            "object_sidebar_copy": object_sidebar_copy,
            "object_sidebar_rows": object_sidebar_rows,
            "object_sections": object_sections,
            "object_sidebar_form": object_sidebar_form or {},
            "object_feedback": object_feedback or {},
        },
    )


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
    return facts


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
    rooms_value = str(facts.get("rooms") or facts.get("room_count") or "").strip()
    if area_value or rooms_value:
        detail = " | ".join(
            part for part in (
                f"{rooms_value} rooms" if rooms_value else "",
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
                f"{facts.get('rooms')} rooms" if facts.get("rooms") else "",
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
                f"{facts.get('rooms')} rooms" if facts.get("rooms") else "",
                f"{facts.get('area_m2')} m2" if facts.get("area_m2") else "",
            ) if part
        ) or "Unknown"
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
        allowed.update({"properties", "shortlist", "research", "profile", "alerts", "billing", "settings"})
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
                workspace_label=str(workspace.get("name") or "PropertyQuarry Workspace"),
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
            workspace_label=str(workspace.get("name") or "PropertyQuarry Workspace"),
            cards=list(payload["cards"]),
            stats=list(payload["stats"]),
            console_form=dict(payload.get("console_form") or {}),
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
    return RedirectResponse("/register", status_code=307)


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
