from __future__ import annotations

import logging
from typing import Any

from app.domain.models import (
    IntentSpecV3,
    TaskContract,
    TaskContractPolicyRecord,
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
        "brain_profile": str(policy.brain_profile or ""),
        "posthoc_review_profile": str(policy.posthoc_review_profile or ""),
        "posthoc_review_required": bool(policy.posthoc_review_required),
        "fallback_brain_profile": str(policy.fallback_brain_profile or ""),
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
    if str(policy.pre_artifact_capability_key or "").strip():
        metadata["pre_artifact_capability_key"] = str(policy.pre_artifact_capability_key).strip()
    return metadata


class TaskContractService:
    def __init__(self, repo: TaskContractRepository) -> None:
        self._repo = repo

    def _has_meaningful_policy_keys(self, payload: dict[str, object] | None) -> bool:
        return any(str(key or "").strip() not in {"", "class"} for key in dict(payload or {}))

    def _canonical_policy_payloads(
        self,
        *,
        budget_policy_json: dict[str, object] | None = None,
        runtime_policy_json: dict[str, object] | None = None,
        runtime_policy: TaskContractRuntimePolicy | None = None,
    ) -> tuple[dict[str, object], dict[str, Any]]:
        legacy_budget_payload = dict(budget_policy_json or {})
        runtime_payload = dict(runtime_policy_json or {})
        if runtime_policy is not None:
            parsed_policy = runtime_policy
        else:
            parsed_policy = parse_task_contract_runtime_policy(
                legacy_budget_payload,
                runtime_payload,
            )
        canonical_runtime_payload = serialize_task_contract_runtime_policy(parsed_policy)
        runtime_budget_class = str(
            parsed_policy.budget_class
            or legacy_budget_payload.get("class")
            or canonical_runtime_payload.get("class")
            or "low"
        ).strip() or "low"
        legacy_budget_class = str(
            legacy_budget_payload.get("class")
            or runtime_budget_class
            or "low"
        ).strip() or "low"
        if self._has_meaningful_policy_keys(legacy_budget_payload):
            legacy_budget_out = dict(legacy_budget_payload)
            legacy_budget_out["class"] = legacy_budget_class
        elif runtime_policy is not None or self._has_meaningful_policy_keys(runtime_payload):
            legacy_budget_out = {"class": runtime_budget_class}
        elif legacy_budget_payload:
            legacy_budget_out = dict(legacy_budget_payload)
            legacy_budget_out["class"] = legacy_budget_class
        else:
            legacy_budget_out = {"class": runtime_budget_class}
        return legacy_budget_out, canonical_runtime_payload

    def _builtin_contract(self, task_key: str) -> TaskContract | None:
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
                runtime_policy_json={
                    "workflow_template": "rewrite",
                    "brain_profile": "easy",
                    "posthoc_review_profile": "review_light",
                    "posthoc_review_required": False,
                    "fallback_brain_profile": "survival",
                    "skill_catalog_json": {
                        "skill_key": "rewrite_text",
                        "name": "rewrite text",
                        "description": "Cheap-smart default rewrite contract.",
                        "model_policy_json": {
                            "brain_profile": "easy",
                            "posthoc_review_profile": "review_light",
                            "fallback_brain_profile": "survival",
                        },
                    },
                },
            )
        if normalized in {
            "meeting_prep",
            "decision_briefing",
            "stakeholder_briefing",
            "deadline_briefing",
            "commitment_briefing",
            "reflection_brief",
            "replan_brief",
        }:
            deliverable_type = {
                "meeting_prep": "meeting_brief",
                "decision_briefing": "decision_brief",
                "stakeholder_briefing": "stakeholder_briefing",
                "deadline_briefing": "deadline_brief",
                "commitment_briefing": "commitment_brief",
                "reflection_brief": "reflection_brief",
                "replan_brief": "replan_brief",
            }[normalized]
            return TaskContract(
                task_key=normalized,
                deliverable_type=deliverable_type,
                default_risk_class="low",
                default_approval_class="none",
                allowed_tools=(
                    "provider.gemini_vortex.structured_generate",
                    "provider.magixai.structured_generate",
                    "browseract.chatplayground_audit",
                    "artifact_repository",
                ),
                evidence_requirements=(),
                memory_write_policy="reviewed_only",
                budget_policy_json={"class": "low"},
                updated_at=now_utc_iso(),
                runtime_policy_json={
                    "workflow_template": "tool_then_artifact",
                    "pre_artifact_capability_key": "structured_generate",
                    "brain_profile": "groundwork",
                    "posthoc_review_profile": "review_light",
                    "posthoc_review_required": False,
                    "fallback_brain_profile": "survival",
                    "artifact_output_template": "groundwork_brief",
                    "skill_catalog_json": {
                        "skill_key": normalized,
                        "name": normalized.replace("_", " "),
                        "description": "Groundwork-first briefing contract.",
                        "output_schema_json": {
                            "type": "object",
                            "required": [
                                "plan",
                                "risks",
                                "missing_evidence",
                                "recommended_next_lane",
                                "acceptance_checklist",
                            ],
                        },
                        "model_policy_json": {
                            "brain_profile": "groundwork",
                            "posthoc_review_profile": "review_light",
                            "fallback_brain_profile": "survival",
                        },
                    },
                },
            )
        return None

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
        runtime_policy_json: dict[str, object] | None = None,
        runtime_policy: TaskContractRuntimePolicy | None = None,
    ) -> TaskContract:
        policy_payload, typed_policy_payload = self._canonical_policy_payloads(
            budget_policy_json=budget_policy_json,
            runtime_policy_json=runtime_policy_json,
            runtime_policy=runtime_policy,
        )
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
            runtime_policy_json=typed_policy_payload,
        )
        return self._repo.upsert(row)

    def get_contract(self, task_key: str) -> TaskContract | None:
        found = self._repo.get(task_key)
        if found is not None:
            return found
        return self._builtin_contract(task_key)

    def contract_to_policy_record(self, contract: TaskContract) -> TaskContractPolicyRecord:
        runtime_policy = contract.runtime_policy()
        return TaskContractPolicyRecord(
            task_key=contract.task_key,
            deliverable_type=contract.deliverable_type,
            default_risk_class=contract.default_risk_class,
            default_approval_class=contract.default_approval_class,
            allowed_tools=tuple(contract.allowed_tools or ()),
            evidence_requirements=tuple(contract.evidence_requirements or ()),
            memory_write_policy=contract.memory_write_policy,
            runtime_policy=runtime_policy,
            updated_at=contract.updated_at,
        )

    def get_policy_record(self, task_key: str) -> TaskContractPolicyRecord | None:
        contract = self.get_contract(task_key)
        if contract is None:
            return None
        return self.contract_to_policy_record(contract)

    def get_contract_or_raise(self, task_key: str) -> TaskContract:
        found = self.get_contract(task_key)
        if found is not None:
            return found
        normalized = str(task_key or "").strip() or "unknown"
        raise ValueError(f"task_contract_not_found:{normalized}")

    def list_contracts(self, limit: int = 100) -> list[TaskContract]:
        return self._repo.list_all(limit=limit)

    def list_policy_records(self, limit: int = 100) -> list[TaskContractPolicyRecord]:
        return [self.contract_to_policy_record(contract) for contract in self.list_contracts(limit=limit)]

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
