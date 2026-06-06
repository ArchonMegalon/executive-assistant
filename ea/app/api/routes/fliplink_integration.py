from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.container import AppContainer
from app.domain.property_preference_events import (
    FLIPLINK_FEEDBACK_SOURCE,
    PREFERENCE_EVENT_FEEDBACK_ACCEPTED,
    PREFERENCE_OBJECT_FEEDBACK,
    PROPERTY_PACKET_FEEDBACK_SOURCE,
    PROPERTY_PREFERENCE_DOMAIN,
)
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


class FlipLinkArchivePublicationIn(BaseModel):
    note: str = Field(default="", max_length=1000)


class BrowserActFlipLinkPublishIn(BaseModel):
    lead_capture_enabled: bool = True
    password_required: bool = False


class BrowserActFlipLinkPublishCompleteIn(BaseModel):
    fliplink_url: str = Field(min_length=8, max_length=500)
    embed_code: str = Field(default="", max_length=4000)
    qr_url: str = Field(default="", max_length=500)
    screenshot_proof_ref: str = Field(default="", max_length=500)
    lead_capture_enabled: bool = True
    password_required: bool = False
    sale_mode_enabled: bool = False


class FlipLinkAnalyticsSnapshotIn(BaseModel):
    views: int | None = Field(default=None, ge=0, le=10_000_000)
    unique_visitors: int | None = Field(default=None, ge=0, le=10_000_000)
    average_time_seconds: int | None = Field(default=None, ge=0, le=10_000_000)
    top_pages: list[dict[str, object]] = Field(default_factory=list, max_length=20)
    referral_sources: list[dict[str, object]] = Field(default_factory=list, max_length=20)
    device_breakdown: dict[str, int] = Field(default_factory=dict)
    geography_breakdown: dict[str, int] = Field(default_factory=dict)
    source: Literal["manual", "browseract", "api"] = "manual"
    screenshot_proof_ref: str = Field(default="", max_length=500)
    captured_from_url: str = Field(default="", max_length=500)


def _actor(context: RequestContext) -> str:
    return str(context.operator_id or context.access_email or context.principal_id or "browser").strip()


def _publication_out(row: dict[str, object], *, analytics: dict[str, object] | None = None) -> dict[str, object]:
    summary = dict(row.get("packet_summary_json") or {}) if isinstance(row.get("packet_summary_json"), dict) else {}
    analytics_out = {
        "views": None,
        "unique_visitors": None,
        "average_time_seconds": None,
        "captured_at": "",
        **dict(analytics or {}),
    }
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
        "renderer_version": str(summary.get("renderer_version") or ""),
        "analytics": analytics_out,
    }


def _feedback_text(*, custom_fields: dict[str, object], note: str = "") -> str:
    parts = [str(note or "")]
    for key in ("reaction", "question", "intent", "viewer_role"):
        parts.append(str(custom_fields.get(key) or ""))
    return " ".join(" ".join(part.split()) for part in parts if str(part or "").strip()).strip().lower()


def _feedback_preference_hints(*, custom_fields: dict[str, object], action: str, note: str = "") -> list[dict[str, object]]:
    text = _feedback_text(custom_fields=custom_fields, note=note)
    hard = str(action or "").strip() == "convert_to_hard_rule"
    strength = "high" if hard else "medium"
    source_mode = "explicit_correction" if hard else "explicit_feedback"
    hints: list[dict[str, object]] = []

    def add(category: str, key: str, value_json: object, *, merge_mode: str = "replace") -> None:
        hint = {
            "domain": PROPERTY_PREFERENCE_DOMAIN,
            "category": category,
            "key": key,
            "value_json": value_json,
            "strength": strength,
            "confidence": 0.95 if hard else 0.75,
            "source_mode": source_mode,
        }
        if merge_mode != "replace":
            hint["merge_mode"] = merge_mode
        if hint not in hints:
            hints.append(hint)

    if any(marker in text for marker in ("floorplan", "floor plan", "grundriss", "plan")):
        add("constraint" if hard else "soft_preference", "require_floorplan" if hard else "requires_floorplan_for_remote_review", True)
    if any(marker in text for marker in ("360", "tour", "virtual")):
        add("constraint" if hard else "soft_preference", "require_360" if hard else "prefer_360_for_remote_review", True)
    if any(marker in text for marker in ("lift", "elevator", "aufzug")):
        add("constraint" if hard else "soft_preference", "require_lift" if hard else "prefer_lift", True)
    if any(marker in text for marker in ("quiet", "noise", "noisy", "traffic", "street noise", "laerm", "lärm", "ruhig")):
        add("constraint" if hard else "soft_preference", "require_quiet_micro_location" if hard else "prefer_quiet_micro_location", True)
    if any(marker in text for marker in ("balcony", "terrace", "garden", "outdoor", "balkon", "terrasse", "garten")):
        add("soft_preference", "prefer_outdoor_space", True)
    if any(marker in text for marker in ("playground", "spielplatz")):
        add("soft_preference", "prefer_playgrounds_nearby", True)
    if any(marker in text for marker in ("supermarket", "grocery", "supermarkt")):
        add("soft_preference", "prefer_supermarket_nearby", True)
    if any(marker in text for marker in ("pharmacy", "apotheke")):
        add("soft_preference", "prefer_pharmacy_nearby", True)
    if any(marker in text for marker in ("subway", "underground", "metro", "u-bahn", "tube")):
        add("soft_preference", "prefer_subway_nearby", True)
    if any(marker in text for marker in ("gas heating", "gasheizung", "gas heater", "gas boiler")):
        add("aversion", "avoid_heating_types", ["Gasheizung"], merge_mode="append_unique")
    return hints


def _apply_feedback_preferences(
    *,
    container: AppContainer,
    context: RequestContext,
    event_id: str,
    review_event: dict[str, object],
    action: str,
    note: str,
    actor: str,
) -> dict[str, object]:
    payload = dict(review_event.get("payload_json") or {})
    target_payload = dict(payload.get("target_payload") or {})
    custom_fields = dict(target_payload.get("custom_fields") or {})
    hints = _feedback_preference_hints(custom_fields=custom_fields, action=action, note=note)
    interpreted: dict[str, object] = {
        "trust": "owner_reviewed",
        "accepted_as": action,
        "feedback_source": PROPERTY_PACKET_FEEDBACK_SOURCE,
        "external_source": FLIPLINK_FEEDBACK_SOURCE,
    }
    if hints:
        interpreted["preference_hints"] = hints
    evidence = container.preference_profiles.record_evidence_event(
        principal_id=context.principal_id,
        person_id="self",
        domain=PROPERTY_PREFERENCE_DOMAIN,
        event_type=PREFERENCE_EVENT_FEEDBACK_ACCEPTED,
        object_type=PREFERENCE_OBJECT_FEEDBACK,
        object_id=event_id,
        source_ref=f"fliplink:event:{event_id}",
        raw_signal_json={
            "event_id": event_id,
            "action": action,
            "note": note,
            "property_ref": str(target_payload.get("property_ref") or ""),
            "packet_kind": str(target_payload.get("packet_kind") or ""),
            "privacy_mode": str(target_payload.get("privacy_mode") or ""),
            "custom_fields": custom_fields,
        },
        interpreted_signal_json=interpreted,
        signal_strength=0.7 if action == "accept_as_preference_signal" else 0.9,
        reversible=True,
    )
    application: dict[str, object] = {
        "evidence_event_id": str(dict(evidence.get("event") or {}).get("event_id") or ""),
        "applied_nodes": list(evidence.get("applied_nodes") or []),
    }
    if action == "convert_to_hard_rule":
        if not hints:
            raise ValueError("fliplink_feedback_no_supported_hard_rule_candidate")
        primary = hints[0]
        correction = container.preference_profiles.apply_correction(
            principal_id=context.principal_id,
            person_id="self",
            domain=str(primary.get("domain") or PROPERTY_PREFERENCE_DOMAIN),
            category=str(primary.get("category") or "soft_preference"),
            key=str(primary.get("key") or ""),
            value_json=primary.get("value_json"),
            strength="high",
            reason=str(note or f"Converted FlipLink feedback {event_id} into an owner-confirmed property rule.").strip(),
            corrected_by=actor,
        )
        application["hard_rule_node"] = dict(correction.get("node") or {})
        application["correction"] = dict(correction.get("correction") or {})
    return application


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@authenticated_router.get("/app/properties/packets", response_class=HTMLResponse)
def property_packets_dashboard(
    request: Request,
    limit: int = Query(default=100, ge=1, le=300),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    service = build_fliplink_packet_service(container)
    raw_rows = service.list_publications(principal_id=context.principal_id, limit=limit)
    analytics = service.analytics_by_publication(
        principal_id=context.principal_id,
        publication_ids=[str(row.get("publication_id") or "") for row in raw_rows],
    )
    rows = [
        _publication_out(row, analytics=analytics.get(str(row.get("publication_id") or ""), {}))
        for row in raw_rows
    ]
    inbox = service.feedback_inbox(principal_id=context.principal_id, limit=100)
    capacity = service.capacity_status(principal_id=context.principal_id)
    webhook_url = f"{str(request.base_url).rstrip('/')}/v1/integrations/fliplink/webhook"
    return templates.TemplateResponse(
        request,
        "app/property_packets.html",
        {
            "brand": request_brand(request),
            "workspace_label": "PropertyQuarry Workspace",
            "current_nav": "packets",
            "publications": rows,
            "fliplink_capacity": capacity,
            "feedback_items": list(inbox.get("items") or []),
            "feedback_total": int(inbox.get("total") or 0),
            "fliplink_webhook_url": webhook_url,
            "lead_capture_schema": {
                "property_ref": "<property_ref>",
                "packet_kind": "<packet_kind>",
                "privacy_mode": "<privacy_mode>",
                "viewer_role": "family",
                "reaction": "maybe",
                "question": "",
                "intent": "review",
            },
        },
    )


@authenticated_router.get("/app/api/properties/packets")
def list_property_packets(
    limit: int = Query(default=100, ge=1, le=300),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    raw_rows = service.list_publications(principal_id=context.principal_id, limit=limit)
    analytics = service.analytics_by_publication(
        principal_id=context.principal_id,
        publication_ids=[str(row.get("publication_id") or "") for row in raw_rows],
    )
    rows = [
        _publication_out(row, analytics=analytics.get(str(row.get("publication_id") or ""), {}))
        for row in raw_rows
    ]
    return {"items": rows, "total": len(rows), "capacity": service.capacity_status(principal_id=context.principal_id)}


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
    preference_application: dict[str, object] = {}
    if body.action in {"accept_as_preference_signal", "convert_to_hard_rule"}:
        try:
            preference_application = _apply_feedback_preferences(
                container=container,
                context=context,
                event_id=event_id,
                review_event=event,
                action=body.action,
                note=body.note,
                actor=_actor(context),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "status": "reviewed",
        "event": dict(event),
        "preference_application": preference_application,
        "viewing_question_event": dict(event.get("viewing_question_event") or {}),
        "block_event": dict(event.get("block_event") or {}),
    }


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
    if (pdf_path != artifact_root and artifact_root not in pdf_path.parents) or not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="property_packet_pdf_not_found")
    expected_sha = str(row.get("source_pdf_sha256") or "").strip().lower()
    if expected_sha and _sha256_file(pdf_path) != expected_sha:
        raise HTTPException(status_code=409, detail="property_packet_pdf_hash_mismatch")
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


@authenticated_router.post("/app/api/properties/packets/{publication_id}/archive")
def archive_property_packet_publication(
    publication_id: str,
    body: FlipLinkArchivePublicationIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        row = service.archive_publication(
            principal_id=context.principal_id,
            publication_id=publication_id,
            note=body.note,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"publication": _publication_out(row)}


@authenticated_router.post("/app/api/properties/packets/{publication_id}/fliplink/browseract-publish")
def request_browseract_fliplink_publication(
    publication_id: str,
    body: BrowserActFlipLinkPublishIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        return service.request_browseract_publish(
            principal_id=context.principal_id,
            publication_id=publication_id,
            lead_capture_enabled=body.lead_capture_enabled,
            password_required=body.password_required,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@authenticated_router.post("/app/api/properties/packets/{publication_id}/fliplink/browseract-complete")
def complete_browseract_fliplink_publication(
    publication_id: str,
    body: BrowserActFlipLinkPublishCompleteIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        row = service.complete_browseract_publish(
            principal_id=context.principal_id,
            publication_id=publication_id,
            fliplink_url=body.fliplink_url,
            embed_code=body.embed_code,
            qr_url=body.qr_url,
            screenshot_proof_ref=body.screenshot_proof_ref,
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


@authenticated_router.post("/app/api/properties/packets/{publication_id}/fliplink/analytics-snapshot")
def record_fliplink_analytics_snapshot(
    publication_id: str,
    body: FlipLinkAnalyticsSnapshotIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        return service.record_analytics_snapshot(
            principal_id=context.principal_id,
            publication_id=publication_id,
            views=body.views,
            unique_visitors=body.unique_visitors,
            average_time_seconds=body.average_time_seconds,
            top_pages=body.top_pages,
            referral_sources=body.referral_sources,
            device_breakdown=body.device_breakdown,
            geography_breakdown=body.geography_breakdown,
            source=body.source,
            screenshot_proof_ref=body.screenshot_proof_ref,
            captured_from_url=body.captured_from_url,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
            include_floorplan=body.include_floorplan,
            include_photos=body.include_photos,
            source_payload=body.property_payload,
            actor=_actor(context),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"publication": _publication_out(row), "capacity": service.capacity_status(principal_id=context.principal_id)}


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
        secret_mode = service.verify_webhook_secret(
            provided_header=str(request.headers.get("x-propertyquarry-webhook-secret") or ""),
            provided_query=secret,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        raw_body = await request.body()
        if len(raw_body) > 64_000:
            raise HTTPException(status_code=413, detail="fliplink_webhook_payload_too_large")
        payload = json.loads(raw_body)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=400, detail="invalid_fliplink_webhook_json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="fliplink_webhook_object_required")
    return service.ingest_lead_webhook(payload=payload, secret_mode=secret_mode)
