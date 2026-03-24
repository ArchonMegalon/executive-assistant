from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.domain.models import DeliveryOutboxItem, ObservationEvent
from app.repositories.delivery_outbox import DeliveryOutboxRepository, InMemoryDeliveryOutboxRepository
from app.repositories.delivery_outbox_postgres import PostgresDeliveryOutboxRepository
from app.repositories.observation import ObservationEventRepository, InMemoryObservationEventRepository
from app.repositories.observation_postgres import PostgresObservationEventRepository
from app.services.cognitive_load import CognitiveLoadService
from app.services.policy import PolicyDecisionService
from app.settings import Settings, ensure_storage_fallback_allowed, get_settings


class ChannelRuntimeService:
    def __init__(
        self,
        observations: ObservationEventRepository,
        outbox: DeliveryOutboxRepository,
        *,
        cognitive_load: CognitiveLoadService | None = None,
        policy: PolicyDecisionService | None = None,
    ) -> None:
        self._observations = observations
        self._outbox = outbox
        self._cognitive_load = cognitive_load
        self._policy = policy

    def ingest_observation(
        self,
        principal_id: str,
        channel: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        *,
        source_id: str = "",
        external_id: str = "",
        dedupe_key: str = "",
        auth_context_json: dict[str, object] | None = None,
        raw_payload_uri: str = "",
    ) -> ObservationEvent:
        event = self._observations.append(
            principal_id=principal_id,
            channel=channel,
            event_type=event_type,
            payload=payload,
            source_id=source_id,
            external_id=external_id,
            dedupe_key=dedupe_key,
            auth_context_json=auth_context_json,
            raw_payload_uri=raw_payload_uri,
        )
        if self._cognitive_load is not None and self._is_principal_originated(
            event_type=event_type,
            payload=payload,
            auth_context_json=auth_context_json,
        ):
            self._cognitive_load.refresh_for_principal(principal_id)
        return event

    def list_recent_observations(self, limit: int = 50, *, principal_id: str | None = None) -> list[ObservationEvent]:
        return self._observations.list_recent(limit=limit, principal_id=principal_id)

    def find_observation_by_dedupe(self, dedupe_key: str, *, principal_id: str | None = None) -> ObservationEvent | None:
        normalized = str(dedupe_key or "").strip()
        if not normalized:
            return None
        return self._observations.get_by_dedupe(normalized, principal_id=principal_id)

    def count_recent_observations_for_principal(self, principal_id: str, *, since: str) -> int:
        return self._observations.count_recent_for_principal(str(principal_id or "").strip(), since=since)

    def queue_delivery(
        self,
        channel: str,
        recipient: str,
        content: str,
        metadata: dict[str, object] | None = None,
        *,
        principal_id: str = "",
        idempotency_key: str = "",
    ) -> DeliveryOutboxItem:
        normalized_metadata = dict(metadata or {})
        normalized_principal = str(principal_id or normalized_metadata.get("principal_id") or "").strip()
        normalized_metadata["principal_id"] = normalized_principal
        row = self._outbox.enqueue(
            principal_id=normalized_principal,
            channel=channel,
            recipient=recipient,
            content=content,
            metadata=normalized_metadata,
            idempotency_key=idempotency_key,
        )
        if self._should_defer_delivery(normalized_metadata):
            deferred = self._outbox.mark_failed(
                row.delivery_id,
                principal_id=normalized_principal,
                error="deferred_by_interruption_budget",
                next_attempt_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                dead_letter=False,
            )
            if deferred is not None:
                return deferred
        return row

    def mark_delivery_sent(
        self,
        delivery_id: str,
        *,
        principal_id: str,
        receipt_json: dict[str, object] | None = None,
    ) -> DeliveryOutboxItem | None:
        return self._outbox.mark_sent(
            delivery_id=delivery_id,
            principal_id=str(principal_id or "").strip(),
            receipt_json=receipt_json,
        )

    def mark_delivery_failed(
        self,
        delivery_id: str,
        *,
        principal_id: str,
        error: str,
        next_attempt_at: str | None = None,
        dead_letter: bool = False,
    ) -> DeliveryOutboxItem | None:
        return self._outbox.mark_failed(
            delivery_id=delivery_id,
            principal_id=str(principal_id or "").strip(),
            error=error,
            next_attempt_at=next_attempt_at,
            dead_letter=dead_letter,
        )

    def list_pending_delivery(self, limit: int = 50, *, principal_id: str | None = None) -> list[DeliveryOutboxItem]:
        return self._outbox.list_pending(limit=limit, principal_id=principal_id)

    def _is_principal_originated(
        self,
        *,
        event_type: str,
        payload: dict[str, object] | None,
        auth_context_json: dict[str, object] | None,
    ) -> bool:
        auth = dict(auth_context_json or {})
        if bool(auth.get("principal_originated")):
            return True
        if str(auth.get("actor_type") or "").strip().lower() == "principal":
            return True
        event_name = str(event_type or "").strip().lower()
        if event_name.startswith("principal.") or event_name.startswith("user."):
            return True
        body = dict(payload or {})
        return bool(body.get("principal_originated") or body.get("user_originated"))

    def _should_defer_delivery(self, metadata: dict[str, object]) -> bool:
        if self._cognitive_load is None or self._policy is None:
            return False
        principal_id = str(metadata.get("principal_id") or "").strip()
        if not principal_id:
            return False
        if metadata.get("defer_if_focus") is False:
            return False
        state = self._cognitive_load.refresh_for_principal(principal_id)
        priority = str(metadata.get("priority") or "normal").strip().lower() or "normal"
        return self._policy.should_defer_delivery(
            principal_id=principal_id,
            priority=priority,
            interruption_budget_state=state.interruption_budget_state,
        )


def _build_observation_repo(settings: Settings) -> ObservationEventRepository:
    backend = str(settings.storage.backend or "auto").strip().lower()
    log = logging.getLogger("ea.observations")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "observation repo configured for memory")
        return InMemoryObservationEventRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresObservationEventRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresObservationEventRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "observation repo auto fallback", exc)
            log.warning("postgres observation backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "observation repo auto backend without DATABASE_URL")
    return InMemoryObservationEventRepository()


def _build_outbox_repo(settings: Settings) -> DeliveryOutboxRepository:
    backend = str(settings.storage.backend or "auto").strip().lower()
    log = logging.getLogger("ea.outbox")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "delivery outbox configured for memory")
        return InMemoryDeliveryOutboxRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresDeliveryOutboxRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresDeliveryOutboxRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "delivery outbox auto fallback", exc)
            log.warning("postgres outbox backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "delivery outbox auto backend without DATABASE_URL")
    return InMemoryDeliveryOutboxRepository()


def build_channel_runtime(
    settings: Settings | None = None,
    *,
    cognitive_load: CognitiveLoadService | None = None,
    policy: PolicyDecisionService | None = None,
) -> ChannelRuntimeService:
    resolved = settings or get_settings()
    return ChannelRuntimeService(
        observations=_build_observation_repo(resolved),
        outbox=_build_outbox_repo(resolved),
        cognitive_load=cognitive_load,
        policy=policy,
    )
