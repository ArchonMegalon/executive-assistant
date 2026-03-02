from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.db import get_db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunk_text(text: str, size: int = 600) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    return [t[i : i + size] for i in range(0, len(t), size)]


class RetrievalControlPlane:
    def __init__(self) -> None:
        self.db = get_db()

    def ingest_pointer_first(
        self,
        *,
        tenant_key: str,
        connector_id: str,
        source_uri: str,
        external_object_id: str,
        file_class: str,
        normalized_text: str,
        metadata: dict[str, Any],
        principal_id: str,
    ) -> int:
        source = self.db.fetchone(
            """
            INSERT INTO source_objects
                (tenant_key, connector_id, source_uri, external_object_id, file_class, etag, content_fingerprint, is_deleted, created_at, updated_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, FALSE, %s, %s)
            ON CONFLICT (tenant_key, connector_id, external_object_id)
            DO UPDATE SET
                source_uri = EXCLUDED.source_uri,
                file_class = EXCLUDED.file_class,
                etag = EXCLUDED.etag,
                content_fingerprint = EXCLUDED.content_fingerprint,
                updated_at = EXCLUDED.updated_at
            RETURNING source_object_id
            """,
            (
                tenant_key,
                connector_id,
                source_uri,
                external_object_id,
                file_class,
                metadata.get("etag"),
                _fingerprint(normalized_text),
                _utcnow(),
                _utcnow(),
            ),
        )
        source_object_id = int(source["source_object_id"])
        self.db.execute(
            """
            INSERT INTO source_permissions (source_object_id, principal_id, permission_level, granted_at)
            VALUES (%s, %s, 'read', %s)
            """,
            (source_object_id, principal_id, _utcnow()),
        )
        run = self.db.fetchone(
            """
            INSERT INTO extraction_runs (tenant_key, source_object_id, run_status, cache_mode, started_at, finished_at)
            VALUES (%s, %s, 'completed', 'ephemeral', %s, %s)
            RETURNING extraction_run_id
            """,
            (tenant_key, source_object_id, _utcnow(), _utcnow()),
        )
        doc = self.db.fetchone(
            """
            INSERT INTO extracted_documents (tenant_key, source_object_id, normalized_text, metadata_json, created_at)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            RETURNING extracted_document_id
            """,
            (tenant_key, source_object_id, normalized_text, __import__("json").dumps(metadata), _utcnow()),
        )
        doc_id = int(doc["extracted_document_id"])
        chunks = _chunk_text(normalized_text)
        for i, chunk in enumerate(chunks):
            self.db.execute(
                """
                INSERT INTO retrieval_chunks (tenant_key, extracted_document_id, chunk_index, chunk_text, embedding_ref, provenance_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    tenant_key,
                    doc_id,
                    i,
                    chunk,
                    f"embed:{_fingerprint(chunk)[:20]}",
                    __import__("json").dumps({"source_object_id": source_object_id, "source_uri": source_uri}),
                    _utcnow(),
                ),
            )
        self.db.execute(
            """
            INSERT INTO retrieval_acl_rules (tenant_key, principal_id, source_object_id, policy, created_at)
            VALUES (%s, %s, %s, 'allow', %s)
            """,
            (tenant_key, principal_id, source_object_id, _utcnow()),
        )
        self.db.execute(
            """
            INSERT INTO retrieval_audit_events (tenant_key, event_type, correlation_id, details_json, created_at)
            VALUES (%s, 'pointer_ingest', %s, %s::jsonb, %s)
            """,
            (
                tenant_key,
                f"retrieval-{run['extraction_run_id']}",
                __import__("json").dumps({"source_object_id": source_object_id, "chunks": len(chunks)}),
                _utcnow(),
            ),
        )
        return source_object_id

    def retrieve_for_principal(self, *, tenant_key: str, principal_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT c.chunk_text, c.provenance_json, c.chunk_index
            FROM retrieval_chunks c
            JOIN extracted_documents d ON d.extracted_document_id = c.extracted_document_id
            JOIN retrieval_acl_rules a ON a.source_object_id = d.source_object_id
            WHERE c.tenant_key = %s AND a.principal_id = %s AND a.policy = 'allow'
            ORDER BY c.chunk_index ASC
            LIMIT %s
            """,
            (tenant_key, principal_id, max(1, limit)),
        )
        return [dict(r) for r in (rows or [])]

