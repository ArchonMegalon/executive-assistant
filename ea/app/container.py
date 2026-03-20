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
from app.repositories.provider_bindings import build_provider_binding_service_repo
from app.repositories.stakeholders import InMemoryStakeholderRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.brain_router import BrainRouterService
from app.services.cognitive_load import CognitiveLoadService
from app.services.channel_runtime import ChannelRuntimeService, build_channel_runtime
from app.services.evidence_runtime import EvidenceRuntimeService, build_evidence_runtime
from app.services.memory_runtime import MemoryRuntimeService, build_memory_runtime
from app.services.orchestrator import RewriteOrchestrator, build_artifact_repo, build_default_orchestrator
from app.services.onboarding import OnboardingService, build_onboarding_service
from app.services.planner import PlannerService
from app.services.policy import PolicyDecisionService
from app.services.proactive_horizon import ProactiveHorizonService
from app.services.provider_registry import ProviderRegistryService
from app.services.skills import SkillCatalogService
from app.services.task_contracts import TaskContractService, build_task_contract_service
from app.services.tool_execution import ToolExecutionService
from app.services.tool_runtime import ToolRuntimeService, build_tool_runtime
from app.settings import (
    RuntimeProfile,
    Settings,
    ensure_storage_fallback_allowed,
    ensure_prod_api_token_configured,
    get_settings,
    settings_with_storage_backend,
    validate_startup_settings,
)


def _database_url(settings: Settings) -> str:
    direct = getattr(settings, "database_url", None)
    if direct is not None:
        value = str(direct or "").strip()
        if value:
            return value
    storage = getattr(settings, "storage", None)
    if storage is None:
        return str(direct or "").strip()
    return str(getattr(storage, "database_url", "") or "").strip()


class ReadinessService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check(self) -> tuple[bool, str]:
        try:
            profile = validate_startup_settings(self._settings)
        except RuntimeError as exc:
            message = str(exc)
            if "EA_API_TOKEN" in message:
                return False, "prod_api_token_missing"
            if "DATABASE_URL" in message:
                return False, "database_url_missing"
            return False, "startup_validation_failed"
        if profile.storage_backend == "memory":
            if str(self._settings.storage.backend or "").strip().lower() == "memory":
                return True, "memory_ready"
            return True, "auto_memory_ready"
        if not _database_url(self._settings):
            return False, "database_url_missing"
        return self._probe_database()

    def _probe_database(self) -> tuple[bool, str]:
        try:
            import psycopg
        except Exception:
            return False, "psycopg_missing"
        try:
            with psycopg.connect(_database_url(self._settings), autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    _ = cur.fetchone()
            return True, "postgres_ready"
        except Exception as exc:
            return False, f"postgres_unavailable:{exc.__class__.__name__}"


@dataclass(frozen=True)
class AppContainer:
    settings: Settings
    runtime_profile: RuntimeProfile
    orchestrator: RewriteOrchestrator
    channel_runtime: ChannelRuntimeService
    tool_runtime: ToolRuntimeService
    tool_execution: ToolExecutionService
    evidence_runtime: EvidenceRuntimeService
    memory_runtime: MemoryRuntimeService
    task_contracts: TaskContractService
    skills: SkillCatalogService
    planner: PlannerService
    provider_registry: ProviderRegistryService
    brain_router: BrainRouterService
    cognitive_load: CognitiveLoadService
    proactive_horizon: ProactiveHorizonService
    onboarding: OnboardingService
    readiness: ReadinessService


def _build_container_for_settings(settings: Settings, profile: RuntimeProfile) -> AppContainer:
    provider_registry = ProviderRegistryService(provider_binding_repo=build_provider_binding_service_repo(settings))
    brain_router = BrainRouterService(provider_registry=provider_registry)
    artifacts = build_artifact_repo(settings)
    task_contracts = build_task_contract_service(settings=settings)
    planner = PlannerService(task_contracts, provider_registry=provider_registry, brain_router=brain_router)
    skills = SkillCatalogService(task_contracts)
    policy = PolicyDecisionService(
        max_rewrite_chars=settings.policy.max_rewrite_chars,
        approval_required_chars=settings.policy.approval_required_chars,
    )
    try:
        channel_runtime = build_channel_runtime(
            settings=settings,
            policy=policy,
        )
    except Exception as exc:
        ensure_storage_fallback_allowed(settings, "channel runtime bootstrap", exc)
        raise
    try:
        memory_runtime = build_memory_runtime(settings=settings)
    except Exception as exc:
        ensure_storage_fallback_allowed(settings, "memory runtime bootstrap", exc)
        raise
    cognitive_load = CognitiveLoadService(
        count_recent_for_principal=channel_runtime.count_recent_observations_for_principal,
        memory_runtime=memory_runtime,
    )
    channel_runtime._cognitive_load = cognitive_load  # type: ignore[attr-defined]
    channel_runtime._policy = policy  # type: ignore[attr-defined]
    evidence_runtime = build_evidence_runtime(settings=settings)
    tool_runtime = build_tool_runtime(settings=settings)
    tool_execution = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=artifacts,
        channel_runtime=channel_runtime,
        evidence_runtime=evidence_runtime,
        provider_registry=provider_registry,
    )
    orchestrator = build_default_orchestrator(
        settings=settings,
        artifacts=artifacts,
        task_contracts=task_contracts,
        skills=skills,
        planner=planner,
        evidence_runtime=evidence_runtime,
        memory_runtime=memory_runtime,
        provider_registry=provider_registry,
        tool_execution=tool_execution,
    )
    proactive_horizon = ProactiveHorizonService(
        memory_runtime=memory_runtime,
        orchestrator=orchestrator,
        task_contracts=task_contracts,
        channel_runtime=channel_runtime,
    )
    onboarding = build_onboarding_service(
        settings=settings,
        provider_registry=provider_registry,
        tool_runtime=tool_runtime,
    )
    return AppContainer(
        settings=settings,
        runtime_profile=profile,
        orchestrator=orchestrator,
        channel_runtime=channel_runtime,
        tool_runtime=tool_runtime,
        tool_execution=tool_execution,
        evidence_runtime=evidence_runtime,
        memory_runtime=memory_runtime,
        task_contracts=task_contracts,
        skills=skills,
        planner=planner,
        provider_registry=provider_registry,
        brain_router=brain_router,
        cognitive_load=cognitive_load,
        proactive_horizon=proactive_horizon,
        onboarding=onboarding,
        readiness=ReadinessService(settings),
    )


def build_container(settings: Settings | None = None) -> AppContainer:
    configured = settings or get_settings()
    profile = validate_startup_settings(configured)
    ensure_prod_api_token_configured(configured)
    log = logging.getLogger("ea.container")
    if profile.storage_backend == "memory":
        effective_settings = settings_with_storage_backend(configured, "memory")
        memory_profile = validate_startup_settings(effective_settings)
        return _build_container_for_settings(effective_settings, memory_profile)

    effective_settings = settings_with_storage_backend(configured, "postgres")
    postgres_profile = validate_startup_settings(effective_settings)
    try:
        return _build_container_for_settings(effective_settings, postgres_profile)
    except Exception as exc:
        if str(configured.storage.backend or "").strip().lower() == "auto" and configured.storage_fallback_allowed:
            log.warning("postgres runtime profile unavailable, switching whole container to memory: %s", exc)
            memory_settings = settings_with_storage_backend(configured, "memory")
            memory_profile = validate_startup_settings(memory_settings)
            return _build_container_for_settings(memory_settings, memory_profile)
        raise
