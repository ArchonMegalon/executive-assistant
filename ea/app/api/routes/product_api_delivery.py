from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.api.routes.product_api_contracts import (
    ChannelDigestDeliveryCreateIn,
    ChannelDigestDeliveryOut,
    ChannelLoopOut,
    GoogleSignalSyncOut,
    GoogleSignalSyncStatusOut,
    OfficeEventOut,
    OfficeEventResponse,
    OfficeSignalIn,
    OfficeSignalResultOut,
    PocketSignalCursorResetIn,
    PocketSignalCursorResetOut,
    PocketRecordingDetailOut,
    PocketSignalImportIn,
    PocketSignalImportOut,
    PocketSignalSyncOut,
    SignalIngestEndpointCreateIn,
    SignalIngestEndpointOut,
    WillhabenPropertyTourIn,
    WillhabenPropertyTourOut,
    WebhookDeliveryOut,
    WebhookDeliveryResponse,
    WebhookOut,
    WebhookRegisterIn,
    WebhookResponse,
    WebhookTestResultOut,
    now_iso,
)
from app.container import AppContainer
from app.product.service import build_product_service

router = APIRouter(prefix="/app/api", tags=["product"])


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


@router.get("/events", response_model=OfficeEventResponse)
def get_office_events(
    limit: int = Query(default=50, ge=1, le=200),
    event_type: str = Query(default=""),
    channel: str = Query(default=""),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> OfficeEventResponse:
    service = build_product_service(container)
    items = service.list_office_events(
        principal_id=context.principal_id,
        limit=limit,
        event_type=event_type,
        channel=channel,
    )
    return OfficeEventResponse(generated_at=now_iso(), items=[OfficeEventOut(**item) for item in items], total=len(items))


@router.post("/signals/ingest", response_model=OfficeSignalResultOut)
def ingest_office_signal(
    body: OfficeSignalIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> OfficeSignalResultOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    payload = service.ingest_office_signal(
        principal_id=context.principal_id,
        signal_type=body.signal_type,
        channel=body.channel,
        title=body.title,
        summary=body.summary,
        text=body.text,
        source_ref=body.source_ref,
        external_id=body.external_id,
        counterparty=body.counterparty,
        stakeholder_id=body.stakeholder_id,
        due_at=body.due_at,
        payload=body.payload,
        actor=actor,
    )
    return OfficeSignalResultOut(**payload)


@router.post("/signals/willhaben/property-tour", response_model=WillhabenPropertyTourOut)
def create_willhaben_property_tour(
    body: WillhabenPropertyTourIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WillhabenPropertyTourOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    try:
        payload = service.create_willhaben_property_tour(
            principal_id=context.principal_id,
            property_url=body.property_url,
            recipient_email=body.recipient_email,
            variant_key=body.variant_key,
            binding_id=body.binding_id,
            source_ref=body.source_ref,
            external_id=body.external_id,
            auto_deliver=body.auto_deliver,
            actor=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WillhabenPropertyTourOut(**payload)


@router.post("/signals/pocket/upload-url", response_model=SignalIngestEndpointOut)
def create_pocket_signal_upload_url(
    request: Request,
    body: SignalIngestEndpointCreateIn | None = None,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> SignalIngestEndpointOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    spec = body or SignalIngestEndpointCreateIn()
    payload = service.issue_signal_ingest_endpoint(
        principal_id=context.principal_id,
        channel="pocket",
        signal_type=spec.signal_type,
        label=spec.label,
        counterparty=spec.counterparty,
        base_url=_public_base_url(request),
        actor=actor,
    )
    return SignalIngestEndpointOut(**payload)


@router.post("/signals/pocket/import-local", response_model=PocketSignalImportOut)
def import_pocket_saved_links_from_local_path(
    body: PocketSignalImportIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PocketSignalImportOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    try:
        payload = service.import_pocket_saved_links_from_local_path(
            principal_id=context.principal_id,
            path=body.path,
            counterparty=body.counterparty,
            actor=actor,
        )
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 404 if detail == "pocket_import_path_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return PocketSignalImportOut(**payload)


@router.post("/signals/pocket/sync", response_model=PocketSignalSyncOut)
def sync_pocket_recordings(
    limit: int = Query(default=5, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PocketSignalSyncOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    try:
        payload = service.sync_pocket_recordings(
            principal_id=context.principal_id,
            actor=actor,
            limit=limit,
        )
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 429 if detail.startswith("pocket_api_http_429:") else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return PocketSignalSyncOut(**payload)


@router.post("/signals/pocket/backfill", response_model=PocketSignalSyncOut)
def backfill_pocket_recordings(
    limit: int = Query(default=25, ge=1, le=250),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PocketSignalSyncOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    try:
        payload = service.backfill_pocket_recordings(
            principal_id=context.principal_id,
            actor=actor,
            limit=limit,
        )
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 429 if detail.startswith("pocket_api_http_429:") else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return PocketSignalSyncOut(**payload)


@router.post("/signals/pocket/reset-cursor", response_model=PocketSignalCursorResetOut)
def reset_pocket_recording_sync_cursor(
    body: PocketSignalCursorResetIn | None = None,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PocketSignalCursorResetOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    payload = service.reset_pocket_recording_sync_cursor(
        principal_id=context.principal_id,
        actor=actor,
        reason=str((body.reason if body is not None else "") or "").strip(),
    )
    return PocketSignalCursorResetOut(**payload)


@router.get("/signals/pocket/recordings/{recording_id}", response_model=PocketRecordingDetailOut)
def get_pocket_recording_detail(
    recording_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PocketRecordingDetailOut:
    service = build_product_service(container)
    try:
        payload = service.get_pocket_recording_detail(recording_id=recording_id)
    except RuntimeError as exc:
        detail = str(exc)
        if detail == "pocket_recording_not_found":
            status_code = 404
        elif detail.startswith("pocket_api_http_429:"):
            status_code = 429
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return PocketRecordingDetailOut(**payload)


@router.post("/signals/google/sync", response_model=GoogleSignalSyncOut)
def sync_google_workspace_signals(
    email_limit: int = Query(default=5, ge=0, le=25),
    calendar_limit: int = Query(default=5, ge=0, le=25),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> GoogleSignalSyncOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "google_sync").strip()
    try:
        payload = service.sync_google_workspace_signals(
            principal_id=context.principal_id,
            actor=actor,
            email_limit=email_limit,
            calendar_limit=calendar_limit,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GoogleSignalSyncOut(**payload)


@router.get("/signals/google/status", response_model=GoogleSignalSyncStatusOut)
def get_google_signal_sync_status(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> GoogleSignalSyncStatusOut:
    service = build_product_service(container)
    return GoogleSignalSyncStatusOut(**service.google_signal_sync_status(principal_id=context.principal_id))


@router.get("/webhooks", response_model=WebhookResponse)
def get_webhooks(
    limit: int = Query(default=50, ge=1, le=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WebhookResponse:
    service = build_product_service(container)
    items = service.list_webhooks(principal_id=context.principal_id, limit=limit)
    return WebhookResponse(generated_at=now_iso(), items=[WebhookOut(**item) for item in items], total=len(items))


@router.post("/webhooks", response_model=WebhookOut)
def register_webhook(
    body: WebhookRegisterIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WebhookOut:
    service = build_product_service(container)
    payload = service.register_webhook(
        principal_id=context.principal_id,
        label=body.label,
        target_url=body.target_url,
        event_types=tuple(body.event_types),
        status=body.status,
    )
    return WebhookOut(**payload)


@router.get("/webhooks/deliveries", response_model=WebhookDeliveryResponse)
def get_webhook_deliveries(
    webhook_id: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WebhookDeliveryResponse:
    service = build_product_service(container)
    items = service.list_webhook_deliveries(
        principal_id=context.principal_id,
        webhook_id=webhook_id,
        limit=limit,
    )
    return WebhookDeliveryResponse(generated_at=now_iso(), items=[WebhookDeliveryOut(**item) for item in items], total=len(items))


@router.post("/webhooks/{webhook_id}/test", response_model=WebhookTestResultOut)
def test_webhook(
    webhook_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WebhookTestResultOut:
    service = build_product_service(container)
    payload = service.test_webhook(principal_id=context.principal_id, webhook_id=webhook_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="webhook_not_found")
    return WebhookTestResultOut(webhook=WebhookOut(**payload["webhook"]), delivery=WebhookDeliveryOut(**payload["delivery"]))


@router.get("/channel-loop", response_model=ChannelLoopOut)
def get_channel_loop(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ChannelLoopOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="channel_loop_opened",
        surface="channel_loop_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return ChannelLoopOut(
        **service.channel_loop_pack(
            principal_id=context.principal_id,
            operator_id=str(context.operator_id or "").strip(),
        )
    )


@router.get("/channel-loop/{digest_key}/plain", response_class=PlainTextResponse)
def get_channel_digest_plain(
    digest_key: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PlainTextResponse:
    service = build_product_service(container)
    text = service.channel_digest_text(
        principal_id=context.principal_id,
        digest_key=digest_key,
        operator_id=str(context.operator_id or "").strip(),
        base_url=_public_base_url(request),
    )
    if not text:
        raise HTTPException(status_code=404, detail="channel_digest_not_found")
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="channel_digest_plain_opened",
        surface=f"channel_digest_{digest_key}_plain_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return PlainTextResponse(text)


@router.post("/channel-loop/{digest_key}/deliveries", response_model=ChannelDigestDeliveryOut)
def create_channel_digest_delivery(
    digest_key: str,
    body: ChannelDigestDeliveryCreateIn,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ChannelDigestDeliveryOut:
    service = build_product_service(container)
    payload = service.issue_channel_digest_delivery(
        principal_id=context.principal_id,
        digest_key=digest_key,
        recipient_email=body.recipient_email,
        role=body.role,
        display_name=body.display_name,
        operator_id=body.operator_id,
        delivery_channel=body.delivery_channel,
        expires_in_hours=body.expires_in_hours,
        base_url=_public_base_url(request),
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="channel_digest_not_found")
    return ChannelDigestDeliveryOut(**payload)
