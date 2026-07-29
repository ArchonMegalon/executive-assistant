from __future__ import annotations

import urllib.parse

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from markupsafe import Markup

from app.api.dependencies import (
    RequestContext,
    _workspace_session_payload,
    get_cloudflare_access_identity,
    get_container,
    get_request_context,
)
from app.api.routes.landing_browser import _form_value, _normalize_browser_return_to, _shared_browser_fields, _workspace_session_cookie_kwargs
from app.api.routes.landing_content import sign_in_notes_for_brand
from app.api.routes.property_surface_boundary import is_property_app_surface_path
from app.api.routes.landing_public_support import (
    _activation_preview_for_brand,
    _load_status,
    _public_app_base_url,
    _public_context,
    _render_public_template,
    _render_secure_link_page,
)
from app.container import AppContainer
from app.product.service import build_product_service, workspace_sign_in_email_delivery_available
from app.services.cloudflare_access import CloudflareAccessIdentity
from app.services.public_branding import request_brand


def _brand_create_account_href(brand: dict[str, str]) -> str:
    return "/register" if str(brand.get("key") or "").strip().lower() == "propertyquarry" else "/get-started"


def _brand_safe_return_target(brand: dict[str, str], target: str) -> str:
    normalized_target = str(target or "").strip() or str(brand.get("app_home") or "/app/today")
    if str(brand.get("key") or "").strip().lower() != "ea":
        return normalized_target
    if is_property_app_surface_path(urllib.parse.urlsplit(normalized_target).path):
        return str(brand.get("app_home") or "/app/today")
    return normalized_target


def _trusted_public_actor(
    *,
    request: Request,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
    default_actor: str,
) -> str:
    workspace_session = _workspace_session_payload(request, container)
    authenticated_context: RequestContext | None = None
    try:
        authenticated_context = get_request_context(request, container, access_identity)
    except HTTPException:
        authenticated_context = None
    actor_context = authenticated_context or RequestContext(principal_id="", authenticated=False)
    actor = str(
        getattr(access_identity, "email", "")
        or str(actor_context.access_email or "").strip().lower()
        or str(actor_context.operator_id or "").strip()
        or str(actor_context.principal_id or "").strip()
        or str((workspace_session or {}).get("email") or "").strip().lower()
        or str((workspace_session or {}).get("operator_id") or "").strip()
        or str((workspace_session or {}).get("principal_id") or "").strip()
        or default_actor
    ).strip()
    return actor or default_actor


def sign_in_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(request=request, container=container, access_identity=access_identity)
    link_status = str(request.query_params.get("link_status") or "").strip()
    link_email = str(request.query_params.get("link_email") or "").strip()
    google_error = str(request.query_params.get("google_error") or "").strip()
    brand = request_brand(request)
    sign_in_return_to = _brand_safe_return_target(
        brand,
        _normalize_browser_return_to(
            request.query_params.get("return_to"),
            default=str(brand.get("app_home") or "/app/today"),
        ),
    )
    return _render_public_template(
        request,
        "sign_in.html",
        **_public_context(
            request=request,
            current_nav="sign-in",
            page_title=f"Sign in to {brand['name']}",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "sign_in_notes": sign_in_notes_for_brand(brand["key"]),
                "sign_in_link_enabled": workspace_sign_in_email_delivery_available(),
                "sign_in_link_status": link_status,
                "sign_in_link_email": link_email,
                "sign_in_google_error": google_error,
                "sign_in_return_to": sign_in_return_to,
            },
        ),
    )


async def sign_in_email_link(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    email = _form_value(form_data, "email", "").lower()
    brand = request_brand(request)
    return_to = _brand_safe_return_target(
        brand,
        _normalize_browser_return_to(
            _form_value(form_data, "return_to", ""),
            default=str(brand.get("app_home") or "/app/today"),
        ),
    )
    product = build_product_service(container)
    try:
        result = product.request_workspace_sign_in_email_links(
            email=email,
            base_url=_public_app_base_url(request),
            default_target=return_to,
        )
    except ValueError:
        return RedirectResponse(
            "/sign-in?" + urllib.parse.urlencode({"link_status": "invalid"}),
            status_code=303,
        )
    except RuntimeError:
        return RedirectResponse(
            "/sign-in?" + urllib.parse.urlencode({"link_status": "failed"}),
            status_code=303,
        )
    internal_status = str(result.get("status") or "failed").strip() or "failed"
    # Do not turn the public form into an account-enumeration endpoint. A valid
    # request gets the same confirmation whether or not a matching workspace
    # exists; delivery failures remain honest without exposing provider detail.
    public_status = "requested" if internal_status in {"sent", "partial", "not_found"} else "failed"
    query = {"link_status": public_status}
    return RedirectResponse("/sign-in?" + urllib.parse.urlencode(query), status_code=303)


async def sign_in_google(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> RedirectResponse:
    del container
    brand = request_brand(request)
    return_to = _brand_safe_return_target(
        brand,
        _normalize_browser_return_to(
            request.query_params.get("return_to"),
            default=str(brand.get("app_home") or "/app/today"),
        ),
    )
    return RedirectResponse(
        "/sign-in?"
        + urllib.parse.urlencode(
            {
                "google_error": "Use the secure email link for workspace access. Connect Google from Settings after you sign in.",
                "return_to": return_to,
            }
        ),
        status_code=303,
    )


def register_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
):
    principal_id, status = _load_status(request=request, container=container, access_identity=access_identity)
    brand = request_brand(request)
    if principal_id:
        build_product_service(container).record_surface_event(principal_id=principal_id, event_type="activation_opened", surface="register")
    if brand["key"] == "ea":
        response = RedirectResponse("/get-started", status_code=307)
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
        return response
    return _render_public_template(
        request,
        "register.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title="Create your property workspace" if brand["key"] == "propertyquarry" else "Start your workspace",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
        ),
    )


def workspace_invite_preview(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> HTMLResponse:
    product = build_product_service(container)
    invite = product.preview_workspace_invitation(token=token)
    if invite is None:
        create_account_href = _brand_create_account_href(request_brand(request))
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
            secondary_action_href=create_account_href,
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
            {"label": "Expires", "value": str(invite.get("expires_at") or "Not recorded")[:19] or "Not recorded", "detail": "Accept before the invite expires so the workspace can issue access cleanly."},
        ],
        primary_action_href=f"/workspace-invites/{urllib.parse.quote(token, safe='')}/accept",
        primary_action_label="Accept invitation",
        secondary_action_href="/sign-in",
        secondary_action_label="Return through existing access",
    )


def workspace_access_session(token: str, request: Request, container: AppContainer = Depends(get_container)):
    product = build_product_service(container)
    brand = request_brand(request)
    try:
        access_identity = get_cloudflare_access_identity(request, container)
    except HTTPException:
        access_identity = None
    actor = _trusted_public_actor(
        request=request,
        container=container,
        access_identity=access_identity,
        default_actor="workspace_access",
    )
    session = product.open_workspace_access_session(token=token, actor=actor)
    if session is None:
        create_account_href = _brand_create_account_href(brand)
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
            secondary_action_href=create_account_href,
            secondary_action_label="Create account",
            status_code=404,
        )
    session_default_target = str(session.get("default_target") or "").strip() or str(brand.get("app_home") or "/app/today")
    target = _normalize_browser_return_to(request.query_params.get("return_to") or session_default_target, default=session_default_target)
    target = _brand_safe_return_target(brand, target)
    response = RedirectResponse(target, status_code=303)
    response.set_cookie("ea_workspace_session", str(session.get("access_token") or "").strip(), **_workspace_session_cookie_kwargs(request, expires_at=str(session.get("expires_at") or "").strip()))
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


def workspace_invite_accept(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    product = build_product_service(container)
    actor = _trusted_public_actor(
        request=request,
        container=container,
        access_identity=access_identity,
        default_actor="workspace_invite",
    )
    try:
        invite = product.accept_workspace_invitation(token=token, accepted_by=actor)
    except ValueError as exc:
        if str(exc or "").strip() == "operator_seat_limit_reached":
            create_account_href = _brand_create_account_href(request_brand(request))
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
                secondary_action_href=create_account_href,
                secondary_action_label="Create account",
                status_code=409,
            )
        raise
    if invite is None:
        create_account_href = _brand_create_account_href(request_brand(request))
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
            secondary_action_href=create_account_href,
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


def get_started(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(request=request, container=container, access_identity=access_identity)
    brand = request_brand(request)
    if principal_id:
        build_product_service(container).record_surface_event(principal_id=principal_id, event_type="activation_opened", surface="get_started")
    activation_preview = _activation_preview_for_brand(brand["key"], status)
    return _render_public_template(
        request,
        "ea/get_started.html" if brand["key"] == "ea" else "get_started.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title="Get started" if brand["key"] == "ea" else "Get started with PropertyQuarry",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "activation_preview": activation_preview,
                "google": dict(status.get("channels") or {}).get("google") or {},
                "shared_browser_fields": Markup(_shared_browser_fields(principal_id=principal_id, access_identity=access_identity, container=container)),
            },
        ),
    )
