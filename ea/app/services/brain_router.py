from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import SkillContract, TaskContract
from app.services.brain_catalog import BrainProfile, get_brain_profile, list_brain_profiles
from app.services.provider_registry import CapabilityRoute, ProviderRegistryService
from app.services.tool_execution_common import ToolExecutionError


@dataclass(frozen=True)
class BrainRouteDecision:
    profile: str
    lane: str
    public_model: str
    provider_hint_order: tuple[str, ...]
    backend_key: str
    health_provider_key: str
    review_required: bool
    needs_review: bool
    merge_policy: str
    risk_labels: tuple[str, ...]


def _collect_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        cleaned = str(value or "").strip()
        return (cleaned,) if cleaned else ()
    if isinstance(value, dict):
        collected: list[str] = []
        for nested in value.values():
            collected.extend(_collect_strings(nested))
        return tuple(collected)
    if isinstance(value, (list, tuple, set)):
        collected: list[str] = []
        for nested in value:
            collected.extend(_collect_strings(nested))
        return tuple(collected)
    return ()


class BrainRouterService:
    def __init__(self, provider_registry: ProviderRegistryService | None = None) -> None:
        self._provider_registry = provider_registry or ProviderRegistryService()

    def list_profile_decisions(self, *, principal_id: str | None = None) -> tuple[BrainRouteDecision, ...]:
        return tuple(self.resolve_profile(profile.profile, principal_id=principal_id) for profile in list_brain_profiles())

    def resolve_profile(
        self,
        name_or_model: str,
        *,
        principal_id: str | None = None,
        provider_hints: tuple[str, ...] = (),
    ) -> BrainRouteDecision:
        profile = self._brain_profile(name_or_model)
        merged_hints = self._merge_provider_hints(profile.provider_hint_order, provider_hints)
        filtered_hints = self._filter_available_provider_hints(merged_hints, principal_id=principal_id)
        effective_hints = filtered_hints or merged_hints
        default_provider_key = effective_hints[0] if effective_hints else ""
        backend_key = str(profile.backend_key or default_provider_key).strip()
        health_provider_key = str(profile.health_provider_key or default_provider_key or backend_key).strip()
        return BrainRouteDecision(
            profile=profile.profile,
            lane=profile.lane,
            public_model=profile.public_model,
            provider_hint_order=effective_hints,
            backend_key=backend_key,
            health_provider_key=health_provider_key,
            review_required=bool(profile.review_required),
            needs_review=bool(profile.needs_review),
            merge_policy=str(profile.merge_policy or "auto"),
            risk_labels=tuple(profile.risk_labels or ()),
        )

    def provider_hints_for_contract(
        self,
        contract: TaskContract,
        *,
        principal_id: str | None = None,
    ) -> tuple[str, ...]:
        runtime_policy = contract.runtime_policy()
        skill_catalog = runtime_policy.skill_catalog
        requested_hints = _collect_strings(skill_catalog.provider_hints_json)
        profile_name = self._profile_name_from_contract(contract)
        return self.resolve_profile(
            profile_name,
            principal_id=principal_id,
            provider_hints=requested_hints,
        ).provider_hint_order

    def route_capability_for_contract(
        self,
        *,
        contract: TaskContract,
        capability_key: str,
        principal_id: str | None = None,
    ) -> CapabilityRoute:
        provider_hints = self.provider_hints_for_contract(contract, principal_id=principal_id)
        try:
            return self._provider_registry.route_tool_by_capability_with_context(
                capability_key=capability_key,
                principal_id=principal_id,
                provider_hints=provider_hints,
                allowed_tools=contract.allowed_tools,
                require_executable=True,
            )
        except ToolExecutionError:
            raise

    def binding_states_for_skill(
        self,
        skill: SkillContract,
        *,
        principal_id: str | None = None,
    ):
        profile_name = self._profile_name_from_skill(skill)
        provider_hints = self.resolve_profile(
            profile_name,
            principal_id=principal_id,
            provider_hints=_collect_strings(skill.provider_hints_json),
        ).provider_hint_order
        states = []
        for provider_key in provider_hints:
            state = self._provider_registry.binding_state(provider_key, principal_id=principal_id)
            if state is not None:
                states.append(state)
        return tuple(states)

    def _brain_profile(self, name_or_model: str) -> BrainProfile:
        found = get_brain_profile(name_or_model)
        if found is not None:
            return found
        fallback = get_brain_profile("easy")
        if fallback is None:
            raise RuntimeError("brain_profile_easy_missing")
        return fallback

    def _profile_name_from_contract(self, contract: TaskContract) -> str:
        policy = contract.runtime_policy()
        model_policy = policy.skill_catalog.model_policy_json
        for candidate in (
            model_policy.get("brain_profile"),
            model_policy.get("profile"),
            model_policy.get("default_model"),
            model_policy.get("model"),
        ):
            resolved = str(candidate or "").strip()
            if get_brain_profile(resolved) is not None:
                return resolved
        workflow_template = policy.workflow_template_key
        if workflow_template in {"browseract_extract_then_artifact", "artifact_then_packs"}:
            return "groundwork"
        return "easy"

    def _profile_name_from_skill(self, skill: SkillContract) -> str:
        model_policy = dict(skill.model_policy_json or {})
        for candidate in (
            model_policy.get("brain_profile"),
            model_policy.get("profile"),
            model_policy.get("default_model"),
            model_policy.get("model"),
        ):
            resolved = str(candidate or "").strip()
            if get_brain_profile(resolved) is not None:
                return resolved
        workflow = str(skill.workflow_template or "").strip().lower()
        if workflow in {"browseract_extract_then_artifact", "artifact_then_packs"}:
            return "groundwork"
        return "easy"

    def _merge_provider_hints(self, *groups: tuple[str, ...]) -> tuple[str, ...]:
        deduped: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for value in group:
                normalized = self._normalize_provider_hint(value)
                if not normalized:
                    continue
                if normalized in seen:
                    continue
                seen.add(normalized)
                deduped.append(normalized)
        return tuple(deduped)

    def _normalize_provider_hint(self, value: object) -> str:
        state = self._provider_registry.binding_state(str(value or "").strip())
        if state is not None:
            return state.provider_key
        return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    def _filter_available_provider_hints(
        self,
        provider_hints: tuple[str, ...],
        *,
        principal_id: str | None = None,
    ) -> tuple[str, ...]:
        available: list[str] = []
        for provider_key in provider_hints:
            state = self._provider_registry.binding_state(provider_key, principal_id=principal_id)
            if state is None:
                continue
            if not state.enabled:
                continue
            if not state.executable:
                continue
            if state.state in {"disabled", "catalog_only", "unconfigured"}:
                continue
            available.append(state.provider_key)
        return tuple(available)
