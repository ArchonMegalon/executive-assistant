from __future__ import annotations

import copy
from typing import Dict, List, Protocol
from uuid import uuid4

from app.domain.models import now_utc_iso
from app.settings import Settings, ensure_storage_fallback_allowed


class PropertyPacketPublicationRepository(Protocol):
    def create_publication(self, row: dict[str, object]) -> dict[str, object]:
        ...

    def update_publication(self, *, publication_id: str, updates: dict[str, object]) -> dict[str, object] | None:
        ...

    def get_publication(self, *, publication_id: str, principal_id: str | None = None) -> dict[str, object] | None:
        ...

    def find_publication(
        self,
        *,
        publication_id: str = "",
        fliplink_url: str = "",
        principal_id: str | None = None,
    ) -> dict[str, object] | None:
        ...

    def list_publications(self, *, principal_id: str, limit: int = 100) -> list[dict[str, object]]:
        ...

    def record_event(self, row: dict[str, object]) -> dict[str, object]:
        ...

    def list_events(
        self,
        *,
        publication_id: str | None = None,
        principal_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        ...


def _text(value: object) -> str:
    return str(value or "").strip()


def _limit(value: int, *, default: int = 100) -> int:
    try:
        out = int(value)
    except Exception:
        return default
    return max(1, min(out, 500))


def _publication_defaults(row: dict[str, object]) -> dict[str, object]:
    now = now_utc_iso()
    publication_id = _text(row.get("publication_id")) or f"pub_{uuid4().hex}"
    normalized = {
        "publication_id": publication_id,
        "principal_id": _text(row.get("principal_id")),
        "person_id": _text(row.get("person_id")) or "self",
        "property_ref": _text(row.get("property_ref")),
        "search_run_id": _text(row.get("search_run_id")),
        "packet_kind": _text(row.get("packet_kind")) or "owner_review",
        "privacy_mode": _text(row.get("privacy_mode")) or "owner_private",
        "fliplink_format": _text(row.get("fliplink_format")) or "smart_document",
        "source_packet_ref": _text(row.get("source_packet_ref")),
        "source_pdf_artifact_ref": _text(row.get("source_pdf_artifact_ref")),
        "source_pdf_sha256": _text(row.get("source_pdf_sha256")),
        "source_pdf_size_bytes": int(row.get("source_pdf_size_bytes") or 0),
        "redaction_policy_version": _text(row.get("redaction_policy_version")) or "property_packet_v1",
        "fliplink_publication_id": _text(row.get("fliplink_publication_id")),
        "fliplink_url": _text(row.get("fliplink_url")),
        "fliplink_custom_domain_url": _text(row.get("fliplink_custom_domain_url")),
        "fliplink_embed_code": _text(row.get("fliplink_embed_code")),
        "fliplink_qr_url": _text(row.get("fliplink_qr_url")),
        "lead_capture_enabled": bool(row.get("lead_capture_enabled")),
        "password_required": bool(row.get("password_required")),
        "sale_mode_enabled": bool(row.get("sale_mode_enabled")),
        "status": _text(row.get("status")) or "rendered",
        "created_at": _text(row.get("created_at")) or now,
        "updated_at": _text(row.get("updated_at")) or now,
        "published_at": _text(row.get("published_at")),
        "archived_at": _text(row.get("archived_at")),
        "error_code": _text(row.get("error_code")),
        "error_detail": _text(row.get("error_detail")),
        "recommended_title": _text(row.get("recommended_title")),
        "recommended_format": _text(row.get("recommended_format")),
        "artifact_download_path": _text(row.get("artifact_download_path")),
        "receipt_artifact_ref": _text(row.get("receipt_artifact_ref")),
        "redaction_receipt_json": copy.deepcopy(row.get("redaction_receipt_json") or {}),
        "packet_summary_json": copy.deepcopy(row.get("packet_summary_json") or {}),
    }
    return normalized


def _event_defaults(row: dict[str, object]) -> dict[str, object]:
    now = now_utc_iso()
    return {
        "event_id": _text(row.get("event_id")) or f"evt_{uuid4().hex}",
        "publication_id": _text(row.get("publication_id")),
        "principal_id": _text(row.get("principal_id")),
        "event_type": _text(row.get("event_type")),
        "actor": _text(row.get("actor")) or "system",
        "payload_json": copy.deepcopy(row.get("payload_json") or {}),
        "created_at": _text(row.get("created_at")) or now,
    }


class InMemoryPropertyPacketPublicationRepository:
    def __init__(self) -> None:
        self._publications: Dict[str, dict[str, object]] = {}
        self._publication_order: List[str] = []
        self._events: Dict[str, dict[str, object]] = {}
        self._event_order: List[str] = []

    def create_publication(self, row: dict[str, object]) -> dict[str, object]:
        normalized = _publication_defaults(row)
        publication_id = str(normalized["publication_id"])
        if publication_id not in self._publications:
            self._publication_order.append(publication_id)
        self._publications[publication_id] = copy.deepcopy(normalized)
        return copy.deepcopy(normalized)

    def update_publication(self, *, publication_id: str, updates: dict[str, object]) -> dict[str, object] | None:
        normalized_id = _text(publication_id)
        if not normalized_id or normalized_id not in self._publications:
            return None
        current = dict(self._publications[normalized_id])
        current.update(copy.deepcopy(updates))
        current["publication_id"] = normalized_id
        current["updated_at"] = _text(updates.get("updated_at")) or now_utc_iso()
        self._publications[normalized_id] = _publication_defaults(current)
        return copy.deepcopy(self._publications[normalized_id])

    def get_publication(self, *, publication_id: str, principal_id: str | None = None) -> dict[str, object] | None:
        row = self._publications.get(_text(publication_id))
        if row is None:
            return None
        if principal_id is not None and _text(row.get("principal_id")) != _text(principal_id):
            return None
        return copy.deepcopy(row)

    def find_publication(
        self,
        *,
        publication_id: str = "",
        fliplink_url: str = "",
        principal_id: str | None = None,
    ) -> dict[str, object] | None:
        if _text(publication_id):
            return self.get_publication(publication_id=publication_id, principal_id=principal_id)
        normalized_url = _text(fliplink_url)
        if not normalized_url:
            return None
        for publication_key in reversed(self._publication_order):
            row = self._publications.get(publication_key) or {}
            if principal_id is not None and _text(row.get("principal_id")) != _text(principal_id):
                continue
            if normalized_url in {
                _text(row.get("fliplink_url")),
                _text(row.get("fliplink_custom_domain_url")),
            }:
                return copy.deepcopy(row)
        return None

    def list_publications(self, *, principal_id: str, limit: int = 100) -> list[dict[str, object]]:
        normalized_principal = _text(principal_id)
        rows = [
            copy.deepcopy(self._publications[key])
            for key in reversed(self._publication_order)
            if _text((self._publications.get(key) or {}).get("principal_id")) == normalized_principal
        ]
        return rows[: _limit(limit)]

    def record_event(self, row: dict[str, object]) -> dict[str, object]:
        normalized = _event_defaults(row)
        event_id = str(normalized["event_id"])
        if event_id not in self._events:
            self._event_order.append(event_id)
        self._events[event_id] = copy.deepcopy(normalized)
        return copy.deepcopy(normalized)

    def list_events(
        self,
        *,
        publication_id: str | None = None,
        principal_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        normalized_publication = _text(publication_id)
        normalized_principal = _text(principal_id)
        normalized_type = _text(event_type)
        rows: list[dict[str, object]] = []
        for event_key in reversed(self._event_order):
            row = self._events.get(event_key) or {}
            if normalized_publication and _text(row.get("publication_id")) != normalized_publication:
                continue
            if normalized_principal and _text(row.get("principal_id")) != normalized_principal:
                continue
            if normalized_type and _text(row.get("event_type")) != normalized_type:
                continue
            rows.append(copy.deepcopy(row))
            if len(rows) >= _limit(limit):
                break
        return rows


_MEMORY_REPO = InMemoryPropertyPacketPublicationRepository()


def build_property_packet_publication_repository(settings: Settings) -> PropertyPacketPublicationRepository:
    backend = str(getattr(getattr(settings, "storage", None), "backend", "") or "auto").strip().lower() or "auto"
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "property packet publications configured for memory")
        return _MEMORY_REPO
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        from app.repositories.property_packet_publications_postgres import PostgresPropertyPacketPublicationRepository

        return PostgresPropertyPacketPublicationRepository(settings.database_url)
    if settings.database_url:
        try:
            from app.repositories.property_packet_publications_postgres import PostgresPropertyPacketPublicationRepository

            return PostgresPropertyPacketPublicationRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "property packet publications auto fallback", exc)
    ensure_storage_fallback_allowed(settings, "property packet publications auto backend without DATABASE_URL")
    return _MEMORY_REPO
