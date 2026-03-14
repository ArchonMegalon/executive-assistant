from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass

from app.domain.models import ProviderBindingState, SkillContract
from app.services.tool_execution_common import ToolExecutionError


def _collect_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        normalized = str(value or "").strip()
        return (normalized,) if normalized else ()
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


@dataclass(frozen=True)
class ProviderCapability:
    provider_key: str
    capability_key: str
    tool_name: str
    executable: bool = True


@dataclass(frozen=True)
class ProviderBinding:
    provider_key: str
    display_name: str
    executable: bool
    capabilities: tuple[ProviderCapability, ...]
    source: str = "runtime"


@dataclass(frozen=True)
class CapabilityRoute:
    provider_key: str
    capability_key: str
    tool_name: str
    executable: bool


class ProviderRegistryService:
    def __init__(self) -> None:
        self._bindings = (
            ProviderBinding(
                provider_key="artifact_repository",
                display_name="Artifact Repository",
                executable=True,
                capabilities=(
                    ProviderCapability(
                        provider_key="artifact_repository",
                        capability_key="artifact_save",
                        tool_name="artifact_repository",
                    ),
                ),
            ),
            ProviderBinding(
                provider_key="browseract",
                display_name="BrowserAct",
                executable=True,
                capabilities=(
                    ProviderCapability(
                        provider_key="browseract",
                        capability_key="account_facts",
                        tool_name="browseract.extract_account_facts",
                    ),
                    ProviderCapability(
                        provider_key="browseract",
                        capability_key="account_inventory",
                        tool_name="browseract.extract_account_inventory",
                    ),
                    ProviderCapability(
                        provider_key="browseract",
                        capability_key="workflow_spec_build",
                        tool_name="browseract.build_workflow_spec",
                    ),
                    ProviderCapability(
                        provider_key="browseract",
                        capability_key="workflow_spec_repair",
                        tool_name="browseract.repair_workflow_spec",
                    ),
                ),
            ),
            ProviderBinding(
                provider_key="connector_dispatch",
                display_name="Connector Dispatch",
                executable=True,
                capabilities=(
                    ProviderCapability(
                        provider_key="connector_dispatch",
                        capability_key="dispatch",
                        tool_name="connector.dispatch",
                    ),
                ),
            ),
            ProviderBinding(
                provider_key="gemini_vortex",
                display_name="Gemini Vortex",
                executable=True,
                capabilities=(
                    ProviderCapability(
                        provider_key="gemini_vortex",
                        capability_key="structured_generate",
                        tool_name="provider.gemini_vortex.structured_generate",
                    ),
                ),
            ),
            ProviderBinding(
                provider_key="prompting_systems",
                display_name="Prompting Systems",
                executable=False,
                capabilities=(
                    ProviderCapability(
                        provider_key="prompting_systems",
                        capability_key="prompt_refine",
                        tool_name="provider.prompting_systems.prompt_refine",
                        executable=False,
                    ),
                    ProviderCapability(
                        provider_key="prompting_systems",
                        capability_key="image_to_prompt",
                        tool_name="provider.prompting_systems.image_to_prompt",
                        executable=False,
                    ),
                ),
                source="catalog",
            ),
            ProviderBinding(
                provider_key="magixai",
                display_name="AI Magicx",
                executable=False,
                capabilities=(
                    ProviderCapability(
                        provider_key="magixai",
                        capability_key="image_generate",
                        tool_name="provider.magixai.image_generate",
                        executable=False,
                    ),
                ),
                source="catalog",
            ),
            ProviderBinding(
                provider_key="markupgo",
                display_name="MarkupGo",
                executable=False,
                capabilities=(
                    ProviderCapability(
                        provider_key="markupgo",
                        capability_key="image_composite",
                        tool_name="provider.markupgo.image_composite",
                        executable=False,
                    ),
                ),
                source="catalog",
            ),
            ProviderBinding(
                provider_key="onemin",
                display_name="1min.AI",
                executable=False,
                capabilities=(
                    ProviderCapability(
                        provider_key="onemin",
                        capability_key="image_generate",
                        tool_name="provider.onemin.image_generate",
                        executable=False,
                    ),
                ),
                source="catalog",
            ),

            ProviderBinding(
                provider_key="browserly",
                display_name="Browserly",
                executable=False,
                capabilities=(
                    ProviderCapability(
                        provider_key="browserly",
                        capability_key="browser_capture",
                        tool_name="provider.browserly.browser_capture",
                        executable=False,
                    ),
                ),
                source="catalog",
            ),
            ProviderBinding(
                provider_key="teable",
                display_name="Teable",
                executable=False,
                capabilities=(
                    ProviderCapability(
                        provider_key="teable",
                        capability_key="table_sync",
                        tool_name="provider.teable.table_sync",
                        executable=False,
                    ),
                ),
                source="catalog",
            ),
            ProviderBinding(
                provider_key="unmixr",
                display_name="Unmixr AI",
                executable=False,
                capabilities=(
                    ProviderCapability(
                        provider_key="unmixr",
                        capability_key="voice_render",
                        tool_name="provider.unmixr.voice_render",
                        executable=False,
                    ),
                ),
                source="catalog",
            ),
        )

    def list_bindings(self) -> tuple[ProviderBinding, ...]:
        return self._bindings

    def _secret_env_names(self, provider_key: str) -> tuple[str, ...]:
        mapping = {
            "browseract": ("BROWSERACT_API_KEY", "BROWSERACT_API_KEY_FALLBACK_1"),
            "browserly": ("BROWSERLY_API_KEY",),
            "gemini_vortex": ("EA_GEMINI_VORTEX_COMMAND",),
            "magixai": ("AI_MAGICX_API_KEY",),
            "markupgo": ("MARKUPGO_API_KEY",),
            "onemin": ("ONEMIN_AI_API_KEY", "ONEMIN_AI_API_KEY_FALLBACK_1"),
            "prompting_systems": ("PROMPTING_SYSTEMS_API_KEY",),
            "teable": ("TEABLE_API_KEY",),
            "unmixr": ("UNMIXR_API_KEY",),
        }
        return mapping.get(str(provider_key or "").strip(), ())

    def _auth_mode(self, binding: ProviderBinding) -> str:
        if binding.provider_key in {"artifact_repository", "connector_dispatch"}:
            return "internal"
        if binding.provider_key == "gemini_vortex":
            return "cli"
        if self._secret_env_names(binding.provider_key):
            return "api_key"
        return "catalog"

    def _secret_configured(self, binding: ProviderBinding) -> bool:
        auth_mode = self._auth_mode(binding)
        if auth_mode == "internal":
            return True
        if auth_mode == "cli":
            command = str(os.environ.get("EA_GEMINI_VORTEX_COMMAND") or "gemini").strip() or "gemini"
            argv = shlex.split(command)
            executable = argv[0] if argv else "gemini"
            return bool(shutil.which(executable))
        return any(str(os.environ.get(name) or "").strip() for name in self._secret_env_names(binding.provider_key))

    def binding_state(self, provider_key: str) -> ProviderBindingState | None:
        normalized = self._normalize_provider_key(provider_key)
        for binding in self._bindings:
            if binding.provider_key != normalized:
                continue
            auth_mode = self._auth_mode(binding)
            secret_env_names = self._secret_env_names(binding.provider_key)
            secret_configured = self._secret_configured(binding)
            if binding.executable and secret_configured:
                state = "ready"
            elif secret_configured:
                state = "configured"
            elif binding.executable:
                state = "unconfigured"
            else:
                state = "catalog_only"
            return ProviderBindingState(
                provider_key=binding.provider_key,
                display_name=binding.display_name,
                executable=binding.executable,
                enabled=secret_configured or binding.executable,
                source=binding.source,
                auth_mode=auth_mode,
                secret_env_names=secret_env_names,
                secret_configured=secret_configured,
                capabilities=tuple(capability.capability_key for capability in binding.capabilities),
                tool_names=tuple(capability.tool_name for capability in binding.capabilities),
                state=state,
                health_state="ready" if state == "ready" else "unknown",
            )
        return None

    def list_binding_states(self) -> tuple[ProviderBindingState, ...]:
        states: list[ProviderBindingState] = []
        for binding in self._bindings:
            state = self.binding_state(binding.provider_key)
            if state is not None:
                states.append(state)
        return tuple(states)

    def knows_tool(self, tool_name: str) -> bool:
        normalized_tool = str(tool_name or "").strip()
        if not normalized_tool:
            return False
        for binding in self._bindings:
            for capability in binding.capabilities:
                if capability.tool_name == normalized_tool:
                    return True
        return False

    def bindings_for_skill(self, skill: SkillContract) -> tuple[ProviderBinding, ...]:
        hints = {
            self._normalize_provider_key(value)
            for value in _collect_strings(skill.provider_hints_json)
            if str(value or "").strip()
        }
        allowed_tools = {str(value or "").strip() for value in skill.allowed_tools if str(value or "").strip()}
        matched: list[ProviderBinding] = []
        for binding in self._bindings:
            capability_tools = {cap.tool_name for cap in binding.capabilities}
            if binding.provider_key in hints or capability_tools.intersection(allowed_tools):
                matched.append(binding)
        return tuple(matched)

    def binding_states_for_skill(self, skill: SkillContract) -> tuple[ProviderBindingState, ...]:
        states: list[ProviderBindingState] = []
        for binding in self.bindings_for_skill(skill):
            state = self.binding_state(binding.provider_key)
            if state is not None:
                states.append(state)
        return tuple(states)

    def route_tool_by_capability(
        self,
        *,
        capability_key: str,
        provider_hints: tuple[str, ...] = (),
        allowed_tools: tuple[str, ...] = (),
        require_executable: bool = True,
    ) -> CapabilityRoute:
        normalized_capability = self._normalize_capability_key(capability_key)
        if not normalized_capability:
            raise ToolExecutionError("provider_capability_required")
        normalized_hints = {
            self._normalize_provider_key(value)
            for value in provider_hints
            if str(value or "").strip()
        }
        allowed_tool_set = {str(value or "").strip() for value in allowed_tools if str(value or "").strip()}

        def _binding_score(binding: ProviderBinding) -> tuple[int, int]:
            hint_rank = 0 if binding.provider_key in normalized_hints else 1
            exec_rank = 0 if binding.executable else 1
            return (hint_rank, exec_rank)

        candidate_bindings = sorted(self._bindings, key=_binding_score)
        for binding in candidate_bindings:
            if require_executable and not binding.executable:
                continue
            for capability in binding.capabilities:
                if self._normalize_capability_key(capability.capability_key) != normalized_capability:
                    continue
                if require_executable and not capability.executable:
                    continue
                if allowed_tool_set and capability.tool_name not in allowed_tool_set:
                    continue
                return CapabilityRoute(
                    provider_key=binding.provider_key,
                    capability_key=capability.capability_key,
                    tool_name=capability.tool_name,
                    executable=binding.executable and capability.executable,
                )
        raise ToolExecutionError(f"provider_capability_unavailable:{normalized_capability}")

    def route_tool(self, tool_name: str) -> CapabilityRoute:
        normalized_tool = str(tool_name or "").strip()
        if not normalized_tool:
            raise ToolExecutionError("tool_name_required")
        for binding in self._bindings:
            if not binding.executable:
                continue
            for capability in binding.capabilities:
                if not capability.executable:
                    continue
                if capability.tool_name == normalized_tool:
                    return CapabilityRoute(
                        provider_key=binding.provider_key,
                        capability_key=capability.capability_key,
                        tool_name=capability.tool_name,
                        executable=True,
                    )
        raise ToolExecutionError(f"provider_tool_unavailable:{normalized_tool}")

    def _normalize_capability_key(self, value: object) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "artifact": "artifact_save",
            "save_artifact": "artifact_save",
            "account_facts_extract": "account_facts",
            "extract_account_facts": "account_facts",
            "account_inventory_extract": "account_inventory",
            "extract_account_inventory": "account_inventory",
            "workflow_spec": "workflow_spec_build",
            "build_workflow_spec": "workflow_spec_build",
            "browseract_workflow_spec": "workflow_spec_build",
            "workflow_repair": "workflow_spec_repair",
            "repair_workflow_spec": "workflow_spec_repair",
            "browseract_workflow_repair": "workflow_spec_repair",
            "delivery_dispatch": "dispatch",
            "connector_dispatch": "dispatch",
            "generate_json": "structured_generate",
            "json_generate": "structured_generate",
            "structured_generation": "structured_generate",
        }
        return aliases.get(normalized, normalized)

    def _normalize_provider_key(self, value: object) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "1min.ai": "onemin",
            "1min_ai": "onemin",
            "ai_magicx": "magixai",
            "aimagicx": "magixai",
            "browserly.ai": "browserly",
            "browsely": "browserly",
            "prompting.systems": "prompting_systems",
            "gemini": "gemini_vortex",
            "gemini_cli": "gemini_vortex",
            "vortex": "gemini_vortex",
            "gemini_vortex": "gemini_vortex",
        }
        return aliases.get(normalized, normalized)
