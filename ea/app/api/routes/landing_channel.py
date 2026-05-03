from __future__ import annotations

import html
import json
import os
import urllib.parse
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.dependencies import (
    CloudflareAccessIdentity,
    RequestContext,
    _workspace_session_payload,
    get_cloudflare_access_identity,
    get_container,
    get_request_context,
)
from app.api.routes.landing import (
    _console_shell_context,
    _default_operator_id_for_browser,
    _normalize_browser_return_to,
    _render_public_template,
    _render_secure_link_page,
    _workspace_session_cookie_kwargs,
)
from app.api.routes.product_api_contracts import OfficeSignalResultOut, SignalIngestEndpointOut
from app.api.routes.landing_content import APP_NAV_GROUPS
from app.container import AppContainer
from app.product.service import build_product_service

router = APIRouter(tags=["landing"])


def _channel_action_object_label(kind: str) -> str:
    normalized = str(kind or "").strip().lower()
    labels = {
        "draft": "draft reply",
        "candidate": "commitment candidate",
        "commitment_candidate": "commitment candidate",
        "queue": "queue item",
        "decision": "decision",
        "handoff": "handoff",
        "support_verification": "support verification",
        "support_fix_verification": "support verification",
    }
    return labels.get(normalized, normalized.replace("_", " ") or "workspace item")


def _channel_action_label(action: str, *, object_kind: str) -> str:
    normalized = str(action or "").strip().lower()
    if normalized == "approve":
        return "Approve"
    if normalized == "reject":
        return "Reject"
    if normalized in {"assign", "claim"}:
        return "Assign"
    if normalized in {"retry_send", "retry-send", "retry"}:
        return "Retry send"
    if normalized == "recreate":
        return "Recreate"
    if normalized == "confirm":
        return "Confirm"
    if object_kind == "handoff" and normalized == "completed":
        return "Complete"
    return normalized.replace("_", " ").replace("-", " ").title() or "Apply"


def _render_channel_action_confirmation(
    request: Request,
    *,
    token: str,
    preview: dict[str, object],
) -> HTMLResponse:
    object_kind = str(preview.get("object_kind") or "").strip().lower()
    action = str(preview.get("action") or "").strip().lower()
    action_label = _channel_action_label(action, object_kind=object_kind)
    object_label = _channel_action_object_label(object_kind)
    return_to = _normalize_browser_return_to(str(preview.get("return_to") or "").strip(), default="/sign-in")
    expires_at = str(preview.get("expires_at") or "").strip()
    return _render_secure_link_page(
        request,
        page_title="Confirm secure workspace action",
        current_nav="sign-in",
        link_kicker="Secure action preview",
        link_title="Review this secure action before applying it.",
        link_summary="Email scanners and previews will not apply this action. Confirm it once from a real browser session.",
        link_detail_title="Pending action",
        link_status_label="Awaiting confirmation",
        link_rows=[
            {
                "label": "Action",
                "value": f"{action_label} {object_label}",
                "detail": "The workspace will update only after you confirm this one secure action.",
            },
            {
                "label": "Workspace item",
                "value": str(preview.get("object_ref") or "").strip() or object_label.title(),
                "detail": str(preview.get("reason") or "").strip() or "This action will write a single reviewed decision into the workspace.",
            },
            {
                "label": "Next surface",
                "value": return_to,
                "detail": f"After confirmation, EA will return you to {return_to}.",
            },
            {
                "label": "Expiry",
                "value": expires_at[:19] if expires_at else "Not recorded",
                "detail": "Secure action links expire and cannot be reused indefinitely.",
            },
        ],
        primary_action_href=f"/app/channel-actions/{token}",
        primary_action_label=f"{action_label} now",
        primary_action_method="post",
        secondary_action_href="/sign-in",
        secondary_action_label="Request sign-in link",
    )


def _public_base_url(request: Request) -> str:
    explicit = str(os.environ.get("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    redirect_uri = str(os.environ.get("EA_GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
    if redirect_uri:
        parsed = urlparse(redirect_uri)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return str(request.base_url).rstrip("/")


async def _signal_upload_payload(request: Request) -> dict[str, object]:
    raw_bytes = await request.body()
    raw_text = raw_bytes.decode("utf-8", "replace").strip()
    content_type = str(request.headers.get("content-type") or "").strip().lower()
    body_payload: dict[str, object] = {}
    if "application/json" in content_type and raw_text:
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            body_payload = {"raw_body": raw_text}
        else:
            if isinstance(parsed, dict):
                body_payload = dict(parsed)
            else:
                body_payload = {"value": parsed}
    elif "application/x-www-form-urlencoded" in content_type and raw_text:
        body_payload = {
            key: values[0] if len(values) == 1 else values
            for key, values in urllib.parse.parse_qs(raw_text, keep_blank_values=True).items()
        }
    elif raw_text:
        body_payload = {"raw_body": raw_text}

    query_payload = {key: value for key, value in request.query_params.items()}
    merged = {**query_payload, **body_payload}
    merged["_query"] = query_payload
    merged["_request_meta"] = {
        "content_type": content_type.split(";", 1)[0].strip(),
        "user_agent": str(request.headers.get("user-agent") or "").strip(),
    }
    return merged


@router.get("/app/channel/drafts/{draft_ref}/approve")
def app_channel_approve_draft(
    draft_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    return_to = _normalize_browser_return_to(request.query_params.get("return_to"), default="/app/channel-loop")
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


@router.api_route("/app/channel-actions/{token}", methods=["GET", "HEAD", "POST"], response_model=None, include_in_schema=False)
def app_channel_action(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
):
    product = build_product_service(container)
    preview = product.preview_channel_action_token(token=token)
    if preview is None:
        return _render_secure_link_page(
            request,
            page_title="Action link unavailable",
            current_nav="sign-in",
            link_kicker="Action unavailable",
            link_title="This action link is no longer valid.",
            link_summary="Use another secure workspace path to review the item directly or request a fresh sign-in link.",
            link_detail_title="What happened",
            link_status_label="Link unavailable",
            link_rows=[
                {"label": "Action state", "value": "Expired or already used", "detail": "Secure action links are time-bound and rotate after use."},
                {"label": "Next step", "value": "Open the workspace directly", "detail": "Use a current session, sign-in link, invite, or SSO to reach the same review surface."},
            ],
            primary_action_href="/sign-in",
            primary_action_label="Request new sign-in link",
            secondary_action_href="/register",
            secondary_action_label="Create personal workspace",
            status_code=404,
        )
    workspace_session = _workspace_session_payload(request, container)
    trusted_browser = (
        access_identity is not None
        or bool(str(request.headers.get("X-EA-Principal-ID") or "").strip())
        or workspace_session is not None
    )
    if request.method == "HEAD":
        return _render_channel_action_confirmation(request, token=token, preview=preview)
    if request.method == "GET" and not trusted_browser:
        return _render_channel_action_confirmation(request, token=token, preview=preview)
    actor = str(
        getattr(access_identity, "email", "")
        or str((workspace_session or {}).get("email") or "").strip().lower()
        or str((workspace_session or {}).get("principal_id") or "").strip()
        or request.headers.get("X-EA-Operator-ID")
        or request.headers.get("X-EA-Principal-ID")
        or "channel_link"
    ).strip() or "channel_link"
    preferred_operator_id = str((workspace_session or {}).get("operator_id") or "").strip()
    resolved = product.redeem_channel_action_token(token=token, actor=actor, preferred_operator_id=preferred_operator_id)
    if resolved is None:
        return _render_secure_link_page(
            request,
            page_title="Action link unavailable",
            current_nav="sign-in",
            link_kicker="Action unavailable",
            link_title="This action link is no longer valid.",
            link_summary="Use another secure workspace path to review the item directly or request a fresh sign-in link.",
            link_detail_title="What happened",
            link_status_label="Link unavailable",
            link_rows=[
                {"label": "Action state", "value": "Expired or already used", "detail": "Secure action links are time-bound and rotate after use."},
                {"label": "Next step", "value": "Open the workspace directly", "detail": "Use a current session, sign-in link, invite, or SSO to reach the same review surface."},
            ],
            primary_action_href="/sign-in",
            primary_action_label="Request new sign-in link",
            secondary_action_href="/register",
            secondary_action_label="Create personal workspace",
            status_code=404,
        )
    return_to = _normalize_browser_return_to(str(resolved.get("return_to") or "").strip(), default="/sign-in")
    if trusted_browser:
        return RedirectResponse(return_to, status_code=303)
    return _render_secure_link_page(
        request,
        page_title="Action recorded",
        current_nav="sign-in",
        link_kicker="Action recorded",
        link_title="The requested action was recorded.",
        link_summary="Open the related workspace surface to confirm the result or continue through sign in if you need a fresh session.",
        link_detail_title="Recorded action",
        link_status_label="Applied",
        link_rows=[
            {
                "label": "Action type",
                "value": str(resolved.get("object_kind") or "Workspace action").replace("_", " ").title(),
                "detail": "This secure link already wrote the requested decision into the workspace.",
            },
            {
                "label": "Next surface",
                "value": return_to,
                "detail": "Open the related workspace surface to review the updated state.",
            },
        ],
        primary_action_href=return_to,
        primary_action_label="Open related workspace surface",
        secondary_action_href="/sign-in",
        secondary_action_label="Request sign-in link",
    )


@router.api_route("/channel-loop/deliveries/{token}", methods=["GET", "HEAD"], response_model=None, include_in_schema=False)
def channel_digest_delivery_open(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
):
    product = build_product_service(container)
    delivery = product.preview_channel_digest_delivery(token=token, base_url=_public_base_url(request))
    if delivery is None:
        return _render_secure_link_page(
            request,
            page_title="Delivery link unavailable",
            current_nav="sign-in",
            link_kicker="Delivery unavailable",
            link_title="This delivered workspace link is no longer valid.",
            link_summary="Request a fresh sign-in link or wait for the next memo or approval delivery if you still need this view.",
            link_detail_title="What happened",
            link_status_label="Delivery unavailable",
            link_rows=[
                {"label": "Delivery state", "value": "Expired or replaced", "detail": "Delivered workspace links are secure, time-bound, and eventually rotate out."},
                {"label": "Recovery", "value": "Request another secure link", "detail": "Use sign in if you already have workspace access or wait for the next delivered memo."},
            ],
            primary_action_href="/sign-in",
            primary_action_label="Request new sign-in link",
            secondary_action_href="/register",
            secondary_action_label="Create personal workspace",
            status_code=404,
        )
    response = RedirectResponse(
        _normalize_browser_return_to(str(delivery.get("open_url") or "").strip(), default="/app/channel-loop"),
        status_code=303,
    )
    response.set_cookie(
        "ea_workspace_session",
        str(delivery.get("access_token") or "").strip(),
        **_workspace_session_cookie_kwargs(request, expires_at=str(delivery.get("expires_at") or "").strip()),
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


@router.get("/signals/pocket/{token}", response_model=SignalIngestEndpointOut)
def preview_pocket_signal_upload(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> SignalIngestEndpointOut:
    product = build_product_service(container)
    payload = product.preview_signal_ingest_endpoint(token=token, base_url=_public_base_url(request))
    if payload is None or str(payload.get("channel") or "").strip().lower() != "pocket":
        raise HTTPException(status_code=404, detail="signal_ingest_endpoint_not_found")
    return SignalIngestEndpointOut(**payload)


@router.post("/signals/pocket/{token}", response_model=OfficeSignalResultOut)
async def ingest_pocket_signal_upload(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> OfficeSignalResultOut:
    product = build_product_service(container)
    preview = product.preview_signal_ingest_endpoint(token=token)
    if preview is None or str(preview.get("channel") or "").strip().lower() != "pocket":
        raise HTTPException(status_code=404, detail="signal_ingest_endpoint_not_found")
    payload = await _signal_upload_payload(request)
    result = product.ingest_signal_upload(
        token=token,
        payload=payload,
        actor="pocket_webhook",
    )
    if result is None:
        raise HTTPException(status_code=404, detail="signal_ingest_endpoint_not_found")
    return OfficeSignalResultOut(**result)


@router.get("/app/channel-loop/{digest_key}/plain", response_class=HTMLResponse)
def app_channel_digest_plain(
    digest_key: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    product = build_product_service(container)
    text = product.channel_digest_text(
        principal_id=context.principal_id,
        digest_key=digest_key,
        operator_id=str(context.operator_id or "").strip(),
        base_url=_public_base_url(request),
    )
    if not text:
        raise HTTPException(status_code=404, detail="channel_digest_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="channel_digest_plain_opened",
        surface=f"channel_digest_{digest_key}_plain",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    response = HTMLResponse(text, media_type="text/plain; charset=utf-8")
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


@router.get("/app/channel-loop/{digest_key}", response_class=HTMLResponse)
def app_channel_digest(
    digest_key: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    product = build_product_service(container)
    pack = product.channel_loop_pack(
        principal_id=context.principal_id,
        operator_id=str(context.operator_id or "").strip(),
    )
    digest = next((row for row in list(pack.get("digests") or []) if str(row.get("key") or "").strip() == digest_key), None)
    if digest is None:
        raise HTTPException(status_code=404, detail="channel_digest_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="channel_digest_opened",
        surface=f"channel_digest_{digest_key}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    workspace = dict(container.onboarding.status(principal_id=context.principal_id).get("workspace") or {})
    stats = [
        {
            "label": str(key).replace("_", " ").title(),
            "value": str(int(value or 0)),
        }
        for key, value in dict(digest.get("stats") or {}).items()
    ]
    return _render_public_template(
        request,
        "console_shell.html",
        **_console_shell_context(
            request=request,
            page_title=f"Executive Assistant {str(digest.get('headline') or 'Channel digest')}",
            current_nav="today",
            context=context,
            console_title=str(digest.get("headline") or "Channel digest"),
            console_summary=" ".join(
                part
                for part in (
                    str(digest.get("summary") or "").strip(),
                    str(digest.get("preview_text") or "").strip(),
                )
                if part
            ),
            nav_groups=APP_NAV_GROUPS,
            workspace_label=str(workspace.get("name") or "Executive Workspace"),
            cards=[
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
            ],
            stats=stats,
        ),
    )


@router.get("/app/channel/queue/{item_ref:path}/resolve")
def app_channel_resolve_queue_item(
    item_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    return_to = _normalize_browser_return_to(request.query_params.get("return_to"), default="/app/channel-loop")
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


@router.get("/app/channel/decisions/{decision_ref:path}/resolve")
def app_channel_resolve_decision(
    decision_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    return_to = _normalize_browser_return_to(request.query_params.get("return_to"), default="/app/channel-loop")
    action = str(request.query_params.get("action") or "resolve").strip() or "resolve"
    reason = str(request.query_params.get("reason") or "Resolved from inline loop.").strip() or "Resolved from inline loop."
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    updated = product.resolve_decision(
        principal_id=context.principal_id,
        decision_ref=decision_ref,
        actor=actor,
        action=action,
        reason=reason,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.get("/app/channel/handoffs/{handoff_ref:path}/assign")
def app_channel_assign_handoff(
    handoff_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    return_to = _normalize_browser_return_to(request.query_params.get("return_to"), default="/app/channel-loop")
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
    return_to = _normalize_browser_return_to(request.query_params.get("return_to"), default="/app/channel-loop")
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
