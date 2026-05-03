from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from urllib.parse import quote

from app.services.browseract_ui_service_catalog import (
    BrowserActUiServiceDefinition,
    browseract_ui_service_by_alias,
)
from app.services.provider_registry import ProviderBinding, ProviderRegistryService


_INVENTORY_SECTION_HEADINGS = (
    "## Non-AppSumo / Other LTDs",
    "## AppSumo LTDs",
)
_TIER_PRIORITY = {
    "tier 1": 4,
    "tier 2": 3,
    "tier 3": 2,
    "tier 4": 1,
}
_PROVIDER_NAME_ALIASES: dict[str, str] = {
    "1min_ai": "onemin",
    "1minai": "onemin",
    "ai_magicx": "magixai",
    "prompting_systems": "prompting_systems",
    "unmixr_ai": "unmixr",
}


@dataclass(frozen=True)
class LtdInventoryRow:
    service_name: str
    plan_tier: str
    holding: str
    status: str
    redeem_by: str
    workspace_integration_tier: str
    local_integration: str
    notes: str


def _inventory_markdown_path(*, module_path: Path | None = None) -> Path:
    configured = str(os.environ.get("EA_LTDS_MARKDOWN_PATH") or "").strip()
    if configured:
        return Path(configured).expanduser()

    resolved_module_path = (module_path or Path(__file__)).resolve()
    candidates = (
        resolved_module_path.parents[3] / "LTDs.md",
        resolved_module_path.parents[2] / "LTDs.md",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "ltd_inventory_markdown_not_found:"
        + ",".join(str(candidate) for candidate in candidates)
    )


_LTDS_PATH = _inventory_markdown_path()


@dataclass(frozen=True)
class LtdRuntimeAction:
    action_key: str
    label: str
    description: str
    execution_mode: str
    executable: bool
    tool_name: str
    action_kind: str
    route_path: str
    provider_key: str
    input_schema_json: dict[str, object]
    notes: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "action_key": self.action_key,
            "label": self.label,
            "description": self.description,
            "execution_mode": self.execution_mode,
            "executable": self.executable,
            "tool_name": self.tool_name,
            "action_kind": self.action_kind,
            "route_path": self.route_path,
            "provider_key": self.provider_key,
            "input_schema_json": dict(self.input_schema_json or {}),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class LtdRuntimeProfile:
    service_name: str
    plan_tier: str
    holding: str
    status: str
    redeem_by: str
    workspace_integration_tier: str
    local_integration: str
    notes: str
    runtime_state: str
    aliases: tuple[str, ...]
    matched_provider_key: str
    matched_provider_display_name: str
    browseract_ui_service_key: str
    actions: tuple[LtdRuntimeAction, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "service_name": self.service_name,
            "plan_tier": self.plan_tier,
            "holding": self.holding,
            "status": self.status,
            "redeem_by": self.redeem_by,
            "workspace_integration_tier": self.workspace_integration_tier,
            "local_integration": self.local_integration,
            "notes": self.notes,
            "runtime_state": self.runtime_state,
            "aliases": list(self.aliases),
            "matched_provider_key": self.matched_provider_key,
            "matched_provider_display_name": self.matched_provider_display_name,
            "browseract_ui_service_key": self.browseract_ui_service_key,
            "actions": [action.as_dict() for action in self.actions],
        }


def _normalize_lookup(value: object) -> str:
    lowered = str(value or "").strip().strip("`").lower()
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def _alias_variants(*values: object) -> tuple[str, ...]:
    aliases: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip().strip("`")
        if not text:
            continue
        normalized = _normalize_lookup(text)
        words = [part for part in re.split(r"[^a-z0-9]+", text.lower()) if part]
        candidates = (
            text,
            text.lower(),
            normalized,
            normalized.replace("_", ""),
            "_".join(words),
            "-".join(words),
            "".join(words),
        )
        for candidate in candidates:
            cleaned = str(candidate or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            aliases.append(cleaned)
    return tuple(aliases)


def _humanize_action_key(value: str) -> str:
    words = [part for part in _normalize_lookup(value).split("_") if part]
    return " ".join(word.capitalize() for word in words) or "Action"


def _table_bounds(lines: list[str], heading: str) -> tuple[int, int]:
    try:
        heading_index = next(index for index, value in enumerate(lines) if value.strip() == heading)
    except StopIteration as exc:
        raise ValueError(f"inventory_heading_not_found:{heading}") from exc
    try:
        table_start = next(
            index for index in range(heading_index + 1, len(lines)) if lines[index].strip().startswith("|")
        )
    except StopIteration as exc:
        raise ValueError(f"inventory_table_not_found:{heading}") from exc
    table_end = table_start
    while table_end < len(lines) and lines[table_end].strip().startswith("|"):
        table_end += 1
    return table_start, table_end


def _parse_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    parts = [part.strip() for part in stripped.strip("|").split("|")]
    return parts if len(parts) >= 8 else None


def parse_ltd_inventory_markdown(markdown_text: str) -> tuple[LtdInventoryRow, ...]:
    lines = markdown_text.splitlines()
    rows: list[LtdInventoryRow] = []
    for heading in _INVENTORY_SECTION_HEADINGS:
        table_start, table_end = _table_bounds(lines, heading)
        for line in lines[table_start + 2 : table_end]:
            parts = _parse_table_row(line)
            if parts is None:
                continue
            rows.append(
                LtdInventoryRow(
                    service_name=str(parts[0]).strip().strip("`"),
                    plan_tier=str(parts[1]).strip().strip("`"),
                    holding=str(parts[2]).strip(),
                    status=str(parts[3]).strip(),
                    redeem_by=str(parts[4]).strip(),
                    workspace_integration_tier=str(parts[5]).strip().strip("`"),
                    local_integration=str(parts[6]).strip(),
                    notes=str(parts[7]).strip(),
                )
            )
    return tuple(rows)


def load_ltd_inventory_rows(markdown_path: Path | None = None) -> tuple[LtdInventoryRow, ...]:
    path = markdown_path or _inventory_markdown_path()
    return parse_ltd_inventory_markdown(path.read_text(encoding="utf-8"))


def _provider_aliases(binding: ProviderBinding) -> tuple[str, ...]:
    normalized_provider = _normalize_lookup(binding.provider_key)
    aliases = _alias_variants(
        binding.provider_key,
        binding.display_name,
        _PROVIDER_NAME_ALIASES.get(normalized_provider, ""),
    )
    if normalized_provider == "onemin":
        aliases = _alias_variants(*aliases, "1min.ai", "1min ai")
    elif normalized_provider == "magixai":
        aliases = _alias_variants(*aliases, "ai magicx")
    elif normalized_provider == "unmixr":
        aliases = _alias_variants(*aliases, "unmixr ai")
    return aliases


def _provider_index(provider_registry: ProviderRegistryService) -> dict[str, ProviderBinding]:
    index: dict[str, ProviderBinding] = {}
    for binding in provider_registry.list_bindings():
        for alias in _provider_aliases(binding):
            normalized = _normalize_lookup(alias)
            if normalized:
                index.setdefault(normalized, binding)
    return index


def _matched_provider(row: LtdInventoryRow, *, provider_index: dict[str, ProviderBinding]) -> ProviderBinding | None:
    for alias in _alias_variants(row.service_name):
        matched = provider_index.get(_normalize_lookup(alias))
        if matched is not None:
            return matched
    return None


def _matched_browseract_ui_service(row: LtdInventoryRow) -> BrowserActUiServiceDefinition | None:
    candidates = _alias_variants(row.service_name)
    for candidate in candidates:
        matched = browseract_ui_service_by_alias(candidate)
        if matched is not None:
            return matched
    return None


def _discover_account_action(row: LtdInventoryRow) -> LtdRuntimeAction:
    encoded_service = quote(row.service_name, safe="")
    return LtdRuntimeAction(
        action_key="discover_account",
        label="Discover Account Facts",
        description=f"Use BrowserAct account discovery to refresh facts for {row.service_name}.",
        execution_mode="tool_execution",
        executable=True,
        tool_name="browseract.extract_account_facts",
        action_kind="account.extract",
        route_path=f"/v1/ltds/runtime-catalog/{encoded_service}/discover-account",
        provider_key="browseract",
        input_schema_json={
            "type": "object",
            "required": ["binding_id"],
            "properties": {
                "binding_id": {"type": "string"},
                "requested_fields": {"type": "array", "items": {"type": "string"}},
                "instructions": {"type": "string"},
                "run_url": {"type": "string"},
            },
        },
        notes="Requires an enabled BrowserAct connector binding for the target principal.",
    )


def _browseract_ui_action(row: LtdInventoryRow, service: BrowserActUiServiceDefinition) -> LtdRuntimeAction:
    encoded_service = quote(row.service_name, safe="")
    action_key = "inspect_workspace"
    route_path = f"/v1/ltds/runtime-catalog/{encoded_service}/inspect-workspace"
    if "queue" in service.service_key:
        action_key = "read_queue"
        route_path = f"/v1/ltds/runtime-catalog/{encoded_service}/actions/{action_key}"
    elif "results" in service.service_key:
        action_key = "read_results"
        route_path = f"/v1/ltds/runtime-catalog/{encoded_service}/actions/{action_key}"
    elif "movie" in service.service_key:
        action_key = "create_movie"
        route_path = f"/v1/ltds/runtime-catalog/{encoded_service}/actions/{action_key}"
    elif "flyover" in service.service_key:
        action_key = "create_flyover"
        route_path = f"/v1/ltds/runtime-catalog/{encoded_service}/actions/{action_key}"
    return LtdRuntimeAction(
        action_key=action_key,
        label=service.name,
        description=service.description,
        execution_mode="tool_execution",
        executable=True,
        tool_name=service.tool_name,
        action_kind=service.action_kind,
        route_path=route_path,
        provider_key="browseract",
        input_schema_json=service.input_schema_json(),
        notes=f"BrowserAct template-backed lane via {service.service_key}.",
    )


def _crezlo_property_tour_action(row: LtdInventoryRow) -> LtdRuntimeAction | None:
    if _normalize_lookup(row.service_name) not in {"crezlo_tours", "crezlo"}:
        return None
    encoded_service = quote(row.service_name, safe="")
    return LtdRuntimeAction(
        action_key="create_property_tour",
        label="Create Property Tour",
        description="Run the BrowserAct-backed Crezlo property-tour pipeline.",
        execution_mode="tool_execution",
        executable=True,
        tool_name="browseract.crezlo_property_tour",
        action_kind="property_tour.create",
        route_path=f"/v1/ltds/runtime-catalog/{encoded_service}/actions/create_property_tour",
        provider_key="browseract",
        input_schema_json={
            "type": "object",
            "required": ["binding_id", "property_json"],
            "properties": {
                "binding_id": {"type": "string"},
                "property_json": {"type": "object"},
                "result_title": {"type": "string"},
                "workflow_id": {"type": "string"},
                "run_url": {"type": "string"},
            },
        },
        notes="Requires the Crezlo BrowserAct workflow metadata on the binding or an explicit run target.",
    )


def _provider_actions(binding: ProviderBinding, service_name: str) -> tuple[LtdRuntimeAction, ...]:
    if not binding.executable:
        return ()
    encoded_service = quote(service_name, safe="")
    actions: list[LtdRuntimeAction] = []
    for capability in binding.capabilities:
        if not capability.executable:
            continue
        action_key = _normalize_lookup(capability.capability_key)
        if action_key in {"account_facts", "account_inventory"}:
            continue
        actions.append(
            LtdRuntimeAction(
                action_key=action_key,
                label=_humanize_action_key(action_key),
                description=f"Invoke {binding.display_name} capability `{capability.capability_key}` directly.",
                execution_mode="tool_execution",
                executable=True,
                tool_name=capability.tool_name,
                action_kind=capability.capability_key,
                route_path=f"/v1/ltds/runtime-catalog/{encoded_service}/actions/{action_key}",
                provider_key=binding.provider_key,
                input_schema_json={"type": "object", "properties": {}},
                notes="Uses the provider's existing runtime contract; payload shape depends on the underlying tool.",
            )
        )
    return tuple(actions)


def _onemin_specialized_actions(binding: ProviderBinding, service_name: str) -> tuple[LtdRuntimeAction, ...]:
    if str(binding.provider_key or "").strip().lower() != "onemin":
        return ()
    media_transform = next(
        (
            capability
            for capability in binding.capabilities
            if capability.executable and str(capability.capability_key or "").strip().lower() == "media_transform"
        ),
        None,
    )
    if media_transform is None:
        return ()
    encoded_service = quote(service_name, safe="")
    return (
        LtdRuntimeAction(
            action_key="background_remove",
            label="Background Remove",
            description="Remove the background from an image with 1min.AI.",
            execution_mode="tool_execution",
            executable=True,
            tool_name=media_transform.tool_name,
            action_kind=media_transform.capability_key,
            route_path=f"/v1/ltds/runtime-catalog/{encoded_service}/actions/background_remove",
            provider_key=binding.provider_key,
            input_schema_json={
                "type": "object",
                "required": ["image_url"],
                "properties": {
                    "image_url": {"type": "string"},
                    "output_format": {"type": "string"},
                    "model": {"type": "string"},
                },
            },
            notes="Defaults feature_type=BACKGROUND_REMOVER and accepts a top-level image_url.",
        ),
        LtdRuntimeAction(
            action_key="image_upscale",
            label="Image Upscale",
            description="Upscale an image with 1min.AI.",
            execution_mode="tool_execution",
            executable=True,
            tool_name=media_transform.tool_name,
            action_kind=media_transform.capability_key,
            route_path=f"/v1/ltds/runtime-catalog/{encoded_service}/actions/image_upscale",
            provider_key=binding.provider_key,
            input_schema_json={
                "type": "object",
                "required": ["image_url"],
                "properties": {
                    "image_url": {"type": "string"},
                    "output_format": {"type": "string"},
                    "model": {"type": "string"},
                },
            },
            notes="Defaults feature_type=IMAGE_UPSCALER and accepts a top-level image_url.",
        ),
    )


def _emailit_runtime_action(row: LtdInventoryRow) -> LtdRuntimeAction | None:
    if _normalize_lookup(row.service_name) != "emailit":
        return None
    encoded_service = quote(row.service_name, safe="")
    return LtdRuntimeAction(
        action_key="delivery_outbox",
        label="Delivery Outbox",
        description="Emailit already operates through EA's delivery outbox and sender-domain wiring.",
        execution_mode="runtime_lane",
        executable=False,
        tool_name="",
        action_kind="delivery.outbox.process",
        route_path=f"/v1/ltds/runtime-catalog/{encoded_service}",
        provider_key="emailit",
        input_schema_json={"type": "object", "properties": {}},
        notes="Operational lane exists, but not as a free-form direct tool execution endpoint.",
    )


def _unique_actions(actions: tuple[LtdRuntimeAction | None, ...]) -> tuple[LtdRuntimeAction, ...]:
    deduped: list[LtdRuntimeAction] = []
    seen: set[str] = set()
    for action in actions:
        if action is None:
            continue
        key = str(action.action_key or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return tuple(deduped)


def _runtime_state(
    row: LtdInventoryRow,
    *,
    actions: tuple[LtdRuntimeAction, ...],
    provider_binding: ProviderBinding | None,
    browseract_ui_service: BrowserActUiServiceDefinition | None,
) -> str:
    if any(action.execution_mode == "runtime_lane" for action in actions):
        specific_executable_actions = [action for action in actions if action.executable and action.action_key != "discover_account"]
        if not specific_executable_actions:
            return "runtime_managed"
    if any(action.executable for action in actions):
        if provider_binding is not None and provider_binding.executable:
            return "provider_executable"
        if browseract_ui_service is not None:
            return "browseract_ui_ready"
        return "browseract_discoverable"
    tier_key = str(row.workspace_integration_tier or "").strip().lower()
    if tier_key == "tier 4":
        return "credentials_only"
    if tier_key == "tier 3":
        return "tracked_only"
    if tier_key == "tier 2":
        return "staged"
    return "inventory_only"


class LtdRuntimeCatalogService:
    def __init__(
        self,
        *,
        provider_registry: ProviderRegistryService | None = None,
        markdown_path: Path | None = None,
    ) -> None:
        self._provider_registry = provider_registry or ProviderRegistryService()
        self._markdown_path = markdown_path or _LTDS_PATH

    def list_profiles(self) -> tuple[LtdRuntimeProfile, ...]:
        rows = load_ltd_inventory_rows(self._markdown_path)
        provider_index = _provider_index(self._provider_registry)
        profiles: list[LtdRuntimeProfile] = []
        for row in rows:
            provider_binding = _matched_provider(row, provider_index=provider_index)
            browseract_ui_service = _matched_browseract_ui_service(row)
            actions = _unique_actions(
                (
                    _discover_account_action(row),
                    _browseract_ui_action(row, browseract_ui_service) if browseract_ui_service is not None else None,
                    _crezlo_property_tour_action(row),
                    _emailit_runtime_action(row),
                    *(_onemin_specialized_actions(provider_binding, row.service_name) if provider_binding is not None else ()),
                    *(_provider_actions(provider_binding, row.service_name) if provider_binding is not None else ()),
                )
            )
            aliases = _alias_variants(
                row.service_name,
                provider_binding.display_name if provider_binding is not None else "",
                browseract_ui_service.service_key if browseract_ui_service is not None else "",
                *(browseract_ui_service.aliases if browseract_ui_service is not None else ()),
            )
            profiles.append(
                LtdRuntimeProfile(
                    service_name=row.service_name,
                    plan_tier=row.plan_tier,
                    holding=row.holding,
                    status=row.status,
                    redeem_by=row.redeem_by,
                    workspace_integration_tier=row.workspace_integration_tier,
                    local_integration=row.local_integration,
                    notes=row.notes,
                    runtime_state=_runtime_state(
                        row,
                        actions=actions,
                        provider_binding=provider_binding,
                        browseract_ui_service=browseract_ui_service,
                    ),
                    aliases=aliases,
                    matched_provider_key=str(provider_binding.provider_key if provider_binding is not None else ""),
                    matched_provider_display_name=str(provider_binding.display_name if provider_binding is not None else ""),
                    browseract_ui_service_key=str(browseract_ui_service.service_key if browseract_ui_service is not None else ""),
                    actions=actions,
                )
            )
        profiles.sort(
            key=lambda profile: (
                -_TIER_PRIORITY.get(str(profile.workspace_integration_tier or "").strip().lower(), 0),
                profile.service_name.lower(),
            )
        )
        return tuple(profiles)

    def get_profile(self, service_name: str) -> LtdRuntimeProfile | None:
        normalized = _normalize_lookup(service_name)
        for profile in self.list_profiles():
            if normalized == _normalize_lookup(profile.service_name):
                return profile
            if any(normalized == _normalize_lookup(alias) for alias in profile.aliases):
                return profile
        return None

    def get_action(self, service_name: str, action_key: str) -> LtdRuntimeAction | None:
        profile = self.get_profile(service_name)
        if profile is None:
            return None
        normalized = _normalize_lookup(action_key)
        for action in profile.actions:
            if normalized == _normalize_lookup(action.action_key):
                return action
        return None
