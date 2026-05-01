from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
import pytest

from app.domain.models import PlanValidationError, SkillContract
from app.repositories.provider_bindings import InMemoryProviderBindingRepository
from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.services.brain_router import BrainRouterService
from app.services.planner import PlannerService
from app.services.provider_registry import ProviderRegistryService
from app.services.task_contracts import TaskContractService
from app.services.tool_execution_common import ToolExecutionError


@pytest.fixture(autouse=True)
def _configured_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "python3")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-key")


def test_provider_registry_matches_allowed_tools_and_provider_hints() -> None:
    registry = ProviderRegistryService()
    skill = SkillContract(
        skill_key="inventory_refresh",
        task_key="inventory_refresh",
        name="Inventory Refresh",
        description="refresh inventory",
        deliverable_type="inventory",
        default_risk_class="low",
        default_approval_class="none",
        workflow_template="tool_then_artifact",
        allowed_tools=("browseract.extract_account_inventory", "artifact_repository"),
        evidence_requirements=(),
        memory_write_policy="none",
        memory_reads=(),
        memory_writes=(),
        tags=("inventory",),
        input_schema_json={},
        output_schema_json={},
        authority_profile_json={},
        model_policy_json={},
        provider_hints_json={"preferred": ["browseract"], "research": ["browserly"]},
        tool_policy_json={},
        human_policy_json={},
        evaluation_cases_json=(),
        updated_at="2026-03-12T00:00:00Z",
    )
    bindings = registry.bindings_for_skill(skill)
    keys = {binding.provider_key for binding in bindings}
    assert "browseract" in keys
    assert "browserly" in keys
    assert "artifact_repository" in keys


def test_provider_registry_routes_capability_with_provider_hints() -> None:
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key="account_inventory",
        provider_hints=("BrowserAct",),
        allowed_tools=("browseract.extract_account_inventory", "artifact_repository"),
    )
    assert route.provider_key == "browseract"
    assert route.tool_name == "browseract.extract_account_inventory"
    assert route.executable is True


def test_provider_registry_routes_gemini_vortex_structured_generate_with_alias_hints() -> None:
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key="generate_json",
        provider_hints=("Gemini", "Vortex"),
        allowed_tools=("provider.gemini_vortex.structured_generate", "artifact_repository"),
    )
    assert route.provider_key == "gemini_vortex"
    assert route.capability_key == "structured_generate"
    assert route.tool_name == "provider.gemini_vortex.structured_generate"
    assert route.executable is True


def test_provider_registry_routes_browseract_reasoned_patch_review_with_aliases() -> None:
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key="patch_review",
        provider_hints=("BrowserAct", "chatplayground"),
        allowed_tools=("browseract.chatplayground_audit",),
    )
    assert route.provider_key == "browseract"
    assert route.capability_key == "reasoned_patch_review"
    assert route.tool_name == "browseract.chatplayground_audit"
    assert route.executable is True


def test_provider_registry_routes_magixai_structured_generate_with_alias_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key="generate_json",
        provider_hints=("Magicx",),
        allowed_tools=("provider.magixai.structured_generate", "artifact_repository"),
    )
    assert route.provider_key == "magixai"
    assert route.capability_key == "structured_generate"
    assert route.tool_name == "provider.magixai.structured_generate"
    assert route.executable is True


def test_provider_registry_does_not_route_unconfigured_magixai_when_gemini_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_MAGICX_API_KEY", raising=False)
    repo = InMemoryProviderBindingRepository()
    repo.upsert(principal_id="exec-1", provider_key="gemini_vortex", status="disabled")
    registry = ProviderRegistryService(provider_binding_repo=repo)

    with pytest.raises(ToolExecutionError, match="brain_profile_provider_unavailable:easy:structured_generate"):
        registry.route_brain_profile_capability_with_context(
            profile_name="easy",
            capability_key="structured_generate",
            principal_id="exec-1",
            provider_hints=("gemini_vortex", "magixai"),
            allowed_tools=("provider.gemini_vortex.structured_generate", "provider.magixai.structured_generate"),
        )


def test_provider_registry_does_not_route_unconfigured_browseract_direct_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BROWSERACT_API_KEY", raising=False)
    registry = ProviderRegistryService()

    with pytest.raises(ToolExecutionError, match="provider_capability_unavailable:account_facts"):
        registry.route_tool_by_capability_with_context(
            capability_key="account_facts",
            principal_id="exec-1",
            allowed_tools=("browseract.extract_account_facts",),
        )


def test_provider_registry_routes_browseract_workflow_spec_build_with_alias_hints() -> None:
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key="build_workflow_spec",
        provider_hints=("BrowserAct",),
        allowed_tools=("browseract.build_workflow_spec", "artifact_repository"),
    )
    assert route.provider_key == "browseract"
    assert route.capability_key == "workflow_spec_build"
    assert route.tool_name == "browseract.build_workflow_spec"
    assert route.executable is True


def test_provider_registry_routes_browseract_workflow_spec_repair_with_alias_hints() -> None:
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key="repair_workflow_spec",
        provider_hints=("BrowserAct",),
        allowed_tools=("browseract.repair_workflow_spec", "artifact_repository"),
    )
    assert route.provider_key == "browseract"
    assert route.capability_key == "workflow_spec_repair"
    assert route.tool_name == "browseract.repair_workflow_spec"
    assert route.executable is True


def test_provider_registry_routes_crezlo_property_tour_with_alias_hints() -> None:
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key="create_property_tour",
        provider_hints=("BrowserAct", "Crezlo"),
        allowed_tools=("browseract.crezlo_property_tour", "artifact_repository"),
    )
    assert route.provider_key == "browseract"
    assert route.capability_key == "crezlo_property_tour"
    assert route.tool_name == "browseract.crezlo_property_tour"
    assert route.executable is True


@pytest.mark.parametrize(
    ("capability_key", "provider_hints", "allowed_tool", "expected_tool"),
    [
        ("create_mootion_movie", ("BrowserAct", "Mootion"), "browseract.mootion_movie", "browseract.mootion_movie"),
        ("route_flyover", ("BrowserAct", "AvoMap"), "browseract.avomap_flyover", "browseract.avomap_flyover"),
        ("first_book_ai", ("BrowserAct", "Booka"), "browseract.booka_book", "browseract.booka_book"),
        ("apixdrive", ("BrowserAct", "ApiX-Drive"), "browseract.apixdrive_workspace_reader", "browseract.apixdrive_workspace_reader"),
        ("approvethis", ("BrowserAct", "ApproveThis"), "browseract.approvethis_queue_reader", "browseract.approvethis_queue_reader"),
        ("metasurvey", ("BrowserAct", "MetaSurvey"), "browseract.metasurvey_results_reader", "browseract.metasurvey_results_reader"),
        ("nonverbia", ("BrowserAct", "Nonverbia"), "browseract.nonverbia_workspace_reader", "browseract.nonverbia_workspace_reader"),
        ("documentation_ai", ("BrowserAct", "Documentation.AI"), "browseract.documentation_ai_workspace_reader", "browseract.documentation_ai_workspace_reader"),
        ("invoiless", ("BrowserAct", "Invoiless"), "browseract.invoiless_workspace_reader", "browseract.invoiless_workspace_reader"),
        ("markupgo", ("BrowserAct", "MarkupGo"), "browseract.markupgo_workspace_reader", "browseract.markupgo_workspace_reader"),
        ("paperguide", ("BrowserAct", "Paperguide"), "browseract.paperguide_workspace_reader", "browseract.paperguide_workspace_reader"),
        ("peekshot", ("BrowserAct", "PeekShot"), "browseract.peekshot_workspace_reader", "browseract.peekshot_workspace_reader"),
        ("unmixr", ("BrowserAct", "Unmixr AI"), "browseract.unmixr_workspace_reader", "browseract.unmixr_workspace_reader"),
        ("vizologi", ("BrowserAct", "Vizologi"), "browseract.vizologi_workspace_reader", "browseract.vizologi_workspace_reader"),
    ],
)
def test_provider_registry_routes_browseract_ui_services_with_alias_hints(
    capability_key: str,
    provider_hints: tuple[str, ...],
    allowed_tool: str,
    expected_tool: str,
) -> None:
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key=capability_key,
        provider_hints=provider_hints,
        allowed_tools=(allowed_tool, "artifact_repository"),
    )
    assert route.provider_key == "browseract"
    assert route.tool_name == expected_tool
    assert route.executable is True


def test_provider_registry_routes_chatplayground_audit_with_aliases() -> None:
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key="chatplayground_audit",
        provider_hints=("chatplayground",),
        allowed_tools=("browseract.chatplayground_audit", "artifact_repository"),
    )
    assert route.provider_key == "browseract"
    assert route.capability_key == "chatplayground_audit"
    assert route.tool_name == "browseract.chatplayground_audit"
    assert route.executable is True


def test_provider_registry_routes_browseract_gemini_web_generate_with_aliases() -> None:
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key="gemini_web",
        provider_hints=("gemini_web",),
        allowed_tools=("browseract.gemini_web_generate", "artifact_repository"),
    )
    assert route.provider_key == "browseract"
    assert route.capability_key == "gemini_web_generate"
    assert route.tool_name == "browseract.gemini_web_generate"
    assert route.executable is True


def test_provider_registry_onemin_secret_rotation_includes_declared_fallback_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_ACTIVE_SLOTS", "primary,fallback_1")
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_RESERVE_SLOTS",
        ",".join(f"fallback_{index}" for index in range(2, 34)),
    )
    for index in range(1, 34):
        monkeypatch.setenv(f"ONEMIN_AI_API_KEY_FALLBACK_{index}", f"onemin-key-{index}")
    registry = ProviderRegistryService()
    state = registry.binding_state("onemin")
    assert state is not None
    assert list(state.secret_env_names) == [
        "ONEMIN_AI_API_KEY",
        *[f"ONEMIN_AI_API_KEY_FALLBACK_{index}" for index in range(1, 34)],
    ]


def test_provider_registry_onemin_secret_rotation_includes_json_manifest_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_ACTIVE_SLOTS", "primary,fallback_1,fallback_55")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_RESERVE_SLOTS", "fallback_56")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "onemin-key-1")
    monkeypatch.setenv(
        "ONEMIN_DIRECT_API_KEYS_JSON",
        json.dumps(
            [
                {
                    "slot": "fallback_55",
                    "account_name": "ONEMIN_AI_API_KEY_FALLBACK_55",
                    "key": "onemin-key-55",
                },
                {
                    "slot": "fallback_56",
                    "account_name": "ONEMIN_AI_API_KEY_FALLBACK_56",
                    "key": "onemin-key-56",
                },
            ]
        ),
    )
    registry = ProviderRegistryService()
    state = registry.binding_state("onemin")
    assert state is not None
    assert list(state.secret_env_names) == [
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
        "ONEMIN_AI_API_KEY_FALLBACK_55",
        "ONEMIN_AI_API_KEY_FALLBACK_56",
    ]


def test_provider_registry_exposes_executable_onemin_specialist_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-key")

    registry = ProviderRegistryService()
    state = registry.binding_state("onemin")

    assert state is not None
    assert state.executable is True
    assert state.auth_mode == "api_key"
    assert state.state == "ready"
    assert "code_generate" in state.capabilities
    assert "reasoned_patch_review" in state.capabilities
    assert "image_generate" in state.capabilities
    assert "media_transform" in state.capabilities


def test_provider_registry_marks_comfyui_unconfigured_without_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COMFYUI_URL", raising=False)

    registry = ProviderRegistryService()
    state = registry.binding_state("comfyui")

    assert state is not None
    assert state.auth_mode == "http"
    assert state.state == "unconfigured"
    assert state.secret_configured is False


def test_provider_registry_marks_comfyui_ready_with_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMFYUI_URL", "https://images.example")

    registry = ProviderRegistryService()
    state = registry.binding_state("comfyui")

    assert state is not None
    assert state.auth_mode == "http"
    assert state.state == "ready"
    assert state.secret_configured is True
    assert "image_generate" in state.capabilities


def test_provider_registry_exposes_google_gmail_oauth_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://ea.example/v1/providers/google/oauth/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret-key")

    registry = ProviderRegistryService()
    state = registry.binding_state("google_gmail")

    assert state is not None
    assert state.provider_key == "google_gmail"
    assert state.auth_mode == "oauth"
    assert state.state == "configured"
    assert "oauth_connect" in state.capabilities
    assert "gmail_send" in state.capabilities


def test_provider_registry_routes_onemin_specialist_capability_with_aliases() -> None:
    registry = ProviderRegistryService()

    route = registry.route_tool_by_capability(
        capability_key="codegen",
        provider_hints=("1min.AI",),
        allowed_tools=("provider.onemin.code_generate",),
    )
    assert route.provider_key == "onemin"
    assert route.capability_key == "code_generate"
    assert route.tool_name == "provider.onemin.code_generate"
    assert route.executable is True

    review_route = registry.route_tool_by_capability(
        capability_key="patch_review",
        provider_hints=("onemin",),
        allowed_tools=("provider.onemin.reasoned_patch_review",),
    )
    assert review_route.provider_key == "onemin"
    assert review_route.capability_key == "reasoned_patch_review"
    assert review_route.tool_name == "provider.onemin.reasoned_patch_review"
    assert review_route.executable is True


def test_provider_registry_normalizes_chatplayground_aliases() -> None:
    registry = ProviderRegistryService()

    state = registry.binding_state("chatplayground")
    assert state is not None
    assert state.provider_key == "browseract"

    state = registry.binding_state("chat_playground")
    assert state is not None
    assert state.provider_key == "browseract"


def test_provider_registry_normalizes_magicx_aliases() -> None:
    registry = ProviderRegistryService()

    state = registry.binding_state("magicxai")
    assert state is not None
    assert state.provider_key == "magixai"

    state = registry.binding_state("aimagicx")
    assert state is not None
    assert state.provider_key == "magixai"

    state = registry.binding_state("ai_magicx")
    assert state is not None
    assert state.provider_key == "magixai"


def test_provider_registry_exposes_executable_magixai_structured_generate_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    registry = ProviderRegistryService()
    state = registry.binding_state("magixai")
    assert state is not None
    assert state.executable is True
    assert state.auth_mode == "api_key"
    assert state.state == "ready"
    assert "structured_generate" in state.capabilities


def test_provider_registry_route_tool_respects_principal_binding_state() -> None:
    repo = InMemoryProviderBindingRepository()
    repo.upsert(
        principal_id="exec-1",
        provider_key="browseract",
        status="disabled",
        priority=10,
    )
    registry = ProviderRegistryService(provider_binding_repo=repo)
    with pytest.raises(ToolExecutionError, match="provider_tool_unavailable:browseract.extract_account_inventory"):
        registry.route_tool_with_context("browseract.extract_account_inventory", principal_id="exec-1")

    route = registry.route_tool_with_context("browseract.extract_account_inventory", principal_id="exec-2")
    assert route.provider_key == "browseract"
    assert route.tool_name == "browseract.extract_account_inventory"


def test_provider_registry_binding_state_reflects_degraded_probe_health() -> None:
    repo = InMemoryProviderBindingRepository()
    repo.upsert(
        principal_id="exec-1",
        provider_key="browseract",
        status="enabled",
        priority=10,
        probe_state="degraded",
        probe_details_json={"reason": "quota_low"},
    )
    registry = ProviderRegistryService(provider_binding_repo=repo)
    state = registry.binding_state("browseract", principal_id="exec-1")
    assert state is not None
    assert state.state == "degraded"
    assert state.health_state == "degraded"


def test_provider_registry_route_tool_by_capability_blocks_future_retry_window() -> None:
    repo = InMemoryProviderBindingRepository()
    retry_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    repo.upsert(
        principal_id="exec-1",
        provider_key="browseract",
        status="enabled",
        priority=10,
        probe_state="degraded",
        probe_details_json={"next_retry_at": retry_at},
    )
    registry = ProviderRegistryService(provider_binding_repo=repo)
    with pytest.raises(ToolExecutionError, match="provider_capability_unavailable:account_inventory"):
        registry.route_tool_by_capability(
            capability_key="account_inventory",
            provider_hints=("browseract",),
            allowed_tools=("browseract.extract_account_inventory",),
            principal_id="exec-1",
        )


def test_provider_registry_route_tool_by_capability_respects_binding_scope() -> None:
    repo = InMemoryProviderBindingRepository()
    repo.upsert(
        principal_id="exec-1",
        provider_key="browseract",
        status="enabled",
        priority=10,
        scope_json={
            "allowed_capabilities": ["account_inventory"],
            "allowed_tools": ["browseract.extract_account_inventory"],
        },
    )
    registry = ProviderRegistryService(provider_binding_repo=repo)
    route = registry.route_tool_by_capability(
        capability_key="account_inventory",
        provider_hints=("browseract",),
        allowed_tools=("browseract.extract_account_inventory",),
        principal_id="exec-1",
    )
    assert route.provider_key == "browseract"
    with pytest.raises(ToolExecutionError, match="provider_capability_unavailable:chatplayground_audit"):
        registry.route_tool_by_capability(
            capability_key="chatplayground_audit",
            provider_hints=("browseract",),
            allowed_tools=("browseract.chatplayground_audit",),
            principal_id="exec-1",
        )


def test_provider_registry_rejects_non_executable_capability_route() -> None:
    registry = ProviderRegistryService()
    with pytest.raises(ToolExecutionError, match="provider_capability_unavailable:prompt_refine"):
        registry.route_tool_by_capability(
            capability_key="prompt_refine",
            provider_hints=("prompting_systems",),
            allowed_tools=("provider.prompting_systems.prompt_refine",),
        )


def test_provider_registry_exposes_hub_owner_projection_from_principal_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_PRINCIPAL_HUB_USER_OVERRIDES_JSON", json.dumps({"participant-1": "usr_1"}))
    monkeypatch.setenv("EA_PRINCIPAL_HUB_GROUP_OVERRIDES_JSON", json.dumps({"participant-1": "grp_1"}))
    monkeypatch.setenv("EA_PRINCIPAL_SPONSOR_SESSION_OVERRIDES_JSON", json.dumps({"participant-1": "sps_1"}))

    registry = ProviderRegistryService()
    read_model = registry.registry_read_model(
        principal_id="participant-1",
        provider_health={
            "providers": {
                "gemini_vortex": {
                    "provider_key": "gemini_vortex",
                    "backend": "gemini_vortex_cli",
                    "configured_slots": 1,
                    "slots": [
                        {
                            "slot": "primary",
                            "state": "ready",
                            "lease_holder": "participant-1",
                            "last_used_principal_id": "participant-1",
                            "last_used_at": "2026-03-19T10:00:00Z",
                        }
                    ],
                }
            }
        },
        profile_decisions=(
            {
                "profile": "groundwork",
                "lane": "groundwork",
                "public_model": "ea-groundwork-gemini",
                "backend_key": "gemini_vortex_cli",
                "provider_hint_order": ("gemini_vortex",),
                "review_required": False,
                "needs_review": False,
                "merge_policy": "auto",
            },
        ),
    )

    provider = next(item for item in read_model["providers"] if item["provider_key"] == "gemini_vortex")
    assert provider["last_used_hub_user_id"] == "usr_1"
    assert provider["last_used_hub_group_id"] == "grp_1"
    assert provider["last_used_sponsor_session_id"] == "sps_1"

    lane = next(item for item in read_model["lanes"] if item["profile"] == "groundwork")
    assert lane["last_used_hub_user_id"] == "usr_1"
    assert lane["last_used_hub_group_id"] == "grp_1"
    assert lane["last_used_sponsor_session_id"] == "sps_1"


def test_provider_registry_read_model_exposes_lane_backend_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import responses_upstream as upstream

    upstream._test_reset_onemin_states()
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "sh")
    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "vertex-fallback")
    monkeypatch.setenv("EA_GEMINI_VORTEX_SLOT_DEFAULT_OWNER", "fleet-primary")
    monkeypatch.setenv("EA_GEMINI_VORTEX_SLOT_FALLBACK_1_OWNER", "fleet-shadow")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")

    registry = ProviderRegistryService()
    router = BrainRouterService(provider_registry=registry)
    payload = registry.registry_read_model(
        principal_id="codex-fleet",
        provider_health=upstream._provider_health_report(),
        profile_decisions=router.list_profile_decisions(principal_id="codex-fleet"),
    )

    assert payload["contract_name"] == "ea.provider_registry"
    assert payload["principal_id"] == "codex-fleet"

    groundwork = next(item for item in payload["lanes"] if item["profile"] == "groundwork")
    assert groundwork["backend"] == "gemini_vortex"
    assert groundwork["health_provider_key"] == "gemini_vortex"
    assert groundwork["providers"][0]["provider_key"] == "gemini_vortex"
    assert groundwork["capacity_summary"]["configured_slots"] == 2
    assert groundwork["capacity_summary"]["slot_owners"] == ["fleet-primary", "fleet-shadow"]

    review_light = next(item for item in payload["lanes"] if item["profile"] == "review_light")
    assert review_light["backend"] == "browseract"
    assert review_light["health_provider_key"] == "browseract"
    assert review_light["providers"][0]["provider_key"] == "browseract"

    browseract = next(item for item in payload["providers"] if item["provider_key"] == "browseract")
    assert browseract["health_provider_key"] == "chatplayground"
    assert any(capability["capability_key"] == "account_inventory" for capability in browseract["capabilities"])


def test_provider_registry_prefers_ready_fallback_provider_for_lane_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-key")

    registry = ProviderRegistryService()
    payload = registry.registry_read_model(
        principal_id="codex-fleet",
        provider_health={
            "providers": {
                "magixai": {
                    "provider_key": "magixai",
                    "state": "degraded",
                    "slots": [{"slot": "primary", "state": "degraded"}],
                },
                "onemin": {
                    "provider_key": "onemin",
                    "state": "ready",
                    "slots": [{"slot": "primary", "state": "ready"}],
                },
            }
        },
        profile_decisions=(
            {
                "profile": "repair",
                "lane": "repair",
                "public_model": "ea-coder-fast",
                "backend_key": "magixai",
                "health_provider_key": "magixai",
                "provider_hint_order": ("magixai", "onemin"),
                "review_required": False,
                "needs_review": False,
                "merge_policy": "auto_if_low_risk",
            },
        ),
    )

    repair = next(item for item in payload["lanes"] if item["profile"] == "repair")
    assert repair["backend"] == "onemin"
    assert repair["health_provider_key"] == "onemin"
    assert repair["provider_hint_order"] == ["onemin", "magixai"]
    assert repair["primary_provider_key"] == "onemin"
    assert repair["primary_state"] == "ready"
    assert repair["capacity_summary"]["ready_slots"] == 1
    assert repair["providers"][0]["provider_key"] == "magixai"
    assert repair["providers"][1]["provider_key"] == "onemin"


def test_planner_rejects_non_executable_provider_capability_routes() -> None:
    contracts = TaskContractService(InMemoryTaskContractRepository())
    contracts.upsert_contract(
        task_key="prompt_refine_attempt",
        deliverable_type="refined_prompt",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("provider.prompting_systems.prompt_refine", "artifact_repository"),
        memory_write_policy="none",
        budget_policy_json={
            "class": "low",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_capability_key": "prompt_refine",
            "skill_catalog_json": {"provider_hints_json": {"preferred": ["prompting_systems"]}},
        },
    )
    planner = PlannerService(contracts)

    with pytest.raises(PlanValidationError, match="provider_capability_unavailable:prompt_refine"):
        planner.build_plan(
            task_key="prompt_refine_attempt",
            principal_id="exec-1",
            goal="try a non-executable provider capability",
        )
