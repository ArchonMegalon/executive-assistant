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
    get_cloudflare_access_identity,
    get_container,
    get_request_context,
)
from app.api.routes.landing import (
    _console_shell_context,
    _default_operator_id_for_browser,
    _render_public_template,
)
from app.api.routes.product_api_contracts import OfficeSignalResultOut, SignalIngestEndpointOut
from app.api.routes.landing_content import APP_NAV_GROUPS
from app.container import AppContainer
from app.product.service import build_product_service

router = APIRouter(tags=["landing"])


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


@router.get("/app/channel-actions/{token}", response_model=None)
def app_channel_action(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
):
    product = build_product_service(container)
    actor = str(
        getattr(access_identity, "email", "")
        or request.headers.get("X-EA-Operator-ID")
        or request.headers.get("X-EA-Principal-ID")
        or "channel_link"
    ).strip() or "channel_link"
    resolved = product.redeem_channel_action_token(token=token, actor=actor)
    if resolved is None:
        raise HTTPException(status_code=404, detail="channel_action_not_found")
    return_to = str(resolved.get("return_to") or "/sign-in").strip() or "/sign-in"
    if access_identity is not None or str(request.headers.get("X-EA-Principal-ID") or "").strip():
        return RedirectResponse(return_to, status_code=303)
    body = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="robots" content="noindex,nofollow,noarchive,nosnippet">
    <title>Executive Assistant action applied</title>
  </head>
  <body>
    <main>
      <h1>Executive Assistant action applied</h1>
      <p>The requested {html.escape(str(resolved.get("object_kind") or "workspace action"))} action was recorded.</p>
      <p><a href="{html.escape(return_to)}">Open the related workspace surface</a></p>
      <p><a href="/sign-in">Workspace access</a></p>
    </main>
  </body>
</html>"""
    response = HTMLResponse(body)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


@router.get("/channel-loop/deliveries/{token}", response_model=None)
def channel_digest_delivery_open(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
):
    product = build_product_service(container)
    delivery = product.preview_channel_digest_delivery(token=token, base_url=_public_base_url(request))
    if delivery is None:
        raise HTTPException(status_code=404, detail="channel_digest_delivery_not_found")
    response = RedirectResponse(str(delivery.get("open_url") or "/app/channel-loop").strip() or "/app/channel-loop", status_code=303)
    response.set_cookie("ea_workspace_session", str(delivery.get("access_token") or "").strip(), httponly=True, samesite="lax", path="/")
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


@router.get("/app/channel/decisions/{decision_ref:path}/resolve")
def app_channel_resolve_decision(
    decision_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    return_to = str(request.query_params.get("return_to") or "/app/channel-loop").strip() or "/app/channel-loop"
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
