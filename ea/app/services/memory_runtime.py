from __future__ import annotations

import logging

from app.domain.models import Commitment, Entity, MemoryCandidate, MemoryItem, RelationshipEdge, now_utc_iso
from app.repositories.commitments import CommitmentRepository, InMemoryCommitmentRepository
from app.repositories.commitments_postgres import PostgresCommitmentRepository
from app.repositories.entities import EntityRepository, InMemoryEntityRepository
from app.repositories.entities_postgres import PostgresEntityRepository
from app.repositories.memory_candidates import InMemoryMemoryCandidateRepository, MemoryCandidateRepository
from app.repositories.memory_candidates_postgres import PostgresMemoryCandidateRepository
from app.repositories.memory_items import InMemoryMemoryItemRepository, MemoryItemRepository
from app.repositories.memory_items_postgres import PostgresMemoryItemRepository
from app.repositories.relationships import InMemoryRelationshipRepository, RelationshipRepository
from app.repositories.relationships_postgres import PostgresRelationshipRepository
from app.settings import Settings, get_settings


class MemoryRuntimeService:
    def __init__(
        self,
        candidates: MemoryCandidateRepository,
        items: MemoryItemRepository,
        entities: EntityRepository,
        relationships: RelationshipRepository,
        commitments: CommitmentRepository,
    ) -> None:
        self._candidates = candidates
        self._items = items
        self._entities = entities
        self._relationships = relationships
        self._commitments = commitments

    def stage_candidate(
        self,
        *,
        principal_id: str,
        category: str,
        summary: str,
        fact_json: dict[str, object] | None = None,
        source_session_id: str = "",
        source_event_id: str = "",
        source_step_id: str = "",
        confidence: float = 0.5,
        sensitivity: str = "internal",
    ) -> MemoryCandidate:
        return self._candidates.create_candidate(
            principal_id=principal_id,
            category=category,
            summary=summary,
            fact_json=fact_json,
            source_session_id=source_session_id,
            source_event_id=source_event_id,
            source_step_id=source_step_id,
            confidence=confidence,
            sensitivity=sensitivity,
        )

    def list_candidates(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
        principal_id: str | None = None,
    ) -> list[MemoryCandidate]:
        return self._candidates.list_candidates(limit=limit, status=status, principal_id=principal_id)

    def promote_candidate(
        self,
        candidate_id: str,
        *,
        reviewer: str,
        sharing_policy: str = "private",
        confidence_override: float | None = None,
    ) -> tuple[MemoryCandidate, MemoryItem] | None:
        candidate = self._candidates.get(candidate_id)
        if not candidate:
            return None

        if candidate.status == "promoted" and candidate.promoted_item_id:
            existing = self._items.get(candidate.promoted_item_id)
            if existing:
                refreshed = self._candidates.review(
                    candidate.candidate_id,
                    status="promoted",
                    reviewer=reviewer,
                    promoted_item_id=existing.item_id,
                )
                return (refreshed or candidate, existing)

        confidence_value = candidate.confidence if confidence_override is None else float(confidence_override)
        provenance_json = {
            "candidate_id": candidate.candidate_id,
            "source_session_id": candidate.source_session_id,
            "source_event_id": candidate.source_event_id,
            "source_step_id": candidate.source_step_id,
        }
        item = self._items.create_item(
            principal_id=candidate.principal_id,
            category=candidate.category,
            summary=candidate.summary,
            fact_json=candidate.fact_json,
            provenance_json=provenance_json,
            confidence=confidence_value,
            sensitivity=candidate.sensitivity,
            sharing_policy=sharing_policy,
            reviewer=reviewer,
            last_verified_at=now_utc_iso(),
        )
        updated = self._candidates.review(
            candidate.candidate_id,
            status="promoted",
            reviewer=reviewer,
            promoted_item_id=item.item_id,
        )
        return (updated or candidate, item)

    def reject_candidate(self, candidate_id: str, *, reviewer: str) -> MemoryCandidate | None:
        return self._candidates.review(
            candidate_id,
            status="rejected",
            reviewer=reviewer,
            promoted_item_id="",
        )

    def list_items(self, *, limit: int = 100, principal_id: str | None = None) -> list[MemoryItem]:
        return self._items.list_items(limit=limit, principal_id=principal_id)

    def get_item(self, item_id: str) -> MemoryItem | None:
        return self._items.get(item_id)

    def upsert_entity(
        self,
        *,
        principal_id: str,
        entity_type: str,
        canonical_name: str,
        attributes_json: dict[str, object] | None = None,
        confidence: float = 0.5,
        status: str = "active",
    ) -> Entity:
        return self._entities.upsert_entity(
            principal_id=principal_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
            attributes_json=attributes_json,
            confidence=confidence,
            status=status,
        )

    def list_entities(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
        entity_type: str | None = None,
    ) -> list[Entity]:
        return self._entities.list_entities(limit=limit, principal_id=principal_id, entity_type=entity_type)

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def upsert_relationship(
        self,
        *,
        principal_id: str,
        from_entity_id: str,
        to_entity_id: str,
        relationship_type: str,
        attributes_json: dict[str, object] | None = None,
        confidence: float = 0.5,
        valid_from: str | None = None,
        valid_to: str | None = None,
    ) -> RelationshipEdge:
        return self._relationships.upsert_relationship(
            principal_id=principal_id,
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            relationship_type=relationship_type,
            attributes_json=attributes_json,
            confidence=confidence,
            valid_from=valid_from,
            valid_to=valid_to,
        )

    def list_relationships(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
        from_entity_id: str | None = None,
        to_entity_id: str | None = None,
        relationship_type: str | None = None,
    ) -> list[RelationshipEdge]:
        return self._relationships.list_relationships(
            limit=limit,
            principal_id=principal_id,
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            relationship_type=relationship_type,
        )

    def get_relationship(self, relationship_id: str) -> RelationshipEdge | None:
        return self._relationships.get(relationship_id)

    def upsert_commitment(
        self,
        *,
        principal_id: str,
        title: str,
        details: str = "",
        status: str = "open",
        priority: str = "medium",
        due_at: str | None = None,
        source_json: dict[str, object] | None = None,
        commitment_id: str | None = None,
    ) -> Commitment:
        return self._commitments.upsert_commitment(
            principal_id=principal_id,
            title=title,
            details=details,
            status=status,
            priority=priority,
            due_at=due_at,
            source_json=source_json,
            commitment_id=commitment_id,
        )

    def list_commitments(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[Commitment]:
        return self._commitments.list_commitments(
            principal_id=principal_id,
            limit=limit,
            status=status,
        )

    def get_commitment(self, commitment_id: str, *, principal_id: str) -> Commitment | None:
        found = self._commitments.get(commitment_id)
        if not found:
            return None
        if found.principal_id != str(principal_id or "").strip():
            return None
        return found


def _backend_mode(settings: Settings) -> str:
    return str(settings.storage.backend or "auto").strip().lower()


def _build_candidate_repo(settings: Settings) -> MemoryCandidateRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.memory_candidates")
    if backend == "memory":
        return InMemoryMemoryCandidateRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresMemoryCandidateRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresMemoryCandidateRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres memory-candidate backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryMemoryCandidateRepository()


def _build_item_repo(settings: Settings) -> MemoryItemRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.memory_items")
    if backend == "memory":
        return InMemoryMemoryItemRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresMemoryItemRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresMemoryItemRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres memory-item backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryMemoryItemRepository()


def _build_entity_repo(settings: Settings) -> EntityRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.entities")
    if backend == "memory":
        return InMemoryEntityRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresEntityRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresEntityRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres entity backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryEntityRepository()


def _build_relationship_repo(settings: Settings) -> RelationshipRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.relationships")
    if backend == "memory":
        return InMemoryRelationshipRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresRelationshipRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresRelationshipRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres relationship backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryRelationshipRepository()


def _build_commitment_repo(settings: Settings) -> CommitmentRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.commitments")
    if backend == "memory":
        return InMemoryCommitmentRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresCommitmentRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresCommitmentRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres commitment backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryCommitmentRepository()


def build_memory_runtime(settings: Settings | None = None) -> MemoryRuntimeService:
    resolved = settings or get_settings()
    return MemoryRuntimeService(
        candidates=_build_candidate_repo(resolved),
        items=_build_item_repo(resolved),
        entities=_build_entity_repo(resolved),
        relationships=_build_relationship_repo(resolved),
        commitments=_build_commitment_repo(resolved),
    )
