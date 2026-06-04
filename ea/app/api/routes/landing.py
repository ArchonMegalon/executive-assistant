from __future__ import annotations

import html
import hmac
import os
import hashlib
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
        learning_summary = dict(
            product.property_feedback_learning_summary(
                principal_id=principal_id,
                person_id=str(preferences.get("preference_person_id") or "self").strip() or "self",
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
        "property_type_options": property_type_options_catalog(),
        "country_label": property_country_label(selected_country),
        "language_label": property_language_label(preferences.get("language_code"), country_code=selected_country),
        "listing_mode_label": property_listing_mode_label(preferences.get("listing_mode")),
        "property_type_label": property_type_label_for_value(preferences.get("property_type")),
        "provider_total_for_country": len(country_provider_options),
        "preferences": preferences,
        "selected_platforms": list(selected_platforms),
        "run": run_payload,
        "recent_matches": recent_matches,
        "learning_summary": learning_summary,
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
    object_sidebar_title: str,
    object_sidebar_copy: str,
    object_sidebar_rows: list[dict[str, str]],
    object_sections: list[dict[str, object]],
    object_sidebar_form: dict[str, object] | None = None,
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
            "object_sidebar_title": object_sidebar_title,
            "object_sidebar_copy": object_sidebar_copy,
            "object_sidebar_rows": object_sidebar_rows,
            "object_sections": object_sections,
            "object_sidebar_form": object_sidebar_form or {},
        },
    )


def _property_candidate_ref(candidate: dict[str, object]) -> str:
    raw = "|".join(
        str(candidate.get(key) or "").strip()
        for key in ("title", "property_url", "review_url", "tour_url", "source_label")
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


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
        "distance_pharmacy_m": "Pharmacy",
        "distance_underground_m": "Underground",
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


@router.get("/app/research/{candidate_ref}", response_class=HTMLResponse)
def property_research_packet(
    candidate_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    run_id: str = Query(default=""),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
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
    facts = dict(candidate.get("property_facts") or {})
    match_reasons = [str(item).strip() for item in list(candidate.get("match_reasons") or []) if str(item).strip()]
    mismatch_reasons = [str(item).strip() for item in list(candidate.get("mismatch_reasons") or []) if str(item).strip()]
    fit_summary = str(candidate.get("fit_summary") or candidate.get("detail") or "No fit summary captured.").strip()
    review_url = str(candidate.get("review_url") or "").strip()
    tour_url = str(candidate.get("tour_url") or "").strip()
    property_url = str(candidate.get("property_url") or "").strip()
    source_label = str(candidate.get("source_label") or "Property scout").strip() or "Property scout"
    title = str(candidate.get("title") or property_url or "Research packet").strip() or "Research packet"
    run_target = f"/app/research/{candidate_ref}" + (f"?run_id={urllib.parse.quote(run_id, safe='')}" if str(run_id or "").strip() else "")
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "PropertyQuarry Workspace"),
        page_title=f"PropertyQuarry {title}",
        current_nav="research",
        console_title=title,
        console_summary="Internal property dossier with fit reasoning, supporting facts, and next research actions.",
        object_kind="Research packet",
        object_title=title,
        object_summary=f"{fit_summary} · {source_label}",
        object_meta=[
            {"label": "Source", "value": source_label},
            {"label": "Recommendation", "value": str(candidate.get("tag") or candidate.get("recommendation") or "Candidate").strip() or "Candidate"},
            {"label": "Run", "value": str(run_id or "latest").strip() or "latest"},
            {"label": "Packet", "value": str(candidate_ref)},
        ],
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
                tour_url or "No hosted 360 tour exists for this candidate yet.",
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
        ],
        object_sections=[
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
                "eyebrow": "Research next",
                "title": "What still needs verification",
                "items": [
                    _object_detail_row(
                        "Confirm missing building facts",
                        "Lift, heating, exact address, and neighbourhood distances should be explicit before a human spends more time here.",
                        "Follow-up",
                    ),
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
        ],
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
        return _render_public_template(
            request,
            "app/property_workspace.html",
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
