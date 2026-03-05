from __future__ import annotations

import logging
from dataclasses import dataclass

from app.repositories.delivery_outbox import InMemoryDeliveryOutboxRepository
from app.repositories.observation import InMemoryObservationEventRepository
from app.services.channel_runtime import ChannelRuntimeService, build_channel_runtime
from app.services.orchestrator import RewriteOrchestrator, build_default_orchestrator
from app.services.policy import PolicyDecisionService
from app.settings import Settings, get_settings


class ReadinessService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check(self) -> tuple[bool, str]:
        backend = str(self._settings.storage.backend or "auto").strip().lower()
        if backend == "memory":
            return True, "memory_ready"
        if backend == "postgres":
            if not self._settings.database_url:
                return False, "database_url_missing"
            return self._probe_database()
        # auto mode: ready without DB URL (memory fallback), otherwise require DB probe.
        if not self._settings.database_url:
            return True, "auto_memory_ready"
        return self._probe_database()

    def _probe_database(self) -> tuple[bool, str]:
        try:
            import psycopg
        except Exception:
            return False, "psycopg_missing"
        try:
            with psycopg.connect(self._settings.database_url, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    _ = cur.fetchone()
            return True, "postgres_ready"
        except Exception as exc:
            return False, f"postgres_unavailable:{exc.__class__.__name__}"


@dataclass(frozen=True)
class AppContainer:
    settings: Settings
    orchestrator: RewriteOrchestrator
    channel_runtime: ChannelRuntimeService
    readiness: ReadinessService


def build_container(settings: Settings | None = None) -> AppContainer:
    resolved = settings or get_settings()
    log = logging.getLogger("ea.container")
    try:
        orchestrator = build_default_orchestrator(settings=resolved)
    except Exception as exc:
        log.warning("orchestrator bootstrap failed, using in-memory fallback: %s", exc)
        orchestrator = RewriteOrchestrator(
            policy=PolicyDecisionService(
                max_rewrite_chars=resolved.policy.max_rewrite_chars,
                approval_required_chars=resolved.policy.approval_required_chars,
            )
        )
    try:
        channel_runtime = build_channel_runtime(settings=resolved)
    except Exception as exc:
        log.warning("channel runtime bootstrap failed, using in-memory fallback: %s", exc)
        channel_runtime = ChannelRuntimeService(
            observations=InMemoryObservationEventRepository(),
            outbox=InMemoryDeliveryOutboxRepository(),
        )
    return AppContainer(
        settings=resolved,
        orchestrator=orchestrator,
        channel_runtime=channel_runtime,
        readiness=ReadinessService(resolved),
    )
