from __future__ import annotations

import logging

from app.domain.models import Artifact, EvidenceMergeResult, EvidenceObject
from app.repositories.evidence_objects import (
    EvidenceObjectRepository,
    InMemoryEvidenceObjectRepository,
    normalize_evidence_strings,
)
from app.repositories.evidence_objects_postgres import PostgresEvidenceObjectRepository
from app.settings import Settings, ensure_storage_fallback_allowed, get_settings


class EvidenceRuntimeService:
    def __init__(self, objects: EvidenceObjectRepository) -> None:
        self._objects = objects

    def record_artifact(self, artifact: Artifact) -> EvidenceObject | None:
        return self._objects.upsert_from_artifact(artifact)

    def list_objects(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
        artifact_id: str | None = None,
        session_id: str | None = None,
        evidence_ref: str | None = None,
    ) -> list[EvidenceObject]:
        return self._objects.list_objects(
            limit=limit,
            principal_id=principal_id,
            artifact_id=artifact_id,
            session_id=session_id,
            evidence_ref=evidence_ref,
        )

    def get_object(self, evidence_id: str, *, principal_id: str | None = None) -> EvidenceObject | None:
        found = self._objects.get(evidence_id)
        if found is None:
            return None
        if principal_id and found.principal_id != str(principal_id or "").strip():
            return None
        return found

    def get_object_for_artifact(self, artifact_id: str, *, principal_id: str | None = None) -> EvidenceObject | None:
        found = self._objects.get_by_artifact(artifact_id)
        if found is None:
            return None
        if principal_id and found.principal_id != str(principal_id or "").strip():
            return None
        return found

    def merge_objects(
        self,
        evidence_ids: list[str] | tuple[str, ...],
        *,
        principal_id: str | None = None,
    ) -> EvidenceMergeResult:
        ordered_ids = normalize_evidence_strings(evidence_ids)
        if not ordered_ids:
            raise ValueError("evidence_ids_required")
        rows: list[EvidenceObject] = []
        missing: list[str] = []
        for evidence_id in ordered_ids:
            found = self.get_object(evidence_id, principal_id=principal_id)
            if found is None:
                missing.append(evidence_id)
                continue
            rows.append(found)
        if missing:
            raise LookupError(",".join(missing))
        summaries = normalize_evidence_strings([row.summary for row in rows if row.summary])
        claims = normalize_evidence_strings([claim for row in rows for claim in row.claims])
        evidence_refs = normalize_evidence_strings([ref for row in rows for ref in row.evidence_refs])
        open_questions = normalize_evidence_strings([question for row in rows for question in row.open_questions])
        citation_handles = normalize_evidence_strings([row.citation_handle for row in rows if row.citation_handle])
        source_artifact_ids = normalize_evidence_strings([row.artifact_id for row in rows if row.artifact_id])
        confidence = round(sum(row.confidence for row in rows) / len(rows), 4)
        return EvidenceMergeResult(
            summary=" | ".join(summaries[:3]),
            claims=claims,
            evidence_refs=evidence_refs,
            open_questions=open_questions,
            confidence=confidence,
            source_evidence_ids=ordered_ids,
            source_artifact_ids=source_artifact_ids,
            citation_handles=citation_handles,
        )


def _backend_mode(settings: Settings) -> str:
    return str(settings.storage.backend or "auto").strip().lower()


def _build_evidence_repo(settings: Settings) -> EvidenceObjectRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.evidence_objects")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "evidence objects configured for memory")
        return InMemoryEvidenceObjectRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresEvidenceObjectRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresEvidenceObjectRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "evidence objects auto fallback", exc)
            log.warning("postgres evidence-object backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "evidence objects auto backend without DATABASE_URL")
    return InMemoryEvidenceObjectRepository()


def build_evidence_runtime(settings: Settings | None = None) -> EvidenceRuntimeService:
    resolved = settings or get_settings()
    return EvidenceRuntimeService(_build_evidence_repo(resolved))
