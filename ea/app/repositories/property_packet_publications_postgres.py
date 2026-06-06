from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from app.domain.models import now_utc_iso
from app.repositories.property_packet_publications import (
    PROPERTY_PACKET_SCHEMA_NAME,
    PROPERTY_PACKET_SCHEMA_VERSION,
    _event_defaults,
    _publication_defaults,
)


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class PostgresPropertyPacketPublicationRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresPropertyPacketPublicationRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for postgres property packet publication backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: object):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(copy.deepcopy(value))

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS property_packet_publications (
                        publication_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        person_id TEXT NOT NULL DEFAULT 'self',
                        property_ref TEXT NOT NULL,
                        search_run_id TEXT NOT NULL DEFAULT '',
                        packet_kind TEXT NOT NULL,
                        privacy_mode TEXT NOT NULL,
                        fliplink_format TEXT NOT NULL,
                        source_packet_ref TEXT NOT NULL,
                        source_pdf_artifact_ref TEXT NOT NULL,
                        source_pdf_sha256 TEXT NOT NULL,
                        source_pdf_size_bytes INTEGER NOT NULL,
                        redaction_policy_version TEXT NOT NULL,
                        fliplink_publication_id TEXT NOT NULL DEFAULT '',
                        fliplink_url TEXT NOT NULL DEFAULT '',
                        fliplink_custom_domain_url TEXT NOT NULL DEFAULT '',
                        fliplink_embed_code TEXT NOT NULL DEFAULT '',
                        fliplink_qr_url TEXT NOT NULL DEFAULT '',
                        lead_capture_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                        password_required BOOLEAN NOT NULL DEFAULT FALSE,
                        sale_mode_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        published_at TEXT NOT NULL DEFAULT '',
                        archived_at TEXT NOT NULL DEFAULT '',
                        error_code TEXT NOT NULL DEFAULT '',
                        error_detail TEXT NOT NULL DEFAULT '',
                        recommended_title TEXT NOT NULL DEFAULT '',
                        recommended_format TEXT NOT NULL DEFAULT '',
                        artifact_download_path TEXT NOT NULL DEFAULT '',
                        receipt_artifact_ref TEXT NOT NULL DEFAULT '',
                        redaction_receipt_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        packet_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_property_packet_publications_principal_updated
                    ON property_packet_publications(principal_id, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_property_packet_publications_fliplink_url
                    ON property_packet_publications(fliplink_url)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS property_packet_publication_events (
                        event_id TEXT PRIMARY KEY,
                        publication_id TEXT NOT NULL,
                        principal_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        actor TEXT NOT NULL,
                        payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_property_packet_publication_events_publication_created
                    ON property_packet_publication_events(publication_id, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_property_packet_publication_events_principal_type_created
                    ON property_packet_publication_events(principal_id, event_type, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS property_packet_schema_versions (
                        schema_name TEXT PRIMARY KEY,
                        schema_version INTEGER NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    INSERT INTO property_packet_schema_versions (schema_name, schema_version, updated_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (schema_name) DO UPDATE
                    SET schema_version = EXCLUDED.schema_version,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (PROPERTY_PACKET_SCHEMA_NAME, PROPERTY_PACKET_SCHEMA_VERSION, now_utc_iso()),
                )

    def _row(self, row: tuple[Any, ...]) -> dict[str, object]:
        keys = (
            "publication_id",
            "principal_id",
            "person_id",
            "property_ref",
            "search_run_id",
            "packet_kind",
            "privacy_mode",
            "fliplink_format",
            "source_packet_ref",
            "source_pdf_artifact_ref",
            "source_pdf_sha256",
            "source_pdf_size_bytes",
            "redaction_policy_version",
            "fliplink_publication_id",
            "fliplink_url",
            "fliplink_custom_domain_url",
            "fliplink_embed_code",
            "fliplink_qr_url",
            "lead_capture_enabled",
            "password_required",
            "sale_mode_enabled",
            "status",
            "created_at",
            "updated_at",
            "published_at",
            "archived_at",
            "error_code",
            "error_detail",
            "recommended_title",
            "recommended_format",
            "artifact_download_path",
            "receipt_artifact_ref",
            "redaction_receipt_json",
            "packet_summary_json",
        )
        out = dict(zip(keys, row, strict=False))
        out["created_at"] = _to_iso(out.get("created_at"))
        out["updated_at"] = _to_iso(out.get("updated_at"))
        return _publication_defaults(out)

    def _event_row(self, row: tuple[Any, ...]) -> dict[str, object]:
        keys = ("event_id", "publication_id", "principal_id", "event_type", "actor", "payload_json", "created_at")
        out = dict(zip(keys, row, strict=False))
        out["created_at"] = _to_iso(out.get("created_at"))
        return _event_defaults(out)

    def create_publication(self, row: dict[str, object]) -> dict[str, object]:
        normalized = _publication_defaults(row)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO property_packet_publications (
                        publication_id, principal_id, person_id, property_ref, search_run_id,
                        packet_kind, privacy_mode, fliplink_format, source_packet_ref,
                        source_pdf_artifact_ref, source_pdf_sha256, source_pdf_size_bytes,
                        redaction_policy_version, fliplink_publication_id, fliplink_url,
                        fliplink_custom_domain_url, fliplink_embed_code, fliplink_qr_url,
                        lead_capture_enabled, password_required, sale_mode_enabled, status,
                        created_at, updated_at, published_at, archived_at, error_code, error_detail,
                        recommended_title, recommended_format, artifact_download_path, receipt_artifact_ref,
                        redaction_receipt_json, packet_summary_json
                    )
                    VALUES (
                        %(publication_id)s, %(principal_id)s, %(person_id)s, %(property_ref)s, %(search_run_id)s,
                        %(packet_kind)s, %(privacy_mode)s, %(fliplink_format)s, %(source_packet_ref)s,
                        %(source_pdf_artifact_ref)s, %(source_pdf_sha256)s, %(source_pdf_size_bytes)s,
                        %(redaction_policy_version)s, %(fliplink_publication_id)s, %(fliplink_url)s,
                        %(fliplink_custom_domain_url)s, %(fliplink_embed_code)s, %(fliplink_qr_url)s,
                        %(lead_capture_enabled)s, %(password_required)s, %(sale_mode_enabled)s, %(status)s,
                        %(created_at)s, %(updated_at)s, %(published_at)s, %(archived_at)s, %(error_code)s, %(error_detail)s,
                        %(recommended_title)s, %(recommended_format)s, %(artifact_download_path)s, %(receipt_artifact_ref)s,
                        %(redaction_receipt_json)s, %(packet_summary_json)s
                    )
                    ON CONFLICT (publication_id) DO UPDATE
                    SET updated_at = EXCLUDED.updated_at,
                        status = EXCLUDED.status,
                        redaction_receipt_json = EXCLUDED.redaction_receipt_json,
                        packet_summary_json = EXCLUDED.packet_summary_json
                    RETURNING *
                    """,
                    {
                        **normalized,
                        "redaction_receipt_json": self._json_value(normalized.get("redaction_receipt_json") or {}),
                        "packet_summary_json": self._json_value(normalized.get("packet_summary_json") or {}),
                    },
                )
                stored = cur.fetchone()
        return self._row(stored)

    def update_publication(self, *, publication_id: str, updates: dict[str, object]) -> dict[str, object] | None:
        current = self.get_publication(publication_id=publication_id)
        if current is None:
            return None
        merged = {**current, **copy.deepcopy(updates), "publication_id": publication_id, "updated_at": now_utc_iso()}
        normalized = _publication_defaults(merged)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE property_packet_publications
                    SET fliplink_publication_id = %(fliplink_publication_id)s,
                        fliplink_url = %(fliplink_url)s,
                        fliplink_custom_domain_url = %(fliplink_custom_domain_url)s,
                        fliplink_embed_code = %(fliplink_embed_code)s,
                        fliplink_qr_url = %(fliplink_qr_url)s,
                        lead_capture_enabled = %(lead_capture_enabled)s,
                        password_required = %(password_required)s,
                        sale_mode_enabled = %(sale_mode_enabled)s,
                        status = %(status)s,
                        updated_at = %(updated_at)s,
                        published_at = %(published_at)s,
                        archived_at = %(archived_at)s,
                        error_code = %(error_code)s,
                        error_detail = %(error_detail)s,
                        recommended_title = %(recommended_title)s,
                        recommended_format = %(recommended_format)s,
                        packet_summary_json = %(packet_summary_json)s
                    WHERE publication_id = %(publication_id)s
                    RETURNING *
                    """,
                    {
                        **normalized,
                        "packet_summary_json": self._json_value(normalized.get("packet_summary_json") or {}),
                    },
                )
                row = cur.fetchone()
        return self._row(row) if row else None

    def get_publication(self, *, publication_id: str, principal_id: str | None = None) -> dict[str, object] | None:
        query = "SELECT * FROM property_packet_publications WHERE publication_id = %s"
        params: list[object] = [str(publication_id or "").strip()]
        if principal_id is not None:
            query += " AND principal_id = %s"
            params.append(str(principal_id or "").strip())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
        return self._row(row) if row else None

    def find_publication(
        self,
        *,
        publication_id: str = "",
        fliplink_url: str = "",
        principal_id: str | None = None,
    ) -> dict[str, object] | None:
        normalized_publication = str(publication_id or "").strip()
        if normalized_publication:
            return self.get_publication(publication_id=normalized_publication, principal_id=principal_id)
        normalized_url = str(fliplink_url or "").strip()
        if not normalized_url:
            return None
        query = """
            SELECT * FROM property_packet_publications
            WHERE (fliplink_url = %s OR fliplink_custom_domain_url = %s)
        """
        params: list[object] = [normalized_url, normalized_url]
        if principal_id is not None:
            query += " AND principal_id = %s"
            params.append(str(principal_id or "").strip())
        query += " ORDER BY updated_at DESC LIMIT 1"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
        return self._row(row) if row else None

    def list_publications(self, *, principal_id: str, limit: int = 100) -> list[dict[str, object]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM property_packet_publications
                    WHERE principal_id = %s
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (str(principal_id or "").strip(), max(1, min(int(limit or 100), 500))),
                )
                rows = cur.fetchall()
        return [self._row(row) for row in rows]

    def count_publications(
        self,
        *,
        principal_id: str | None = None,
        statuses: object = None,
    ) -> int:
        clauses: list[str] = []
        params: list[object] = []
        if principal_id:
            clauses.append("principal_id = %s")
            params.append(str(principal_id or "").strip())
        normalized_statuses = [str(status or "").strip() for status in list(statuses or []) if str(status or "").strip()]
        if normalized_statuses:
            clauses.append("status = ANY(%s)")
            params.append(normalized_statuses)
        query = "SELECT COUNT(*) FROM property_packet_publications"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
        return int((row or [0])[0] or 0)

    def record_event(self, row: dict[str, object]) -> dict[str, object]:
        normalized = _event_defaults(row)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO property_packet_publication_events
                    (event_id, publication_id, principal_id, event_type, actor, payload_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO UPDATE
                    SET payload_json = EXCLUDED.payload_json
                    RETURNING event_id, publication_id, principal_id, event_type, actor, payload_json, created_at
                    """,
                    (
                        normalized["event_id"],
                        normalized["publication_id"],
                        normalized["principal_id"],
                        normalized["event_type"],
                        normalized["actor"],
                        self._json_value(normalized.get("payload_json") or {}),
                        normalized["created_at"],
                    ),
                )
                stored = cur.fetchone()
        return self._event_row(stored)

    def list_events(
        self,
        *,
        publication_id: str | None = None,
        principal_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []
        if publication_id:
            clauses.append("publication_id = %s")
            params.append(str(publication_id or "").strip())
        if principal_id:
            clauses.append("principal_id = %s")
            params.append(str(principal_id or "").strip())
        if event_type:
            clauses.append("event_type = %s")
            params.append(str(event_type or "").strip())
        query = "SELECT event_id, publication_id, principal_id, event_type, actor, payload_json, created_at FROM property_packet_publication_events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(max(1, min(int(limit or 100), 500)))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [self._event_row(row) for row in rows]
