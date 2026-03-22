from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.domain.models import ProviderBindingState, SkillContract, now_utc_iso
from app.repositories.provider_bindings import ProviderBindingRecord, ProviderBindingRepository
from app.services.browseract_ui_service_catalog import browseract_ui_service_definitions
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


def _principal_override_map(env_name: str) -> dict[str, str]:
    raw = str(os.environ.get(env_name) or "").strip()
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    payload: dict[str, str] = {}
    for key, value in loaded.items():
        normalized_key = str(key or "").strip()
        normalized_value = str(value or "").strip()
        if normalized_key and normalized_value:
            payload[normalized_key] = normalized_value
    return payload


def _principal_label(principal_id: object) -> str:
    normalized = str(principal_id or "").strip()
    if not normalized:
        return "system"
    overrides = _principal_override_map("EA_PRINCIPAL_LABEL_OVERRIDES_JSON")
    return str(overrides.get(normalized) or normalized).strip() or normalized


def _principal_owner_category(principal_id: object) -> str:
    normalized = str(principal_id or "").strip()
    if not normalized:
        return "system"
    overrides = _principal_override_map("EA_PRINCIPAL_OWNER_CATEGORY_OVERRIDES_JSON")
    override = str(overrides.get(normalized) or "").strip().lower()
    if override in {"participant", "operator", "system"}:
        return override
    lowered = normalized.lower().replace("_", "-")
    if (
        lowered.startswith(("participant", "acct-participant", "lane-participant", "chatgpt-participant"))
        or "-participant-" in lowered
        or lowered.endswith("-participant")
    ):
        return "participant"
    if lowered.startswith(("system", "scheduler", "health", "survival", "automation", "telemetry", "cron", "daemon")):
        return "system"
    return "operator"


def _principal_hub_user_id(principal_id: object) -> str:
    normalized = str(principal_id or "").strip()
    if not normalized:
        return ""
    return str(_principal_override_map("EA_PRINCIPAL_HUB_USER_OVERRIDES_JSON").get(normalized) or "").strip()


def _principal_hub_group_id(principal_id: object) -> str:
    normalized = str(principal_id or "").strip()
    if not normalized:
        return ""
    return str(_principal_override_map("EA_PRINCIPAL_HUB_GROUP_OVERRIDES_JSON").get(normalized) or "").strip()


def _principal_sponsor_session_id(principal_id: object) -> str:
    normalized = str(principal_id or "").strip()
    if not normalized:
        return ""
    return str(_principal_override_map("EA_PRINCIPAL_SPONSOR_SESSION_OVERRIDES_JSON").get(normalized) or "").strip()


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


@dataclass(frozen=True)
class ProviderRegistryCapabilityView:
    capability_key: str
    tool_name: str
    executable: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "capability_key": self.capability_key,
            "tool_name": self.tool_name,
            "executable": self.executable,
        }


@dataclass(frozen=True)
class ProviderRegistryProviderView:
    provider_key: str
    display_name: str
    health_provider_key: str
    backend: str
    source: str
    executable: bool
    enabled: bool
    state: str
    status: str
    auth_mode: str
    priority: int
    binding_id: str
    secret_configured: bool
    health_state: str
    detail: str
    capabilities: tuple[ProviderRegistryCapabilityView, ...]
    slot_pool: dict[str, object] = field(default_factory=dict)
    capacity: dict[str, object] = field(default_factory=dict)
    last_used_principal_id: str = ""
    last_used_principal_label: str = ""
    last_used_owner_category: str = ""
    last_used_lane_role: str = ""
    last_used_hub_user_id: str = ""
    last_used_hub_group_id: str = ""
    last_used_sponsor_session_id: str = ""
    last_used_at: object = None
    active_lease_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_key": self.provider_key,
            "display_name": self.display_name,
            "health_provider_key": self.health_provider_key,
            "backend": self.backend,
            "source": self.source,
            "executable": self.executable,
            "enabled": self.enabled,
            "state": self.state,
            "status": self.status,
            "auth_mode": self.auth_mode,
            "priority": self.priority,
            "binding_id": self.binding_id,
            "secret_configured": self.secret_configured,
            "health_state": self.health_state,
            "detail": self.detail,
            "capabilities": [item.as_dict() for item in self.capabilities],
            "slot_pool": dict(self.slot_pool or {}),
            "capacity": dict(self.capacity or {}),
            "last_used_principal_id": self.last_used_principal_id,
            "last_used_principal_label": self.last_used_principal_label,
            "last_used_owner_category": self.last_used_owner_category,
            "last_used_lane_role": self.last_used_lane_role,
            "last_used_hub_user_id": self.last_used_hub_user_id,
            "last_used_hub_group_id": self.last_used_hub_group_id,
            "last_used_sponsor_session_id": self.last_used_sponsor_session_id,
            "last_used_at": self.last_used_at,
            "active_lease_count": self.active_lease_count,
        }


@dataclass(frozen=True)
class ProviderRegistryLaneView:
    profile: str
    lane: str
    public_model: str
    brain: str
    backend: str
    health_provider_key: str
    provider_hint_order: tuple[str, ...]
    review_required: bool
    needs_review: bool
    merge_policy: str
    primary_provider_key: str
    primary_state: str
    providers: tuple[ProviderRegistryProviderView, ...]
    capacity_summary: dict[str, object] = field(default_factory=dict)
    last_used_principal_id: str = ""
    last_used_principal_label: str = ""
    last_used_owner_category: str = ""
    last_used_lane_role: str = ""
    last_used_hub_user_id: str = ""
    last_used_hub_group_id: str = ""
    last_used_sponsor_session_id: str = ""
    last_used_at: object = None

    def as_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "lane": self.lane,
            "public_model": self.public_model,
            "brain": self.brain,
            "backend": self.backend,
            "health_provider_key": self.health_provider_key,
            "provider_hint_order": list(self.provider_hint_order),
            "review_required": self.review_required,
            "needs_review": self.needs_review,
            "merge_policy": self.merge_policy,
            "primary_provider_key": self.primary_provider_key,
            "primary_state": self.primary_state,
            "providers": [item.as_dict() for item in self.providers],
            "capacity_summary": dict(self.capacity_summary or {}),
            "last_used_principal_id": self.last_used_principal_id,
            "last_used_principal_label": self.last_used_principal_label,
            "last_used_owner_category": self.last_used_owner_category,
            "last_used_lane_role": self.last_used_lane_role,
            "last_used_hub_user_id": self.last_used_hub_user_id,
            "last_used_hub_group_id": self.last_used_hub_group_id,
            "last_used_sponsor_session_id": self.last_used_sponsor_session_id,
            "last_used_at": self.last_used_at,
        }


class ProviderRegistryService:
    def __init__(
        self,
        provider_binding_repo: ProviderBindingRepository | None = None,
    ) -> None:
        self._provider_binding_repo = provider_binding_repo
        browseract_ui_capabilities = tuple(
            ProviderCapability(
                provider_key="browseract",
                capability_key=service.capability_key,
                tool_name=service.tool_name,
            )
            for service in browseract_ui_service_definitions()
        )
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
                    ProviderCapability(
                        provider_key="browseract",
                        capability_key="crezlo_property_tour",
                        tool_name="browseract.crezlo_property_tour",
                    ),
                    *browseract_ui_capabilities,
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
                provider_key="google_gmail",
                display_name="Google Gmail",
                executable=False,
                capabilities=(
                    ProviderCapability(
                        provider_key="google_gmail",
                        capability_key="oauth_connect",
                        tool_name="provider.google_gmail.oauth_connect",
                        executable=False,
                    ),
                    ProviderCapability(
                        provider_key="google_gmail",
                        capability_key="gmail_send",
                        tool_name="provider.google_gmail.gmail_send",
                        executable=False,
                    ),
                    ProviderCapability(
                        provider_key="google_gmail",
                        capability_key="gmail_smoke_test",
                        tool_name="provider.google_gmail.gmail_smoke_test",
                        executable=False,
                    ),
                ),
                source="catalog",
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
            "google_gmail": (
                "EA_GOOGLE_OAUTH_CLIENT_ID",
                "EA_GOOGLE_OAUTH_CLIENT_SECRET",
                "EA_GOOGLE_OAUTH_REDIRECT_URI",
                "EA_GOOGLE_OAUTH_STATE_SECRET",
                "EA_PROVIDER_SECRET_KEY",
            ),
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
        if binding.provider_key == "google_gmail":
            return "oauth"
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
        if auth_mode == "oauth" and binding.provider_key == "google_gmail":
            return all(
                str(os.environ.get(name) or "").strip()
                for name in (
                    "EA_GOOGLE_OAUTH_CLIENT_ID",
                    "EA_GOOGLE_OAUTH_CLIENT_SECRET",
                    "EA_GOOGLE_OAUTH_REDIRECT_URI",
                    "EA_GOOGLE_OAUTH_STATE_SECRET",
                    "EA_PROVIDER_SECRET_KEY",
                )
            )
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

    def _health_provider_keys(self, provider_key: str) -> tuple[str, ...]:
        normalized = self._normalize_provider_key(provider_key)
        aliases = {
            "browseract": ("chatplayground", "browseract"),
            "chatplayground": ("chatplayground", "browseract"),
        }
        return aliases.get(normalized, (normalized,))

    def _provider_health_payload(
        self,
        *,
        provider_key: str,
        provider_health: dict[str, object] | None,
    ) -> tuple[str, dict[str, object]]:
        providers = dict(((provider_health or {}).get("providers")) or {})
        for health_provider_key in self._health_provider_keys(provider_key):
            payload = dict(providers.get(health_provider_key) or {})
            if payload:
                return health_provider_key, payload
        return "", {}

    @staticmethod
    def _slot_pool_summary(provider_payload: dict[str, object]) -> dict[str, object]:
        slots = [dict(item) for item in provider_payload.get("slots") or [] if isinstance(item, dict)]
        states = Counter(str(item.get("state") or "unknown").strip().lower() or "unknown" for item in slots)
        owners = list(
            dict.fromkeys(
                str(item.get("slot_owner") or item.get("owner_label") or item.get("owner_name") or "").strip()
                for item in slots
                if str(item.get("slot_owner") or item.get("owner_label") or item.get("owner_name") or "").strip()
            )
        )
        lease_holders = list(
            dict.fromkeys(
                str(item.get("lease_holder") or "").strip()
                for item in slots
                if str(item.get("lease_holder") or "").strip()
            )
        )
        last_used_slots = sorted(
            slots,
            key=lambda item: str(item.get("last_used_at") or item.get("last_probe_at") or ""),
            reverse=True,
        )
        last_used_slot = last_used_slots[0] if last_used_slots else {}
        last_used_principal_id = str(
            last_used_slot.get("last_used_principal_id")
            or last_used_slot.get("lease_holder")
            or provider_payload.get("last_used_principal_id")
            or ""
        ).strip()
        configured_slots = int(provider_payload.get("configured_slots") or len(slots))
        ready_slots = int(states.get("ready", 0))
        degraded_slots = sum(int(states.get(name, 0)) for name in ("degraded", "cooldown", "maintenance"))
        unavailable_slots = max(configured_slots - ready_slots - degraded_slots, 0)
        return {
            "configured_slots": configured_slots,
            "slot_count": len(slots),
            "slot_state_counts": dict(states),
            "ready_slots": ready_slots,
            "degraded_slots": degraded_slots,
            "unavailable_slots": unavailable_slots,
            "leased_slots": len(lease_holders),
            "owners": owners,
            "lease_holders": lease_holders,
            "selection_mode": str(provider_payload.get("selection_mode") or "").strip(),
            "remaining_percent_of_max": provider_payload.get("remaining_percent_of_max"),
            "estimated_hours_remaining_at_current_pace": provider_payload.get("estimated_hours_remaining_at_current_pace"),
            "active_lease_count": int(provider_payload.get("active_lease_count") or len(lease_holders)),
            "last_used_principal_id": last_used_principal_id,
            "last_used_principal_label": str(
                provider_payload.get("last_used_principal_label") or _principal_label(last_used_principal_id)
            ).strip()
            if last_used_principal_id
            else "",
            "last_used_owner_category": str(
                provider_payload.get("last_used_owner_category") or _principal_owner_category(last_used_principal_id)
            ).strip()
            if last_used_principal_id
            else "",
            "last_used_lane_role": str(provider_payload.get("last_used_lane_role") or last_used_slot.get("last_used_lane_role") or "").strip(),
            "last_used_hub_user_id": str(
                provider_payload.get("last_used_hub_user_id") or _principal_hub_user_id(last_used_principal_id)
            ).strip()
            if last_used_principal_id
            else "",
            "last_used_hub_group_id": str(
                provider_payload.get("last_used_hub_group_id") or _principal_hub_group_id(last_used_principal_id)
            ).strip()
            if last_used_principal_id
            else "",
            "last_used_sponsor_session_id": str(
                provider_payload.get("last_used_sponsor_session_id") or _principal_sponsor_session_id(last_used_principal_id)
            ).strip()
            if last_used_principal_id
            else "",
            "last_used_at": provider_payload.get("last_used_at") or last_used_slot.get("last_used_at") or None,
        }

    def _provider_view(
        self,
        *,
        state: ProviderBindingState,
        provider_health: dict[str, object] | None,
    ) -> ProviderRegistryProviderView:
        health_provider_key, health_payload = self._provider_health_payload(
            provider_key=state.provider_key,
            provider_health=provider_health,
        )
        capabilities: list[ProviderRegistryCapabilityView] = []
        binding = next((item for item in self._bindings if item.provider_key == state.provider_key), None)
        for capability in ((binding.capabilities if binding is not None else ()) or ()):
            capabilities.append(
                ProviderRegistryCapabilityView(
                    capability_key=capability.capability_key,
                    tool_name=capability.tool_name,
                    executable=bool(state.executable and capability.executable),
                )
            )
        effective_state = str(health_payload.get("state") or state.state or "unknown").strip() or "unknown"
        detail = str(health_payload.get("detail") or "").strip() or str((state.health_details_json or {}).get("detail") or "").strip()
        capacity = {
            "state": effective_state,
            "remaining_percent_of_max": health_payload.get("remaining_percent_of_max"),
            "estimated_hours_remaining_at_current_pace": health_payload.get("estimated_hours_remaining_at_current_pace"),
            "estimated_remaining_credits_total": health_payload.get("estimated_remaining_credits_total"),
            "max_requests_per_hour": health_payload.get("max_requests_per_hour"),
            "max_credits_per_hour": health_payload.get("max_credits_per_hour"),
            "max_credits_per_day": health_payload.get("max_credits_per_day"),
            "detail": detail,
        }
        slot_pool_summary = self._slot_pool_summary(health_payload)
        last_used_principal_id = str(
            health_payload.get("last_used_principal_id") or slot_pool_summary.get("last_used_principal_id") or ""
        ).strip()
        return ProviderRegistryProviderView(
            provider_key=state.provider_key,
            display_name=state.display_name,
            health_provider_key=health_provider_key or state.provider_key,
            backend=str(health_payload.get("backend") or state.provider_key).strip() or state.provider_key,
            source=state.source,
            executable=bool(state.executable),
            enabled=bool(state.enabled),
            state=effective_state,
            status=state.status,
            auth_mode=state.auth_mode,
            priority=int(state.priority or 0),
            binding_id=state.binding_id,
            secret_configured=bool(state.secret_configured),
            health_state=str(state.health_state or "unknown"),
            detail=detail,
            capabilities=tuple(capabilities),
            slot_pool=slot_pool_summary,
            capacity=capacity,
            last_used_principal_id=last_used_principal_id,
            last_used_principal_label=str(
                health_payload.get("last_used_principal_label")
                or slot_pool_summary.get("last_used_principal_label")
                or _principal_label(last_used_principal_id)
            ).strip()
            if last_used_principal_id
            else "",
            last_used_owner_category=str(
                health_payload.get("last_used_owner_category")
                or slot_pool_summary.get("last_used_owner_category")
                or _principal_owner_category(last_used_principal_id)
            ).strip()
            if last_used_principal_id
            else "",
            last_used_lane_role=str(
                health_payload.get("last_used_lane_role")
                or slot_pool_summary.get("last_used_lane_role")
                or ""
            ).strip(),
            last_used_hub_user_id=str(
                health_payload.get("last_used_hub_user_id")
                or slot_pool_summary.get("last_used_hub_user_id")
                or _principal_hub_user_id(last_used_principal_id)
            ).strip()
            if last_used_principal_id
            else "",
            last_used_hub_group_id=str(
                health_payload.get("last_used_hub_group_id")
                or slot_pool_summary.get("last_used_hub_group_id")
                or _principal_hub_group_id(last_used_principal_id)
            ).strip()
            if last_used_principal_id
            else "",
            last_used_sponsor_session_id=str(
                health_payload.get("last_used_sponsor_session_id")
                or slot_pool_summary.get("last_used_sponsor_session_id")
                or _principal_sponsor_session_id(last_used_principal_id)
            ).strip()
            if last_used_principal_id
            else "",
            last_used_at=health_payload.get("last_used_at") or slot_pool_summary.get("last_used_at"),
            active_lease_count=int(health_payload.get("active_lease_count") or slot_pool_summary.get("active_lease_count") or 0),
        )

    @staticmethod
    def _decision_field(decision: object, field_name: str, default: object = "") -> object:
        if isinstance(decision, dict):
            return decision.get(field_name, default)
        return getattr(decision, field_name, default)

    @staticmethod
    def _lane_capacity_summary(primary: ProviderRegistryProviderView | None) -> dict[str, object]:
        if primary is None:
            return {
                "state": "unknown",
                "configured_slots": 0,
                "ready_slots": 0,
                "degraded_slots": 0,
                "leased_slots": 0,
                "slot_owners": [],
                "lease_holders": [],
                "selection_mode": "",
                "remaining_percent_of_max": None,
                "estimated_hours_remaining_at_current_pace": None,
                "estimated_remaining_credits_total": None,
                "active_lease_count": 0,
                "last_used_principal_id": "",
                "last_used_principal_label": "",
                "last_used_owner_category": "",
                "last_used_lane_role": "",
                "last_used_hub_user_id": "",
                "last_used_hub_group_id": "",
                "last_used_sponsor_session_id": "",
                "last_used_at": None,
            }
        slot_pool = dict(primary.slot_pool or {})
        capacity = dict(primary.capacity or {})
        return {
            "state": str(capacity.get("state") or primary.state or "unknown").strip() or "unknown",
            "configured_slots": int(slot_pool.get("configured_slots") or 0),
            "ready_slots": int(slot_pool.get("ready_slots") or 0),
            "degraded_slots": int(slot_pool.get("degraded_slots") or 0),
            "leased_slots": int(slot_pool.get("leased_slots") or 0),
            "slot_owners": list(slot_pool.get("owners") or []),
            "lease_holders": list(slot_pool.get("lease_holders") or []),
            "selection_mode": str(slot_pool.get("selection_mode") or "").strip(),
            "remaining_percent_of_max": capacity.get("remaining_percent_of_max"),
            "estimated_hours_remaining_at_current_pace": capacity.get("estimated_hours_remaining_at_current_pace"),
            "estimated_remaining_credits_total": capacity.get("estimated_remaining_credits_total"),
            "active_lease_count": int(slot_pool.get("active_lease_count") or primary.active_lease_count or 0),
            "last_used_principal_id": str(slot_pool.get("last_used_principal_id") or primary.last_used_principal_id or "").strip(),
            "last_used_principal_label": str(
                slot_pool.get("last_used_principal_label") or primary.last_used_principal_label or ""
            ).strip(),
            "last_used_owner_category": str(
                slot_pool.get("last_used_owner_category") or primary.last_used_owner_category or ""
            ).strip(),
            "last_used_lane_role": str(
                slot_pool.get("last_used_lane_role") or primary.last_used_lane_role or ""
            ).strip(),
            "last_used_hub_user_id": str(
                slot_pool.get("last_used_hub_user_id") or primary.last_used_hub_user_id or ""
            ).strip(),
            "last_used_hub_group_id": str(
                slot_pool.get("last_used_hub_group_id") or primary.last_used_hub_group_id or ""
            ).strip(),
            "last_used_sponsor_session_id": str(
                slot_pool.get("last_used_sponsor_session_id") or primary.last_used_sponsor_session_id or ""
            ).strip(),
            "last_used_at": slot_pool.get("last_used_at") or primary.last_used_at,
        }

    def registry_read_model(
        self,
        *,
        principal_id: str | None = None,
        provider_health: dict[str, object] | None = None,
        profile_decisions: Sequence[object] = (),
    ) -> dict[str, object]:
        provider_views = {
            state.provider_key: self._provider_view(state=state, provider_health=provider_health)
            for state in self.list_binding_states(principal_id=principal_id)
        }
        capability_index: dict[str, dict[str, object]] = {}
        for provider in provider_views.values():
            for capability in provider.capabilities:
                entry = capability_index.setdefault(
                    capability.capability_key,
                    {
                        "capability_key": capability.capability_key,
                        "providers": [],
                        "executable_providers": [],
                        "tool_routes": [],
                    },
                )
                entry["providers"].append(provider.provider_key)
                if capability.executable:
                    entry["executable_providers"].append(provider.provider_key)
                entry["tool_routes"].append(
                    {
                        "provider_key": provider.provider_key,
                        "tool_name": capability.tool_name,
                        "executable": capability.executable,
                    }
                )

        lane_views: list[ProviderRegistryLaneView] = []
        for decision in profile_decisions:
            provider_hint_order = tuple(
                str(value or "").strip()
                for value in (self._decision_field(decision, "provider_hint_order", ()) or ())
                if str(value or "").strip()
            )
            lane_providers = tuple(
                provider_views[provider_key]
                for provider_key in provider_hint_order
                if provider_key in provider_views
            )
            primary = lane_providers[0] if lane_providers else None
            capacity_summary = self._lane_capacity_summary(primary)
            lane_views.append(
                ProviderRegistryLaneView(
                    profile=str(self._decision_field(decision, "profile", "") or ""),
                    lane=str(self._decision_field(decision, "lane", "") or ""),
                    public_model=str(self._decision_field(decision, "public_model", "") or ""),
                    brain=str(self._decision_field(decision, "public_model", "") or ""),
                    backend=str(self._decision_field(decision, "backend_key", "") or (primary.backend if primary else "")),
                    health_provider_key=str(
                        self._decision_field(decision, "health_provider_key", "") or (primary.health_provider_key if primary else "")
                    ),
                    provider_hint_order=provider_hint_order,
                    review_required=bool(self._decision_field(decision, "review_required", False)),
                    needs_review=bool(self._decision_field(decision, "needs_review", False)),
                    merge_policy=str(self._decision_field(decision, "merge_policy", "auto") or "auto"),
                    primary_provider_key=primary.provider_key if primary is not None else "",
                    primary_state=primary.state if primary is not None else "unknown",
                    providers=lane_providers,
                    capacity_summary=capacity_summary,
                    last_used_principal_id=str(capacity_summary.get("last_used_principal_id") or ""),
                    last_used_principal_label=str(capacity_summary.get("last_used_principal_label") or ""),
                    last_used_owner_category=str(capacity_summary.get("last_used_owner_category") or ""),
                    last_used_lane_role=str(capacity_summary.get("last_used_lane_role") or ""),
                    last_used_hub_user_id=str(capacity_summary.get("last_used_hub_user_id") or ""),
                    last_used_hub_group_id=str(capacity_summary.get("last_used_hub_group_id") or ""),
                    last_used_sponsor_session_id=str(capacity_summary.get("last_used_sponsor_session_id") or ""),
                    last_used_at=capacity_summary.get("last_used_at"),
                )
            )

        return {
            "contract_name": "ea.provider_registry",
            "contract_version": "2026-03-18",
            "generated_at": now_utc_iso(),
            "principal_id": self._normalize_principal_id(principal_id),
            "principal_label": _principal_label(principal_id),
            "principal_owner_category": _principal_owner_category(principal_id),
            "provider_count": len(provider_views),
            "lane_count": len(lane_views),
            "capability_count": len(capability_index),
            "providers": [row.as_dict() for row in provider_views.values()],
            "lanes": [row.as_dict() for row in lane_views],
            "capabilities": sorted(capability_index.values(), key=lambda item: str(item.get("capability_key") or "")),
        }

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

    def candidate_routes_by_capability_with_context(
        self,
        *,
        capability_key: str,
        principal_id: str | None = None,
        provider_hints: tuple[str, ...] = (),
        allowed_tools: tuple[str, ...] = (),
        require_executable: bool = True,
    ) -> tuple[CapabilityRoute, ...]:
        normalized_capability = self._normalize_capability_key(capability_key)
        if not normalized_capability:
            raise ToolExecutionError("provider_capability_required")
        normalized_hints = tuple(
            hint
            for hint in (self._normalize_provider_key(value) for value in provider_hints)
            if hint
        )
        allowed_tool_set = {str(value or "").strip() for value in allowed_tools if str(value or "").strip()}
        hint_priority = {provider: index for index, provider in enumerate(normalized_hints)}
        candidates: list[tuple[int, str, CapabilityRoute]] = []
        for binding in self._bindings:
            record = self._get_binding_record(principal_id=principal_id, provider_key=binding.provider_key)
            if record is not None and str(record.status or "").strip().lower() == "disabled":
                continue
            if require_executable and not binding.executable:
                continue
            for capability in binding.capabilities:
                if self._normalize_capability_key(capability.capability_key) != normalized_capability:
                    continue
                if require_executable and not capability.executable:
                    continue
                if allowed_tool_set and capability.tool_name not in allowed_tool_set:
                    continue
                priority = hint_priority.get(self._normalize_provider_key(binding.provider_key), len(normalized_hints))
                route = CapabilityRoute(
                    provider_key=binding.provider_key,
                    capability_key=capability.capability_key,
                    tool_name=capability.tool_name,
                    executable=binding.executable and capability.executable,
                )
                candidates.append((priority, str(route.tool_name or ""), route))
        candidates.sort(key=lambda item: (item[0], item[1]))
        return tuple(route for _, _, route in candidates)

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
            "property_tour": "crezlo_property_tour",
            "create_property_tour": "crezlo_property_tour",
            "crezlo_tour": "crezlo_property_tour",
            "crezlo_property_tour_create": "crezlo_property_tour",
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
        for service in browseract_ui_service_definitions():
            aliases.setdefault(service.capability_key, service.capability_key)
            aliases.setdefault(service.service_key, service.capability_key)
            aliases.setdefault(service.task_key, service.capability_key)
            aliases.setdefault(service.skill_key, service.capability_key)
            for alias in service.aliases:
                normalized_alias = str(alias or "").strip().lower().replace("-", "_").replace(" ", "_")
                if normalized_alias:
                    aliases.setdefault(normalized_alias, service.capability_key)
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
