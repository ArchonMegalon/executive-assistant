from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.container import AppContainer
from app.services.fliplink import build_fliplink_packet_service
from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.public_branding import request_brand


authenticated_router = APIRouter(tags=["fliplink"])
public_router = APIRouter(prefix="/v1/integrations/fliplink", tags=["fliplink"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))


PacketKindLiteral = Literal[
    "owner_review",
    "family_review",
    "agent_brief",
    "shortlist_brochure",
    "paid_market_report",
    "open_house_qr",
]
FlipLinkFormatLiteral = Literal["smart_document", "flipbook_3d"]
PacketPrivacyLiteral = Literal["owner_private", "family_review", "agent_share", "anonymous_public", "paid_customer"]
FeedbackReviewAction = Literal[
    "accept_as_preference_signal",
    "accept_as_viewing_question",
    "dismiss",
    "block_reviewer",
    "convert_to_hard_rule",
]


class PropertyPacketRenderIn(BaseModel):
    packet_kind: PacketKindLiteral = "owner_review"
    privacy_mode: PacketPrivacyLiteral | None = None
    fliplink_format: FlipLinkFormatLiteral | None = None
    person_id: str = Field(default="self", max_length=120)
    search_run_id: str = Field(default="", max_length=160)
    include_floorplan: bool = True
    include_photos: bool = True
    include_exact_address: bool = False
    property_payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("property_payload")
    @classmethod
    def _payload_size_guard(cls, value: dict[str, object]) -> dict[str, object]:
        try:
            encoded = json.dumps(value, separators=(",", ":"), default=str)
        except TypeError as exc:
            raise ValueError("property_payload_must_be_json_serializable") from exc
        if len(encoded.encode("utf-8")) > 100_000:
            raise ValueError("property_payload_too_large")
        return value


class ManualFlipLinkPublicationIn(BaseModel):
    fliplink_url: str = Field(min_length=8, max_length=500)
    fliplink_format: FlipLinkFormatLiteral | None = None
    embed_code: str = Field(default="", max_length=4000)
    qr_url: str = Field(default="", max_length=500)
    lead_capture_enabled: bool = False
    password_required: bool = False
    sale_mode_enabled: bool = False


class FlipLinkFeedbackReviewIn(BaseModel):
    action: FeedbackReviewAction
    note: str = Field(default="", max_length=1000)


def _actor(context: RequestContext) -> str:
    return str(context.operator_id or context.access_email or context.principal_id or "browser").strip()


def _publication_out(row: dict[str, object]) -> dict[str, object]:
    summary = dict(row.get("packet_summary_json") or {}) if isinstance(row.get("packet_summary_json"), dict) else {}
    return {
        "publication_id": str(row.get("publication_id") or ""),
        "principal_id": str(row.get("principal_id") or ""),
        "person_id": str(row.get("person_id") or "self"),
        "property_ref": str(row.get("property_ref") or ""),
        "search_run_id": str(row.get("search_run_id") or ""),
        "packet_kind": str(row.get("packet_kind") or ""),
        "privacy_mode": str(row.get("privacy_mode") or ""),
        "fliplink_format": str(row.get("fliplink_format") or ""),
        "source_pdf_sha256": str(row.get("source_pdf_sha256") or ""),
        "source_pdf_size_bytes": int(row.get("source_pdf_size_bytes") or 0),
        "redaction_policy_version": str(row.get("redaction_policy_version") or ""),
        "fliplink_url": str(row.get("fliplink_url") or ""),
        "fliplink_custom_domain_url": str(row.get("fliplink_custom_domain_url") or ""),
        "fliplink_embed_code": str(row.get("fliplink_embed_code") or ""),
        "fliplink_qr_url": str(row.get("fliplink_qr_url") or ""),
        "lead_capture_enabled": bool(row.get("lead_capture_enabled")),
        "password_required": bool(row.get("password_required")),
        "sale_mode_enabled": bool(row.get("sale_mode_enabled")),
        "status": str(row.get("status") or ""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "published_at": str(row.get("published_at") or ""),
        "recommended_title": str(row.get("recommended_title") or ""),
        "recommended_format": str(row.get("recommended_format") or ""),
        "artifact_download_path": str(row.get("artifact_download_path") or ""),
        "recommended_folder": str(summary.get("recommended_folder") or ""),
        "recommended_custom_domain": str(summary.get("recommended_custom_domain") or ""),
    }


@authenticated_router.get("/app/properties/packets", response_class=HTMLResponse)
def property_packets_dashboard(
    request: Request,
    limit: int = Query(default=100, ge=1, le=300),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    service = build_fliplink_packet_service(container)
    rows = [_publication_out(row) for row in service.list_publications(principal_id=context.principal_id, limit=limit)]
    inbox = service.feedback_inbox(principal_id=context.principal_id, limit=100)
    return templates.TemplateResponse(
        request,
        "app/property_packets.html",
        {
            "brand": request_brand(request),
            "workspace_label": "PropertyQuarry Workspace",
            "current_nav": "packets",
            "publications": rows,
            "feedback_items": list(inbox.get("items") or []),
            "feedback_total": int(inbox.get("total") or 0),
        },
    )


@authenticated_router.get("/app/api/properties/packets")
def list_property_packets(
    limit: int = Query(default=100, ge=1, le=300),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    rows = [_publication_out(row) for row in service.list_publications(principal_id=context.principal_id, limit=limit)]
    return {"items": rows, "total": len(rows)}


@authenticated_router.get("/app/api/properties/packets/feedback-inbox")
def property_packet_feedback_inbox(
    limit: int = Query(default=100, ge=1, le=300),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    return build_fliplink_packet_service(container).feedback_inbox(principal_id=context.principal_id, limit=limit)


@authenticated_router.post("/app/api/properties/packets/feedback/{event_id}/review")
def review_property_packet_feedback(
    event_id: str,
    body: FlipLinkFeedbackReviewIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        event = service.review_feedback(
            principal_id=context.principal_id,
            event_id=event_id,
            action=body.action,
            note=body.note,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.action in {"accept_as_preference_signal", "convert_to_hard_rule"}:
        container.preference_profiles.record_evidence_event(
            principal_id=context.principal_id,
            person_id="self",
            domain="property_scout",
            event_type="fliplink_external_feedback_accepted",
            object_type="property_packet_feedback",
            object_id=event_id,
            source_ref=f"fliplink:event:{event_id}",
            raw_signal_json={"event_id": event_id, "action": body.action, "note": body.note},
            interpreted_signal_json={"trust": "owner_reviewed", "accepted_as": body.action},
            signal_strength=0.7 if body.action == "accept_as_preference_signal" else 0.9,
            reversible=True,
        )
    return {"status": "reviewed", "event": dict(event)}


@authenticated_router.get("/app/api/properties/packets/{publication_id}/pdf")
def download_property_packet_pdf(
    publication_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> FileResponse:
    service = build_fliplink_packet_service(container)
    row = service.get_publication(publication_id=publication_id, principal_id=context.principal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="property_packet_publication_not_found")
    artifact_root = Path(str(container.settings.storage.artifacts_dir or "/tmp/ea_artifacts")).resolve()
    pdf_path = Path(str(row.get("source_pdf_artifact_ref") or "")).resolve()
    if not str(pdf_path).startswith(str(artifact_root)) or not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="property_packet_pdf_not_found")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename=f"{publication_id}.pdf",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@authenticated_router.get("/app/api/properties/packets/{publication_id}")
def get_property_packet_publication(
    publication_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    row = service.get_publication(publication_id=publication_id, principal_id=context.principal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="property_packet_publication_not_found")
    events = service.list_events(publication_id=publication_id, principal_id=context.principal_id, limit=100)
    return {"publication": _publication_out(row), "events": [dict(event) for event in events]}


@authenticated_router.post("/app/api/properties/packets/{publication_id}/fliplink/manual-link")
def record_manual_fliplink_publication(
    publication_id: str,
    body: ManualFlipLinkPublicationIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        row = service.record_manual_link(
            principal_id=context.principal_id,
            publication_id=publication_id,
            fliplink_url=body.fliplink_url,
            fliplink_format=body.fliplink_format,
            embed_code=body.embed_code,
            qr_url=body.qr_url,
            lead_capture_enabled=body.lead_capture_enabled,
            password_required=body.password_required,
            sale_mode_enabled=body.sale_mode_enabled,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"publication": _publication_out(row)}


@authenticated_router.post("/app/api/properties/{property_ref:path}/packets/render")
def render_property_packet(
    property_ref: str,
    body: PropertyPacketRenderIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        row = service.render_packet(
            principal_id=context.principal_id,
            person_id=body.person_id,
            property_ref=property_ref,
            packet_kind=PropertyPacketKind(body.packet_kind),
            privacy_mode=PacketPrivacyMode(body.privacy_mode) if body.privacy_mode else "",
            fliplink_format=FlipLinkFormat(body.fliplink_format) if body.fliplink_format else "",
            search_run_id=body.search_run_id,
            include_exact_address=body.include_exact_address,
            source_payload=body.property_payload,
            actor=_actor(context),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"publication": _publication_out(row)}


@public_router.post("/webhook")
async def fliplink_webhook(
    request: Request,
    secret: str = Query(default=""),
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    content_length = int(request.headers.get("content-length") or 0)
    if content_length > 64_000:
        raise HTTPException(status_code=413, detail="fliplink_webhook_payload_too_large")
    service = build_fliplink_packet_service(container)
    try:
        service.verify_webhook_secret(
            provided_header=str(request.headers.get("x-propertyquarry-webhook-secret") or ""),
            provided_query=secret,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_fliplink_webhook_json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="fliplink_webhook_object_required")
    return service.ingest_lead_webhook(payload=payload)
