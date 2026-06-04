from __future__ import annotations

import os
import urllib.parse
from urllib.parse import urlparse
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.api.routes.product_api_contracts import (
    ChannelDigestDeliveryCreateIn,
    ChannelDigestDeliveryOut,
    ChannelLoopOut,
    GoogleLocationHistoryConnectCallbackOut,
    GoogleLocationHistoryConnectStartOut,
    GoogleLocationHistoryImportIn,
    GoogleLocationHistoryImportOut,
    GoogleLocationHistorySyncOut,
    GooglePhotosPickerSessionIn,
    GooglePhotosPickerSessionOut,
    GooglePhotosSignalSyncIn,
    GooglePhotosSignalSyncOut,
    GoogleSignalSyncOut,
    GoogleSignalSyncStatusOut,
    NoneverbiaSignalImportIn,
    NoneverbiaSignalImportOut,
    OneDriveDocumentQueryTelegramDeliveryOut,
    OfficeEventOut,
    OfficeEventResponse,
    OfficeSignalIn,
    OfficeSignalResultOut,
    PocketSignalCursorResetIn,
    PocketSignalCursorResetOut,
    PocketRecordingDetailOut,
    PocketRecordingAudioEnhanceOut,
    PocketRecordingSearchOut,
    PocketRecordingTelegramDeliveryOut,
    PocketRecordingQueryTelegramDeliveryOut,
    PocketSignalImportIn,
    PocketSignalImportOut,
    PocketSignalSyncOut,
    PropertyBillingCaptureIn,
    PropertyBillingCaptureOut,
    PropertyBillingCheckoutCreateIn,
    PropertyBillingCheckoutOut,
    PropertyScoutSyncOut,
    PropertySearchRunStartIn,
    PropertySearchRunStartOut,
    PropertySearchRunStatusOut,
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
from app.services.property_billing import (
    capture_paypal_property_order,
    create_payfunnels_property_checkout,
    create_paypal_property_order,
    enforce_property_plan_limits,
    merge_property_commercial,
    paid_plan_expiry,
    payfunnels_configured,
    paypal_configured,
    property_plan_spec,
    verify_payfunnels_webhook_signature,
)

router = APIRouter(prefix="/app/api", tags=["product"])


_PAYFUNNELS_TITLE_PRINCIPAL_RE = re.compile(r"pq_principal:([^|]+)")
_PAYFUNNELS_TITLE_ORDER_RE = re.compile(r"pq_order:([^|]+)")


def _payfunnels_title_value(pattern: re.Pattern[str], title: str) -> str:
    match = pattern.search(str(title or ""))
    if match is None:
        return ""
    return str(match.group(1) or "").strip()


def _payfunnels_field_value(payload: dict[str, object], label: str) -> str:
    target = str(label or "").strip().lower()
    if not target:
        return ""
    fields = payload.get("additionalFields")
    if not isinstance(fields, list):
        return ""
    for item in fields:
        if not isinstance(item, dict):
            continue
        item_label = str(item.get("label") or item.get("name") or "").strip().lower()
        if item_label != target:
            continue
        for key in ("hiddenFieldValue", "value", "fieldValue"):
            value = str(item.get(key) or "").strip()
            if value:
                return value
    return ""


def _public_base_url(request: Request) -> str:
    forwarded_host = str(request.headers.get("x-forwarded-host") or "").strip().lower().rstrip(".")
    request_host = str(request.url.hostname or "").strip().lower().rstrip(".")
    effective_host = forwarded_host or request_host
    if effective_host in {"propertyquarry.com", "www.propertyquarry.com"}:
        explicit_property = (
            str(os.environ.get("PROPERTYQUARRY_PUBLIC_BASE_URL") or "").strip().rstrip("/")
            or str(os.environ.get("EA_PROPERTY_PUBLIC_BASE_URL") or "").strip().rstrip("/")
        )
        if explicit_property:
            return explicit_property
        return f"https://{effective_host}"
    explicit = str(os.environ.get("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    redirect_uri = str(os.environ.get("EA_GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
    if redirect_uri:
        parsed = urlparse(redirect_uri)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return str(request.base_url).rstrip("/")


def _property_preferences(container: AppContainer, *, principal_id: str) -> dict[str, object]:
    state = container.onboarding.status(principal_id=principal_id)
    preferences = dict(state.get("property_search_preferences") or {})
    raw_preferences = dict(preferences.get("raw_preferences") or {})
    return raw_preferences or preferences


def _save_property_preferences(
    container: AppContainer,
    *,
    principal_id: str,
    property_preferences: dict[str, object],
) -> dict[str, object]:
    return container.onboarding.upsert_property_search_preferences(
        principal_id=principal_id,
        property_search_preferences_json=property_preferences,
    )


def _property_billing_return_path(plan_key: str) -> str:
    return f"/app/api/signals/property/billing/paypal/return?plan_key={plan_key}"


def _property_billing_cancel_path(plan_key: str) -> str:
    return f"/app/api/signals/property/billing/paypal/cancel?plan_key={plan_key}"


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


@router.post("/signals/noneverbia/import-local", response_model=NoneverbiaSignalImportOut)
def import_noneverbia_meetings_from_local_path(
    body: NoneverbiaSignalImportIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> NoneverbiaSignalImportOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    try:
        payload = service.import_noneverbia_meetings_from_local_path(
            principal_id=context.principal_id,
            path=body.path,
            counterparty=body.counterparty,
            actor=actor,
        )
    except RuntimeError as exc:
        detail = str(exc)
        if detail == "noneverbia_import_path_not_found":
            status_code = 404
        elif detail == "noneverbia_import_path_not_allowed":
            status_code = 403
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return NoneverbiaSignalImportOut(**payload)


@router.post("/signals/google/location-history/import", response_model=GoogleLocationHistoryImportOut)
def import_google_location_history(
    body: GoogleLocationHistoryImportIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> GoogleLocationHistoryImportOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    try:
        payload = service.import_google_location_history(
            principal_id=context.principal_id,
            actor=actor,
            path=body.path,
        )
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 404 if detail == "google_location_history_import_path_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return GoogleLocationHistoryImportOut(**payload)


@router.post("/signals/google/location-history/connect-start", response_model=GoogleLocationHistoryConnectStartOut)
def start_google_location_history_connect(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> GoogleLocationHistoryConnectStartOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    payload = service.start_google_location_history_connect(
        principal_id=context.principal_id,
        actor=actor,
        redirect_uri_override=f"{_public_base_url(request)}/google/callback",
    )
    return GoogleLocationHistoryConnectStartOut(**payload)


@router.get("/signals/google/location-history/callback", response_model=GoogleLocationHistoryConnectCallbackOut)
def complete_google_location_history_connect(
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    container: AppContainer = Depends(get_container),
) -> GoogleLocationHistoryConnectCallbackOut:
    service = build_product_service(container)
    try:
        payload = service.complete_google_location_history_connect(
            code=code,
            state=state,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GoogleLocationHistoryConnectCallbackOut(**payload)


@router.post("/signals/google/location-history/sync", response_model=GoogleLocationHistorySyncOut)
def sync_google_location_history_portability(
    force: bool = Query(default=False),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> GoogleLocationHistorySyncOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    try:
        payload = service.sync_google_location_history_portability(
            principal_id=context.principal_id,
            actor=actor,
            force=force,
        )
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 409 if detail == "google_location_history_binding_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return GoogleLocationHistorySyncOut(**payload)


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
    limit: int = Query(default=0, ge=0, le=250),
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


@router.get("/signals/pocket/recordings/search", response_model=PocketRecordingSearchOut)
def search_pocket_recordings(
    q: str = Query(default=""),
    before: str = Query(default=""),
    after: str = Query(default=""),
    limit: int = Query(default=10, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PocketRecordingSearchOut:
    service = build_product_service(container)
    payload = service.search_pocket_recordings(
        principal_id=context.principal_id,
        actor=str(context.operator_id or context.access_email or context.principal_id or "office_api").strip(),
        query=q,
        before=before,
        after=after,
        limit=limit,
    )
    return PocketRecordingSearchOut(**payload)


@router.get("/signals/pocket/recordings/{recording_id}", response_model=PocketRecordingDetailOut)
def get_pocket_recording_detail(
    recording_id: str,
    prefer_audio_fallback: bool = Query(default=False),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PocketRecordingDetailOut:
    service = build_product_service(container)
    try:
        payload = service.get_pocket_recording_detail(
            recording_id=recording_id,
            prefer_audio_fallback=prefer_audio_fallback,
            principal_id=context.principal_id,
            actor=str(context.operator_id or context.access_email or context.principal_id or "office_api").strip(),
        )
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


@router.post("/signals/pocket/recordings/{recording_id}/retranscribe", response_model=PocketRecordingDetailOut)
def retranscribe_pocket_recording(
    recording_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PocketRecordingDetailOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    try:
        payload = service.retranscribe_pocket_recording(
            principal_id=context.principal_id,
            actor=actor,
            recording_id=recording_id,
        )
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


@router.post("/signals/pocket/recordings/{recording_id}/deliver-telegram", response_model=PocketRecordingTelegramDeliveryOut)
def deliver_pocket_recording_to_telegram(
    recording_id: str,
    enhanced: bool = Query(default=False),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PocketRecordingTelegramDeliveryOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    try:
        payload = service.deliver_pocket_recording_to_telegram(
            principal_id=context.principal_id,
            actor=actor,
            recording_id=recording_id,
            prefer_enhanced=enhanced,
        )
    except RuntimeError as exc:
        detail = str(exc)
        if detail == "pocket_recording_not_found":
            status_code = 404
        elif detail.startswith("pocket_api_http_429:"):
            status_code = 429
        elif detail in {"telegram_binding_not_found", "pocket_recording_audio_unavailable"}:
            status_code = 409
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return PocketRecordingTelegramDeliveryOut(**payload)


@router.post("/signals/pocket/recordings/{recording_id}/enhance-audio", response_model=PocketRecordingAudioEnhanceOut)
def enhance_pocket_recording_audio(
    recording_id: str,
    force: bool = Query(default=False),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PocketRecordingAudioEnhanceOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    try:
        payload = service.enhance_pocket_recording_audio(
            principal_id=context.principal_id,
            actor=actor,
            recording_id=recording_id,
            force=force,
        )
    except RuntimeError as exc:
        detail = str(exc)
        if detail == "pocket_recording_not_found":
            status_code = 404
        elif detail.startswith("pocket_api_http_429:"):
            status_code = 429
        elif detail in {"pocket_recording_audio_unavailable", "pocket_recording_audio_archive_missing", "ffmpeg_unavailable"}:
            status_code = 409
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return PocketRecordingAudioEnhanceOut(**payload)


@router.post("/signals/pocket/recordings/deliver-telegram", response_model=PocketRecordingQueryTelegramDeliveryOut)
def deliver_pocket_recording_search_to_telegram(
    q: str = Query(default=""),
    before: str = Query(default=""),
    after: str = Query(default=""),
    limit: int = Query(default=10, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PocketRecordingQueryTelegramDeliveryOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    try:
        payload = service.deliver_pocket_recording_search_to_telegram(
            principal_id=context.principal_id,
            actor=actor,
            query=q,
            before=before,
            after=after,
            limit=limit,
        )
    except RuntimeError as exc:
        detail = str(exc)
        if detail == "pocket_recording_search_match_not_found":
            status_code = 404
        elif detail.startswith("pocket_api_http_429:"):
            status_code = 429
        elif detail in {"telegram_binding_not_found", "pocket_recording_audio_unavailable"}:
            status_code = 409
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return PocketRecordingQueryTelegramDeliveryOut(**payload)


@router.post("/signals/onedrive/documents/deliver-telegram", response_model=OneDriveDocumentQueryTelegramDeliveryOut)
def deliver_onedrive_document_search_to_telegram(
    q: str = Query(default=""),
    limit: int = Query(default=10, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> OneDriveDocumentQueryTelegramDeliveryOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "office_api").strip()
    try:
        payload = service.deliver_onedrive_document_search_to_telegram(
            principal_id=context.principal_id,
            actor=actor,
            query=q,
            limit=limit,
        )
    except RuntimeError as exc:
        detail = str(exc)
        if detail == "onedrive_document_search_match_not_found":
            status_code = 404
        elif detail == "telegram_binding_not_found":
            status_code = 409
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return OneDriveDocumentQueryTelegramDeliveryOut(**payload)


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
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GoogleSignalSyncOut(**payload)


@router.post("/signals/google/willhaben-sync", response_model=GoogleSignalSyncOut)
@router.post("/signals/google/property-sync", response_model=GoogleSignalSyncOut)
def sync_google_willhaben_signals(
    email_limit: int = Query(default=10, ge=0, le=50),
    account_email: str = Query(default=""),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> GoogleSignalSyncOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "google_sync").strip()
    try:
        payload = service.sync_google_willhaben_signals(
            principal_id=context.principal_id,
            actor=actor,
            account_email=account_email,
            email_limit=email_limit,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GoogleSignalSyncOut(**payload)


@router.post("/signals/property/scout", response_model=PropertyScoutSyncOut)
def sync_direct_property_scout(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PropertyScoutSyncOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "property_scout").strip()
    try:
        payload = service.sync_direct_property_scout(
            principal_id=context.principal_id,
            actor=actor,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PropertyScoutSyncOut(**payload)


@router.post("/signals/property/search/run", response_model=PropertySearchRunStartOut)
def start_property_search_run(
    body: PropertySearchRunStartIn,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PropertySearchRunStartOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "property_search").strip()
    try:
        merged_preferences = _property_preferences(container, principal_id=context.principal_id)
        merged_preferences.update(dict(body.property_preferences))
        enforce_property_plan_limits(
            property_preferences=merged_preferences,
            selected_platforms=tuple(body.selected_platforms),
            max_results_per_source=body.max_results_per_source,
        )
        payload = service.start_property_search_run(
            principal_id=context.principal_id,
            actor=actor,
            selected_platforms=tuple(body.selected_platforms),
            property_search_preferences=dict(body.property_preferences),
            force_refresh=bool(body.force_refresh),
            max_results_per_source=body.max_results_per_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not str(payload.get("status_url") or "").strip() and str(payload.get("run_id") or "").strip():
        payload["status_url"] = f"/app/api/signals/property/search/run/{payload.get('run_id')}"
    return PropertySearchRunStartOut(**payload)


@router.post("/signals/property/billing/paypal/order", response_model=PropertyBillingCheckoutOut)
def create_property_billing_order(
    body: PropertyBillingCheckoutCreateIn,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PropertyBillingCheckoutOut:
    if not paypal_configured():
        raise HTTPException(status_code=409, detail="paypal_not_configured")
    try:
        spec = property_plan_spec(body.plan_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if spec.plan_key == "free":
        raise HTTPException(status_code=400, detail="property_plan_free_does_not_require_checkout")
    base_url = _public_base_url(request)
    try:
        order = create_paypal_property_order(
            principal_id=context.principal_id,
            plan_key=spec.plan_key,
            return_url=f"{base_url}{_property_billing_return_path(spec.plan_key)}",
            cancel_url=f"{base_url}{_property_billing_cancel_path(spec.plan_key)}",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    updated = merge_property_commercial(
        _property_preferences(container, principal_id=context.principal_id),
        updates={
            "pending_order_id": str(order.get("order_id") or ""),
            "pending_plan_key": spec.plan_key,
            "pending_approval_url": str(order.get("approve_url") or ""),
            "last_payment_status": str(order.get("status") or ""),
            "plan_source": "paypal",
        },
    )
    _save_property_preferences(container, principal_id=context.principal_id, property_preferences=updated)
    return PropertyBillingCheckoutOut(
        generated_at=now_iso(),
        plan_key=spec.plan_key,
        order_id=str(order.get("order_id") or ""),
        approve_url=str(order.get("approve_url") or ""),
        status=str(order.get("status") or ""),
        amount_eur=str(order.get("amount_eur") or spec.amount_eur),
    )


@router.post("/signals/property/billing/payfunnels/order", response_model=PropertyBillingCheckoutOut)
def create_property_billing_order_payfunnels(
    body: PropertyBillingCheckoutCreateIn,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PropertyBillingCheckoutOut:
    try:
        spec = property_plan_spec(body.plan_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if spec.plan_key == "free":
        raise HTTPException(status_code=400, detail="property_plan_free_does_not_require_checkout")
    if not payfunnels_configured(plan_key=spec.plan_key):
        raise HTTPException(status_code=409, detail="payfunnels_not_configured")
    base_url = _public_base_url(request)
    try:
        checkout = create_payfunnels_property_checkout(
            principal_id=context.principal_id,
            plan_key=spec.plan_key,
            return_url=f"{base_url}/app/api/signals/property/billing/payfunnels/return?plan_key={spec.plan_key}",
            cancel_url=f"{base_url}/app/api/signals/property/billing/payfunnels/cancel?plan_key={spec.plan_key}",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    updated = merge_property_commercial(
        _property_preferences(container, principal_id=context.principal_id),
        updates={
            "pending_order_id": str(checkout.get("order_id") or ""),
            "pending_plan_key": spec.plan_key,
            "pending_approval_url": str(checkout.get("approve_url") or ""),
            "last_payment_status": str(checkout.get("status") or ""),
            "plan_source": "payfunnels",
        },
    )
    _save_property_preferences(container, principal_id=context.principal_id, property_preferences=updated)
    return PropertyBillingCheckoutOut(
        generated_at=now_iso(),
        plan_key=spec.plan_key,
        order_id=str(checkout.get("order_id") or ""),
        approve_url=str(checkout.get("approve_url") or ""),
        status=str(checkout.get("status") or ""),
        amount_eur=str(checkout.get("amount_eur") or spec.amount_eur),
    )


@router.post("/signals/property/billing/paypal/capture", response_model=PropertyBillingCaptureOut)
def capture_property_billing_order(
    body: PropertyBillingCaptureIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PropertyBillingCaptureOut:
    try:
        spec = property_plan_spec(body.plan_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if spec.plan_key == "free":
        raise HTTPException(status_code=400, detail="property_plan_free_does_not_require_checkout")
    try:
        captured = capture_paypal_property_order(order_id=body.order_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    active_until = paid_plan_expiry(plan_key=spec.plan_key)
    updated = merge_property_commercial(
        _property_preferences(container, principal_id=context.principal_id),
        updates={
            "active_plan_key": spec.plan_key,
            "status": "active",
            "active_until": active_until,
            "last_order_id": str(captured.get("order_id") or ""),
            "last_capture_id": str(captured.get("capture_id") or ""),
            "last_payment_status": str(captured.get("payment_status") or ""),
            "last_payment_amount_eur": str(captured.get("amount_eur") or spec.amount_eur),
            "last_payer_email": str(captured.get("payer_email") or ""),
            "captured_at": now_iso(),
            "pending_order_id": "",
            "pending_plan_key": "",
            "pending_approval_url": "",
            "plan_source": "paypal",
        },
    )
    _save_property_preferences(container, principal_id=context.principal_id, property_preferences=updated)
    return PropertyBillingCaptureOut(
        generated_at=now_iso(),
        order_id=str(captured.get("order_id") or body.order_id),
        plan_key=spec.plan_key,
        capture_id=str(captured.get("capture_id") or ""),
        payment_status=str(captured.get("payment_status") or ""),
        payer_email=str(captured.get("payer_email") or ""),
        amount_eur=str(captured.get("amount_eur") or spec.amount_eur),
        active_until=active_until,
        current_plan_key=spec.plan_key,
    )


@router.get("/signals/property/billing/paypal/return", include_in_schema=False)
def capture_property_billing_order_return(
    token: str = Query(default=""),
    plan_key: str = Query(default=""),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    order_id = str(token or "").strip()
    if not order_id:
        raise HTTPException(status_code=400, detail="paypal_order_id_required")
    capture_property_billing_order(
        PropertyBillingCaptureIn(order_id=order_id, plan_key=plan_key or "free"),
        container=container,
        context=context,
    )
    return RedirectResponse(f"/app/properties?billing=success&plan={plan_key}", status_code=303)


@router.get("/signals/property/billing/payfunnels/return", include_in_schema=False)
def payfunnels_property_billing_return(
    plan_key: str = Query(default=""),
) -> RedirectResponse:
    return RedirectResponse(f"/app/properties?billing=pending_confirmation&plan={plan_key}&provider=payfunnels", status_code=303)


@router.get("/signals/property/billing/payfunnels/cancel", include_in_schema=False)
def payfunnels_property_billing_cancel(
    plan_key: str = Query(default=""),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    updated = merge_property_commercial(
        _property_preferences(container, principal_id=context.principal_id),
        updates={
            "status": "free",
            "pending_order_id": "",
            "pending_plan_key": "",
            "pending_approval_url": "",
            "last_payment_status": "cancelled",
            "plan_source": "payfunnels",
        },
    )
    _save_property_preferences(container, principal_id=context.principal_id, property_preferences=updated)
    return RedirectResponse(f"/app/properties?billing=cancelled&plan={plan_key}&provider=payfunnels", status_code=303)


@router.post("/signals/property/billing/payfunnels/webhook")
async def payfunnels_property_billing_webhook(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    body_bytes = await request.body()
    signature = str(request.headers.get("x-payfunnels-signature") or "").strip()
    if not verify_payfunnels_webhook_signature(body_bytes=body_bytes, signature=signature):
        raise HTTPException(status_code=401, detail="payfunnels_signature_invalid")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="payfunnels_webhook_invalid_json") from exc
    metadata = dict(payload.get("metadata") or {})
    invoice_title = str(payload.get("invoiceTitle") or payload.get("title") or "").strip()
    title_principal = _payfunnels_title_value(_PAYFUNNELS_TITLE_PRINCIPAL_RE, invoice_title)
    title_order = _payfunnels_title_value(_PAYFUNNELS_TITLE_ORDER_RE, invoice_title)
    field_principal = _payfunnels_field_value(payload, "pq_principal")
    field_order = _payfunnels_field_value(payload, "pq_order")
    field_plan = _payfunnels_field_value(payload, "pq_plan")
    principal_id = str(
        metadata.get("principal_id")
        or payload.get("principal_id")
        or payload.get("client_reference_id")
        or field_principal
        or urllib.parse.unquote(title_principal)
        or ""
    ).strip()
    plan_key = str(metadata.get("plan_key") or payload.get("plan_key") or field_plan or "").strip().lower()
    if not plan_key and "plus" in invoice_title.lower():
        plan_key = "plus"
    if not plan_key and "agent" in invoice_title.lower():
        plan_key = "agent"
    order_id = str(
        payload.get("order_id")
        or payload.get("checkout_id")
        or payload.get("external_id")
        or payload.get("chargeId")
        or payload.get("invoiceId")
        or field_order
        or urllib.parse.unquote(title_order)
        or metadata.get("order_id")
        or ""
    ).strip()
    payment_status = str(payload.get("payment_status") or payload.get("status") or "").strip().lower()
    payer_email = str(
        payload.get("payer_email")
        or payload.get("customerEmail")
        or dict(payload.get("customer") or {}).get("email")
        or ""
    ).strip()
    amount_eur = str(payload.get("amount_eur") or payload.get("amount") or payload.get("chargeAmount") or "").strip()
    event_type = str(payload.get("event_type") or payload.get("event") or "").strip().lower()
    if not principal_id or not plan_key or not order_id:
        raise HTTPException(status_code=400, detail="payfunnels_webhook_missing_fields")
    try:
        spec = property_plan_spec(plan_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    completed = payment_status in {"paid", "completed", "succeeded", "active"} or event_type in {
        "payment.completed",
        "checkout.completed",
        "subscription.activated",
    }
    if completed:
        active_until = paid_plan_expiry(plan_key=spec.plan_key)
        updated = merge_property_commercial(
            _property_preferences(container, principal_id=principal_id),
            updates={
                "active_plan_key": spec.plan_key,
                "status": "active",
                "active_until": active_until,
                "last_order_id": order_id,
                "last_capture_id": order_id,
                "last_payment_status": payment_status or event_type or "completed",
                "last_payment_amount_eur": amount_eur or spec.amount_eur,
                "last_payer_email": payer_email,
                "captured_at": now_iso(),
                "pending_order_id": "",
                "pending_plan_key": "",
                "pending_approval_url": "",
                "plan_source": "payfunnels",
            },
        )
        _save_property_preferences(container, principal_id=principal_id, property_preferences=updated)
        return {
            "status": "ok",
            "principal_id": principal_id,
            "plan_key": spec.plan_key,
            "current_plan_key": spec.plan_key,
            "payment_status": payment_status or event_type or "completed",
        }
    return {
        "status": "ignored",
        "principal_id": principal_id,
        "plan_key": spec.plan_key,
        "payment_status": payment_status or event_type or "pending",
    }


@router.get("/signals/property/billing/paypal/cancel", include_in_schema=False)
def cancel_property_billing_order_return(
    plan_key: str = Query(default=""),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    updated = merge_property_commercial(
        _property_preferences(container, principal_id=context.principal_id),
        updates={
            "status": "free",
            "pending_order_id": "",
            "pending_plan_key": "",
            "pending_approval_url": "",
            "last_payment_status": "cancelled",
            "plan_source": "paypal",
        },
    )
    _save_property_preferences(container, principal_id=context.principal_id, property_preferences=updated)
    return RedirectResponse(f"/app/properties?billing=cancelled&plan={plan_key}", status_code=303)


@router.get("/signals/property/search/run/{run_id}", response_model=PropertySearchRunStatusOut)
def property_search_run_status(
    run_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PropertySearchRunStatusOut:
    service = build_product_service(container)
    payload = service.get_property_search_run_status(
        principal_id=context.principal_id,
        run_id=run_id,
    )
    if not payload:
        raise HTTPException(status_code=404, detail="property_search_run_not_found")
    return PropertySearchRunStatusOut(**payload)


@router.post("/signals/google/photos/session", response_model=GooglePhotosPickerSessionOut)
def create_google_photos_picker_session(
    body: GooglePhotosPickerSessionIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> GooglePhotosPickerSessionOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "google_photos").strip()
    try:
        payload = service.create_google_photos_picker_session(
            principal_id=context.principal_id,
            actor=actor,
            account_email=body.account_email,
            binding_id=body.binding_id,
            max_item_count=body.max_item_count,
            autoclose=body.autoclose,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GooglePhotosPickerSessionOut(**payload)


@router.get("/signals/google/photos/session/{session_id}", response_model=GooglePhotosPickerSessionOut)
def get_google_photos_picker_session(
    session_id: str,
    account_email: str = Query(default=""),
    binding_id: str = Query(default=""),
    autoclose: bool = Query(default=True),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> GooglePhotosPickerSessionOut:
    service = build_product_service(container)
    try:
        payload = service.get_google_photos_picker_session(
            principal_id=context.principal_id,
            session_id=session_id,
            account_email=account_email,
            binding_id=binding_id,
            autoclose=autoclose,
        )
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 404 if detail == "google_photos_picker_session_not_found" else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return GooglePhotosPickerSessionOut(**payload)


@router.post("/signals/google/photos/sync", response_model=GooglePhotosSignalSyncOut)
def sync_google_photos_signals(
    body: GooglePhotosSignalSyncIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> GooglePhotosSignalSyncOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "google_photos").strip()
    try:
        payload = service.sync_google_photos_signals(
            principal_id=context.principal_id,
            actor=actor,
            session_id=body.session_id,
            account_email=body.account_email,
            binding_id=body.binding_id,
            max_items=body.max_items,
            delete_session=body.delete_session,
        )
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 404 if detail == "google_photos_picker_session_not_found" else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return GooglePhotosSignalSyncOut(**payload)


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
