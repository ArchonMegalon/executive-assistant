from __future__ import annotations

import logging
from typing import Any

from app.domain.models import (
    IntentSpecV3,
    TaskContract,
    TaskContractRuntimePolicy,
    TaskContractSkillCatalogPolicy,
    now_utc_iso,
    parse_task_contract_runtime_policy,
)
from app.repositories.task_contracts import InMemoryTaskContractRepository, TaskContractRepository
from app.repositories.task_contracts_postgres import PostgresTaskContractRepository
from app.settings import Settings, ensure_storage_fallback_allowed, get_settings


def serialize_task_contract_runtime_policy(policy: TaskContractRuntimePolicy) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "class": str(policy.budget_class or "low"),
        "workflow_template": str(policy.workflow_template or "rewrite"),
        "browseract_timeout_budget_seconds": int(policy.browseract_timeout_budget_seconds),
        "post_artifact_packs": list(policy.post_artifact_packs or ()),
        "artifact_failure_strategy": policy.artifact_retry.failure_strategy,
        "artifact_max_attempts": int(policy.artifact_retry.max_attempts),
        "artifact_retry_backoff_seconds": int(policy.artifact_retry.retry_backoff_seconds),
        "dispatch_failure_strategy": policy.dispatch_retry.failure_strategy,
        "dispatch_max_attempts": int(policy.dispatch_retry.max_attempts),
        "dispatch_retry_backoff_seconds": int(policy.dispatch_retry.retry_backoff_seconds),
        "browseract_failure_strategy": policy.browseract_retry.failure_strategy,
        "browseract_max_attempts": int(policy.browseract_retry.max_attempts),
        "browseract_retry_backoff_seconds": int(policy.browseract_retry.retry_backoff_seconds),
        "human_review_role": str(policy.human_review.role or ""),
        "human_review_task_type": str(policy.human_review.task_type or ""),
        "human_review_brief": str(policy.human_review.brief or ""),
        "human_review_priority": str(policy.human_review.priority or ""),
        "human_review_sla_minutes": int(policy.human_review.sla_minutes),
        "human_review_auto_assign_if_unique": bool(policy.human_review.auto_assign_if_unique),
        "human_review_desired_output_json": dict(policy.human_review.desired_output_json or {}),
        "human_review_authority_required": str(policy.human_review.authority_required or ""),
        "human_review_why_human": str(policy.human_review.why_human or ""),
        "human_review_quality_rubric_json": dict(policy.human_review.quality_rubric_json or {}),
        "memory_candidate_category": str(policy.memory_candidate.category or ""),
        "memory_candidate_sensitivity": str(policy.memory_candidate.sensitivity or ""),
        "memory_candidate_confidence": float(policy.memory_candidate.confidence),
        "artifact_output_template": str(policy.artifact_output.template or ""),
        "evidence_pack_confidence": float(policy.artifact_output.default_confidence),
        "skill_catalog_json": {
            "skill_key": str(policy.skill_catalog.skill_key or ""),
            "name": str(policy.skill_catalog.name or ""),
            "description": str(policy.skill_catalog.description or ""),
            "memory_reads": list(policy.skill_catalog.memory_reads or ()),
            "memory_writes": list(policy.skill_catalog.memory_writes or ()),
            "tags": list(policy.skill_catalog.tags or ()),
            "input_schema_json": dict(policy.skill_catalog.input_schema_json or {}),
            "output_schema_json": dict(policy.skill_catalog.output_schema_json or {}),
            "authority_profile_json": dict(policy.skill_catalog.authority_profile_json or {}),
            "model_policy_json": dict(policy.skill_catalog.model_policy_json or {}),
            "provider_hints_json": dict(policy.skill_catalog.provider_hints_json or {}),
            "tool_policy_json": dict(policy.skill_catalog.tool_policy_json or {}),
            "human_policy_json": dict(policy.skill_catalog.human_policy_json or {}),
            "evaluation_cases_json": [dict(value) for value in policy.skill_catalog.evaluation_cases_json],
        },
    }
    if str(policy.pre_artifact_tool_name or "").strip():
        metadata["pre_artifact_tool_name"] = str(policy.pre_artifact_tool_name).strip()
    return metadata


class TaskContractService:
    def __init__(self, repo: TaskContractRepository) -> None:
        self._repo = repo

    def _require_principal_id(self, principal_id: str) -> str:
        resolved = str(principal_id or "").strip()
        if resolved:
            return resolved
        raise ValueError("principal_id_required")

    def upsert_contract(
        self,
        *,
        task_key: str,
        deliverable_type: str,
        default_risk_class: str,
        default_approval_class: str,
        allowed_tools: tuple[str, ...] = (),
        evidence_requirements: tuple[str, ...] = (),
        memory_write_policy: str = "reviewed_only",
        budget_policy_json: dict[str, object] | None = None,
        runtime_policy: TaskContractRuntimePolicy | None = None,
    ) -> TaskContract:
        policy_payload = dict(budget_policy_json or {})
        if runtime_policy is not None:
            policy_payload.update(serialize_task_contract_runtime_policy(runtime_policy))
        row = TaskContract(
            task_key=str(task_key or "").strip(),
            deliverable_type=str(deliverable_type or ""),
            default_risk_class=str(default_risk_class or "low"),
            default_approval_class=str(default_approval_class or "none"),
            allowed_tools=tuple(str(v) for v in allowed_tools),
            evidence_requirements=tuple(str(v) for v in evidence_requirements),
            memory_write_policy=str(memory_write_policy or "reviewed_only"),
            budget_policy_json=policy_payload,
            updated_at=now_utc_iso(),
        )
        return self._repo.upsert(row)

    def get_contract(self, task_key: str) -> TaskContract | None:
        return self._repo.get(task_key)

    def get_contract_or_raise(self, task_key: str) -> TaskContract:
        found = self._repo.get(task_key)
        if found is not None:
            return found
        normalized = str(task_key or "").strip() or "unknown"
        if normalized == "rewrite_text":
            return TaskContract(
                task_key="rewrite_text",
                deliverable_type="rewrite_note",
                default_risk_class="low",
                default_approval_class="none",
                allowed_tools=("artifact_repository",),
                evidence_requirements=(),
                memory_write_policy="reviewed_only",
                budget_policy_json={"class": "low"},
                updated_at=now_utc_iso(),
            )
        raise ValueError(f"task_contract_not_found:{normalized}")

    def list_contracts(self, limit: int = 100) -> list[TaskContract]:
        return self._repo.list_all(limit=limit)

    def contract_or_default(self, task_key: str) -> TaskContract:
        return self.get_contract_or_raise(task_key)

    def compile_rewrite_intent(
        self,
        principal_id: str,
        *,
        goal: str = "rewrite supplied text into an artifact",
    ) -> IntentSpecV3:
        contract = self.contract_or_default("rewrite_text")
        budget_class = str(contract.runtime_policy().budget_class or "low")
        return IntentSpecV3(
            principal_id=self._require_principal_id(principal_id),
            goal=str(goal or "rewrite supplied text into an artifact"),
            task_type=contract.task_key,
            deliverable_type=contract.deliverable_type,
            risk_class=contract.default_risk_class,
            approval_class=contract.default_approval_class,
            budget_class=budget_class,
            allowed_tools=contract.allowed_tools,
            evidence_requirements=contract.evidence_requirements,
            desired_artifact=contract.deliverable_type,
            memory_write_policy=contract.memory_write_policy,
        )


def _backend_mode(settings: Settings) -> str:
    return str(settings.storage.backend or "auto").strip().lower()


def build_task_contract_repo(settings: Settings) -> TaskContractRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.task_contracts")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "task contracts configured for memory")
        return InMemoryTaskContractRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresTaskContractRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresTaskContractRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "task contracts auto fallback", exc)
            log.warning("postgres task-contract backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "task contracts auto backend without DATABASE_URL")
    return InMemoryTaskContractRepository()


def build_task_contract_service(settings: Settings | None = None) -> TaskContractService:
    resolved = settings or get_settings()
    return TaskContractService(build_task_contract_repo(resolved))
