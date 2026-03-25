from __future__ import annotations

import html
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

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
    DOC_LINKS,
    FEATURE_CARDS,
    HOW_STEPS,
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
            preview.get("first_brief"),
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
        "principal_id": context.principal_id,
        "access_email": context.access_email,
        "operator_id": context.operator_id,
    }



def _render_public_template(request: Request, template_name: str, **context: Any) -> HTMLResponse:
    context.setdefault("request", request)
    return templates.TemplateResponse(request, template_name, context)


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
                "personas": PERSONAS,
                "trust_cards": TRUST_CARDS,
            },
        ),
    )


@router.get("/product", response_class=HTMLResponse)
def product_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "product_page.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title="Executive Assistant Product",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={"product_modules": PRODUCT_MODULES, "app_nav_groups": APP_NAV_GROUPS},
        ),
    )


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
            current_nav="docs",
            page_title="Sign in to Executive Assistant",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={"sign_in_notes": SIGN_IN_NOTES},
        ),
    )


@router.get("/get-started", response_class=HTMLResponse)
def get_started(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    channels = dict(status.get("channels") or {})
    workspace = dict(status.get("workspace") or {})
    privacy = dict(status.get("privacy") or {})
    selected_channels = {str(value) for value in (status.get("selected_channels") or []) if str(value).strip()}
    google = dict(channels.get("google") or {})
    activation_plan = workspace_plan_for_mode(str(workspace.get("mode") or "personal"))
    activation_diagnostics: dict[str, object] = {
        "plan": {
            "display_name": activation_plan.display_name,
            "unit_of_sale": activation_plan.unit_of_sale,
        },
        "billing": {
            "billing_state": activation_plan.billing_state,
            "support_tier": activation_plan.support_tier,
            "renewal_owner_role": activation_plan.renewal_owner_role,
            "contract_note": activation_plan.contract_note,
        },
        "entitlements": {
            "principal_seats": activation_plan.entitlements.principal_seats,
            "operator_seats": activation_plan.entitlements.operator_seats,
            "messaging_channels_enabled": activation_plan.entitlements.messaging_channels_enabled,
            "audit_retention": activation_plan.entitlements.audit_retention,
            "feature_flags": list(activation_plan.entitlements.feature_flags),
        },
        "operators": {
            "active_count": 0,
            "seats_used": 0,
            "seats_remaining": activation_plan.entitlements.operator_seats,
        },
        "analytics": {
            "counts": {},
        },
    }
    activation_preview = {
        "brief": (),
        "queue": (),
        "commitments": (),
    }
    if principal_id:
        product = build_product_service(container)
        snapshot = product.workspace_snapshot(principal_id=principal_id)
        activation_diagnostics = product.workspace_diagnostics(principal_id=principal_id)
        product.record_surface_event(
            principal_id=principal_id,
            event_type="activation_opened",
            surface="get_started",
        )
        activation_preview = {
            "brief": tuple(item.title for item in snapshot.brief_items[:3]),
            "queue": tuple(item.title for item in snapshot.queue_items[:3]),
            "commitments": tuple(item.statement for item in snapshot.commitments[:3]),
        }
    return _render_public_template(
        request,
        "get_started.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title="Get started with Executive Assistant",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "workspace": workspace,
                "privacy": privacy,
                "channels": channels,
                "selected_channels": selected_channels,
                "google": google,
                "activation_preview": activation_preview,
                "activation_diagnostics": activation_diagnostics,
                "activation_plan": dict(activation_diagnostics.get("plan") or {}),
                "activation_billing": dict(activation_diagnostics.get("billing") or {}),
                "activation_entitlements": dict(activation_diagnostics.get("entitlements") or {}),
                "shared_browser_fields": _shared_browser_fields(
                    principal_id=principal_id,
                    access_identity=access_identity,
                    container=container,
                ),
            },
        ),
    )


@router.get("/app", response_class=HTMLResponse)
def app_root() -> RedirectResponse:
    return RedirectResponse("/app/today", status_code=307)


@router.get("/app/people", response_class=HTMLResponse)
def people_root() -> RedirectResponse:
    return RedirectResponse("/app/memory", status_code=307)


def _object_detail_row(title: str, detail: str, tag: str) -> dict[str, str]:
    return {
        "title": str(title or "").strip(),
        "detail": str(detail or "").strip(),
        "tag": str(tag or "").strip(),
    }


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


@router.get("/app/people/{person_id}", response_class=HTMLResponse)
def person_detail(
    person_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    detail = product.get_person_detail(
        principal_id=context.principal_id,
        person_id=person_id,
        operator_id=str(context.operator_id or "").strip(),
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="person_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="people_opened",
        surface=f"people:{person_id}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_public_template(
        request,
        "app/people_detail.html",
        **{
            **_console_shell_context(
                request=request,
                page_title=f"Executive Assistant {detail.profile.display_name}",
                current_nav="memory",
                context=context,
                console_title=detail.profile.display_name,
                console_summary="Relationship context, open loops, current drafts, and evidence tied to one person.",
                nav_groups=APP_NAV_GROUPS,
                workspace_label=str(workspace.get("name") or "Executive Workspace"),
                cards=[],
                stats=[
                    {"label": "Open loops", "value": str(detail.profile.open_loops_count)},
                    {"label": "Commitments", "value": str(len(detail.commitments))},
                    {"label": "Drafts", "value": str(len(detail.drafts))},
                    {"label": "Evidence", "value": str(len(detail.evidence_refs))},
                ],
            ),
            "person": detail.profile,
            "detail": detail,
        },
    )


@router.get("/app/commitment-items/{commitment_ref:path}", response_class=HTMLResponse)
def commitment_detail(
    commitment_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    commitment = product.get_commitment(principal_id=context.principal_id, commitment_ref=commitment_ref)
    if commitment is None:
        raise HTTPException(status_code=404, detail="commitment_not_found")
    history = product.get_commitment_history(principal_id=context.principal_id, commitment_ref=commitment_ref, limit=8)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="commitment_opened",
        surface=f"commitment:{commitment_ref}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {commitment.statement}",
        current_nav="follow-ups",
        console_title=commitment.statement,
        console_summary="Commitment source, owner, due date, risk, and recent ledger activity.",
        object_kind="Commitment ledger",
        object_title=commitment.statement,
        object_summary=f"{commitment.counterparty or 'Office loop'} · {commitment.status.replace('_', ' ')}",
        object_meta=[
            {"label": "Owner", "value": str(commitment.owner or "office").replace("_", " ").title()},
            {"label": "Counterparty", "value": commitment.counterparty or "Unknown"},
            {"label": "Due", "value": str(commitment.due_at or "")[:10] or "No due date"},
            {"label": "Risk", "value": str(commitment.risk_level or "normal").title()},
        ],
        object_sidebar_title="Commitment posture",
        object_sidebar_copy="A commitment should stay visible until it is closed, deferred, dropped, or reopened with a reason.",
        object_sidebar_rows=[
            _object_detail_row("Source", str(commitment.source_type or "manual").replace("_", " ").title(), "Source"),
            _object_detail_row("Source ref", commitment.source_ref or "No source ref attached.", "Reference"),
            _object_detail_row("Last activity", str(commitment.last_activity_at or "")[:10] or "Unknown", "Activity"),
        ],
        object_sections=[
            {
                "eyebrow": "Evidence",
                "title": "Supporting proof",
                "items": _evidence_detail_rows(commitment.proof_refs),
            },
            {
                "eyebrow": "History",
                "title": "Recent ledger activity",
                "items": [
                    _object_detail_row(
                        str(item.event_type or "history").replace("_", " ").title(),
                        item.detail or "Ledger event recorded.",
                        str(item.created_at or "")[:10] or "Event",
                    )
                    for item in history
                ] or [_object_detail_row("No history yet", "No commitment history rows were recorded.", "History")],
            },
        ],
    )


@router.get("/app/decisions/{decision_ref}", response_class=HTMLResponse)
def decision_detail(
    decision_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    decision = product.get_decision(principal_id=context.principal_id, decision_ref=decision_ref)
    if decision is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="decision_opened",
        surface=f"decision:{decision_ref}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {decision.title}",
        current_nav="briefing",
        console_title=decision.title,
        console_summary="Decision context, ownership, deadline pressure, and supporting evidence.",
        object_kind="Decision queue",
        object_title=decision.title,
        object_summary=decision.summary or "This decision is open in the office loop.",
        object_meta=[
            {"label": "Priority", "value": str(decision.priority or "normal").title()},
            {"label": "Owner", "value": str(decision.owner_role or "office").replace("_", " ").title()},
            {"label": "Deadline", "value": str(decision.due_at or "")[:10] or "No due date"},
            {"label": "Status", "value": str(decision.status or "open").replace("_", " ").title()},
            {"label": "SLA", "value": str(decision.sla_status or "unscheduled").replace("_", " ").title()},
        ],
        object_sidebar_title="Decision pressure",
        object_sidebar_copy="A decision should stay tied to ownership, time pressure, and evidence instead of living as a generic card in a queue.",
        object_sidebar_rows=[
            _object_detail_row("Recommendation", decision.recommendation or "No recommendation projected yet.", "Recommend"),
            _object_detail_row("Impact", decision.impact_summary or "Impact has not been projected yet.", "Impact"),
            _object_detail_row("Rationale", decision.rationale or "No rationale projected yet.", "Why"),
            _object_detail_row("Evidence attached", f"{len(decision.evidence_refs or [])} supporting refs attached to this decision.", "Evidence"),
            _object_detail_row("SLA", str(decision.sla_status or "unscheduled").replace("_", " ").title(), "SLA"),
            _object_detail_row("Why now", decision.summary or "This decision is still active in the queue.", "Priority"),
        ],
        object_sections=[
            {
                "eyebrow": "Decision summary",
                "title": "Current recommendation",
                "items": [
                    _object_detail_row(
                        decision.title,
                        decision.recommendation or decision.summary or "Review this decision with its current evidence and owner context.",
                        str(decision.priority or "normal").title(),
                    ),
                    _object_detail_row("Options", ", ".join(decision.options or ()) or "No explicit options projected.", "Options"),
                    _object_detail_row("Impact", decision.impact_summary or "No projected downstream impact yet.", "Impact"),
                    _object_detail_row("Related commitments", ", ".join(decision.related_commitment_ids or ()) or "No linked commitments.", "Commitment"),
                    _object_detail_row("Related people", ", ".join(decision.related_people or ()) or "No linked people.", "People"),
                    _object_detail_row("Resolution note", decision.resolution_reason or "No explicit resolution note yet.", "Resolution"),
                ],
            },
            {
                "eyebrow": "Evidence",
                "title": "Supporting evidence",
                "items": _evidence_detail_rows(decision.evidence_refs),
            },
        ],
    )


@router.get("/app/handoffs/{handoff_ref:path}", response_class=HTMLResponse)
def handoff_detail(
    handoff_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    handoff = product.get_handoff(principal_id=context.principal_id, handoff_ref=handoff_ref)
    if handoff is None:
        raise HTTPException(status_code=404, detail="handoff_not_found")
    task_id = handoff.id.split(":", 1)[1] if handoff.id.startswith("human_task:") else handoff.id
    history_rows = container.orchestrator.list_human_task_assignment_history(task_id, principal_id=context.principal_id, limit=8)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="handoff_opened",
        surface=f"handoff:{handoff_ref}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {handoff.summary}",
        current_nav="activity",
        console_title=handoff.summary,
        console_summary="Assignment state, escalation pressure, evidence, and recent handoff routing history.",
        object_kind="Handoffs",
        object_title=handoff.summary,
        object_summary=f"{handoff.owner or 'Office'} · {handoff.status.replace('_', ' ')}",
        object_meta=[
            {"label": "Owner", "value": handoff.owner or "Unassigned"},
            {"label": "Due", "value": str(handoff.due_time or "")[:10] or "No due date"},
            {"label": "Escalation", "value": str(handoff.escalation_status or "normal").title()},
            {"label": "Status", "value": str(handoff.status or "pending").replace("_", " ").title()},
        ],
        object_sidebar_title="Operator workflow",
        object_sidebar_copy="A handoff should show who owns it, whether it is waiting on the principal, and what evidence supports the transfer.",
        object_sidebar_rows=[
            _object_detail_row("Queue item", handoff.queue_item_ref or "No queue item ref attached.", "Queue"),
            _object_detail_row("Evidence attached", f"{len(handoff.evidence_refs or [])} evidence refs attached to this handoff.", "Evidence"),
            _object_detail_row("Assignment state", str(handoff.status or "pending").replace("_", " "), "Status"),
        ],
        object_sections=[
            {
                "eyebrow": "Evidence",
                "title": "Supporting evidence",
                "items": _evidence_detail_rows(handoff.evidence_refs),
            },
            {
                "eyebrow": "Routing history",
                "title": "Recent assignment events",
                "items": [
                    _object_detail_row(
                        str(getattr(item, "event_name", "") or "assignment").replace("_", " ").title(),
                        " · ".join(
                            part
                            for part in (
                                str(getattr(item, "assigned_operator_id", "") or "").strip(),
                                str(getattr(item, "assigned_by_actor_id", "") or "").strip(),
                                str(getattr(item, "assignment_source", "") or "").strip(),
                            )
                            if part
                        ) or "Assignment event recorded.",
                        str(getattr(item, "created_at", "") or "")[:10] or "Event",
                    )
                    for item in history_rows
                ] or [_object_detail_row("No routing history yet", "No assignment changes were recorded yet.", "History")],
            },
        ],
    )


@router.get("/app/threads/{thread_ref}", response_class=HTMLResponse)
def thread_detail(
    thread_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    thread = product.get_thread(principal_id=context.principal_id, thread_ref=thread_ref)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="thread_opened",
        surface=f"thread:{thread_ref}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {thread.title}",
        current_nav="inbox",
        console_title=thread.title,
        console_summary="Conversation state, related drafts, linked commitments, and decision context.",
        object_kind="Conversation thread",
        object_title=thread.title,
        object_summary=thread.summary or "This thread is part of the current office loop.",
        object_meta=[
            {"label": "Channel", "value": str(thread.channel or "unknown").title()},
            {"label": "Status", "value": str(thread.status or "open").replace("_", " ").title()},
            {"label": "Last activity", "value": str(thread.last_activity_at or "")[:10] or "Unknown"},
            {"label": "People", "value": str(len(thread.counterparties or []))},
        ],
        object_sidebar_title="Thread context",
        object_sidebar_copy="A conversation should stay connected to the work it creates: drafts, commitments, decisions, and evidence.",
        object_sidebar_rows=[
            _object_detail_row("Counterparties", " · ".join(thread.counterparties or []) or "No counterparties projected.", "People"),
            _object_detail_row("Drafts", ", ".join(thread.draft_ids or []) or "No active draft ids.", "Drafts"),
            _object_detail_row("Commitments", ", ".join(thread.related_commitment_ids or []) or "No linked commitments yet.", "Ledger"),
        ],
        object_sections=[
            {
                "eyebrow": "Decision links",
                "title": "Related office work",
                "items": [
                    _object_detail_row("Related decisions", ", ".join(thread.related_decision_ids or []) or "No linked decisions.", "Decision"),
                    _object_detail_row("Related commitments", ", ".join(thread.related_commitment_ids or []) or "No linked commitments.", "Commitment"),
                    _object_detail_row("Draft queue", ", ".join(thread.draft_ids or []) or "No active drafts.", "Draft"),
                ],
            },
            {
                "eyebrow": "Evidence",
                "title": "Supporting evidence",
                "items": _evidence_detail_rows(thread.evidence_refs),
            },
        ],
    )


@router.get("/app/evidence/{evidence_ref}", response_class=HTMLResponse)
def evidence_detail(
    evidence_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    evidence = product.get_evidence(
        principal_id=context.principal_id,
        evidence_ref=evidence_ref,
        operator_id=str(context.operator_id or "").strip(),
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="evidence_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="evidence_opened",
        surface=f"evidence:{evidence_ref}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    href_value = str(evidence.href or "").strip()
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {evidence.label}",
        current_nav="contacts",
        console_title=evidence.label,
        console_summary="Evidence provenance, source type, and the objects that currently depend on it.",
        object_kind="Evidence",
        object_title=evidence.label,
        object_summary=evidence.summary or "This evidence ref supports one or more projected product objects.",
        object_meta=[
            {"label": "Source type", "value": str(evidence.source_type or "unknown").replace("_", " ").title()},
            {"label": "Linked objects", "value": str(len(evidence.related_object_refs or []))},
            {"label": "Reference", "value": "External link" if href_value else "Embedded"},
            {"label": "Status", "value": "Available"},
        ],
        object_sidebar_title="Provenance",
        object_sidebar_copy="Evidence should explain why the product surfaced something and what objects currently depend on that fact.",
        object_sidebar_rows=[
            _object_detail_row("Reference", href_value or "No external URL attached to this evidence row.", "Link"),
            _object_detail_row("Related objects", ", ".join(evidence.related_object_refs or []) or "No linked objects yet.", "Objects"),
            _object_detail_row("Source label", evidence.label, "Evidence"),
        ],
        object_sections=[
            {
                "eyebrow": "Evidence summary",
                "title": "What this evidence says",
                "items": [_object_detail_row(evidence.label, evidence.summary or "No summary projected.", str(evidence.source_type or "evidence").title())],
            },
            {
                "eyebrow": "Dependencies",
                "title": "Objects linked to this evidence",
                "items": [
                    _object_detail_row(ref, "This product object currently references the evidence row.", "Linked")
                    for ref in (evidence.related_object_refs or [])
                ]
                or [_object_detail_row("No linked objects", "Nothing else points at this evidence yet.", "Pending")],
            },
        ],
    )


@router.get("/app/rules/{rule_id}", response_class=HTMLResponse)
def rule_detail(
    rule_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    rule = product.get_rule(principal_id=context.principal_id, rule_id=rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="rules_opened",
        surface=f"rule:{rule_id}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    simulated_effect = str(rule.simulated_effect or "").strip()
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {rule.label}",
        current_nav="settings",
        console_title=rule.label,
        console_summary="Rule scope, current value, impact, and whether changes need approval.",
        object_kind="Rules",
        object_title=rule.label,
        object_summary=rule.summary or "This rule shapes how the assistant reads, drafts, sends, remembers, or escalates work.",
        object_meta=[
            {"label": "Scope", "value": str(rule.scope or "workspace").replace("_", " ").title()},
            {"label": "Status", "value": str(rule.status or "active").replace("_", " ").title()},
            {"label": "Current value", "value": str(rule.current_value or "Not set")},
            {"label": "Approval", "value": "Required" if rule.requires_approval else "Direct save"},
        ],
        object_sidebar_title="Rule effect",
        object_sidebar_copy="Rules should be legible in product language: what they change, who they affect, and whether the change needs approval.",
        object_sidebar_rows=[
            _object_detail_row("Impact", rule.impact or "No impact summary projected yet.", "Impact"),
            _object_detail_row("Simulation", simulated_effect or "Run a simulation in Settings before changing this rule.", "Simulate"),
            _object_detail_row("Change posture", "Approval gate applies." if rule.requires_approval else "Directly editable in the current plan.", "Governance"),
        ],
        object_sections=[
            {
                "eyebrow": "Rule summary",
                "title": "Current posture",
                "items": [
                    _object_detail_row(rule.label, rule.summary or "No rule summary projected.", str(rule.status or "active").title()),
                    _object_detail_row("Current value", str(rule.current_value or "Not set"), "Value"),
                ],
            },
            {
                "eyebrow": "Simulation",
                "title": "Expected effect",
                "items": [
                    _object_detail_row("Preview", simulated_effect or "Use the rules surface to simulate this rule before saving changes.", "Effect")
                ],
            },
        ],
    )


@router.get("/app/settings/plan", response_class=HTMLResponse)
def settings_plan_detail(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    diagnostics = product.workspace_diagnostics(principal_id=context.principal_id)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="plan_opened",
        surface="settings_plan",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    plan = dict(diagnostics.get("plan") or {})
    billing = dict(diagnostics.get("billing") or {})
    entitlements = dict(diagnostics.get("entitlements") or {})
    operators = dict(diagnostics.get("operators") or {})
    commercial = dict(diagnostics.get("commercial") or {})
    selected_channels = [str(value) for value in (diagnostics.get("selected_channels") or []) if str(value).strip()]
    feature_flags = [str(value).replace("_", " ") for value in (entitlements.get("feature_flags") or []) if str(value).strip()]
    warnings = [str(value) for value in (commercial.get("warnings") or []) if str(value).strip()]
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title="Executive Assistant Workspace plan",
        current_nav="settings",
        console_title="Workspace plan",
        console_summary="Plan unit, billing posture, messaging scope, and seat boundaries for this office.",
        object_kind="Commercial boundary",
        object_title=str(plan.get("display_name") or "Pilot"),
        object_summary=str(billing.get("contract_note") or "Commercial posture is not yet set."),
        object_meta=[
            {"label": "Plan unit", "value": str(plan.get("unit_of_sale") or "workspace")},
            {"label": "Billing state", "value": str(billing.get("billing_state") or "unknown")},
            {"label": "Support tier", "value": str(billing.get("support_tier") or "standard")},
            {"label": "Seats remaining", "value": str(operators.get("seats_remaining") or 0)},
        ],
        object_sidebar_title="Why this boundary matters",
        object_sidebar_copy="Commercial scope should explain what the office may connect, how many operators may run the queue, and what support posture applies when something goes wrong.",
        object_sidebar_rows=[
            _object_detail_row("Channels", ", ".join(selected_channels) or "Google-first path", "Channels"),
            _object_detail_row("Messaging scope", "Included" if entitlements.get("messaging_channels_enabled") else "Upgrade required for messaging channels", "Entitlement"),
            _object_detail_row("Warnings", "; ".join(warnings) or "No current commercial warnings", "Support"),
        ],
        object_sections=[
            {
                "eyebrow": "Plan",
                "title": "Plan and billing posture",
                "items": [
                    _object_detail_row("Workspace plan", str(plan.get("display_name") or "Pilot"), "Plan"),
                    _object_detail_row("Plan unit", str(plan.get("unit_of_sale") or "workspace"), "Plan"),
                    _object_detail_row("Billing state", str(billing.get("billing_state") or "unknown"), "Billing"),
                    _object_detail_row("Renewal owner", str(billing.get("renewal_owner_role") or "principal").replace("_", " ").title(), "Billing"),
                    _object_detail_row("Contract note", str(billing.get("contract_note") or "No contract note recorded."), "Contract"),
                ],
            },
            {
                "eyebrow": "Entitlements",
                "title": "What this workspace includes",
                "items": [
                    _object_detail_row("Principal seats", str(entitlements.get("principal_seats") or 0), "Seats"),
                    _object_detail_row("Operator seats", str(entitlements.get("operator_seats") or 0), "Seats"),
                    _object_detail_row("Audit retention", str(entitlements.get("audit_retention") or "standard"), "Retention"),
                    _object_detail_row("Feature flags", ", ".join(feature_flags) or "No enabled features", "Flags"),
                ],
            },
        ],
    )


@router.get("/app/settings/usage", response_class=HTMLResponse)
def settings_usage_detail(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="usage_opened",
        surface="settings_usage",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    diagnostics = product.workspace_diagnostics(principal_id=context.principal_id)
    usage = {str(key): int(value or 0) for key, value in dict(diagnostics.get("usage") or {}).items()}
    analytics = dict(diagnostics.get("analytics") or {})
    operators = dict(diagnostics.get("operators") or {})
    readiness = dict(diagnostics.get("readiness") or {})
    queue_health = dict(diagnostics.get("queue_health") or {})
    providers = dict(diagnostics.get("providers") or {})
    counts = {str(key): int(value or 0) for key, value in dict(analytics.get("counts") or {}).items()}
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title="Executive Assistant Workspace usage",
        current_nav="settings",
        console_title="Usage and activation",
        console_summary="Queue pressure, memo activity, operator load, and time-to-value should stay visible while shaping rules and support posture.",
        object_kind="Usage state",
        object_title="Current office loop",
        object_summary=f"{usage.get('queue_items', 0)} queue items · {usage.get('commitments', 0)} commitments · {usage.get('handoffs', 0)} handoffs",
        object_meta=[
            {"label": "Memo items", "value": str(usage.get("brief_items", 0))},
            {"label": "Queue items", "value": str(usage.get("queue_items", 0))},
            {"label": "Commitments", "value": str(usage.get("commitments", 0))},
            {"label": "Handoffs", "value": str(usage.get("handoffs", 0))},
        ],
        object_sidebar_title="Activation and readiness",
        object_sidebar_copy="Usage only matters when it stays attached to readiness, operator capacity, and the speed with which the workspace reaches first real value.",
        object_sidebar_rows=[
            _object_detail_row("Active operators", str(operators.get("active_count") or 0), "Operators"),
            _object_detail_row("Time to first value", str(analytics.get("time_to_first_value_seconds") or "pending"), "Analytics"),
            _object_detail_row("Readiness", str(readiness.get("detail") or "Runtime posture not recorded."), "Runtime"),
            _object_detail_row("Workspace health score", str(readiness.get("health_score") or 0), "Runtime"),
            _object_detail_row("Provider risk", str(providers.get("risk_state") or "unknown"), "Support"),
        ],
        object_sections=[
            {
                "eyebrow": "Analytics",
                "title": "Product loop signals",
                "items": [
                    _object_detail_row("Memo opened", str(counts.get("memo_opened") or 0), "Analytics"),
                    _object_detail_row("Queue opened", str(counts.get("queue_opened") or 0), "Analytics"),
                    _object_detail_row("Draft approved", str(counts.get("draft_approved") or 0), "Analytics"),
                    _object_detail_row("Commitment closed", str(counts.get("commitment_closed") or 0), "Analytics"),
                    _object_detail_row("First value event", str(analytics.get("first_value_event") or "not reached").replace("_", " "), "Analytics"),
                ],
            },
            {
                "eyebrow": "Capacity",
                "title": "Operator and queue load",
                "items": [
                    _object_detail_row("Seats used", str(operators.get("seats_used") or 0), "Operators"),
                    _object_detail_row("Seats remaining", str(operators.get("seats_remaining") or 0), "Operators"),
                    _object_detail_row("Pending approvals", str(counts.get("approval_requested") or 0), "Approvals"),
                    _object_detail_row("Load score", str(queue_health.get("load_score") or 0), "Queue"),
                    _object_detail_row("Retrying delivery", str(queue_health.get("retrying_delivery") or 0), "Queue"),
                    _object_detail_row("Delivery errors", str(queue_health.get("delivery_errors") or 0), "Queue"),
                    _object_detail_row("Fallback lanes", str(providers.get("lanes_with_fallback") or 0), "Provider"),
                    _object_detail_row("Support bundle opened", str(counts.get("support_bundle_opened") or 0), "Support"),
                ],
            },
        ],
    )


@router.get("/app/settings/support", response_class=HTMLResponse)
def settings_support_detail(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="support_opened",
        surface="settings_support",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    bundle = product.workspace_support_bundle(principal_id=context.principal_id)
    billing = dict(bundle.get("billing") or {})
    approvals = dict(bundle.get("approvals") or {})
    human_tasks = [dict(value) for value in (bundle.get("human_tasks") or [])]
    pending_delivery = [dict(value) for value in (bundle.get("pending_delivery") or [])]
    providers = dict(bundle.get("providers") or {})
    queue_health = dict(bundle.get("queue_health") or {})
    commercial = dict(bundle.get("commercial") or {})
    readiness = dict(bundle.get("readiness") or {})
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title="Executive Assistant Workspace support",
        current_nav="settings",
        console_title="Support and diagnostics",
        console_summary="Support posture should explain what is blocked, what is pending human review, what the providers are doing, and what bundle is ready to export.",
        object_kind="Support bundle",
        object_title=str(billing.get("support_tier") or "standard").title(),
        object_summary=str(billing.get("contract_note") or "Support posture is available for export."),
        object_meta=[
            {"label": "Pending approvals", "value": str(len(list(approvals.get("pending") or [])))},
            {"label": "Human tasks", "value": str(len(human_tasks))},
            {"label": "Pending delivery", "value": str(len(pending_delivery))},
            {"label": "Providers", "value": str(providers.get("provider_count") or 0)},
        ],
        object_sidebar_title="What support should answer",
        object_sidebar_copy="A customer-grade support surface should answer what was blocked, what still needs human review, which providers are in play, and what bundle may be exported without reading raw logs.",
        object_sidebar_rows=[
            _object_detail_row("Support tier", str(billing.get("support_tier") or "standard"), "Support"),
            _object_detail_row("Billing state", str(billing.get("billing_state") or "unknown"), "Billing"),
            _object_detail_row("Provider risk", str(providers.get("risk_state") or "unknown"), "Provider"),
            _object_detail_row("Workspace health score", str(readiness.get("health_score") or 0), "Runtime"),
            _object_detail_row(
                "Blocked actions",
                ", ".join(str(value).replace("_", " ") for value in (commercial.get("blocked_actions") or [])[:6]) or "No blocked actions",
                "Support",
            ),
            _object_detail_row("Export bundle", "Open the support-ready workspace bundle from Settings or Diagnostics export.", "Bundle"),
        ],
        object_sections=[
            {
                "eyebrow": "Approvals",
                "title": "Pending review and recent decisions",
                "items": [
                    _object_detail_row(
                        str(item.get("reason") or "Approval pending"),
                        f"{str(item.get('status') or 'pending').replace('_', ' ')} · expires {str(item.get('expires_at') or '')[:10] or 'n/a'}",
                        "Pending",
                    )
                    for item in list(approvals.get("pending") or [])[:6]
                ] or [_object_detail_row("No pending approvals", "Nothing is blocked on approval right now.", "Clear")],
            },
            {
                "eyebrow": "Support bundle",
                "title": "Human tasks and provider posture",
                "items": (
                    [
                        _object_detail_row(
                            str(item.get("brief") or "Human task"),
                            f"{str(item.get('status') or 'pending').replace('_', ' ')} · {str(item.get('assignment_state') or 'unassigned').replace('_', ' ')}",
                            str(item.get("priority") or "normal").title(),
                        )
                        for item in human_tasks[:4]
                    ]
                    + [
                        _object_detail_row(
                            f"{str(item.get('channel') or 'delivery').title()} delivery",
                            f"{str(item.get('recipient') or 'unknown')} · {str(item.get('status') or 'pending').replace('_', ' ')}",
                            "Delivery",
                        )
                        for item in pending_delivery[:2]
                    ]
                )
                or [_object_detail_row("Support surface is clear", "No human tasks or pending delivery are currently blocking the office loop.", "Clear")],
            },
            {
                "eyebrow": "Runtime posture",
                "title": "Queue, delivery, and failover pressure",
                "items": [
                    _object_detail_row("Queue state", str(queue_health.get("state") or "healthy"), "Queue"),
                    _object_detail_row("Load score", str(queue_health.get("load_score") or 0), "Queue"),
                    _object_detail_row("Retrying delivery", str(queue_health.get("retrying_delivery") or 0), "Queue"),
                    _object_detail_row("Delivery errors", str(queue_health.get("delivery_errors") or 0), "Queue"),
                    _object_detail_row("Fallback lanes", str(providers.get("lanes_with_fallback") or 0), "Provider"),
                    _object_detail_row("Failover-ready lanes", str(providers.get("failover_ready_lanes") or 0), "Provider"),
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
) -> HTMLResponse:
    allowed = {row["key"] for group in APP_NAV_GROUPS for row in group["items"]}
    allowed.add("channel-loop")
    if section not in allowed:
        raise HTTPException(status_code=404, detail="app_section_not_found")
    status = container.onboarding.status(principal_id=context.principal_id)
    if section == "channel-loop":
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
                    }
                ],
                stats=stats,
            ),
        )
    core_sections = {"today", "briefing", "inbox", "follow-ups", "memory", "contacts", "activity", "settings"}
    if section in core_sections:
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
        }.get(section)
        if surface_event:
            product.record_surface_event(
                principal_id=context.principal_id,
                event_type=surface_event,
                surface=section,
                actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
            )
        diagnostics = product.workspace_diagnostics(principal_id=context.principal_id)
        payload = _workspace_section_payload(
            section,
            product.workspace_snapshot(
                principal_id=context.principal_id,
                operator_id=str(context.operator_id or "").strip(),
            ),
            diagnostics,
            operator_id=str(context.operator_id or "").strip(),
        )
    else:
        payload = _app_section_payload(
            section,
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
            current_nav=section,
            context=context,
            console_title=str(payload["title"]),
            console_summary=str(payload["summary"]),
            nav_groups=APP_NAV_GROUPS,
            workspace_label=str(workspace.get("name") or "Executive Workspace"),
            cards=list(payload["cards"]),
            stats=list(payload["stats"]),
        ),
    )


@router.get("/app/channel/drafts/{draft_ref}/approve")
def app_channel_approve_draft(
    draft_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    return_to = str(request.query_params.get("return_to") or "/app/channel-loop").strip() or "/app/channel-loop"
    reason = str(request.query_params.get("reason") or "Approved from inline loop.").strip() or "Approved from inline loop."
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    approved = product.approve_draft(
        principal_id=context.principal_id,
        draft_ref=draft_ref,
        decided_by=actor,
        reason=reason,
    )
    if approved is None:
        raise HTTPException(status_code=404, detail="draft_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.get("/app/channel/queue/{item_ref:path}/resolve")
def app_channel_resolve_queue_item(
    item_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    return_to = str(request.query_params.get("return_to") or "/app/channel-loop").strip() or "/app/channel-loop"
    action = str(request.query_params.get("action") or "resolve").strip() or "resolve"
    reason = str(request.query_params.get("reason") or "Resolved from inline loop.").strip() or "Resolved from inline loop."
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    updated = product.resolve_queue_item(
        principal_id=context.principal_id,
        item_ref=item_ref,
        action=action,
        actor=actor,
        reason=reason,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="queue_item_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.get("/app/channel/handoffs/{handoff_ref:path}/assign")
def app_channel_assign_handoff(
    handoff_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    return_to = str(request.query_params.get("return_to") or "/app/channel-loop").strip() or "/app/channel-loop"
    operator_id = str(request.query_params.get("operator_id") or "").strip() or str(context.operator_id or "").strip() or _default_operator_id_for_browser(container, principal_id=context.principal_id)
    if not operator_id:
        raise HTTPException(status_code=409, detail="operator_required")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or operator_id).strip()
    assigned = product.assign_handoff(
        principal_id=context.principal_id,
        handoff_ref=handoff_ref,
        operator_id=operator_id,
        actor=actor,
    )
    if assigned is None:
        raise HTTPException(status_code=404, detail="handoff_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.get("/app/channel/handoffs/{handoff_ref:path}/complete")
def app_channel_complete_handoff(
    handoff_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    return_to = str(request.query_params.get("return_to") or "/app/channel-loop").strip() or "/app/channel-loop"
    resolution = str(request.query_params.get("action") or "completed").strip() or "completed"
    operator_id = str(request.query_params.get("operator_id") or "").strip() or str(context.operator_id or "").strip() or _default_operator_id_for_browser(container, principal_id=context.principal_id)
    if not operator_id:
        raise HTTPException(status_code=409, detail="operator_required")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or operator_id).strip()
    completed = product.complete_handoff(
        principal_id=context.principal_id,
        handoff_ref=handoff_ref,
        operator_id=operator_id,
        actor=actor,
        resolution=resolution,
    )
    if completed is None:
        raise HTTPException(status_code=404, detail="handoff_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.post("/app/actions/drafts/{draft_ref}")
@router.post("/app/actions/drafts/{draft_ref}/approve")
async def app_approve_draft(
    draft_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _form_value(body, "return_to", "/app/inbox")
    reason = _form_value(body, "reason", "Approved from browser workflow.")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    approved = product.approve_draft(
        principal_id=context.principal_id,
        draft_ref=draft_ref,
        decided_by=actor,
        reason=reason,
    )
    if approved is None:
        raise HTTPException(status_code=404, detail="draft_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.post("/app/actions/drafts/{draft_ref}/reject")
async def app_reject_draft(
    draft_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _form_value(body, "return_to", "/app/inbox")
    reason = _form_value(body, "reason", "Rejected from browser workflow.")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    rejected = product.reject_draft(
        principal_id=context.principal_id,
        draft_ref=draft_ref,
        decided_by=actor,
        reason=reason,
    )
    if rejected is None:
        raise HTTPException(status_code=404, detail="draft_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.post("/app/actions/queue/{item_ref}")
@router.post("/app/actions/queue/{item_ref}/resolve")
async def app_resolve_queue_item(
    item_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _form_value(body, "return_to", "/app/briefing")
    action = _form_value(body, "action", "resolve")
    reason = _form_value(body, "reason", "Resolved from browser workflow.")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    updated = product.resolve_queue_item(
        principal_id=context.principal_id,
        item_ref=item_ref,
        action=action,
        actor=actor,
        reason=reason,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="queue_item_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.post("/app/actions/commitments/create")
async def app_create_commitment(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    title = _form_value(body, "title", "")
    if title:
        product = build_product_service(container)
        product.create_commitment(
            principal_id=context.principal_id,
            title=title,
            details=_form_value(body, "details", ""),
            due_at=_form_value(body, "due_at", "") or None,
            counterparty=_form_value(body, "counterparty", ""),
            owner="office",
            kind=_form_value(body, "kind", "follow_up"),
            stakeholder_id=_form_value(body, "stakeholder_id", ""),
            channel_hint=_form_value(body, "channel_hint", "email"),
        )
    return RedirectResponse(_form_value(body, "return_to", "/app/follow-ups"), status_code=303)


@router.post("/app/actions/commitments/extract")
async def app_extract_commitment(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    source_text = _form_value(body, "source_text", "")
    if source_text:
        product = build_product_service(container)
        product.stage_extracted_commitments(
            principal_id=context.principal_id,
            text=source_text,
            counterparty=_form_value(body, "counterparty", ""),
            due_at=_form_value(body, "due_at", "") or None,
            kind=_form_value(body, "kind", "commitment"),
            stakeholder_id=_form_value(body, "stakeholder_id", ""),
        )
    return RedirectResponse(_form_value(body, "return_to", "/app/inbox"), status_code=303)


@router.post("/app/actions/commitments/candidates/{candidate_id}/accept")
async def app_accept_commitment_candidate(
    candidate_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    product = build_product_service(container)
    reviewer = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    created = product.accept_commitment_candidate(
        principal_id=context.principal_id,
        candidate_id=candidate_id,
        reviewer=reviewer,
        title=_form_value(body, "title", ""),
        details=_form_value(body, "details", ""),
        due_at=_form_value(body, "due_at", "") or None,
        counterparty=_form_value(body, "counterparty", ""),
        kind=_form_value(body, "kind", ""),
        stakeholder_id=_form_value(body, "stakeholder_id", ""),
    )
    if created is None:
        raise HTTPException(status_code=404, detail="commitment_candidate_not_found")
    return RedirectResponse(_form_value(body, "return_to", "/app/inbox"), status_code=303)


@router.post("/app/actions/commitments/candidates/{candidate_id}/reject")
async def app_reject_commitment_candidate(
    candidate_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    product = build_product_service(container)
    reviewer = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    rejected = product.reject_commitment_candidate(principal_id=context.principal_id, candidate_id=candidate_id, reviewer=reviewer)
    if rejected is None:
        raise HTTPException(status_code=404, detail="commitment_candidate_not_found")
    return RedirectResponse(_form_value(body, "return_to", "/app/inbox"), status_code=303)


@router.post("/app/actions/handoffs/{handoff_ref:path}/assign")
async def app_assign_handoff(
    handoff_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _form_value(body, "return_to", "/app/follow-ups")
    operator_id = (
        _form_value(body, "operator_id", "")
        or str(context.operator_id or "").strip()
        or _default_operator_id_for_browser(container, principal_id=context.principal_id)
    )
    if not operator_id:
        raise HTTPException(status_code=409, detail="operator_required")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or operator_id).strip()
    assigned = product.assign_handoff(
        principal_id=context.principal_id,
        handoff_ref=handoff_ref,
        operator_id=operator_id,
        actor=actor,
    )
    if assigned is None:
        raise HTTPException(status_code=404, detail="handoff_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.post("/app/actions/handoffs/{handoff_ref:path}/complete")
async def app_complete_handoff(
    handoff_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _form_value(body, "return_to", "/app/follow-ups")
    resolution = _form_value(body, "action", "completed")
    operator_id = (
        _form_value(body, "operator_id", "")
        or str(context.operator_id or "").strip()
        or _default_operator_id_for_browser(container, principal_id=context.principal_id)
    )
    if not operator_id:
        raise HTTPException(status_code=409, detail="operator_required")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or operator_id).strip()
    completed = product.complete_handoff(
        principal_id=context.principal_id,
        handoff_ref=handoff_ref,
        operator_id=operator_id,
        actor=actor,
        resolution=resolution,
    )
    if completed is None:
        raise HTTPException(status_code=404, detail="handoff_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.post("/app/actions/people/{person_id}/correct")
async def app_correct_person(
    person_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _form_value(body, "return_to", f"/app/people/{person_id}")
    product = build_product_service(container)
    corrected = product.correct_person_profile(
        principal_id=context.principal_id,
        person_id=person_id,
        preferred_tone=_form_value(body, "preferred_tone", ""),
        add_theme=_form_value(body, "add_theme", ""),
        remove_theme=_form_value(body, "remove_theme", ""),
        add_risk=_form_value(body, "add_risk", ""),
        remove_risk=_form_value(body, "remove_risk", ""),
    )
    if corrected is None:
        raise HTTPException(status_code=404, detail="person_not_found")
    return RedirectResponse(return_to, status_code=303)


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
    payload = _build_admin_section_payload(section, container=container, principal_id=context.principal_id)
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
    return RedirectResponse("/get-started", status_code=307)


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


@router.post("/setup/start")
async def setup_start(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.start_workspace(
        principal_id=principal_id,
        workspace_name=_form_value(form_data, "workspace_name", "Executive Workspace"),
        workspace_mode=_form_value(form_data, "workspace_mode", "personal"),
        region=_form_value(form_data, "region", ""),
        language=_form_value(form_data, "language", ""),
        timezone=_form_value(form_data, "timezone", ""),
        selected_channels=_form_values(form_data, "selected_channels"),
    )
    return RedirectResponse("/get-started", status_code=303)


@router.post("/setup/telegram")
async def setup_telegram(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    if not _workspace_plan(container, principal_id=principal_id).entitlements.messaging_channels_enabled:
        return RedirectResponse("/pricing", status_code=303)
    container.onboarding.start_telegram(
        principal_id=principal_id,
        telegram_ref=_form_value(form_data, "telegram_ref", ""),
        identity_mode=_form_value(form_data, "identity_mode", "login_widget"),
        history_mode=_form_value(form_data, "history_mode", "future_only"),
        assistant_surfaces=_form_values(form_data, "assistant_surfaces"),
    )
    return RedirectResponse("/get-started", status_code=303)


@router.post("/setup/telegram/link-bot")
async def setup_telegram_link_bot(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    if not _workspace_plan(container, principal_id=principal_id).entitlements.messaging_channels_enabled:
        return RedirectResponse("/pricing", status_code=303)
    container.onboarding.link_telegram_bot(
        principal_id=principal_id,
        bot_handle=_form_value(form_data, "bot_handle", ""),
        install_surfaces=_form_values(form_data, "install_surfaces"),
        default_chat_ref=_form_value(form_data, "default_chat_ref", ""),
    )
    return RedirectResponse("/get-started", status_code=303)


@router.post("/setup/whatsapp/business")
async def setup_whatsapp_business(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    if not _workspace_plan(container, principal_id=principal_id).entitlements.messaging_channels_enabled:
        return RedirectResponse("/pricing", status_code=303)
    container.onboarding.start_whatsapp_business(
        principal_id=principal_id,
        phone_number=_form_value(form_data, "phone_number", ""),
        business_name=_form_value(form_data, "business_name", ""),
        import_history_now=_form_value(form_data, "import_history_now", "").lower() == "true",
    )
    return RedirectResponse("/get-started", status_code=303)


@router.post("/setup/whatsapp/export")
async def setup_whatsapp_export(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    if not _workspace_plan(container, principal_id=principal_id).entitlements.messaging_channels_enabled:
        return RedirectResponse("/pricing", status_code=303)
    chats = tuple(chunk.strip() for chunk in _form_value(form_data, "selected_chat_labels_csv", "").split(",") if chunk.strip())
    container.onboarding.import_whatsapp_export(
        principal_id=principal_id,
        export_label=_form_value(form_data, "export_label", ""),
        selected_chat_labels=chats,
        include_media=_form_value(form_data, "include_media", "").lower() == "true",
    )
    return RedirectResponse("/get-started", status_code=303)


@router.post("/setup/finalize")
async def setup_finalize(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.finalize(
        principal_id=principal_id,
        retention_mode=_form_value(form_data, "retention_mode", "full_bodies"),
        metadata_only_channels=_form_values(form_data, "metadata_only_channels"),
        allow_drafts=_form_value(form_data, "allow_drafts", "").lower() == "true",
        allow_action_suggestions=_form_value(form_data, "allow_action_suggestions", "").lower() == "true",
        allow_auto_briefs=_form_value(form_data, "allow_auto_briefs", "").lower() == "true",
    )
    return RedirectResponse("/app/briefing", status_code=303)


@router.post("/google/connect", response_model=None)
async def google_connect_browser(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse | HTMLResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    result = container.onboarding.start_google(
        principal_id=principal_id,
        scope_bundle=_form_value(form_data, "scope_bundle", "core"),
    )
    google_start = dict(result.get("google_start") or {})
    if bool(google_start.get("ready")) and str(google_start.get("auth_url") or "").strip():
        return RedirectResponse(str(google_start["auth_url"]), status_code=303)
    return _render_public_template(
        request,
        "channel_detail.html",
        page_title="Google onboarding status",
        public_nav=PUBLIC_NAV,
        current_nav="integrations",
        access_identity=access_identity,
        principal_id=principal_id,
        status=result,
        workspace=dict(result.get("workspace") or {}),
        channels=dict(result.get("channels") or {}),
        channel_cards=_channel_cards(dict(result.get("channels") or {})),
        selected_channels_label=", ".join(result.get("selected_channels") or []) or "Google Core recommended",
        workspace_mode_label=_humanize(str(dict(result.get("workspace") or {}).get("mode") or "personal")),
        brief_headline=str(dict(result.get("brief_preview") or {}).get("headline") or "Turn your channels into a prioritized day."),
        first_brief_items=[],
        suggested_actions=[],
        trust_notes=[],
        top_contacts=[],
        top_themes=[],
        channel_title="Google onboarding",
        channel_eyebrow="Google",
        channel={"status": google_start.get("detail") or "not_ready", "detail": google_start.get("detail") or "Google onboarding could not start.", "capabilities": [], "limitations": []},
        detail_points=("Google consent could not start on this host.",),
        body_points=("Check OAuth credentials, redirect URI, and provider configuration.",),
    )


@router.get("/google/callback", response_class=HTMLResponse, name="google_oauth_browser_callback")
def google_oauth_browser_callback(
    request: Request,
    code: str,
    state: str,
    container: AppContainer = Depends(get_container),
) -> HTMLResponse:
    try:
        account = complete_google_oauth_callback(container=container, code=code, state=state)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _render_public_template(
        request,
        "google_connected.html",
        page_title="Google connected",
        public_nav=PUBLIC_NAV,
        current_nav="integrations",
        access_identity=None,
        principal_id=account.binding.principal_id,
        account=account,
        scopes=list(account.granted_scopes),
    )


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
                current_nav="inbox",
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
