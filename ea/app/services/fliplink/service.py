from __future__ import annotations

import hmac
from pathlib import Path
from uuid import uuid4

from app.container import AppContainer
from app.domain.models import now_utc_iso
from app.repositories.property_packet_publications import (
    PropertyPacketPublicationRepository,
    build_property_packet_publication_repository,
)
from app.services.fliplink.adapter import validate_manual_fliplink_url
from app.services.fliplink.models import (
    FlipLinkFormat,
    PacketPrivacyMode,
    PropertyPacketKind,
    fliplink_settings_from_env,
    normalize_fliplink_format,
    normalize_packet_kind,
    normalize_privacy_mode,
)
from app.services.fliplink.browser_adapter import browseract_fliplink_publish_requested
from app.services.fliplink.pdf_renderer import render_property_packet_pdf
from app.services.fliplink.webhooks import FlipLinkLeadWebhook, normalize_lead_webhook
from app.services.fliplink.webhooks import safe_custom_fields


ACTIVE_PACKET_STATUSES = {"rendered", "published", "publish_requested", "queued_operator_assist"}


class FlipLinkPacketService:
    def __init__(
        self,
        *,
        repo: PropertyPacketPublicationRepository,
        artifact_root: Path,
    ) -> None:
        self._repo = repo
        self._artifact_root = artifact_root

    def capacity_status(self, *, principal_id: str) -> dict[str, object]:
        settings = fliplink_settings_from_env()
        active = self._repo.count_publications(principal_id=principal_id, statuses=ACTIVE_PACKET_STATUSES)
        cap = max(1, int(settings.active_publication_cap or 1))
        warning_at = max(1, int(cap * 0.8))
        return {
            "active": active,
            "cap": cap,
            "remaining": max(0, cap - active),
            "warning_at": warning_at,
            "state": "blocked" if active >= cap else "warn" if active >= warning_at else "ok",
            "account_tier": int(settings.account_tier or 0),
            "custom_domain": settings.custom_domain,
        }

    def _require_capacity(self, *, principal_id: str) -> None:
        capacity = self.capacity_status(principal_id=principal_id)
        if str(capacity.get("state") or "") == "blocked":
            raise ValueError("fliplink_active_publication_cap_reached")

    def render_packet(
        self,
        *,
        principal_id: str,
        person_id: str = "self",
        property_ref: str,
        packet_kind: object = PropertyPacketKind.OWNER_REVIEW,
        privacy_mode: object = "",
        fliplink_format: object = "",
        search_run_id: str = "",
        include_exact_address: bool = False,
        source_payload: dict[str, object] | None = None,
        actor: str = "browser",
    ) -> dict[str, object]:
        kind = normalize_packet_kind(packet_kind)
        mode = normalize_privacy_mode(privacy_mode, packet_kind=kind)
        fmt = normalize_fliplink_format(fliplink_format, packet_kind=kind)
        self._require_capacity(principal_id=principal_id)
        publication_id = f"pub_{uuid4().hex}"
        source = dict(source_payload or {})
        source.setdefault("property_ref", str(property_ref or "").strip())
        source.setdefault("search_run_id", str(search_run_id or "").strip())
        source.setdefault("title", str(source.get("property_title") or property_ref or "PropertyQuarry packet").strip())
        rendered = render_property_packet_pdf(
            artifact_root=self._artifact_root,
            publication_id=publication_id,
            principal_id=principal_id,
            source=source,
            packet_kind=kind,
            privacy_mode=mode,
            fliplink_format=fmt,
            include_exact_address=bool(include_exact_address),
        )
        settings = fliplink_settings_from_env()
        row = self._repo.create_publication(
            {
                "publication_id": publication_id,
                "principal_id": principal_id,
                "person_id": person_id or "self",
                "property_ref": str(property_ref or "").strip(),
                "search_run_id": str(search_run_id or "").strip(),
                "packet_kind": kind.value,
                "privacy_mode": mode.value,
                "fliplink_format": fmt.value,
                "source_packet_ref": f"property:{str(property_ref or '').strip()}",
                "source_pdf_artifact_ref": str(rendered["pdf_path"]),
                "source_pdf_sha256": str(rendered["pdf_sha256"]),
                "source_pdf_size_bytes": int(rendered["pdf_size_bytes"] or 0),
                "redaction_policy_version": str(dict(rendered["receipt"]).get("redaction_policy_version") or "property_packet_v1"),
                "status": "rendered",
                "recommended_title": str(rendered.get("recommended_title") or ""),
                "recommended_format": fmt.value,
                "artifact_download_path": f"/app/api/properties/packets/{publication_id}/pdf",
                "receipt_artifact_ref": str(rendered["receipt_path"]),
                "redaction_receipt_json": dict(rendered["receipt"]),
                "packet_summary_json": {
                    "title": str(dict(rendered["redacted_payload"]).get("title") or ""),
                    "renderer_version": str(dict(rendered["receipt"]).get("renderer_version") or ""),
                    "format_is_permanent": True,
                    "manual_publish_required": True,
                    "recommended_folder": _folder_for(kind),
                    "recommended_custom_domain": settings.custom_domain,
                    "redacted_payload": dict(rendered["redacted_payload"]),
                },
            }
        )
        self._repo.record_event(
            {
                "publication_id": publication_id,
                "principal_id": principal_id,
                "event_type": "packet_rendered",
                "actor": actor,
                "payload_json": {
                    "packet_kind": kind.value,
                    "privacy_mode": mode.value,
                    "fliplink_format": fmt.value,
                    "source_pdf_sha256": str(rendered["pdf_sha256"]),
                    "removed_fields": list(dict(rendered["receipt"]).get("removed_fields") or []),
                },
            }
        )
        return row

    def get_publication(self, *, publication_id: str, principal_id: str | None = None) -> dict[str, object] | None:
        return self._repo.get_publication(publication_id=publication_id, principal_id=principal_id)

    def list_publications(self, *, principal_id: str, limit: int = 100) -> list[dict[str, object]]:
        return self._repo.list_publications(principal_id=principal_id, limit=limit)

    def list_events(
        self,
        *,
        publication_id: str | None = None,
        principal_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        return self._repo.list_events(publication_id=publication_id, principal_id=principal_id, event_type=event_type, limit=limit)

    def record_manual_link(
        self,
        *,
        principal_id: str,
        publication_id: str,
        fliplink_url: str,
        fliplink_format: object = "",
        embed_code: str = "",
        qr_url: str = "",
        lead_capture_enabled: bool = False,
        password_required: bool = False,
        sale_mode_enabled: bool = False,
        actor: str = "browser",
    ) -> dict[str, object]:
        publication = self._repo.get_publication(publication_id=publication_id, principal_id=principal_id)
        if publication is None:
            raise KeyError("property_packet_publication_not_found")
        if str(publication.get("status") or "") == "archived":
            raise ValueError("fliplink_publication_archived")
        validated_url = validate_manual_fliplink_url(fliplink_url)
        existing_format = normalize_fliplink_format(publication.get("fliplink_format"))
        requested_format = normalize_fliplink_format(fliplink_format or existing_format.value)
        if requested_format != existing_format:
            raise ValueError("fliplink_format_is_permanent")
        now = now_utc_iso()
        updated = self._repo.update_publication(
            publication_id=publication_id,
            updates={
                "fliplink_url": validated_url,
                "fliplink_custom_domain_url": validated_url if "propertyquarry.com" in validated_url else "",
                "fliplink_embed_code": str(embed_code or "").strip()[:4000],
                "fliplink_qr_url": str(qr_url or "").strip()[:500],
                "lead_capture_enabled": bool(lead_capture_enabled),
                "password_required": bool(password_required),
                "sale_mode_enabled": bool(sale_mode_enabled),
                "status": "published",
                "published_at": now,
            },
        )
        if updated is None:
            raise KeyError("property_packet_publication_not_found")
        self._repo.record_event(
            {
                "publication_id": publication_id,
                "principal_id": principal_id,
                "event_type": "fliplink_manual_publish_completed",
                "actor": actor,
                "payload_json": {
                    "fliplink_url": validated_url,
                    "lead_capture_enabled": bool(lead_capture_enabled),
                    "password_required": bool(password_required),
                    "sale_mode_enabled": bool(sale_mode_enabled),
                },
            }
        )
        return updated

    def archive_publication(
        self,
        *,
        principal_id: str,
        publication_id: str,
        actor: str = "browser",
        note: str = "",
    ) -> dict[str, object]:
        publication = self._repo.get_publication(publication_id=publication_id, principal_id=principal_id)
        if publication is None:
            raise KeyError("property_packet_publication_not_found")
        now = now_utc_iso()
        updated = self._repo.update_publication(
            publication_id=publication_id,
            updates={
                "status": "archived",
                "archived_at": now,
            },
        )
        if updated is None:
            raise KeyError("property_packet_publication_not_found")
        self._repo.record_event(
            {
                "publication_id": publication_id,
                "principal_id": principal_id,
                "event_type": "fliplink_publication_archived",
                "actor": actor,
                "payload_json": {
                    "note": str(note or "").strip()[:1000],
                    "previous_status": str(publication.get("status") or ""),
                    "archived_at": now,
                },
            }
        )
        return updated

    def request_browseract_publish(
        self,
        *,
        principal_id: str,
        publication_id: str,
        password_required: bool = False,
        lead_capture_enabled: bool = True,
        actor: str = "browser",
    ) -> dict[str, object]:
        publication = self._repo.get_publication(publication_id=publication_id, principal_id=principal_id)
        if publication is None:
            raise KeyError("property_packet_publication_not_found")
        if str(publication.get("status") or "") == "archived":
            raise ValueError("fliplink_publication_archived")
        summary = dict(publication.get("packet_summary_json") or {})
        result = browseract_fliplink_publish_requested(
            {
                "publication_id": publication_id,
                "pdf_artifact_ref": str(publication.get("source_pdf_artifact_ref") or ""),
                "redaction_receipt_present": bool(
                    publication.get("receipt_artifact_ref") or publication.get("redaction_receipt_json")
                ),
                "recommended_title": str(publication.get("recommended_title") or ""),
                "fliplink_format": str(publication.get("fliplink_format") or ""),
                "privacy_mode": str(publication.get("privacy_mode") or ""),
                "recommended_folder": str(summary.get("recommended_folder") or _folder_for(normalize_packet_kind(publication.get("packet_kind")))),
                "custom_domain": str(summary.get("recommended_custom_domain") or fliplink_settings_from_env().custom_domain),
                "lead_capture_enabled": bool(lead_capture_enabled),
                "password_required": bool(password_required),
            }
        )
        event = self._repo.record_event(
            {
                "publication_id": publication_id,
                "principal_id": principal_id,
                "event_type": "fliplink_browser_publish_requested",
                "actor": actor,
                "payload_json": {
                    **dict(result),
                    "lead_capture_enabled": bool(lead_capture_enabled),
                    "password_required": bool(password_required),
                },
            }
        )
        self._repo.update_publication(
            publication_id=publication_id,
            updates={
                "status": "publish_requested",
            },
        )
        return {
            **dict(result),
            "publication_id": publication_id,
            "event_id": str(event.get("event_id") or ""),
        }

    def record_analytics_snapshot(
        self,
        *,
        principal_id: str,
        publication_id: str,
        views: int | None = None,
        unique_visitors: int | None = None,
        average_time_seconds: int | None = None,
        top_pages: list[dict[str, object]] | None = None,
        referral_sources: list[dict[str, object]] | None = None,
        device_breakdown: dict[str, int] | None = None,
        geography_breakdown: dict[str, int] | None = None,
        actor: str = "browser",
    ) -> dict[str, object]:
        publication = self._repo.get_publication(publication_id=publication_id, principal_id=principal_id)
        if publication is None:
            raise KeyError("property_packet_publication_not_found")
        payload = {
            "publication_id": publication_id,
            "views": _non_negative_int(views),
            "unique_visitors": _non_negative_int(unique_visitors),
            "average_time_seconds": _non_negative_int(average_time_seconds),
            "top_pages": _bounded_metric_rows(top_pages),
            "referral_sources": _bounded_metric_rows(referral_sources),
            "device_breakdown": _bounded_int_map(device_breakdown),
            "geography_breakdown": _bounded_int_map(geography_breakdown),
            "captured_at": now_utc_iso(),
            "trust": "operator_entered_or_imported",
        }
        event = self._repo.record_event(
            {
                "publication_id": publication_id,
                "principal_id": principal_id,
                "event_type": "fliplink_analytics_snapshot_recorded",
                "actor": actor,
                "payload_json": payload,
            }
        )
        return {"event": event, "snapshot": payload}

    def latest_analytics_snapshot(self, *, principal_id: str, publication_id: str) -> dict[str, object]:
        events = self._repo.list_events(
            publication_id=publication_id,
            principal_id=principal_id,
            event_type="fliplink_analytics_snapshot_recorded",
            limit=1,
        )
        if not events:
            return {}
        payload = dict(events[0].get("payload_json") or {})
        payload["event_id"] = str(events[0].get("event_id") or "")
        payload["created_at"] = str(events[0].get("created_at") or "")
        return payload

    def analytics_by_publication(
        self,
        *,
        principal_id: str,
        publication_ids: list[str],
    ) -> dict[str, dict[str, object]]:
        wanted = {str(item or "").strip() for item in publication_ids if str(item or "").strip()}
        if not wanted:
            return {}
        events = self._repo.list_events(
            principal_id=principal_id,
            event_type="fliplink_analytics_snapshot_recorded",
            limit=500,
        )
        out: dict[str, dict[str, object]] = {}
        for event in events:
            publication_id = str(event.get("publication_id") or "")
            if publication_id not in wanted or publication_id in out:
                continue
            payload = dict(event.get("payload_json") or {})
            payload["event_id"] = str(event.get("event_id") or "")
            payload["created_at"] = str(event.get("created_at") or "")
            out[publication_id] = payload
        return out

    def verify_webhook_secret(self, *, provided_header: str = "", provided_query: str = "") -> str:
        settings = fliplink_settings_from_env()
        if not settings.webhook_allowed:
            raise PermissionError("fliplink_webhook_disabled")
        expected = settings.webhook_secret
        if not expected:
            raise PermissionError("fliplink_webhook_secret_not_configured")
        header = str(provided_header or "").strip()
        query = str(provided_query or "").strip()
        if header:
            if not hmac.compare_digest(header, expected):
                raise PermissionError("fliplink_webhook_secret_invalid")
            return "header"
        if query and not settings.webhook_allow_query_secret:
            raise PermissionError("fliplink_webhook_query_secret_disabled")
        provided = query
        if not provided or not hmac.compare_digest(provided, expected):
            raise PermissionError("fliplink_webhook_secret_invalid")
        return "query"

    def ingest_lead_webhook(
        self,
        *,
        payload: dict[str, object],
        actor: str = "fliplink_webhook",
        secret_mode: str = "",
    ) -> dict[str, object]:
        lead = normalize_lead_webhook(payload)
        publication = self._repo.find_publication(publication_id=lead.publication_id, fliplink_url=lead.fliplink_url)
        if publication is None:
            return {
                "status": "accepted_unmatched",
                "trust": "untrusted_external",
                "publication_id": "",
                "secret_mode": str(secret_mode or ""),
            }
        safe_payload = lead.safe_payload()
        event = self._repo.record_event(
            {
                "publication_id": str(publication.get("publication_id") or ""),
                "principal_id": str(publication.get("principal_id") or ""),
                "event_type": "fliplink_lead_captured",
                "actor": actor,
                "payload_json": {
                    **safe_payload,
                    "property_ref": str(publication.get("property_ref") or ""),
                    "packet_kind": str(publication.get("packet_kind") or ""),
                    "privacy_mode": str(publication.get("privacy_mode") or ""),
                    "secret_mode": str(secret_mode or ""),
                },
            }
        )
        return {
            "status": "accepted",
            "trust": "untrusted_external",
            "publication_id": str(publication.get("publication_id") or ""),
            "event_id": str(event.get("event_id") or ""),
            "secret_mode": str(secret_mode or ""),
        }

    def feedback_inbox(self, *, principal_id: str, limit: int = 100) -> dict[str, object]:
        lead_events = self._repo.list_events(principal_id=principal_id, event_type="fliplink_lead_captured", limit=limit)
        review_events = self._repo.list_events(principal_id=principal_id, event_type="fliplink_feedback_reviewed", limit=limit)
        reviewed_ids = {
            str(dict(event.get("payload_json") or {}).get("target_event_id") or "").strip()
            for event in review_events
        }
        items: list[dict[str, object]] = []
        for event in lead_events:
            payload = dict(event.get("payload_json") or {})
            event_id = str(event.get("event_id") or "")
            items.append(
                {
                    "event_id": event_id,
                    "publication_id": str(event.get("publication_id") or ""),
                    "property_ref": str(payload.get("property_ref") or ""),
                    "packet_kind": str(payload.get("packet_kind") or ""),
                    "privacy_mode": str(payload.get("privacy_mode") or ""),
                    "reviewer": {
                        "name": str(payload.get("name") or ""),
                        "email_masked": str(payload.get("email_masked") or ""),
                        "company": str(payload.get("company") or ""),
                        "job_title": str(payload.get("job_title") or ""),
                    },
                    "custom_fields": dict(payload.get("custom_fields") or {}),
                    "status": "reviewed" if event_id in reviewed_ids else "pending_owner_review",
                    "trust": "untrusted_external",
                    "created_at": str(event.get("created_at") or ""),
                }
            )
        return {"items": items, "total": len(items)}

    def review_feedback(
        self,
        *,
        principal_id: str,
        event_id: str,
        action: str,
        note: str = "",
        actor: str = "browser",
    ) -> dict[str, object]:
        target = next(
            (
                event
                for event in self._repo.list_events(principal_id=principal_id, event_type="fliplink_lead_captured", limit=500)
                if str(event.get("event_id") or "") == str(event_id or "").strip()
            ),
            None,
        )
        if target is None:
            raise KeyError("fliplink_feedback_event_not_found")
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {
            "accept_as_preference_signal",
            "accept_as_viewing_question",
            "dismiss",
            "block_reviewer",
            "convert_to_hard_rule",
        }:
            raise ValueError("invalid_fliplink_feedback_action")
        event = self._repo.record_event(
            {
                "publication_id": str(target.get("publication_id") or ""),
                "principal_id": principal_id,
                "event_type": "fliplink_feedback_reviewed",
                "actor": actor,
                "payload_json": {
                    "target_event_id": str(event_id or "").strip(),
                    "action": normalized_action,
                    "note": str(note or "").strip()[:1000],
                    "trust": "owner_reviewed",
                    "target_payload": _review_target_payload(target),
                },
            }
        )
        return event


def _folder_for(packet_kind: PropertyPacketKind) -> str:
    return {
        PropertyPacketKind.OWNER_REVIEW: "Owner Review Packets",
        PropertyPacketKind.FAMILY_REVIEW: "Family Review Packets",
        PropertyPacketKind.AGENT_BRIEF: "Agent Briefs",
        PropertyPacketKind.SHORTLIST_BROCHURE: "Family Review Packets",
        PropertyPacketKind.PAID_MARKET_REPORT: "Paid Market Reports",
        PropertyPacketKind.OPEN_HOUSE_QR: "Family Review Packets",
    }.get(packet_kind, "Owner Review Packets")


def _non_negative_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except Exception as exc:
        raise ValueError("fliplink_analytics_metric_invalid") from exc
    if parsed < 0:
        raise ValueError("fliplink_analytics_metric_negative")
    return min(parsed, 10_000_000)


def _bounded_metric_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, object]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("page") or item.get("source") or "").strip()[:160]
        if not label:
            continue
        count = _non_negative_int(item.get("count") or item.get("views") or item.get("seconds"))
        rows.append({"label": label, "count": count or 0})
    return rows


def _bounded_int_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for key, raw in list(value.items())[:30]:
        label = str(key or "").strip()[:80]
        if not label:
            continue
        parsed = _non_negative_int(raw)
        out[label] = parsed or 0
    return out


def _review_target_payload(target: dict[str, object]) -> dict[str, object]:
    payload = dict(target.get("payload_json") or {})
    return {
        "publication_id": str(target.get("publication_id") or payload.get("publication_id") or "")[:160],
        "property_ref": str(payload.get("property_ref") or "")[:500],
        "packet_kind": str(payload.get("packet_kind") or "")[:80],
        "privacy_mode": str(payload.get("privacy_mode") or "")[:80],
        "custom_fields": safe_custom_fields(payload.get("custom_fields") or {}),
        "reviewer": {
            "name": str(payload.get("name") or "")[:160],
            "email_hash": str(payload.get("email_hash") or "")[:80],
            "email_masked": str(payload.get("email_masked") or "")[:160],
            "company": str(payload.get("company") or "")[:160],
            "job_title": str(payload.get("job_title") or "")[:160],
        },
    }


def build_fliplink_packet_service(container: AppContainer) -> FlipLinkPacketService:
    artifact_root = Path(str(container.settings.storage.artifacts_dir or "/tmp/ea_artifacts")).resolve()
    repo = build_property_packet_publication_repository(container.settings)
    return FlipLinkPacketService(repo=repo, artifact_root=artifact_root)
