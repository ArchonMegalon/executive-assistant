from __future__ import annotations

from typing import Any

from app.domain.models import (
    SkillCatalogRecord,
    SkillContract,
    TaskContract,
    TaskContractPolicyRecord,
    TaskContractRuntimePolicy,
    TaskContractSkillCatalogPolicy,
    parse_task_contract_runtime_policy,
)
from app.services.task_contracts import TaskContractService, serialize_task_contract_runtime_policy


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

    def _deep_merge_dict(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in override.items():
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                merged[key] = self._deep_merge_dict(existing, value)
                continue
            merged[key] = value
        return merged

    def _runtime_policy(self, contract: TaskContract | TaskContractPolicyRecord) -> TaskContractRuntimePolicy:
        if isinstance(contract, TaskContractPolicyRecord):
            return contract.runtime_policy
        return contract.runtime_policy()

    def _skill_meta(self, contract: TaskContract | TaskContractPolicyRecord) -> TaskContractSkillCatalogPolicy:
        return self._runtime_policy(contract).skill_catalog

    def _workflow_template(self, contract: TaskContract | TaskContractPolicyRecord) -> str:
        return str(self._runtime_policy(contract).workflow_template or "rewrite").strip() or "rewrite"

    def _derive_input_schema(self, contract: TaskContract | TaskContractPolicyRecord) -> dict[str, Any]:
        policy = self._runtime_policy(contract)
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

    def _derive_output_schema(self, contract: TaskContract | TaskContractPolicyRecord) -> dict[str, Any]:
        deliverable_type = contract.deliverable_type
        return {
            "type": "object",
            "properties": {
                "deliverable_type": {"const": deliverable_type},
                "artifact_kind": {"type": "string"},
            },
            "required": ["deliverable_type"],
        }

    def _derive_memory_writes(self, contract: TaskContract | TaskContractPolicyRecord) -> tuple[str, ...]:
        if str(contract.memory_write_policy or "none").strip() == "none":
            return ()
        category = str(self._runtime_policy(contract).memory_candidate.category or "").strip()
        if category:
            return (category,)
        return (contract.memory_write_policy,)

    def _derive_human_policy(self, contract: TaskContract | TaskContractPolicyRecord) -> dict[str, Any]:
        human_review = self._runtime_policy(contract).human_review
        if not str(human_review.role or "").strip():
            return {}
        return {
            "role_required": str(human_review.role or "").strip(),
            "task_type": str(human_review.task_type or "").strip(),
            "priority": str(human_review.priority or "").strip(),
            "sla_minutes": int(human_review.sla_minutes),
            "authority_required": str(human_review.authority_required or "").strip(),
        }

    def policy_record_to_skill_record(self, contract: TaskContractPolicyRecord) -> SkillCatalogRecord:
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
        return SkillCatalogRecord(
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

    def record_to_skill(self, record: SkillCatalogRecord) -> SkillContract:
        return SkillContract(
            skill_key=record.skill_key,
            task_key=record.task_key,
            name=record.name,
            description=record.description,
            deliverable_type=record.deliverable_type,
            default_risk_class=record.default_risk_class,
            default_approval_class=record.default_approval_class,
            workflow_template=record.workflow_template,
            allowed_tools=tuple(record.allowed_tools or ()),
            evidence_requirements=tuple(record.evidence_requirements or ()),
            memory_write_policy=record.memory_write_policy,
            memory_reads=tuple(record.memory_reads or ()),
            memory_writes=tuple(record.memory_writes or ()),
            tags=tuple(record.tags or ()),
            input_schema_json=dict(record.input_schema_json or {}),
            output_schema_json=dict(record.output_schema_json or {}),
            authority_profile_json=dict(record.authority_profile_json or {}),
            model_policy_json=dict(record.model_policy_json or {}),
            provider_hints_json=dict(record.provider_hints_json or {}),
            tool_policy_json=dict(record.tool_policy_json or {}),
            human_policy_json=dict(record.human_policy_json or {}),
            evaluation_cases_json=tuple(dict(value) for value in record.evaluation_cases_json),
            updated_at=record.updated_at,
        )

    def contract_to_skill(self, contract: TaskContract) -> SkillContract:
        return self.record_to_skill(
            self.policy_record_to_skill_record(self._task_contracts.contract_to_policy_record(contract))
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
        runtime_policy_json: dict[str, Any] | None = None,
        provided_fields: set[str] | None = None,
    ) -> SkillContract:
        resolved_task_key = str(task_key or skill_key).strip() or str(skill_key or "").strip()
        presence_aware = provided_fields is not None
        provided = set(provided_fields or ())
        existing_contract = self._task_contracts.get_contract(resolved_task_key) if presence_aware else None
        existing_budget_payload = dict(existing_contract.budget_policy_json or {}) if existing_contract is not None else {}
        existing_runtime_payload = (
            serialize_task_contract_runtime_policy(existing_contract.runtime_policy())
            if existing_contract is not None
            else {}
        )
        if presence_aware:
            merged_runtime_payload = dict(existing_runtime_payload)
            if "budget_policy_json" in provided and budget_policy_json is not None:
                merged_runtime_payload = self._deep_merge_dict(merged_runtime_payload, dict(budget_policy_json))
            if "runtime_policy_json" in provided and runtime_policy_json is not None:
                merged_runtime_payload = self._deep_merge_dict(merged_runtime_payload, dict(runtime_policy_json))
            if existing_contract is None and not merged_runtime_payload:
                merged_runtime_payload = dict(runtime_policy_json or {})
            base_policy = parse_task_contract_runtime_policy(
                existing_budget_payload if existing_contract is not None else dict(budget_policy_json or {}),
                merged_runtime_payload,
            )
            if "budget_policy_json" in provided:
                budget_payload_for_write = dict(budget_policy_json or {})
            elif existing_contract is not None:
                budget_payload_for_write = dict(existing_budget_payload)
            else:
                budget_payload_for_write = dict(budget_policy_json or {})
        else:
            base_policy = parse_task_contract_runtime_policy(
                dict(budget_policy_json or {}),
                dict(runtime_policy_json or {}),
            )
            budget_payload_for_write = dict(budget_policy_json or {})
        base_skill_catalog = base_policy.skill_catalog
        workflow_value = str(base_policy.workflow_template or "rewrite").strip() or "rewrite"
        if not presence_aware:
            candidate = str(workflow_template or "").strip()
            if candidate:
                workflow_value = candidate
        elif "workflow_template" in provided:
            candidate = str(workflow_template or "").strip()
            if candidate:
                workflow_value = candidate

        if presence_aware:
            memory_reads_value = tuple(memory_reads or ()) if "memory_reads" in provided else tuple(base_skill_catalog.memory_reads or ())
            memory_writes_value = tuple(memory_writes or ()) if "memory_writes" in provided else tuple(base_skill_catalog.memory_writes or ())
            tags_value = tuple(tags or ()) if "tags" in provided else tuple(base_skill_catalog.tags or ())
            input_schema_value = dict(input_schema_json or {}) if "input_schema_json" in provided else dict(base_skill_catalog.input_schema_json or {})
            output_schema_value = dict(output_schema_json or {}) if "output_schema_json" in provided else dict(base_skill_catalog.output_schema_json or {})
            authority_profile_value = dict(authority_profile_json or {}) if "authority_profile_json" in provided else dict(base_skill_catalog.authority_profile_json or {})
            model_policy_value = dict(model_policy_json or {}) if "model_policy_json" in provided else dict(base_skill_catalog.model_policy_json or {})
            provider_hints_value = dict(provider_hints_json or {}) if "provider_hints_json" in provided else dict(base_skill_catalog.provider_hints_json or {})
            tool_policy_value = dict(tool_policy_json or {}) if "tool_policy_json" in provided else dict(base_skill_catalog.tool_policy_json or {})
            human_policy_value = dict(human_policy_json or {}) if "human_policy_json" in provided else dict(base_skill_catalog.human_policy_json or {})
            evaluation_cases_value = (
                tuple(dict(value) for value in evaluation_cases_json)
                if "evaluation_cases_json" in provided
                else tuple(dict(value) for value in base_skill_catalog.evaluation_cases_json)
            )
        else:
            memory_reads_value = tuple(memory_reads) or tuple(base_skill_catalog.memory_reads or ())
            memory_writes_value = tuple(memory_writes) or tuple(base_skill_catalog.memory_writes or ())
            tags_value = tuple(tags) or tuple(base_skill_catalog.tags or ())
            input_schema_value = dict(input_schema_json or {}) or dict(base_skill_catalog.input_schema_json or {})
            output_schema_value = dict(output_schema_json or {}) or dict(base_skill_catalog.output_schema_json or {})
            authority_profile_value = dict(authority_profile_json or {}) or dict(base_skill_catalog.authority_profile_json or {})
            model_policy_value = dict(model_policy_json or {}) or dict(base_skill_catalog.model_policy_json or {})
            provider_hints_value = dict(provider_hints_json or {}) or dict(base_skill_catalog.provider_hints_json or {})
            tool_policy_value = dict(tool_policy_json or {}) or dict(base_skill_catalog.tool_policy_json or {})
            human_policy_value = dict(human_policy_json or {}) or dict(base_skill_catalog.human_policy_json or {})
            evaluation_cases_value = (
                tuple(dict(value) for value in evaluation_cases_json)
                or tuple(dict(value) for value in base_skill_catalog.evaluation_cases_json)
            )
        runtime_policy = TaskContractRuntimePolicy(
            budget_class=base_policy.budget_class,
            workflow_template=workflow_value,
            brain_profile=str(base_policy.brain_profile or "").strip(),
            posthoc_review_profile=str(base_policy.posthoc_review_profile or "").strip(),
            posthoc_review_required=bool(base_policy.posthoc_review_required),
            fallback_brain_profile=str(base_policy.fallback_brain_profile or "").strip(),
            pre_artifact_tool_name=base_policy.pre_artifact_tool_name,
            pre_artifact_capability_key=base_policy.pre_artifact_capability_key,
            browseract_timeout_budget_seconds=base_policy.browseract_timeout_budget_seconds,
            post_artifact_packs=base_policy.post_artifact_packs,
            artifact_retry=base_policy.artifact_retry,
            dispatch_retry=base_policy.dispatch_retry,
            browseract_retry=base_policy.browseract_retry,
            human_review=base_policy.human_review,
            memory_candidate=base_policy.memory_candidate,
            artifact_output=base_policy.artifact_output,
            skill_catalog=TaskContractSkillCatalogPolicy(
                skill_key=str(skill_key or base_skill_catalog.skill_key or resolved_task_key).strip() or resolved_task_key,
                name=str(name or "").strip(),
                description=str(description or base_skill_catalog.description or "").strip(),
                memory_reads=memory_reads_value,
                memory_writes=memory_writes_value,
                tags=tags_value,
                input_schema_json=input_schema_value,
                output_schema_json=output_schema_value,
                authority_profile_json=authority_profile_value,
                model_policy_json=model_policy_value,
                provider_hints_json=provider_hints_value,
                tool_policy_json=tool_policy_value,
                human_policy_json=human_policy_value,
                evaluation_cases_json=evaluation_cases_value,
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
            budget_policy_json=budget_payload_for_write,
            runtime_policy=runtime_policy,
        )
        return self.contract_to_skill(contract)

    def get_skill_record(self, skill_key: str) -> SkillCatalogRecord | None:
        resolved = str(skill_key or "").strip()
        if not resolved:
            return None
        direct = self._task_contracts.get_policy_record(resolved)
        if direct is not None:
            return self.policy_record_to_skill_record(direct)
        for contract in self._task_contracts.list_policy_records(limit=500):
            projected = self.policy_record_to_skill_record(contract)
            if projected.skill_key == resolved:
                return projected
        return None

    def get_skill(self, skill_key: str) -> SkillContract | None:
        record = self.get_skill_record(skill_key)
        if record is None:
            return None
        return self.record_to_skill(record)

    def list_skill_records(self, limit: int = 100, provider_hint: str = "") -> list[SkillCatalogRecord]:
        normalized_provider_hint = str(provider_hint or "").strip().lower()
        fetch_limit = 500 if normalized_provider_hint else limit
        rows = [
            self.policy_record_to_skill_record(contract)
            for contract in self._task_contracts.list_policy_records(limit=fetch_limit)
        ]
        if normalized_provider_hint:
            projected = [
                self.policy_record_to_skill_record(self._task_contracts.contract_to_policy_record(contract))
                for contract in self._task_contracts.list_projected_contracts(
                    provider_hint=provider_hint,
                    limit=fetch_limit,
                )
            ]
            if projected:
                rows.extend(projected)
        if normalized_provider_hint:
            rows = [
                row
                for row in rows
                if any(
                    normalized_provider_hint in candidate.lower()
                    for candidate in _collect_string_values(row.provider_hints_json)
                )
            ]
        deduped: list[SkillCatalogRecord] = []
        seen: set[str] = set()
        for row in rows:
            key = str(row.skill_key or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        return deduped[:limit]

    def list_skills(self, limit: int = 100, provider_hint: str = ""):
        return [self.record_to_skill(record) for record in self.list_skill_records(limit=limit, provider_hint=provider_hint)]
