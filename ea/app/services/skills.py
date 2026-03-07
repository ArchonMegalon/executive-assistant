from __future__ import annotations

from typing import Any

from app.domain.models import SkillContract, TaskContract
from app.services.task_contracts import TaskContractService


def _as_string_tuple(values: object) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(str(value or "").strip() for value in values if str(value or "").strip())


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _as_json_object_tuple(values: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(_as_dict(value) for value in values)


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

    def _skill_meta(self, contract: TaskContract) -> dict[str, Any]:
        raw = dict(contract.budget_policy_json or {}).get("skill_catalog_json")
        if isinstance(raw, dict):
            return dict(raw)
        return {}

    def _workflow_template(self, contract: TaskContract) -> str:
        return str(dict(contract.budget_policy_json or {}).get("workflow_template") or "rewrite").strip() or "rewrite"

    def _derive_input_schema(self, contract: TaskContract) -> dict[str, Any]:
        workflow_template = self._workflow_template(contract)
        pre_artifact_tool_name = str(
            dict(contract.budget_policy_json or {}).get("pre_artifact_tool_name") or ""
        ).strip()
        if workflow_template in {"browseract_extract_then_artifact", "tool_then_artifact"} and (
            pre_artifact_tool_name == "browseract.extract_account_facts"
            or workflow_template == "browseract_extract_then_artifact"
        ):
            return {
                "type": "object",
                "properties": {
                    "binding_id": {"type": "string"},
                    "service_name": {"type": "string"},
                    "requested_fields": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["binding_id", "service_name"],
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
        category = str(dict(contract.budget_policy_json or {}).get("memory_candidate_category") or "").strip()
        if category:
            return (category,)
        return (contract.memory_write_policy,)

    def _derive_human_policy(self, contract: TaskContract) -> dict[str, Any]:
        budget = dict(contract.budget_policy_json or {})
        if not str(budget.get("human_review_role") or "").strip():
            return {}
        return {
            "role_required": str(budget.get("human_review_role") or "").strip(),
            "task_type": str(budget.get("human_review_task_type") or "").strip(),
            "priority": str(budget.get("human_review_priority") or "").strip(),
            "sla_minutes": int(budget.get("human_review_sla_minutes") or 0),
            "authority_required": str(budget.get("human_review_authority_required") or "").strip(),
        }

    def contract_to_skill(self, contract: TaskContract) -> SkillContract:
        meta = self._skill_meta(contract)
        workflow_template = self._workflow_template(contract)
        skill_key = str(meta.get("skill_key") or contract.task_key).strip() or contract.task_key
        input_schema_json = _as_dict(meta.get("input_schema_json")) or self._derive_input_schema(contract)
        output_schema_json = _as_dict(meta.get("output_schema_json")) or self._derive_output_schema(contract)
        authority_profile_json = _as_dict(meta.get("authority_profile_json")) or {
            "default_approval_class": contract.default_approval_class,
            "workflow_template": workflow_template,
        }
        provider_hints_json = _as_dict(meta.get("provider_hints_json"))
        tool_policy_json = _as_dict(meta.get("tool_policy_json")) or {
            "allowed_tools": list(contract.allowed_tools),
        }
        human_policy_json = _as_dict(meta.get("human_policy_json")) or self._derive_human_policy(contract)
        return SkillContract(
            skill_key=skill_key,
            task_key=contract.task_key,
            name=str(meta.get("name") or _title_from_key(skill_key)).strip() or _title_from_key(skill_key),
            description=str(meta.get("description") or f"Skill wrapper for task contract `{contract.task_key}`.").strip(),
            deliverable_type=contract.deliverable_type,
            default_risk_class=contract.default_risk_class,
            default_approval_class=contract.default_approval_class,
            workflow_template=workflow_template,
            allowed_tools=tuple(contract.allowed_tools or ()),
            evidence_requirements=tuple(contract.evidence_requirements or ()),
            memory_write_policy=contract.memory_write_policy,
            memory_reads=_as_string_tuple(meta.get("memory_reads")) or tuple(contract.evidence_requirements or ()),
            memory_writes=_as_string_tuple(meta.get("memory_writes")) or self._derive_memory_writes(contract),
            tags=_as_string_tuple(meta.get("tags")) or (workflow_template, contract.deliverable_type),
            input_schema_json=input_schema_json,
            output_schema_json=output_schema_json,
            authority_profile_json=authority_profile_json,
            model_policy_json=_as_dict(meta.get("model_policy_json")),
            provider_hints_json=provider_hints_json,
            tool_policy_json=tool_policy_json,
            human_policy_json=human_policy_json,
            evaluation_cases_json=_as_json_object_tuple(meta.get("evaluation_cases_json")),
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
        budget = dict(budget_policy_json or {})
        budget["workflow_template"] = str(workflow_template or "rewrite").strip() or "rewrite"
        budget["skill_catalog_json"] = {
            "skill_key": str(skill_key or resolved_task_key).strip() or resolved_task_key,
            "name": str(name or "").strip(),
            "description": str(description or "").strip(),
            "memory_reads": list(memory_reads),
            "memory_writes": list(memory_writes),
            "tags": list(tags),
            "input_schema_json": dict(input_schema_json or {}),
            "output_schema_json": dict(output_schema_json or {}),
            "authority_profile_json": dict(authority_profile_json or {}),
            "model_policy_json": dict(model_policy_json or {}),
            "provider_hints_json": dict(provider_hints_json or {}),
            "tool_policy_json": dict(tool_policy_json or {}),
            "human_policy_json": dict(human_policy_json or {}),
            "evaluation_cases_json": [dict(value) for value in evaluation_cases_json],
        }
        contract = self._task_contracts.upsert_contract(
            task_key=resolved_task_key,
            deliverable_type=deliverable_type,
            default_risk_class=default_risk_class,
            default_approval_class=default_approval_class,
            allowed_tools=allowed_tools,
            evidence_requirements=evidence_requirements,
            memory_write_policy=memory_write_policy,
            budget_policy_json=budget,
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

    def list_skills(self, limit: int = 100, provider_hint: str = "") -> list[SkillContract]:
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
