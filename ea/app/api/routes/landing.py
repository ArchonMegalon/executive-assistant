from __future__ import annotations

import html
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.dependencies import (
    RequestContext,
    browser_principal_override_allowed,
    get_cloudflare_access_identity,
    get_container,
    get_request_context,
    is_operator_context,
    require_operator_context,
)
from app.api.routes.landing_content import (
    ADMIN_NAV_GROUPS,
    APP_NAV_GROUPS,
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
)
from app.api.routes.admin_view_models import build_admin_section_payload as _build_admin_section_payload
from app.api.routes.workspace_view_models import workspace_section_payload as _workspace_section_payload
from app.container import AppContainer
from app.product.commercial import workspace_plan_for_mode
from app.product.service import build_product_service
from app.services.cloudflare_access import CloudflareAccessIdentity
from app.services.google_oauth import complete_google_oauth_callback

router = APIRouter(tags=["landing"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))


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
    return {
        "principal_id": "",
        "status": "anonymous",
        "workspace": {"name": "Executive Assistant"},
        "selected_channels": [],
        "privacy": {},
        "assistant_modes": [],
        "featured_domains": [],
        "storage_posture": {},
        "channels": {},
        "brief_preview": {},
        "next_step": "Authenticate to view or change onboarding state.",
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
        if not expected or api_token != expected:
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
    workspace = dict(status.get("workspace") or {})
    channels = dict(status.get("channels") or {})
    preview = dict(status.get("brief_preview") or {})
    selected_channels = [str(row) for row in (status.get("selected_channels") or []) if str(row).strip()]
    context: dict[str, object] = {
        "page_title": page_title,
        "public_nav": PUBLIC_NAV,
        "current_nav": current_nav,
        "access_identity": access_identity,
        "principal_id": principal_id,
        "status": status,
        "workspace": workspace,
        "privacy": dict(status.get("privacy") or {}),
        "channels": channels,
        "channel_cards": _channel_cards(channels),
        "selected_channels_label": ", ".join(selected_channels) if selected_channels else "Google Core recommended",
        "workspace_mode_label": _humanize(str(workspace.get("mode") or "personal")),
        "brief_headline": str(preview.get("headline") or "Turn your channels into a prioritized day."),
        "first_brief_items": _list_rows(
            preview.get("first_brief_preview") or preview.get("first_brief"),
            (
                "Connect Google Core for the fastest useful morning brief.",
                "Add Telegram or WhatsApp only when the real workflow needs them.",
                "Keep approvals and memory rules explicit before automating actions.",
            ),
        ),
        "suggested_actions": _list_rows(
            preview.get("suggested_actions"),
            (
                "Save the workspace posture and connect your first real channel.",
                "Generate the first brief before widening the integration footprint.",
            ),
        ),
        "trust_notes": _list_rows(
            preview.get("trust_notes"),
            (
                "Each channel says clearly what the assistant can actually do today.",
                "Approvals and durable workspace memory are visible product features, not hidden implementation details.",
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
    return {
        "page_title": page_title,
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
    response = templates.TemplateResponse(request, template_name, context)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
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


@router.get("/", response_class=HTMLResponse)
def landing(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "marketing_home.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title="Executive Assistant",
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
            page_title="Executive Assistant Integrations",
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
            "title": "Google Core",
            "eyebrow": "Google",
            "detail_points": (
                "Start with Google Core unless you already know you need wider inbox actions.",
                "Google Core is enough for drafts, delivery verification, calendar context, contacts context, and a useful first brief.",
                "Full Workspace is the explicit upgrade path when you need broader inbox or Drive context.",
            ),
            "body_points": (
                "Explain permissions in plain language first and raw scopes second.",
                "Show a real connected account and a real first success instead of treating consent as the finish line.",
                "Keep Google as the recommended first connection in the public product flow.",
            ),
        },
        "telegram": {
            "title": "Telegram",
            "eyebrow": "Telegram",
            "detail_points": (
                "Personal identity linking and official bot installation are separate decisions.",
                "Login alone does not imply generic history import.",
                "Future-only, import-later, and manual-forward are distinct promises and should stay distinct in the UI.",
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
                "The assistant should not promise generic automated history download outside those paths.",
                "Live messaging and manual history intake should stay visibly distinct in the product contract.",
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
            page_title=f"Executive Assistant {current['title']}",
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
            page_title="Executive Assistant Security",
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
            page_title="Executive Assistant Pricing",
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
            page_title="Executive Assistant Docs",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={"doc_links": DOC_LINKS},
        ),
    )


@router.get("/sign-in", response_class=HTMLResponse)
def sign_in_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "sign_in.html",
        **_public_context(
            request=request,
            current_nav="sign-in",
            page_title="Sign in to Executive Assistant",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={"sign_in_notes": SIGN_IN_NOTES},
        ),
    )


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
            page_title="Create personal workspace",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
        ),
    )


@router.get("/workspace-invites/{token}", response_class=HTMLResponse)
def workspace_invite_preview(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> HTMLResponse:
    product = build_product_service(container)
    invite = product.preview_workspace_invitation(token=token)
    if invite is None:
        raise HTTPException(status_code=404, detail="workspace_invitation_not_found")
    access_url = str(invite.get("access_url") or "").strip()
    if access_url:
        response = RedirectResponse(access_url, status_code=303)
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
        return response
    body = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="robots" content="noindex,nofollow,noarchive,nosnippet">
    <title>Executive Assistant workspace invitation</title>
  </head>
  <body>
    <main>
      <h1>Executive Assistant workspace invitation</h1>
      <p>{html.escape(str(invite.get("email") or "A teammate"))} was invited as {html.escape(str(invite.get("role") or "operator"))}.</p>
      <p>Status: {html.escape(str(invite.get("status") or "pending"))}</p>
      <p><a href="/workspace-invites/{html.escape(token)}/accept">Accept invitation</a></p>
      <p><a href="/sign-in">Workspace access</a></p>
      <p>Access still depends on the workspace identity posture. Google remains a workspace data connection, not app sign-in.</p>
    </main>
  </body>
</html>"""
    response = HTMLResponse(body)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


@router.get("/workspace-access/{token}", response_model=None)
def workspace_access_session(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
):
    product = build_product_service(container)
    actor = str(request.headers.get("X-EA-Operator-ID") or request.headers.get("X-EA-Principal-ID") or "").strip()
    session = product.open_workspace_access_session(token=token, actor=actor)
    if session is None:
        raise HTTPException(status_code=404, detail="workspace_access_session_not_found")
    target = str(request.query_params.get("return_to") or session.get("default_target") or "/app/today").strip() or "/app/today"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie("ea_workspace_session", str(session.get("access_token") or "").strip(), httponly=True, samesite="lax", path="/")
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


@router.get("/workspace-invites/{token}/accept", response_class=HTMLResponse)
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
            raise HTTPException(status_code=409, detail="operator_seat_limit_reached") from exc
        raise
    if invite is None:
        raise HTTPException(status_code=404, detail="workspace_invitation_not_found")
    access_url = str(invite.get("access_url") or "").strip()
    if access_url:
        response = RedirectResponse(access_url, status_code=303)
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
        return response
    body = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="robots" content="noindex,nofollow,noarchive,nosnippet">
    <title>Executive Assistant invitation accepted</title>
  </head>
  <body>
    <main>
      <h1>Workspace invitation accepted</h1>
      <p>{html.escape(str(invite.get("email") or "Workspace teammate"))} is now marked as {html.escape(str(invite.get("status") or "accepted"))}.</p>
      <p><a href="/sign-in">Continue to workspace access</a></p>
    </main>
  </body>
</html>"""
    response = HTMLResponse(body)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


@router.get("/get-started", response_class=HTMLResponse)
def get_started() -> RedirectResponse:
    return RedirectResponse("/register", status_code=307)


@router.get("/app", response_class=HTMLResponse)
def app_root() -> RedirectResponse:
    return RedirectResponse("/app/today", status_code=307)


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
                nav_groups=APP_NAV_GROUPS,
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
        },
    )


@router.get("/app/{section}", response_class=HTMLResponse)
def app_shell(
    section: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    allowed = {item["href"].rstrip("/").rsplit("/", 1)[-1] for group in APP_NAV_GROUPS for item in group["items"]}
    allowed.update({"channel-loop", "briefing", "inbox", "follow-ups", "memory", "contacts", "activity", "channels", "automations"})
    if section not in allowed:
        raise HTTPException(status_code=404, detail="app_section_not_found")
    resolved_section = {
        "queue": "briefing",
        "people": "memory",
    }.get(section, section)
    current_nav = {
        "briefing": "queue",
        "inbox": "queue",
        "follow-ups": "queue",
        "memory": "people",
        "contacts": "people",
        "activity": "settings",
        "channels": "settings",
        "automations": "settings",
    }.get(section, section)
    if resolved_section == "activity" and is_operator_context(context):
        return RedirectResponse("/admin/office", status_code=303)
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
                page_title="Executive Assistant Inline Loop",
                current_nav="today",
                context=context,
                console_title=str(pack.get("headline") or "Inline loop"),
                console_summary=str(pack.get("summary") or "Clear the compact office loop."),
                nav_groups=APP_NAV_GROUPS,
                workspace_label=str(workspace.get("name") or "Executive Workspace"),
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
    core_sections = {"today", "briefing", "inbox", "follow-ups", "memory", "contacts", "activity", "settings"}
    if resolved_section in core_sections:
        product = build_product_service(container)
        surface_event = {
            "today": "memo_opened",
            "briefing": "memo_opened",
            "inbox": "queue_opened",
            "follow-ups": "queue_opened",
            "memory": "people_graph_opened",
            "contacts": "evidence_opened",
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
        )
    else:
        payload = _app_section_payload(
            resolved_section,
            status,
            live_feed=_app_live_feed(container, principal_id=context.principal_id),
        )
    workspace = dict(status.get("workspace") or {})
    return _render_public_template(
        request,
        "console_shell.html",
        **_console_shell_context(
            request=request,
            page_title=f"Executive Assistant {payload['title']}",
            current_nav=current_nav,
            context=context,
            console_title=str(payload["title"]),
            console_summary=str(payload["summary"]),
            nav_groups=APP_NAV_GROUPS,
            workspace_label=str(workspace.get("name") or "Executive Workspace"),
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
    payload = _build_admin_section_payload(
        section,
        container=container,
        principal_id=context.principal_id,
        operator_id=str(context.operator_id or "").strip(),
    )
    return _render_public_template(
        request,
        "console_shell.html",
        **_console_shell_context(
            request=request,
            page_title=f"Executive Assistant Admin {payload['title']}",
            current_nav=section,
            context=context,
            console_title=str(payload["title"]),
            console_summary=str(payload["summary"]),
            nav_groups=ADMIN_NAV_GROUPS,
            workspace_label="Operator Control Plane",
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
    return RedirectResponse("/app/briefing", status_code=307)


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
                page_title=f"Executive Assistant Review {candidate.title}",
                current_nav="queue",
                context=context,
                console_title="Review extracted commitment",
                console_summary="Edit the wording, due date, or ownership before this enters the commitment ledger.",
                nav_groups=APP_NAV_GROUPS,
                workspace_label=str(workspace.get("name") or "Executive Workspace"),
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
