from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskContract:
    key: str
    description: str
    provider_priority: tuple[str, ...]
    output_artifact_type: str
    approval_default: str
    budget_policy: str


TASK_REGISTRY: dict[str, TaskContract] = {
    "approval_router": TaskContract(
        key="approval_router",
        description="Route high-impact operations through explicit approval controls.",
        provider_priority=("approvethis",),
        output_artifact_type="approval_ticket",
        approval_default="explicit_callback_required",
        budget_policy="approval_gate",
    ),
    "bridge_external_action": TaskContract(
        key="bridge_external_action",
        description="Dispatch approved external actions through bridge connectors.",
        provider_priority=("apix_drive",),
        output_artifact_type="bridge_dispatch_record",
        approval_default="explicit_callback_required",
        budget_policy="connector_quota",
    ),
    "bridge_external_event": TaskContract(
        key="bridge_external_event",
        description="Ingest third-party external events through bridge connectors.",
        provider_priority=("apix_drive", "browseract"),
        output_artifact_type="external_event_record",
        approval_default="none",
        budget_policy="connector_quota",
    ),
    "browser_sidecar_ingress": TaskContract(
        key="browser_sidecar_ingress",
        description="Persist browser sidecar ingress payloads for durable processing.",
        provider_priority=("browseract",),
        output_artifact_type="browser_sidecar_event",
        approval_default="none",
        budget_policy="worker_queue",
    ),
    "travel_rescue": TaskContract(
        key="travel_rescue",
        description="Assess trip risk/cost and prepare reroute or rebook options.",
        provider_priority=("oneair", "avomap", "browseract"),
        output_artifact_type="travel_decision_pack",
        approval_default="advisory",
        budget_policy="travel_sidecar_daily",
    ),
    "trip_context_pack": TaskContract(
        key="trip_context_pack",
        description="Build contextual trip prep artifact with sidecar enrichments.",
        provider_priority=("oneair", "avomap", "one_min_ai", "ai_magicx"),
        output_artifact_type="trip_context_pack",
        approval_default="advisory",
        budget_policy="travel_sidecar_daily",
    ),
    "collect_structured_intake": TaskContract(
        key="collect_structured_intake",
        description="Collect structured intake via lightweight or rich form flows.",
        provider_priority=("involve_me", "metasurvey", "apix_drive"),
        output_artifact_type="intake_packet",
        approval_default="none",
        budget_policy="intake_quota",
    ),
    "guided_intake": TaskContract(
        key="guided_intake",
        description="Run guided intake for external contributors.",
        provider_priority=("involve_me", "metasurvey", "apix_drive"),
        output_artifact_type="intake_packet",
        approval_default="none",
        budget_policy="intake_quota",
    ),
    "compile_prompt_pack": TaskContract(
        key="compile_prompt_pack",
        description="Compile structured prompts for downstream multimodal workflows.",
        provider_priority=("prompting_systems", "paperguide", "vizologi"),
        output_artifact_type="prompt_pack",
        approval_default="none",
        budget_policy="content_sidecar_daily",
    ),
    "polish_human_tone": TaskContract(
        key="polish_human_tone",
        description="Polish approved drafts for readability and human tone.",
        provider_priority=("undetectable",),
        output_artifact_type="polished_draft",
        approval_default="none",
        budget_policy="tone_polish_daily",
    ),
    "generate_multimodal_support_asset": TaskContract(
        key="generate_multimodal_support_asset",
        description="Produce non-blocking support assets for communication/prep.",
        provider_priority=("one_min_ai", "ai_magicx", "peekshot"),
        output_artifact_type="support_asset",
        approval_default="none",
        budget_policy="secondary_ai_daily",
    ),
    "event_enrichment": TaskContract(
        key="event_enrichment",
        description="Enrich external events with sidecar/context metadata.",
        provider_priority=("browseract", "apix_drive"),
        output_artifact_type="enriched_event",
        approval_default="none",
        budget_policy="worker_queue",
    ),
    "feedback_intake": TaskContract(
        key="feedback_intake",
        description="Capture and persist user feedback from structured channels.",
        provider_priority=("metasurvey", "involve_me"),
        output_artifact_type="feedback_packet",
        approval_default="none",
        budget_policy="intake_quota",
    ),
    "optimize_trip_cost": TaskContract(
        key="optimize_trip_cost",
        description="Evaluate trip cost optimization and reprice opportunities.",
        provider_priority=("oneair", "avomap"),
        output_artifact_type="trip_cost_options",
        approval_default="advisory",
        budget_policy="travel_sidecar_daily",
    ),
    "route_video_render": TaskContract(
        key="route_video_render",
        description="Render route/arrival visual support assets for trips.",
        provider_priority=("avomap", "one_min_ai", "ai_magicx"),
        output_artifact_type="route_video_asset",
        approval_default="none",
        budget_policy="travel_sidecar_daily",
    ),
    "run_secondary_research_pass": TaskContract(
        key="run_secondary_research_pass",
        description="Run secondary research synthesis across sidecar providers.",
        provider_priority=("paperguide", "vizologi", "ai_magicx"),
        output_artifact_type="research_pack",
        approval_default="none",
        budget_policy="research_sidecar_daily",
    ),
    "strategy_pack": TaskContract(
        key="strategy_pack",
        description="Generate structured strategy synthesis for executive decisions.",
        provider_priority=("vizologi", "paperguide"),
        output_artifact_type="strategy_pack",
        approval_default="advisory",
        budget_policy="research_sidecar_daily",
    ),
    "typed_safe_action": TaskContract(
        key="typed_safe_action",
        description="Stage and execute typed safe actions behind approval policy.",
        provider_priority=("approvethis",),
        output_artifact_type="typed_action_outcome",
        approval_default="explicit_callback_required",
        budget_policy="approval_gate",
    ),
}


def task_or_none(task_key: str) -> TaskContract | None:
    key = str(task_key or "").strip().lower()
    if not key:
        return None
    return TASK_REGISTRY.get(key)


def task_or_raise(task_key: str) -> TaskContract:
    task = task_or_none(task_key)
    if not task:
        raise ValueError(f"unknown_task_contract:{task_key}")
    return task


def list_task_contracts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in sorted(TASK_REGISTRY.keys()):
        task = TASK_REGISTRY[key]
        out.append(
            {
                "key": task.key,
                "description": task.description,
                "provider_priority": list(task.provider_priority),
                "output_artifact_type": task.output_artifact_type,
                "approval_default": task.approval_default,
                "budget_policy": task.budget_policy,
            }
        )
    return out


__all__ = ["TaskContract", "TASK_REGISTRY", "task_or_none", "task_or_raise", "list_task_contracts"]
