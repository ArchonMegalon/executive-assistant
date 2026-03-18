from __future__ import annotations

import os
import re
import shlex
import shutil
from dataclasses import dataclass

from app.domain.models import ProviderBindingState, SkillContract
from app.repositories.provider_bindings import ProviderBindingRecord, ProviderBindingRepository
from app.services.tool_execution_common import ToolExecutionError


_ONEMIN_FALLBACK_ENV_RE = re.compile(r"^ONEMIN_AI_API_KEY_FALLBACK_(\d+)$")
_ONEMIN_FALLBACK_SLOT_RE = re.compile(r"^fallback_?(\d+)$")


def _onemin_fallback_slot_number(raw: object) -> int | None:
    match = _ONEMIN_FALLBACK_SLOT_RE.match(str(raw or "").strip().lower().replace(" ", "_").replace("-", "_"))
    if match is None:
        return None
    try:
        slot_number = int(match.group(1))
    except Exception:
        return None
    return slot_number if slot_number >= 1 else None


def _onemin_secret_env_names() -> tuple[str, ...]:
    fallback_numbers: set[int] = set()
    for env_name in os.environ:
        match = _ONEMIN_FALLBACK_ENV_RE.match(str(env_name or "").strip())
        if match is None:
            continue
        try:
            fallback_numbers.add(int(match.group(1)))
        except Exception:
            continue
    for env_var in ("EA_RESPONSES_ONEMIN_ACTIVE_SLOTS", "EA_RESPONSES_ONEMIN_RESERVE_SLOTS"):
        for slot_name in str(os.environ.get(env_var) or "").split(","):
            slot_number = _onemin_fallback_slot_number(slot_name)
            if slot_number is not None:
                fallback_numbers.add(slot_number)
    names = ["ONEMIN_AI_API_KEY"]
    for slot_number in sorted(fallback_numbers):
        names.append(f"ONEMIN_AI_API_KEY_FALLBACK_{slot_number}")
    return tuple(names)


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
    def __init__(
        self,
        provider_binding_repo: ProviderBindingRepository | None = None,
    ) -> None:
        self._provider_binding_repo = provider_binding_repo
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
                    ProviderCapability(
                        provider_key="browseract",
                        capability_key="chatplayground_audit",
                        tool_name="browseract.chatplayground_audit",
                    ),
                    ProviderCapability(
                        provider_key="browseract",
                        capability_key="gemini_web_generate",
                        tool_name="browseract.gemini_web_generate",
                    ),
                    ProviderCapability(
                        provider_key="browseract",
                        capability_key="onemin_billing_usage",
                        tool_name="browseract.onemin_billing_usage",
                    ),
                    ProviderCapability(
                        provider_key="browseract",
                        capability_key="onemin_member_reconciliation",
                        tool_name="browseract.onemin_member_reconciliation",
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
                executable=True,
                capabilities=(
                    ProviderCapability(
                        provider_key="onemin",
                        capability_key="code_generate",
                        tool_name="provider.onemin.code_generate",
                    ),
                    ProviderCapability(
                        provider_key="onemin",
                        capability_key="reasoned_patch_review",
                        tool_name="provider.onemin.reasoned_patch_review",
                    ),
                    ProviderCapability(
                        provider_key="onemin",
                        capability_key="image_generate",
                        tool_name="provider.onemin.image_generate",
                    ),
                    ProviderCapability(
                        provider_key="onemin",
                        capability_key="media_transform",
                        tool_name="provider.onemin.media_transform",
                    ),
                ),
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

    def _normalize_principal_id(self, principal_id: str | None) -> str:
        return str(principal_id or "").strip()

    def _get_binding_record(
        self,
        principal_id: str | None,
        provider_key: str,
    ) -> ProviderBindingRecord | None:
        if self._provider_binding_repo is None:
            return None
        normalized_principal = self._normalize_principal_id(principal_id)
        if not normalized_principal:
            return None
        normalized_provider = self._normalize_provider_key(provider_key)
        if not normalized_provider:
            return None
        try:
            return self._provider_binding_repo.get_for_provider(
                principal_id=normalized_principal,
                provider_key=normalized_provider,
            )
        except Exception:
            return None

    def _list_binding_records(
        self,
        principal_id: str | None,
    ) -> tuple[ProviderBindingRecord, ...]:
        if self._provider_binding_repo is None:
            return ()
        normalized_principal = self._normalize_principal_id(principal_id)
        if not normalized_principal:
            return ()
        try:
            return tuple(self._provider_binding_repo.list_for_principal(normalized_principal))
        except Exception:
            return ()

    def supports_persisted_bindings(self) -> bool:
        return self._provider_binding_repo is not None

    def upsert_binding_record(
        self,
        *,
        principal_id: str,
        provider_key: str,
        status: str = "enabled",
        priority: int = 100,
        probe_state: str = "unknown",
        probe_details_json: dict[str, object] | None = None,
        scope_json: dict[str, object] | None = None,
        auth_metadata_json: dict[str, object] | None = None,
    ) -> ProviderBindingRecord:
        if self._provider_binding_repo is None:
            raise ToolExecutionError("provider_binding_repo_unavailable")
        principal = self._normalize_principal_id(principal_id)
        provider = self._normalize_provider_key(provider_key)
        if not principal:
            raise ToolExecutionError("principal_id_required")
        if not provider:
            raise ToolExecutionError("provider_key_required")
        return self._provider_binding_repo.upsert(
            principal_id=principal,
            provider_key=provider,
            status=str(status or "enabled").strip().lower() or "enabled",
            priority=int(priority or 100),
            probe_state=str(probe_state or "unknown").strip() or "unknown",
            probe_details_json=dict(probe_details_json or {}),
            scope_json=dict(scope_json or {}),
            auth_metadata_json=dict(auth_metadata_json or {}),
        )

    def list_persisted_binding_records(
        self,
        *,
        principal_id: str,
        limit: int = 100,
    ) -> tuple[ProviderBindingRecord, ...]:
        if self._provider_binding_repo is None:
            return ()
        principal = self._normalize_principal_id(principal_id)
        if not principal:
            return ()
        bounded_limit = max(1, min(500, int(limit or 100)))
        return tuple(self._provider_binding_repo.list_for_principal(principal, limit=bounded_limit))

    def get_persisted_binding_record(
        self,
        *,
        binding_id: str,
        principal_id: str | None = None,
    ) -> ProviderBindingRecord | None:
        if self._provider_binding_repo is None:
            return None
        normalized_binding_id = str(binding_id or "").strip()
        if not normalized_binding_id:
            return None
        record = self._provider_binding_repo.get(normalized_binding_id)
        if record is None:
            return None
        if principal_id and self._normalize_principal_id(principal_id) != record.principal_id:
            return None
        return record

    def set_persisted_binding_status(
        self,
        *,
        binding_id: str,
        status: str,
        principal_id: str | None = None,
    ) -> ProviderBindingRecord | None:
        if self._provider_binding_repo is None:
            return None
        existing = self.get_persisted_binding_record(binding_id=binding_id, principal_id=principal_id)
        if existing is None:
            return None
        return self._provider_binding_repo.set_status(
            existing.binding_id,
            str(status or existing.status).strip().lower() or existing.status,
        )

    def set_persisted_binding_probe(
        self,
        *,
        binding_id: str,
        probe_state: str,
        probe_details_json: dict[str, object] | None = None,
        principal_id: str | None = None,
    ) -> ProviderBindingRecord | None:
        if self._provider_binding_repo is None:
            return None
        existing = self.get_persisted_binding_record(binding_id=binding_id, principal_id=principal_id)
        if existing is None:
            return None
        return self._provider_binding_repo.set_probe(
            existing.binding_id,
            str(probe_state or "unknown").strip() or "unknown",
            dict(probe_details_json or {}),
        )

    def _provider_state_value(self, binding: ProviderBinding, record: ProviderBindingRecord | None) -> str:
        auth_mode = self._auth_mode(binding)
        secret_env_names = self._secret_env_names(binding.provider_key)
        secret_configured = self._secret_configured(binding)
        if record is None:
            if binding.executable and secret_configured:
                return "ready"
            if secret_configured:
                return "configured"
            if binding.executable:
                return "unconfigured"
            return "catalog_only"

        status = str(record.status or "").strip().lower()
        if status == "disabled":
            return "disabled"
        if status == "maintenance":
            return "maintenance"
        if status in {"ready", "degraded"}:
            return status

        if auth_mode == "internal":
            return "ready" if status != "disabled" else "disabled"
        if auth_mode == "cli":
            return "ready" if status == "enabled" else status
        if status == "enabled":
            if binding.executable and secret_configured:
                return "ready"
            if binding.executable:
                return "unconfigured"
            if secret_configured:
                return "configured"
            return "catalog_only"
        if status == "configured":
            return "configured"
        if status == "degraded":
            return "degraded"
        return "catalog_only" if not binding.executable else "unconfigured"

    @staticmethod
    def _to_state_bool(record: ProviderBindingRecord | None, *, fallback: bool) -> bool:
        if record is None:
            return fallback
        return str(record.status or "").strip().lower() == "enabled"

    def list_bindings(self) -> tuple[ProviderBinding, ...]:
        return self._bindings

    def _secret_env_names(self, provider_key: str) -> tuple[str, ...]:
        mapping = {
            "browseract": ("BROWSERACT_API_KEY", "BROWSERACT_API_KEY_FALLBACK_1"),
            "browserly": ("BROWSERLY_API_KEY",),
            "gemini_vortex": ("EA_GEMINI_VORTEX_COMMAND",),
            "magixai": ("AI_MAGICX_API_KEY",),
            "markupgo": ("MARKUPGO_API_KEY",),
            "onemin": _onemin_secret_env_names(),
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

    def binding_state(
        self,
        provider_key: str,
        principal_id: str | None = None,
    ) -> ProviderBindingState | None:
        normalized = self._normalize_provider_key(provider_key)
        for binding in self._bindings:
            if binding.provider_key != normalized:
                continue
            auth_mode = self._auth_mode(binding)
            secret_env_names = self._secret_env_names(binding.provider_key)
            secret_configured = self._secret_configured(binding)
            record = self._get_binding_record(principal_id=principal_id, provider_key=normalized)
            if record is not None:
                status = str(record.status or "disabled").strip().lower()
                if not status:
                    status = "disabled"
            else:
                status = self._provider_state_value(binding, None)
                if status in {"ready", "configured", "unconfigured", "catalog_only"}:
                    status = "enabled" if secret_configured or binding.executable else "catalog_only"
                status = str(status)

            state = self._provider_state_value(binding, record)
            return ProviderBindingState(
                provider_key=binding.provider_key,
                display_name=binding.display_name,
                executable=binding.executable,
                enabled=self._to_state_bool(record, fallback=secret_configured or binding.executable),
                source=binding.source,
                auth_mode=auth_mode,
                secret_env_names=secret_env_names,
                secret_configured=secret_configured,
                capabilities=tuple(capability.capability_key for capability in binding.capabilities),
                tool_names=tuple(capability.tool_name for capability in binding.capabilities),
                state=state,
                status=status,
                priority=record.priority if record is not None else 100,
                binding_id=record.binding_id if record is not None else "",
                health_state=str(record.probe_state or "unknown") if record is not None else "unknown",
                health_details_json=dict(record.probe_details_json or {})
                if record is not None
                else {},
                updated_at=record.updated_at if record is not None else "",
            )
        return None

    def list_binding_states(self, principal_id: str | None = None) -> tuple[ProviderBindingState, ...]:
        states: list[ProviderBindingState] = []
        for binding in self._bindings:
            state = self.binding_state(binding.provider_key, principal_id=principal_id)
            if state is not None:
                states.append(state)

        for record in self._list_binding_records(principal_id=principal_id):
            normalized_provider = self._normalize_provider_key(record.provider_key)
            if any(state.provider_key == normalized_provider for state in states):
                continue
            synthetic = self.binding_state(normalized_provider, principal_id=principal_id)
            if synthetic is not None:
                states.append(synthetic)
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
        principal_id: str | None = None,
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
            record = self._get_binding_record(principal_id=principal_id, provider_key=binding.provider_key)
            if record is not None and str(record.status or "").strip().lower() == "disabled":
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
                    record = self._get_binding_record(principal_id=None, provider_key=binding.provider_key)
                    if record is not None and str(record.status or "").strip().lower() == "disabled":
                        continue
                    return CapabilityRoute(
                        provider_key=binding.provider_key,
                        capability_key=capability.capability_key,
                        tool_name=capability.tool_name,
                        executable=True,
                    )
        raise ToolExecutionError(f"provider_tool_unavailable:{normalized_tool}")

    def route_tool_with_context(
        self,
        tool_name: str,
        *,
        principal_id: str | None = None,
    ) -> CapabilityRoute:
        normalized_tool = str(tool_name or "").strip()
        if not normalized_tool:
            raise ToolExecutionError("tool_name_required")
        for binding in self._bindings:
            if not binding.executable:
                continue
            for capability in binding.capabilities:
                if not capability.executable:
                    continue
                if capability.tool_name != normalized_tool:
                    continue
                record = self._get_binding_record(principal_id=principal_id, provider_key=binding.provider_key)
                if record is not None and str(record.status or "").strip().lower() == "disabled":
                    continue
                return CapabilityRoute(
                    provider_key=binding.provider_key,
                    capability_key=capability.capability_key,
                    tool_name=capability.tool_name,
                    executable=capability.executable,
                )
        raise ToolExecutionError(f"provider_tool_unavailable:{normalized_tool}")

    def route_tool_by_capability_with_context(
        self,
        *,
        capability_key: str,
        principal_id: str | None = None,
        provider_hints: tuple[str, ...] = (),
        allowed_tools: tuple[str, ...] = (),
        require_executable: bool = True,
    ) -> CapabilityRoute:
        return self.route_tool_by_capability(
            capability_key=capability_key,
            provider_hints=provider_hints,
            allowed_tools=allowed_tools,
            require_executable=require_executable,
            principal_id=principal_id,
        )

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
            "gemini_web": "gemini_web_generate",
            "browseract_gemini_web": "gemini_web_generate",
            "delivery_dispatch": "dispatch",
            "connector_dispatch": "dispatch",
            "generate_json": "structured_generate",
            "json_generate": "structured_generate",
            "structured_generation": "structured_generate",
            "codegen": "code_generate",
            "code_generation": "code_generate",
            "patch_review": "reasoned_patch_review",
            "review_patch": "reasoned_patch_review",
            "review_code": "reasoned_patch_review",
            "media": "media_transform",
        }
        return aliases.get(normalized, normalized)

    def _normalize_provider_key(self, value: object) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "1min.ai": "onemin",
            "1min_ai": "onemin",
            "ai_magicx": "magixai",
            "magicxai": "magixai",
            "aimagicx": "magixai",
            "chatplayground": "browseract",
            "chat_playground": "browseract",
            "chatplay": "browseract",
            "gemini_web": "browseract",
            "browserly.ai": "browserly",
            "browsely": "browserly",
            "prompting.systems": "prompting_systems",
            "gemini": "gemini_vortex",
            "gemini_cli": "gemini_vortex",
            "vortex": "gemini_vortex",
            "gemini_vortex": "gemini_vortex",
        }
        return aliases.get(normalized, normalized)
