from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapabilityContract:
    key: str
    display_name: str
    invocation_method: str
    task_types: tuple[str, ...]
    data_classes: tuple[str, ...]
    user_visible: bool
    blocking: bool
    fallback_policy: str
    budget_policy: str


CAPABILITY_REGISTRY: dict[str, CapabilityContract] = {
    "apix_drive": CapabilityContract(
        key="apix_drive",
        display_name="ApiX-Drive",
        invocation_method="webhook",
        task_types=("bridge_external_event", "bridge_external_action"),
        data_classes=("connector_event", "derived_summary"),
        user_visible=False,
        blocking=False,
        fallback_policy="queue_for_retry",
        budget_policy="connector_quota",
    ),
    "oneair": CapabilityContract(
        key="oneair",
        display_name="OneAir Elite",
        invocation_method="api",
        task_types=("optimize_trip_cost", "travel_rescue", "trip_context_pack"),
        data_classes=("travel_commitment", "derived_summary"),
        user_visible=True,
        blocking=False,
        fallback_policy="skip_and_note",
        budget_policy="travel_sidecar_daily",
    ),
    "prompting_systems": CapabilityContract(
        key="prompting_systems",
        display_name="Prompting.Systems",
        invocation_method="api",
        task_types=("compile_prompt_pack",),
        data_classes=("derived_summary",),
        user_visible=False,
        blocking=False,
        fallback_policy="fallback_to_core_prompting",
        budget_policy="content_sidecar_daily",
    ),
    "undetectable": CapabilityContract(
        key="undetectable",
        display_name="Undetectable Humanizer",
        invocation_method="api",
        task_types=("polish_human_tone",),
        data_classes=("approved_outbound_draft",),
        user_visible=True,
        blocking=False,
        fallback_policy="return_unpolished_draft",
        budget_policy="tone_polish_daily",
    ),
    "involve_me": CapabilityContract(
        key="involve_me",
        display_name="involve.me",
        invocation_method="webhook",
        task_types=("collect_structured_intake", "guided_intake"),
        data_classes=("intake_submission", "derived_summary"),
        user_visible=True,
        blocking=False,
        fallback_policy="fallback_to_metasurvey",
        budget_policy="intake_quota",
    ),
    "ai_magicx": CapabilityContract(
        key="ai_magicx",
        display_name="AI Magicx",
        invocation_method="api",
        task_types=("run_secondary_research_pass", "generate_multimodal_support_asset", "trip_context_pack"),
        data_classes=("derived_summary",),
        user_visible=False,
        blocking=False,
        fallback_policy="skip_and_note",
        budget_policy="secondary_ai_daily",
    ),
    "one_min_ai": CapabilityContract(
        key="one_min_ai",
        display_name="1minAI",
        invocation_method="api",
        task_types=("generate_multimodal_support_asset", "trip_context_pack"),
        data_classes=("derived_summary",),
        user_visible=False,
        blocking=False,
        fallback_policy="skip_and_note",
        budget_policy="secondary_ai_daily",
    ),
    "avomap": CapabilityContract(
        key="avomap",
        display_name="AvoMap",
        invocation_method="webhook",
        task_types=("trip_context_pack", "route_video_render", "travel_rescue"),
        data_classes=("travel_commitment", "derived_summary"),
        user_visible=True,
        blocking=False,
        fallback_policy="link_only_late_attach",
        budget_policy="travel_sidecar_daily",
    ),
    "metasurvey": CapabilityContract(
        key="metasurvey",
        display_name="MetaSurvey",
        invocation_method="webhook",
        task_types=("collect_structured_intake", "feedback_intake"),
        data_classes=("intake_submission",),
        user_visible=True,
        blocking=False,
        fallback_policy="queue_for_retry",
        budget_policy="intake_quota",
    ),
    "paperguide": CapabilityContract(
        key="paperguide",
        display_name="Paperguide",
        invocation_method="api",
        task_types=("run_secondary_research_pass",),
        data_classes=("derived_summary",),
        user_visible=False,
        blocking=False,
        fallback_policy="skip_and_note",
        budget_policy="research_sidecar_daily",
    ),
    "vizologi": CapabilityContract(
        key="vizologi",
        display_name="Vizologi",
        invocation_method="api",
        task_types=("run_secondary_research_pass", "strategy_pack"),
        data_classes=("derived_summary",),
        user_visible=False,
        blocking=False,
        fallback_policy="skip_and_note",
        budget_policy="research_sidecar_daily",
    ),
    "peekshot": CapabilityContract(
        key="peekshot",
        display_name="PeekShot",
        invocation_method="api",
        task_types=("generate_multimodal_support_asset",),
        data_classes=("derived_summary",),
        user_visible=False,
        blocking=False,
        fallback_policy="skip_and_note",
        budget_policy="media_sidecar_daily",
    ),
    "approvethis": CapabilityContract(
        key="approvethis",
        display_name="ApproveThis",
        invocation_method="api",
        task_types=("approval_router", "typed_safe_action"),
        data_classes=("approval_event", "derived_summary"),
        user_visible=True,
        blocking=True,
        fallback_policy="manual_approval_required",
        budget_policy="approval_gate",
    ),
    "browseract": CapabilityContract(
        key="browseract",
        display_name="BrowserAct",
        invocation_method="webhook",
        task_types=("browser_sidecar_ingress", "event_enrichment"),
        data_classes=("external_event", "derived_summary"),
        user_visible=False,
        blocking=False,
        fallback_policy="persist_and_retry",
        budget_policy="worker_queue",
    ),
}


def capability_or_raise(capability_key: str) -> CapabilityContract:
    key = str(capability_key or "").strip().lower()
    if key not in CAPABILITY_REGISTRY:
        raise ValueError(f"unknown_capability:{capability_key}")
    return CAPABILITY_REGISTRY[key]


def list_capabilities() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in sorted(CAPABILITY_REGISTRY.keys()):
        cap = CAPABILITY_REGISTRY[key]
        out.append(
            {
                "key": cap.key,
                "display_name": cap.display_name,
                "invocation_method": cap.invocation_method,
                "task_types": list(cap.task_types),
                "data_classes": list(cap.data_classes),
                "user_visible": cap.user_visible,
                "blocking": cap.blocking,
                "fallback_policy": cap.fallback_policy,
                "budget_policy": cap.budget_policy,
            }
        )
    return out


def capabilities_for_task(task_type: str) -> list[str]:
    target = str(task_type or "").strip().lower()
    if not target:
        return []
    out: list[str] = []
    for key in sorted(CAPABILITY_REGISTRY.keys()):
        cap = CAPABILITY_REGISTRY[key]
        if target in {x.strip().lower() for x in cap.task_types}:
            out.append(cap.key)
    return out


__all__ = [
    "CapabilityContract",
    "CAPABILITY_REGISTRY",
    "capability_or_raise",
    "list_capabilities",
    "capabilities_for_task",
]
