from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.models import Artifact, EvidenceObject
from app.repositories.evidence_objects import evidence_object_from_artifact


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class PostgresEvidenceObjectRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresEvidenceObjectRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres evidence-object backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: object):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS evidence_objects (
                        evidence_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        artifact_id TEXT NOT NULL UNIQUE,
                        session_id TEXT NOT NULL,
                        artifact_kind TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        claims_json JSONB NOT NULL,
                        evidence_refs_json JSONB NOT NULL,
                        open_questions_json JSONB NOT NULL,
                        confidence DOUBLE PRECISION NOT NULL,
                        citation_handle TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_evidence_objects_principal_created
                    ON evidence_objects(principal_id, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_evidence_objects_session_created
                    ON evidence_objects(session_id, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_evidence_objects_refs_gin
                    ON evidence_objects
                    USING GIN (evidence_refs_json)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> EvidenceObject:
        (
            evidence_id,
            principal_id,
            artifact_id,
            session_id,
            artifact_kind,
            summary,
            claims_json,
            evidence_refs_json,
            open_questions_json,
            confidence,
            citation_handle,
            created_at,
            updated_at,
        ) = row
        return EvidenceObject(
            evidence_id=str(evidence_id),
            principal_id=str(principal_id),
            artifact_id=str(artifact_id),
            execution_session_id=str(session_id),
            artifact_kind=str(artifact_kind),
            summary=str(summary or ""),
            claims=tuple(str(value or "").strip() for value in (claims_json or []) if str(value or "").strip()),
            evidence_refs=tuple(
                str(value or "").strip() for value in (evidence_refs_json or []) if str(value or "").strip()
            ),
            open_questions=tuple(
                str(value or "").strip() for value in (open_questions_json or []) if str(value or "").strip()
            ),
            confidence=float(confidence or 0.0),
            citation_handle=str(citation_handle or ""),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def upsert_from_artifact(self, artifact: Artifact) -> EvidenceObject | None:
        row = evidence_object_from_artifact(artifact)
        if row is None:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO evidence_objects
                    (evidence_id, principal_id, artifact_id, session_id, artifact_kind, summary,
                     claims_json, evidence_refs_json, open_questions_json, confidence,
                     citation_handle, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (artifact_id) DO UPDATE
                    SET principal_id = EXCLUDED.principal_id,
                        session_id = EXCLUDED.session_id,
                        artifact_kind = EXCLUDED.artifact_kind,
                        summary = EXCLUDED.summary,
                        claims_json = EXCLUDED.claims_json,
                        evidence_refs_json = EXCLUDED.evidence_refs_json,
                        open_questions_json = EXCLUDED.open_questions_json,
                        confidence = EXCLUDED.confidence,
                        citation_handle = EXCLUDED.citation_handle,
                        updated_at = EXCLUDED.updated_at
                    RETURNING evidence_id, principal_id, artifact_id, session_id, artifact_kind, summary,
                              claims_json, evidence_refs_json, open_questions_json, confidence,
                              citation_handle, created_at, updated_at
                    """,
                    (
                        row.evidence_id,
                        row.principal_id,
                        row.artifact_id,
                        row.execution_session_id,
                        row.artifact_kind,
                        row.summary,
                        self._json_value(list(row.claims)),
                        self._json_value(list(row.evidence_refs)),
                        self._json_value(list(row.open_questions)),
                        row.confidence,
                        row.citation_handle,
                        row.created_at,
                        row.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return row
        return self._from_row(out)

    def get(self, evidence_id: str) -> EvidenceObject | None:
        key = str(evidence_id or "").strip()
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT evidence_id, principal_id, artifact_id, session_id, artifact_kind, summary,
                           claims_json, evidence_refs_json, open_questions_json, confidence,
                           citation_handle, created_at, updated_at
                    FROM evidence_objects
                    WHERE evidence_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def get_by_artifact(self, artifact_id: str) -> EvidenceObject | None:
        key = str(artifact_id or "").strip()
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT evidence_id, principal_id, artifact_id, session_id, artifact_kind, summary,
                           claims_json, evidence_refs_json, open_questions_json, confidence,
                           citation_handle, created_at, updated_at
                    FROM evidence_objects
                    WHERE artifact_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_objects(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
        artifact_id: str | None = None,
        session_id: str | None = None,
        evidence_ref: str | None = None,
    ) -> list[EvidenceObject]:
        n = max(1, min(500, int(limit or 100)))
        principal_filter = str(principal_id or "").strip()
        artifact_filter = str(artifact_id or "").strip()
        session_filter = str(session_id or "").strip()
        evidence_ref_filter = str(evidence_ref or "").strip()
        where: list[str] = []
        params: list[object] = []
        if principal_filter:
            where.append("principal_id = %s")
            params.append(principal_filter)
        if artifact_filter:
            where.append("artifact_id = %s")
            params.append(artifact_filter)
        if session_filter:
            where.append("session_id = %s")
            params.append(session_filter)
        if evidence_ref_filter:
            where.append("evidence_refs_json @> %s::jsonb")
            params.append(self._json_value([evidence_ref_filter]))
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        query = (
            "SELECT evidence_id, principal_id, artifact_id, session_id, artifact_kind, summary, "
            "claims_json, evidence_refs_json, open_questions_json, confidence, "
            "citation_handle, created_at, updated_at "
            "FROM evidence_objects "
            f"{where_sql} "
            "ORDER BY created_at DESC, evidence_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
