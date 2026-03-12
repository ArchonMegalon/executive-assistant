from __future__ import annotations

from typing import Any

from app.domain.models import (
    SkillContract,
    TaskContract,
    TaskContractRuntimePolicy,
    TaskContractSkillCatalogPolicy,
    parse_task_contract_runtime_policy,
)
from app.services.task_contracts import TaskContractService


def _collect_string_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        normalized = str(value or "").strip()
        return (normalized,) if normalized else ()
    if isinstance(value, dict):
        collected: list[str] = []
        for nested in value.values():
            collected.extend(_collect_string_values(nested))
        return tuple(collected)
    if isinstance(value, (list, tuple, set)):
        collected: list[str] = []
        for nested in value:
            collected.extend(_collect_string_values(nested))
        return tuple(collected)
    return ()


def _title_from_key(value: str) -> str:
    parts = [part for part in str(value or "").replace("-", "_").split("_") if part]
    if not parts:
        return "Unnamed Skill"
    return " ".join(part.capitalize() for part in parts)


class SkillCatalogService:
    def __init__(self, task_contracts: TaskContractService) -> None:
        self._task_contracts = task_contracts

    def _skill_meta(self, contract: TaskContract) -> TaskContractSkillCatalogPolicy:
        return contract.runtime_policy().skill_catalog

    def _workflow_template(self, contract: TaskContract) -> str:
        return str(contract.runtime_policy().workflow_template or "rewrite").strip() or "rewrite"

    def _derive_input_schema(self, contract: TaskContract) -> dict[str, Any]:
        policy = contract.runtime_policy()
        workflow_template = self._workflow_template(contract)
        pre_artifact_tool_name = str(policy.pre_artifact_tool_name or "").strip()
        if workflow_template == "browseract_extract_then_artifact" or (
            workflow_template == "tool_then_artifact"
            and pre_artifact_tool_name in {"browseract.extract_account_facts", "browseract.extract_account_inventory"}
        ):
            required = ["binding_id", "service_name"]
            if pre_artifact_tool_name == "browseract.extract_account_inventory":
                required = ["binding_id"]
            return {
                "type": "object",
                "properties": {
                    "binding_id": {"type": "string"},
                    "service_name": {"type": "string"},
                    "service_names": {"type": "array", "items": {"type": "string"}},
                    "requested_fields": {"type": "array", "items": {"type": "string"}},
                    "run_url": {"type": "string"},
                    "instructions": {"type": "string"},
                    "account_hints_json": {"type": "object"},
                },
                "required": required,
            }
        return {
            "type": "object",
            "properties": {
                "source_text": {"type": "string"},
            },
            "required": ["source_text"],
        }

    def _derive_output_schema(self, contract: TaskContract) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "deliverable_type": {"const": contract.deliverable_type},
                "artifact_kind": {"type": "string"},
            },
            "required": ["deliverable_type"],
        }

    def _derive_memory_writes(self, contract: TaskContract) -> tuple[str, ...]:
        if str(contract.memory_write_policy or "none").strip() == "none":
            return ()
        category = str(contract.runtime_policy().memory_candidate.category or "").strip()
        if category:
            return (category,)
        return (contract.memory_write_policy,)

    def _derive_human_policy(self, contract: TaskContract) -> dict[str, Any]:
        human_review = contract.runtime_policy().human_review
        if not str(human_review.role or "").strip():
            return {}
        return {
            "role_required": str(human_review.role or "").strip(),
            "task_type": str(human_review.task_type or "").strip(),
            "priority": str(human_review.priority or "").strip(),
            "sla_minutes": int(human_review.sla_minutes),
            "authority_required": str(human_review.authority_required or "").strip(),
        }

    def contract_to_skill(self, contract: TaskContract) -> SkillContract:
        meta = self._skill_meta(contract)
        workflow_template = self._workflow_template(contract)
        skill_key = str(meta.skill_key or contract.task_key).strip() or contract.task_key
        input_schema_json = dict(meta.input_schema_json or {}) or self._derive_input_schema(contract)
        output_schema_json = dict(meta.output_schema_json or {}) or self._derive_output_schema(contract)
        authority_profile_json = dict(meta.authority_profile_json or {}) or {
            "default_approval_class": contract.default_approval_class,
            "workflow_template": workflow_template,
        }
        provider_hints_json = dict(meta.provider_hints_json or {})
        tool_policy_json = dict(meta.tool_policy_json or {}) or {
            "allowed_tools": list(contract.allowed_tools),
        }
        human_policy_json = dict(meta.human_policy_json or {}) or self._derive_human_policy(contract)
        return SkillContract(
            skill_key=skill_key,
            task_key=contract.task_key,
            name=str(meta.name or _title_from_key(skill_key)).strip() or _title_from_key(skill_key),
            description=str(meta.description or f"Skill wrapper for task contract `{contract.task_key}`.").strip(),
            deliverable_type=contract.deliverable_type,
            default_risk_class=contract.default_risk_class,
            default_approval_class=contract.default_approval_class,
            workflow_template=workflow_template,
            allowed_tools=tuple(contract.allowed_tools or ()),
            evidence_requirements=tuple(contract.evidence_requirements or ()),
            memory_write_policy=contract.memory_write_policy,
            memory_reads=tuple(meta.memory_reads or ()) or tuple(contract.evidence_requirements or ()),
            memory_writes=tuple(meta.memory_writes or ()) or self._derive_memory_writes(contract),
            tags=tuple(meta.tags or ()) or (workflow_template, contract.deliverable_type),
            input_schema_json=input_schema_json,
            output_schema_json=output_schema_json,
            authority_profile_json=authority_profile_json,
            model_policy_json=dict(meta.model_policy_json or {}),
            provider_hints_json=provider_hints_json,
            tool_policy_json=tool_policy_json,
            human_policy_json=human_policy_json,
            evaluation_cases_json=tuple(dict(value) for value in meta.evaluation_cases_json),
            updated_at=contract.updated_at,
        )

    def upsert_skill(
        self,
        *,
        skill_key: str,
        task_key: str = "",
        name: str,
        description: str = "",
        deliverable_type: str,
        default_risk_class: str = "low",
        default_approval_class: str = "none",
        workflow_template: str = "rewrite",
        allowed_tools: tuple[str, ...] = (),
        evidence_requirements: tuple[str, ...] = (),
        memory_write_policy: str = "reviewed_only",
        memory_reads: tuple[str, ...] = (),
        memory_writes: tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
        input_schema_json: dict[str, Any] | None = None,
        output_schema_json: dict[str, Any] | None = None,
        authority_profile_json: dict[str, Any] | None = None,
        model_policy_json: dict[str, Any] | None = None,
        provider_hints_json: dict[str, Any] | None = None,
        tool_policy_json: dict[str, Any] | None = None,
        human_policy_json: dict[str, Any] | None = None,
        evaluation_cases_json: tuple[dict[str, Any], ...] = (),
        budget_policy_json: dict[str, Any] | None = None,
    ) -> SkillContract:
        resolved_task_key = str(task_key or skill_key).strip() or str(skill_key or "").strip()
        base_policy = parse_task_contract_runtime_policy(dict(budget_policy_json or {}))
        runtime_policy = TaskContractRuntimePolicy(
            budget_class=base_policy.budget_class,
            workflow_template=str(workflow_template or "rewrite").strip() or "rewrite",
            pre_artifact_tool_name=base_policy.pre_artifact_tool_name,
            browseract_timeout_budget_seconds=base_policy.browseract_timeout_budget_seconds,
            post_artifact_packs=base_policy.post_artifact_packs,
            artifact_retry=base_policy.artifact_retry,
            dispatch_retry=base_policy.dispatch_retry,
            browseract_retry=base_policy.browseract_retry,
            human_review=base_policy.human_review,
            memory_candidate=base_policy.memory_candidate,
            artifact_output=base_policy.artifact_output,
            skill_catalog=TaskContractSkillCatalogPolicy(
                skill_key=str(skill_key or resolved_task_key).strip() or resolved_task_key,
                name=str(name or "").strip(),
                description=str(description or "").strip(),
                memory_reads=tuple(memory_reads),
                memory_writes=tuple(memory_writes),
                tags=tuple(tags),
                input_schema_json=dict(input_schema_json or {}),
                output_schema_json=dict(output_schema_json or {}),
                authority_profile_json=dict(authority_profile_json or {}),
                model_policy_json=dict(model_policy_json or {}),
                provider_hints_json=dict(provider_hints_json or {}),
                tool_policy_json=dict(tool_policy_json or {}),
                human_policy_json=dict(human_policy_json or {}),
                evaluation_cases_json=tuple(dict(value) for value in evaluation_cases_json),
            ),
        )
        contract = self._task_contracts.upsert_contract(
            task_key=resolved_task_key,
            deliverable_type=deliverable_type,
            default_risk_class=default_risk_class,
            default_approval_class=default_approval_class,
            allowed_tools=allowed_tools,
            evidence_requirements=evidence_requirements,
            memory_write_policy=memory_write_policy,
            budget_policy_json=budget_policy_json,
            runtime_policy=runtime_policy,
        )
        return self.contract_to_skill(contract)

    def get_skill(self, skill_key: str) -> SkillContract | None:
        resolved = str(skill_key or "").strip()
        if not resolved:
            return None
        direct = self._task_contracts.get_contract(resolved)
        if direct is not None:
            return self.contract_to_skill(direct)
        for contract in self._task_contracts.list_contracts(limit=500):
            if self.contract_to_skill(contract).skill_key == resolved:
                return self.contract_to_skill(contract)
        return None

    def list_skills(self, limit: int = 100, provider_hint: str = ""):
        normalized_provider_hint = str(provider_hint or "").strip().lower()
        fetch_limit = 500 if normalized_provider_hint else limit
        rows = [self.contract_to_skill(contract) for contract in self._task_contracts.list_contracts(limit=fetch_limit)]
        if normalized_provider_hint:
            rows = [
                row
                for row in rows
                if any(
                    normalized_provider_hint in candidate.lower()
                    for candidate in _collect_string_values(row.provider_hints_json)
                )
            ]
        return rows[:limit]
