from __future__ import annotations

import logging

from app.domain.models import (
    AuthorityBinding,
    CommunicationPolicy,
    Commitment,
    DecisionWindow,
    DeadlineWindow,
    DeliveryPreference,
    Entity,
    FollowUpRule,
    FollowUp,
    MemoryCandidate,
    MemoryItem,
    RelationshipEdge,
    Stakeholder,
    now_utc_iso,
)
from app.repositories.authority_bindings import AuthorityBindingRepository, InMemoryAuthorityBindingRepository
from app.repositories.authority_bindings_postgres import PostgresAuthorityBindingRepository
from app.repositories.commitments import CommitmentRepository, InMemoryCommitmentRepository
from app.repositories.commitments_postgres import PostgresCommitmentRepository
from app.repositories.communication_policies import (
    CommunicationPolicyRepository,
    InMemoryCommunicationPolicyRepository,
)
from app.repositories.communication_policies_postgres import PostgresCommunicationPolicyRepository
from app.repositories.decision_windows import DecisionWindowRepository, InMemoryDecisionWindowRepository
from app.repositories.decision_windows_postgres import PostgresDecisionWindowRepository
from app.repositories.deadline_windows import DeadlineWindowRepository, InMemoryDeadlineWindowRepository
from app.repositories.deadline_windows_postgres import PostgresDeadlineWindowRepository
from app.repositories.delivery_preferences import DeliveryPreferenceRepository, InMemoryDeliveryPreferenceRepository
from app.repositories.delivery_preferences_postgres import PostgresDeliveryPreferenceRepository
from app.repositories.entities import EntityRepository, InMemoryEntityRepository
from app.repositories.entities_postgres import PostgresEntityRepository
from app.repositories.follow_ups import FollowUpRepository, InMemoryFollowUpRepository
from app.repositories.follow_up_rules import FollowUpRuleRepository, InMemoryFollowUpRuleRepository
from app.repositories.follow_up_rules_postgres import PostgresFollowUpRuleRepository
from app.repositories.follow_ups_postgres import PostgresFollowUpRepository
from app.repositories.memory_candidates import InMemoryMemoryCandidateRepository, MemoryCandidateRepository
from app.repositories.memory_candidates_postgres import PostgresMemoryCandidateRepository
from app.repositories.memory_items import InMemoryMemoryItemRepository, MemoryItemRepository
from app.repositories.memory_items_postgres import PostgresMemoryItemRepository
from app.repositories.relationships import InMemoryRelationshipRepository, RelationshipRepository
from app.repositories.relationships_postgres import PostgresRelationshipRepository
from app.repositories.stakeholders import InMemoryStakeholderRepository, StakeholderRepository
from app.repositories.stakeholders_postgres import PostgresStakeholderRepository
from app.settings import Settings, get_settings


class MemoryRuntimeService:
    def __init__(
        self,
        candidates: MemoryCandidateRepository,
        items: MemoryItemRepository,
        entities: EntityRepository,
        relationships: RelationshipRepository,
        commitments: CommitmentRepository,
        communication_policies: CommunicationPolicyRepository,
        decision_windows: DecisionWindowRepository,
        deadline_windows: DeadlineWindowRepository,
        stakeholders: StakeholderRepository,
        authority_bindings: AuthorityBindingRepository,
        delivery_preferences: DeliveryPreferenceRepository,
        follow_ups: FollowUpRepository,
        follow_up_rules: FollowUpRuleRepository,
    ) -> None:
        self._candidates = candidates
        self._items = items
        self._entities = entities
        self._relationships = relationships
        self._commitments = commitments
        self._communication_policies = communication_policies
        self._decision_windows = decision_windows
        self._deadline_windows = deadline_windows
        self._stakeholders = stakeholders
        self._authority_bindings = authority_bindings
        self._delivery_preferences = delivery_preferences
        self._follow_ups = follow_ups
        self._follow_up_rules = follow_up_rules

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

    def upsert_communication_policy(
        self,
        *,
        principal_id: str,
        scope: str,
        preferred_channel: str = "",
        tone: str = "neutral",
        max_length: int = 1200,
        quiet_hours_json: dict[str, object] | None = None,
        escalation_json: dict[str, object] | None = None,
        status: str = "active",
        notes: str = "",
        policy_id: str | None = None,
    ) -> CommunicationPolicy:
        return self._communication_policies.upsert_policy(
            principal_id=principal_id,
            scope=scope,
            preferred_channel=preferred_channel,
            tone=tone,
            max_length=max_length,
            quiet_hours_json=quiet_hours_json,
            escalation_json=escalation_json,
            status=status,
            notes=notes,
            policy_id=policy_id,
        )

    def list_communication_policies(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[CommunicationPolicy]:
        return self._communication_policies.list_policies(
            principal_id=principal_id,
            limit=limit,
            status=status,
        )

    def get_communication_policy(self, policy_id: str, *, principal_id: str) -> CommunicationPolicy | None:
        found = self._communication_policies.get(policy_id)
        if not found:
            return None
        if found.principal_id != str(principal_id or "").strip():
            return None
        return found

    def upsert_decision_window(
        self,
        *,
        principal_id: str,
        title: str,
        context: str = "",
        opens_at: str | None = None,
        closes_at: str | None = None,
        urgency: str = "medium",
        authority_required: str = "manager",
        status: str = "open",
        notes: str = "",
        source_json: dict[str, object] | None = None,
        decision_window_id: str | None = None,
    ) -> DecisionWindow:
        return self._decision_windows.upsert_decision_window(
            principal_id=principal_id,
            title=title,
            context=context,
            opens_at=opens_at,
            closes_at=closes_at,
            urgency=urgency,
            authority_required=authority_required,
            status=status,
            notes=notes,
            source_json=source_json,
            decision_window_id=decision_window_id,
        )

    def list_decision_windows(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[DecisionWindow]:
        return self._decision_windows.list_decision_windows(
            principal_id=principal_id,
            limit=limit,
            status=status,
        )

    def get_decision_window(self, decision_window_id: str, *, principal_id: str) -> DecisionWindow | None:
        found = self._decision_windows.get(decision_window_id)
        if not found:
            return None
        if found.principal_id != str(principal_id or "").strip():
            return None
        return found

    def upsert_deadline_window(
        self,
        *,
        principal_id: str,
        title: str,
        start_at: str | None = None,
        end_at: str | None = None,
        status: str = "open",
        priority: str = "medium",
        notes: str = "",
        source_json: dict[str, object] | None = None,
        window_id: str | None = None,
    ) -> DeadlineWindow:
        return self._deadline_windows.upsert_deadline_window(
            principal_id=principal_id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            status=status,
            priority=priority,
            notes=notes,
            source_json=source_json,
            window_id=window_id,
        )

    def list_deadline_windows(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[DeadlineWindow]:
        return self._deadline_windows.list_deadline_windows(
            principal_id=principal_id,
            limit=limit,
            status=status,
        )

    def get_deadline_window(self, window_id: str, *, principal_id: str) -> DeadlineWindow | None:
        found = self._deadline_windows.get(window_id)
        if not found:
            return None
        if found.principal_id != str(principal_id or "").strip():
            return None
        return found

    def upsert_stakeholder(
        self,
        *,
        principal_id: str,
        display_name: str,
        channel_ref: str = "",
        authority_level: str = "manager",
        importance: str = "medium",
        response_cadence: str = "normal",
        tone_pref: str = "neutral",
        sensitivity: str = "internal",
        escalation_policy: str = "none",
        open_loops_json: dict[str, object] | None = None,
        friction_points_json: dict[str, object] | None = None,
        last_interaction_at: str | None = None,
        status: str = "active",
        notes: str = "",
        stakeholder_id: str | None = None,
    ) -> Stakeholder:
        return self._stakeholders.upsert_stakeholder(
            principal_id=principal_id,
            display_name=display_name,
            channel_ref=channel_ref,
            authority_level=authority_level,
            importance=importance,
            response_cadence=response_cadence,
            tone_pref=tone_pref,
            sensitivity=sensitivity,
            escalation_policy=escalation_policy,
            open_loops_json=open_loops_json,
            friction_points_json=friction_points_json,
            last_interaction_at=last_interaction_at,
            status=status,
            notes=notes,
            stakeholder_id=stakeholder_id,
        )

    def list_stakeholders(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[Stakeholder]:
        return self._stakeholders.list_stakeholders(
            principal_id=principal_id,
            limit=limit,
            status=status,
        )

    def get_stakeholder(self, stakeholder_id: str, *, principal_id: str) -> Stakeholder | None:
        found = self._stakeholders.get(stakeholder_id)
        if not found:
            return None
        if found.principal_id != str(principal_id or "").strip():
            return None
        return found

    def upsert_authority_binding(
        self,
        *,
        principal_id: str,
        subject_ref: str,
        action_scope: str,
        approval_level: str = "manager",
        channel_scope: tuple[str, ...] = (),
        policy_json: dict[str, object] | None = None,
        status: str = "active",
        binding_id: str | None = None,
    ) -> AuthorityBinding:
        return self._authority_bindings.upsert_binding(
            principal_id=principal_id,
            subject_ref=subject_ref,
            action_scope=action_scope,
            approval_level=approval_level,
            channel_scope=channel_scope,
            policy_json=policy_json,
            status=status,
            binding_id=binding_id,
        )

    def list_authority_bindings(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[AuthorityBinding]:
        return self._authority_bindings.list_bindings(
            principal_id=principal_id,
            limit=limit,
            status=status,
        )

    def get_authority_binding(self, binding_id: str, *, principal_id: str) -> AuthorityBinding | None:
        found = self._authority_bindings.get(binding_id)
        if not found:
            return None
        if found.principal_id != str(principal_id or "").strip():
            return None
        return found

    def upsert_delivery_preference(
        self,
        *,
        principal_id: str,
        channel: str,
        recipient_ref: str,
        cadence: str = "normal",
        quiet_hours_json: dict[str, object] | None = None,
        format_json: dict[str, object] | None = None,
        status: str = "active",
        preference_id: str | None = None,
    ) -> DeliveryPreference:
        return self._delivery_preferences.upsert_preference(
            principal_id=principal_id,
            channel=channel,
            recipient_ref=recipient_ref,
            cadence=cadence,
            quiet_hours_json=quiet_hours_json,
            format_json=format_json,
            status=status,
            preference_id=preference_id,
        )

    def list_delivery_preferences(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[DeliveryPreference]:
        return self._delivery_preferences.list_preferences(
            principal_id=principal_id,
            limit=limit,
            status=status,
        )

    def get_delivery_preference(self, preference_id: str, *, principal_id: str) -> DeliveryPreference | None:
        found = self._delivery_preferences.get(preference_id)
        if not found:
            return None
        if found.principal_id != str(principal_id or "").strip():
            return None
        return found

    def upsert_follow_up(
        self,
        *,
        principal_id: str,
        stakeholder_ref: str,
        topic: str,
        status: str = "open",
        due_at: str | None = None,
        channel_hint: str = "",
        notes: str = "",
        source_json: dict[str, object] | None = None,
        follow_up_id: str | None = None,
    ) -> FollowUp:
        return self._follow_ups.upsert_follow_up(
            principal_id=principal_id,
            stakeholder_ref=stakeholder_ref,
            topic=topic,
            status=status,
            due_at=due_at,
            channel_hint=channel_hint,
            notes=notes,
            source_json=source_json,
            follow_up_id=follow_up_id,
        )

    def list_follow_ups(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[FollowUp]:
        return self._follow_ups.list_follow_ups(
            principal_id=principal_id,
            limit=limit,
            status=status,
        )

    def get_follow_up(self, follow_up_id: str, *, principal_id: str) -> FollowUp | None:
        found = self._follow_ups.get(follow_up_id)
        if not found:
            return None
        if found.principal_id != str(principal_id or "").strip():
            return None
        return found

    def upsert_follow_up_rule(
        self,
        *,
        principal_id: str,
        name: str,
        trigger_kind: str,
        channel_scope: tuple[str, ...] = (),
        delay_minutes: int = 60,
        max_attempts: int = 3,
        escalation_policy: str = "notify_exec",
        conditions_json: dict[str, object] | None = None,
        action_json: dict[str, object] | None = None,
        status: str = "active",
        notes: str = "",
        rule_id: str | None = None,
    ) -> FollowUpRule:
        return self._follow_up_rules.upsert_rule(
            principal_id=principal_id,
            name=name,
            trigger_kind=trigger_kind,
            channel_scope=channel_scope,
            delay_minutes=delay_minutes,
            max_attempts=max_attempts,
            escalation_policy=escalation_policy,
            conditions_json=conditions_json,
            action_json=action_json,
            status=status,
            notes=notes,
            rule_id=rule_id,
        )

    def list_follow_up_rules(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[FollowUpRule]:
        return self._follow_up_rules.list_rules(
            principal_id=principal_id,
            limit=limit,
            status=status,
        )

    def get_follow_up_rule(self, rule_id: str, *, principal_id: str) -> FollowUpRule | None:
        found = self._follow_up_rules.get(rule_id)
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


def _build_communication_policy_repo(settings: Settings) -> CommunicationPolicyRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.communication_policies")
    if backend == "memory":
        return InMemoryCommunicationPolicyRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresCommunicationPolicyRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresCommunicationPolicyRepository(settings.database_url)
        except Exception as exc:
            log.warning(
                "postgres communication-policy backend unavailable in auto mode; falling back to memory: %s",
                exc,
            )
    return InMemoryCommunicationPolicyRepository()


def _build_decision_window_repo(settings: Settings) -> DecisionWindowRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.decision_windows")
    if backend == "memory":
        return InMemoryDecisionWindowRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresDecisionWindowRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresDecisionWindowRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres decision-window backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryDecisionWindowRepository()


def _build_deadline_window_repo(settings: Settings) -> DeadlineWindowRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.deadline_windows")
    if backend == "memory":
        return InMemoryDeadlineWindowRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresDeadlineWindowRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresDeadlineWindowRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres deadline-window backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryDeadlineWindowRepository()


def _build_stakeholder_repo(settings: Settings) -> StakeholderRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.stakeholders")
    if backend == "memory":
        return InMemoryStakeholderRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresStakeholderRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresStakeholderRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres stakeholder backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryStakeholderRepository()


def _build_authority_binding_repo(settings: Settings) -> AuthorityBindingRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.authority_bindings")
    if backend == "memory":
        return InMemoryAuthorityBindingRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresAuthorityBindingRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresAuthorityBindingRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres authority-binding backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryAuthorityBindingRepository()


def _build_delivery_preference_repo(settings: Settings) -> DeliveryPreferenceRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.delivery_preferences")
    if backend == "memory":
        return InMemoryDeliveryPreferenceRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresDeliveryPreferenceRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresDeliveryPreferenceRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres delivery-preference backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryDeliveryPreferenceRepository()


def _build_follow_up_repo(settings: Settings) -> FollowUpRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.follow_ups")
    if backend == "memory":
        return InMemoryFollowUpRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresFollowUpRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresFollowUpRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres follow-up backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryFollowUpRepository()


def _build_follow_up_rule_repo(settings: Settings) -> FollowUpRuleRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.follow_up_rules")
    if backend == "memory":
        return InMemoryFollowUpRuleRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresFollowUpRuleRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresFollowUpRuleRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres follow-up-rule backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryFollowUpRuleRepository()


def build_memory_runtime(settings: Settings | None = None) -> MemoryRuntimeService:
    resolved = settings or get_settings()
    return MemoryRuntimeService(
        candidates=_build_candidate_repo(resolved),
        items=_build_item_repo(resolved),
        entities=_build_entity_repo(resolved),
        relationships=_build_relationship_repo(resolved),
        commitments=_build_commitment_repo(resolved),
        communication_policies=_build_communication_policy_repo(resolved),
        decision_windows=_build_decision_window_repo(resolved),
        deadline_windows=_build_deadline_window_repo(resolved),
        stakeholders=_build_stakeholder_repo(resolved),
        authority_bindings=_build_authority_binding_repo(resolved),
        delivery_preferences=_build_delivery_preference_repo(resolved),
        follow_ups=_build_follow_up_repo(resolved),
        follow_up_rules=_build_follow_up_rule_repo(resolved),
    )
