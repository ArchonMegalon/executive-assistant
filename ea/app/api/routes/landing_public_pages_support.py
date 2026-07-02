from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.dependencies import get_cloudflare_access_identity, get_container, require_operator_context
from app.api.routes.landing_archive_support import _archive_home_html, _archive_publication_html_path, _is_archive_host
from app.api.routes.landing_content import (
    EA_DOC_LINKS,
    EA_LANDING_FAQS,
    FEATURE_CARDS,
    HOW_STEPS,
    PRICING_TIERS,
    PRODUCT_MODULES,
    PROPERTY_DOC_LINKS,
    PROPERTY_LANDING_FAQS,
    app_nav_groups_for_brand,
    trust_cards_for_brand,
)
from app.api.routes.landing_public_support import (
    _activation_preview_for_brand,
    _load_status,
    _public_context,
    _public_page_context,
    _render_public_template,
)
from app.api.routes.landing_shared_support import _load_project_mode_payloads
from app.container import AppContainer
from app.services.cloudflare_access import CloudflareAccessIdentity
from app.services.public_branding import request_brand


def landing(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    if _is_archive_host(request):
        return HTMLResponse(_archive_home_html(), headers={"Cache-Control": "no-store"})
    principal_id, status = _load_status(request=request, container=container, access_identity=access_identity)
    brand = request_brand(request)
    activation_preview = _activation_preview_for_brand(brand["key"], status)
    is_ea = brand["key"] == "ea"
    landing_faqs = EA_LANDING_FAQS if is_ea else PROPERTY_LANDING_FAQS
    doc_links = EA_DOC_LINKS if is_ea else PROPERTY_DOC_LINKS
    trust_cards = trust_cards_for_brand(brand["key"])
    seo_title = (
        "Executive Assistant | Morning memo, decision queue, commitments"
        if is_ea
        else f"{brand['name']} | Property search, shortlist, research"
    )
    seo_description = (
        "Executive Assistant gives one office a morning memo, decision queue, commitment ledger, and review-first approvals in one Today view."
        if is_ea
        else "PropertyQuarry keeps one property brief, one ranked sweep, one shortlist, and one research loop in a single review surface."
    )
    return _render_public_template(
        request,
        "propertyquarry_home.html" if brand["key"] == "propertyquarry" else "ea/home.html",
        indexable=True,
        **_public_context(
            request=request,
            current_nav="product",
            page_title=seo_title,
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "feature_cards": FEATURE_CARDS,
                "how_steps": HOW_STEPS,
                "trust_cards": trust_cards,
                "landing_faqs": landing_faqs,
                "doc_links": doc_links,
                "activation_preview": activation_preview,
                **_public_page_context(
                    request=request,
                    page_title=seo_title,
                    page_description=seo_description,
                    path="/",
                    faq_rows=landing_faqs,
                ),
            },
        ),
    )


def archive_publication_page(archive_slug: str, request: Request) -> HTMLResponse:
    if not _is_archive_host(request):
        raise HTTPException(status_code=404, detail="not_found")
    if archive_slug in {"robots.txt", "favicon.ico"}:
        raise HTTPException(status_code=404, detail="not_found")
    path = _archive_publication_html_path(archive_slug)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="archive_publication_not_found")
    return HTMLResponse(path.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


def project_modes_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
    _: None = Depends(require_operator_context),
) -> HTMLResponse:
    principal_id, status = _load_status(request=request, container=container, access_identity=access_identity)
    modes_payload, show_payload = _load_project_mode_payloads()
    display_names = {
        "EA_CORE": "EA Core",
        "MEMORIAL": "Memorial",
        "PROVIDER_LAB": "Provider Lab",
        "CHUMMER_RELEASE_CONTROL": "Chummer Release Control",
        "PROPERTY": "Property",
    }
    mode_rows = []
    for mode in list(modes_payload.get("modes") or []):
        if not isinstance(mode, dict):
            continue
        key = str(mode.get("key") or "").strip()
        mode_rows.append(
            {
                "key": key,
                "display_name": display_names.get(key, key.replace("_", " ").title()),
                "status": str(mode.get("status") or "").strip(),
                "status_class": "blocked" if key == "MEMORIAL" and str(mode.get("status") or "") == "separate_risk_zone" else "ready",
                "purpose": str(mode.get("purpose") or "").strip(),
                "design_language": str(mode.get("design_language") or "").strip(),
                "hard_gate": str(mode.get("hard_gate") or "").strip(),
            }
        )
    return _render_public_template(
        request,
        "project_modes.html",
        **_public_context(
            request=request,
            current_nav="modes",
            page_title=f"{request_brand(request)['name']} Project Modes",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={"project_modes": mode_rows, "show_manifest": show_payload},
        ),
    )


def product_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(request=request, container=container, access_identity=access_identity)
    brand = request_brand(request)
    if brand["key"] == "ea":
        return RedirectResponse("/", status_code=307)
    return _render_public_template(
        request,
        "product_page.html",
        indexable=True,
        **_public_context(
            request=request,
            current_nav="product",
            page_title=f"{brand['name']} Product",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "product_modules": PRODUCT_MODULES,
                "app_nav_groups": app_nav_groups_for_brand(brand["key"]),
                **_public_page_context(
                    request=request,
                    page_title=f"{brand['name']} Product",
                    page_description="PropertyQuarry turns one property brief, one provider sweep, and one shortlist into a visible research loop.",
                    path="/product",
                ),
            },
        ),
    )


def integrations_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(request=request, container=container, access_identity=access_identity)
    brand = request_brand(request)
    return _render_public_template(
        request,
        "ea/integrations.html" if brand["key"] == "ea" else "integrations_page.html",
        indexable=True,
        **_public_context(
            request=request,
            current_nav="integrations",
            page_title=f"{brand['name']} Integrations",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra=_public_page_context(
                request=request,
                page_title=f"{brand['name']} Integrations",
                page_description=(
                    "Connect only the channels that improve the office loop today, starting with optional Google identity and explicit review boundaries."
                    if brand["key"] == "ea"
                    else "Connect only the property channels that improve search, shortlist review, and research quality."
                ),
                path="/integrations",
            ),
        ),
    )


def integration_detail(
    channel_name: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(request=request, container=container, access_identity=access_identity)
    brand = request_brand(request)
    channels = dict(status.get("channels") or {})
    mapping = {
        "google": {
            "title": "Google sign-in",
            "eyebrow": "Google",
            "detail_points": (
                "Start with Google sign-in unless you already know you need broader workspace actions.",
                f"{brand['name']} only needs Google identity by default so the same account can return cleanly.",
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
                "Live messaging, manual history intake, and any future outbound sender stay visibly distinct in the product contract.",
            ),
            "body_points": (
                "Use Business onboarding only for the supported account-linking path that could later unlock live messaging.",
                "Use export intake for personal or unsupported cases without pretending it is live sync or live outbound send.",
                "Keep media inclusion, history source, future live sync, and future outbound send as separate explicit choices.",
            ),
        },
    }
    current = mapping.get(channel_name)
    if current is None:
        raise HTTPException(status_code=404, detail="integration_not_found")
    return _render_public_template(
        request,
        "channel_detail.html",
        **_public_context(
            request=request,
            current_nav="integrations",
            page_title=f"{brand['name']} {current['title']}",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "channel": dict(channels.get(channel_name) or {}),
                "channel_title": current["title"],
                "channel_eyebrow": current["eyebrow"],
                "detail_points": current["detail_points"],
                "body_points": current["body_points"],
            },
        ),
    )


def security_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(request=request, container=container, access_identity=access_identity)
    brand = request_brand(request)
    return _render_public_template(
        request,
        "ea/security.html" if brand["key"] == "ea" else "security_page.html",
        indexable=True,
        **_public_context(
            request=request,
            current_nav="security",
            page_title=f"{brand['name']} Security",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "trust_cards": trust_cards_for_brand(brand["key"]),
                **_public_page_context(
                    request=request,
                    page_title=f"{brand['name']} Security",
                    page_description=(
                        "Executive Assistant keeps signals visible, permissions explicit, and outbound actions review-first."
                        if brand["key"] == "ea"
                        else "PropertyQuarry keeps portal coverage, research posture, and review boundaries explicit."
                    ),
                    path="/security",
                ),
            },
        ),
    )


def data_deletion_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(request=request, container=container, access_identity=access_identity)
    brand = request_brand(request)
    is_ea = brand["key"] == "ea"
    contact_email = "support@example.test" if is_ea else "property@propertyquarry.com"
    return _render_public_template(
        request,
        "data_deletion_page.html",
        indexable=True,
        **_public_context(
            request=request,
            current_nav="security",
            page_title=f"{brand['name']} Data deletion",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "deletion_contact_email": contact_email,
                "deletion_mailto_subject": "Data deletion request",
                "deletion_request_items": (
                    "The workspace name or account email used during onboarding.",
                    "Which channels, imports, or linked services should be removed together.",
                    "Any deadline or legal context that changes the deletion timeline.",
                ),
                "deletion_steps": (
                    {
                        "title": "Identity check",
                        "body": (
                            "The request is matched to the right workspace and contact path before anything is deleted."
                        ),
                    },
                    {
                        "title": "Scope review",
                        "body": (
                            "The linked channels, saved state, and delivery artifacts are reviewed so the deletion covers the intended footprint."
                        ),
                    },
                    {
                        "title": "Deletion confirmation",
                        "body": (
                            "A confirmation is sent back once the requested workspace scope has been removed or if any item needs a follow-up clarification."
                        ),
                    },
                ),
                "deletion_notes": (
                    {
                        "title": "Keep the request specific",
                        "body": (
                            "A precise request is easier to execute safely than a generic \"delete everything\" message spread across multiple accounts."
                        ),
                    },
                    {
                        "title": "Exports may have separate custody",
                        "body": (
                            "If data was exported or delivered into another system, the request should name that destination too so it can be handled explicitly."
                        ),
                    },
                ),
                **_public_page_context(
                    request=request,
                    page_title=f"{brand['name']} Data deletion",
                    page_description=(
                        "Request deletion of your Executive Assistant workspace and linked channel data."
                        if is_ea
                        else "Request deletion of your PropertyQuarry workspace, shortlist, and linked search data."
                    ),
                    path="/data-deletion",
                ),
            },
        ),
    )


def pricing_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(request=request, container=container, access_identity=access_identity)
    brand = request_brand(request)
    if brand["key"] == "ea":
        return RedirectResponse("/get-started", status_code=307)
    return _render_public_template(
        request,
        "ea/pricing.html" if brand["key"] == "ea" else "pricing_page.html",
        indexable=True,
        **_public_context(
            request=request,
            current_nav="pricing",
            page_title=f"{brand['name']} Pricing",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "pricing_tiers": PRICING_TIERS,
                **_public_page_context(
                    request=request,
                    page_title=f"{brand['name']} Pricing",
                    page_description=(
                        "Choose the Executive Assistant plan that matches office load, review depth, and delivery posture."
                        if brand["key"] == "ea"
                        else "Choose the PropertyQuarry plan that matches search volume, research depth, and shortlist complexity."
                    ),
                    path="/pricing",
                ),
            },
        ),
    )


def docs_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(request=request, container=container, access_identity=access_identity)
    brand = request_brand(request)
    if brand["key"] == "ea":
        return RedirectResponse("/security", status_code=307)
    doc_links = EA_DOC_LINKS if brand["key"] == "ea" else PROPERTY_DOC_LINKS
    return _render_public_template(
        request,
        "ea/docs.html" if brand["key"] == "ea" else "docs_page.html",
        indexable=True,
        **_public_context(
            request=request,
            current_nav="docs",
            page_title=f"{brand['name']} Docs",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "doc_links": doc_links,
                **_public_page_context(
                    request=request,
                    page_title=f"{brand['name']} Docs",
                    page_description=(
                        "Read the product, security, and runtime references behind the office loop."
                        if brand["key"] == "ea"
                        else "Read the product, provider, and runtime references behind the property workflow."
                    ),
                    path="/docs",
                ),
            },
        ),
    )
