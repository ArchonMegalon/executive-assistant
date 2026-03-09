from __future__ import annotations

import logging
from dataclasses import dataclass
from app.repositories.artifacts import InMemoryArtifactRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.commitments import InMemoryCommitmentRepository
from app.repositories.communication_policies import InMemoryCommunicationPolicyRepository
from app.repositories.decision_windows import InMemoryDecisionWindowRepository
from app.repositories.deadline_windows import InMemoryDeadlineWindowRepository
from app.repositories.delivery_outbox import InMemoryDeliveryOutboxRepository
from app.repositories.delivery_preferences import InMemoryDeliveryPreferenceRepository
from app.repositories.entities import InMemoryEntityRepository
from app.repositories.evidence_objects import InMemoryEvidenceObjectRepository
from app.repositories.follow_ups import InMemoryFollowUpRepository
from app.repositories.follow_up_rules import InMemoryFollowUpRuleRepository
from app.repositories.interruption_budgets import InMemoryInterruptionBudgetRepository
from app.repositories.authority_bindings import InMemoryAuthorityBindingRepository
from app.repositories.memory_candidates import InMemoryMemoryCandidateRepository
from app.repositories.memory_items import InMemoryMemoryItemRepository
from app.repositories.observation import InMemoryObservationEventRepository
from app.repositories.relationships import InMemoryRelationshipRepository
from app.repositories.stakeholders import InMemoryStakeholderRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.channel_runtime import ChannelRuntimeService, build_channel_runtime
from app.services.evidence_runtime import EvidenceRuntimeService, build_evidence_runtime
from app.services.memory_runtime import MemoryRuntimeService, build_memory_runtime
from app.services.orchestrator import RewriteOrchestrator, build_artifact_repo, build_default_orchestrator
from app.services.planner import PlannerService
from app.services.policy import PolicyDecisionService
from app.services.skills import SkillCatalogService
from app.services.task_contracts import TaskContractService, build_task_contract_service
from app.services.tool_execution import ToolExecutionService
from app.services.tool_runtime import ToolRuntimeService, build_tool_runtime
from app.settings import Settings, ensure_storage_fallback_allowed, get_settings


class ReadinessService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check(self) -> tuple[bool, str]:
        backend = str(self._settings.storage.backend or "auto").strip().lower()
        if self._settings.runtime.mode == "prod":
            if backend != "postgres":
                return False, "prod_requires_postgres_backend"
            if not self._settings.database_url:
                return False, "database_url_missing"
            return self._probe_database()
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
    tool_runtime: ToolRuntimeService
    tool_execution: ToolExecutionService
    evidence_runtime: EvidenceRuntimeService
    memory_runtime: MemoryRuntimeService
    task_contracts: TaskContractService
    skills: SkillCatalogService
    planner: PlannerService
    readiness: ReadinessService


def build_container(settings: Settings | None = None) -> AppContainer:
    resolved = settings or get_settings()
    log = logging.getLogger("ea.container")
    try:
        artifacts = build_artifact_repo(resolved)
    except Exception as exc:
        ensure_storage_fallback_allowed(resolved, "artifact repo bootstrap", exc)
        log.warning("artifact repo bootstrap failed, using in-memory fallback: %s", exc)
        artifacts = InMemoryArtifactRepository()
    try:
        task_contracts = build_task_contract_service(settings=resolved)
    except Exception as exc:
        ensure_storage_fallback_allowed(resolved, "task-contract bootstrap", exc)
        log.warning("task-contract bootstrap failed, using in-memory fallback: %s", exc)
        from app.repositories.task_contracts import InMemoryTaskContractRepository

        task_contracts = TaskContractService(InMemoryTaskContractRepository())
    planner = PlannerService(task_contracts)
    skills = SkillCatalogService(task_contracts)
    try:
        channel_runtime = build_channel_runtime(settings=resolved)
    except Exception as exc:
        ensure_storage_fallback_allowed(resolved, "channel runtime bootstrap", exc)
        log.warning("channel runtime bootstrap failed, using in-memory fallback: %s", exc)
        channel_runtime = ChannelRuntimeService(
            observations=InMemoryObservationEventRepository(),
            outbox=InMemoryDeliveryOutboxRepository(),
        )
    try:
        memory_runtime = build_memory_runtime(settings=resolved)
    except Exception as exc:
        ensure_storage_fallback_allowed(resolved, "memory runtime bootstrap", exc)
        log.warning("memory runtime bootstrap failed, using in-memory fallback: %s", exc)
        memory_runtime = MemoryRuntimeService(
            candidates=InMemoryMemoryCandidateRepository(),
            items=InMemoryMemoryItemRepository(),
            entities=InMemoryEntityRepository(),
            relationships=InMemoryRelationshipRepository(),
            commitments=InMemoryCommitmentRepository(),
            communication_policies=InMemoryCommunicationPolicyRepository(),
            decision_windows=InMemoryDecisionWindowRepository(),
            deadline_windows=InMemoryDeadlineWindowRepository(),
            stakeholders=InMemoryStakeholderRepository(),
            authority_bindings=InMemoryAuthorityBindingRepository(),
            delivery_preferences=InMemoryDeliveryPreferenceRepository(),
            follow_ups=InMemoryFollowUpRepository(),
            follow_up_rules=InMemoryFollowUpRuleRepository(),
            interruption_budgets=InMemoryInterruptionBudgetRepository(),
        )
    try:
        evidence_runtime = build_evidence_runtime(settings=resolved)
    except Exception as exc:
        ensure_storage_fallback_allowed(resolved, "evidence runtime bootstrap", exc)
        log.warning("evidence runtime bootstrap failed, using in-memory fallback: %s", exc)
        evidence_runtime = EvidenceRuntimeService(InMemoryEvidenceObjectRepository())
    try:
        tool_runtime = build_tool_runtime(settings=resolved)
    except Exception as exc:
        ensure_storage_fallback_allowed(resolved, "tool runtime bootstrap", exc)
        log.warning("tool runtime bootstrap failed, using in-memory fallback: %s", exc)
        tool_runtime = ToolRuntimeService(
            tool_registry=InMemoryToolRegistryRepository(),
            connector_bindings=InMemoryConnectorBindingRepository(),
        )
    tool_execution = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=artifacts,
        channel_runtime=channel_runtime,
        evidence_runtime=evidence_runtime,
    )
    try:
        orchestrator = build_default_orchestrator(
            settings=resolved,
            artifacts=artifacts,
            task_contracts=task_contracts,
            planner=planner,
            evidence_runtime=evidence_runtime,
            memory_runtime=memory_runtime,
            tool_execution=tool_execution,
        )
    except Exception as exc:
        ensure_storage_fallback_allowed(resolved, "orchestrator bootstrap", exc)
        log.warning("orchestrator bootstrap failed, using in-memory fallback: %s", exc)
        orchestrator = RewriteOrchestrator(
            artifacts=artifacts,
            policy=PolicyDecisionService(
                max_rewrite_chars=resolved.policy.max_rewrite_chars,
                approval_required_chars=resolved.policy.approval_required_chars,
            ),
            task_contracts=task_contracts,
            planner=planner,
            memory_runtime=memory_runtime,
            tool_execution=tool_execution,
        )
    return AppContainer(
        settings=resolved,
        orchestrator=orchestrator,
        channel_runtime=channel_runtime,
        tool_runtime=tool_runtime,
        tool_execution=tool_execution,
        evidence_runtime=evidence_runtime,
        memory_runtime=memory_runtime,
        task_contracts=task_contracts,
        skills=skills,
        planner=planner,
        readiness=ReadinessService(resolved),
    )
