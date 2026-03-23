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


@dataclass(frozen=True)
class BrainCapabilityRoute:
    decision: BrainRouteDecision
    capability_key: str
    route: CapabilityRoute
    posthoc_review_profile: str
    fallback_brain_profile: str
    used_fallback_profile: bool = False


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
        if effective_hints:
            if profile.backend_key and str(profile.backend_key).strip() in merged_hints and str(profile.backend_key).strip() not in effective_hints:
                backend_key = default_provider_key
            if (
                profile.health_provider_key
                and str(profile.health_provider_key).strip() in merged_hints
                and str(profile.health_provider_key).strip() not in effective_hints
            ):
                health_provider_key = default_provider_key or backend_key
                if str(profile.backend_key or "").strip() == str(profile.health_provider_key or "").strip():
                    backend_key = health_provider_key
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
        return self.contract_brain_decision(contract, principal_id=principal_id).provider_hint_order

    def contract_brain_decision(
        self,
        contract: TaskContract,
        *,
        principal_id: str | None = None,
    ) -> BrainRouteDecision:
        runtime_policy = contract.runtime_policy()
        requested_hints = _collect_strings(runtime_policy.skill_catalog.provider_hints_json)
        profile_name = self._profile_name_from_contract(contract)
        return self.resolve_profile(
            profile_name,
            principal_id=principal_id,
            provider_hints=requested_hints,
        )

    def posthoc_review_profile_for_contract(self, contract: TaskContract) -> str:
        runtime_policy = contract.runtime_policy()
        explicit = str(runtime_policy.posthoc_review_profile or "").strip()
        if get_brain_profile(explicit) is not None:
            return explicit
        decision = self.resolve_profile(self._profile_name_from_contract(contract))
        if decision.review_required or decision.needs_review:
            return "review_light"
        return ""

    def fallback_brain_profile_for_contract(self, contract: TaskContract) -> str:
        runtime_policy = contract.runtime_policy()
        explicit = str(runtime_policy.fallback_brain_profile or "").strip()
        if get_brain_profile(explicit) is not None:
            return explicit
        primary = self._profile_name_from_contract(contract)
        if primary in {"core", "core_batch"}:
            return "survival"
        if primary == "groundwork":
            return "easy"
        return ""

    def route_brain_capability_for_contract(
        self,
        *,
        contract: TaskContract,
        capability_key: str,
        principal_id: str | None = None,
    ) -> BrainCapabilityRoute:
        decision = self.contract_brain_decision(contract, principal_id=principal_id)
        posthoc_review_profile = self.posthoc_review_profile_for_contract(contract)
        fallback_brain_profile = self.fallback_brain_profile_for_contract(contract)
        normalized_capability = str(capability_key or "").strip().lower()
        if normalized_capability not in {"structured_generate", "code_generate", "reasoned_patch_review", "image_generate", "media_transform"}:
            route = self._provider_registry.route_tool_by_capability_with_context(
                capability_key=capability_key,
                principal_id=principal_id,
                provider_hints=decision.provider_hint_order,
                allowed_tools=contract.allowed_tools,
                require_executable=True,
            )
            return BrainCapabilityRoute(
                decision=decision,
                capability_key=capability_key,
                route=route,
                posthoc_review_profile=posthoc_review_profile,
                fallback_brain_profile=fallback_brain_profile,
                used_fallback_profile=False,
            )
        try:
            route = self._provider_registry.route_brain_profile_capability_with_context(
                profile_name=decision.profile,
                capability_key=capability_key,
                principal_id=principal_id,
                allowed_tools=contract.allowed_tools,
                require_executable=True,
                provider_hints=decision.provider_hint_order,
            )
            return BrainCapabilityRoute(
                decision=decision,
                capability_key=capability_key,
                route=route,
                posthoc_review_profile=posthoc_review_profile,
                fallback_brain_profile=fallback_brain_profile,
                used_fallback_profile=False,
            )
        except ToolExecutionError:
            if not fallback_brain_profile or fallback_brain_profile == decision.profile:
                raise
            fallback_decision = self.resolve_profile(fallback_brain_profile, principal_id=principal_id)
            route = self._provider_registry.route_brain_profile_capability_with_context(
                profile_name=fallback_decision.profile,
                capability_key=capability_key,
                principal_id=principal_id,
                allowed_tools=contract.allowed_tools,
                require_executable=True,
                provider_hints=fallback_decision.provider_hint_order,
            )
            return BrainCapabilityRoute(
                decision=fallback_decision,
                capability_key=capability_key,
                route=route,
                posthoc_review_profile=posthoc_review_profile,
                fallback_brain_profile=fallback_brain_profile,
                used_fallback_profile=True,
            )

    def route_capability_for_contract(
        self,
        *,
        contract: TaskContract,
        capability_key: str,
        principal_id: str | None = None,
    ) -> CapabilityRoute:
        return self.route_brain_capability_for_contract(
            contract=contract,
            capability_key=capability_key,
            principal_id=principal_id,
        ).route

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
        explicit = str(policy.brain_profile or "").strip()
        if get_brain_profile(explicit) is not None:
            return explicit
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
