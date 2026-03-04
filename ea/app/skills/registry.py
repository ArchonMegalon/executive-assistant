from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.skills.capability_registry import capability_or_raise
from app.skills.generic import build_generic_skill_handler


SkillHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class SkillContract:
    key: str
    display_name: str
    operations: tuple[str, ...]
    handler: SkillHandler
    capabilities: tuple[str, ...]
    planning_task_type: str = ""


def _payments_handler(
    *,
    operation: str,
    tenant: str,
    chat_id: int,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Lazy import keeps host-level contract smokes independent from DB driver deps.
    from app.skills import payments

    return payments.run_operation(
        operation=operation,
        tenant=tenant,
        chat_id=chat_id,
        payload=payload,
    )


SKILL_REGISTRY: dict[str, SkillContract] = {
    "payments": SkillContract(
        key="payments",
        display_name="Payments",
        operations=("generate_demo_draft", "handle_action"),
        handler=_payments_handler,
        capabilities=("approvethis",),
        planning_task_type="typed_safe_action",
    ),
    "travel_rescue": SkillContract(
        key="travel_rescue",
        display_name="Travel Rescue",
        operations=("plan", "stage"),
        handler=build_generic_skill_handler(
            "travel_rescue",
            ("oneair", "avomap", "browseract"),
            planning_task_type="travel_rescue",
        ),
        capabilities=("oneair", "avomap", "browseract"),
        planning_task_type="travel_rescue",
    ),
    "guided_intake": SkillContract(
        key="guided_intake",
        display_name="Guided Intake",
        operations=("plan", "dispatch"),
        handler=build_generic_skill_handler(
            "guided_intake",
            ("involve_me", "metasurvey", "apix_drive"),
            planning_task_type="collect_structured_intake",
        ),
        capabilities=("involve_me", "metasurvey", "apix_drive"),
        planning_task_type="collect_structured_intake",
    ),
    "draft_and_polish": SkillContract(
        key="draft_and_polish",
        display_name="Draft and Polish",
        operations=("plan", "polish"),
        handler=build_generic_skill_handler(
            "draft_and_polish",
            ("prompting_systems", "undetectable"),
            planning_task_type="polish_human_tone",
        ),
        capabilities=("prompting_systems", "undetectable"),
        planning_task_type="polish_human_tone",
    ),
    "prompt_compiler": SkillContract(
        key="prompt_compiler",
        display_name="Prompt Compiler",
        operations=("compile",),
        handler=build_generic_skill_handler(
            "prompt_compiler",
            ("prompting_systems", "paperguide", "vizologi"),
            planning_task_type="compile_prompt_pack",
        ),
        capabilities=("prompting_systems", "paperguide", "vizologi"),
        planning_task_type="compile_prompt_pack",
    ),
    "multimodal_burst": SkillContract(
        key="multimodal_burst",
        display_name="Multimodal Burst",
        operations=("generate",),
        handler=build_generic_skill_handler(
            "multimodal_burst",
            ("one_min_ai", "ai_magicx", "peekshot"),
            planning_task_type="generate_multimodal_support_asset",
        ),
        capabilities=("one_min_ai", "ai_magicx", "peekshot"),
        planning_task_type="generate_multimodal_support_asset",
    ),
    "evidence_pack_builder": SkillContract(
        key="evidence_pack_builder",
        display_name="Evidence Pack Builder",
        operations=("build", "stage"),
        handler=build_generic_skill_handler(
            "evidence_pack_builder",
            ("involve_me", "prompting_systems", "undetectable"),
            planning_task_type="collect_structured_intake",
        ),
        capabilities=("involve_me", "prompting_systems", "undetectable"),
        planning_task_type="collect_structured_intake",
    ),
    "trip_context_pack": SkillContract(
        key="trip_context_pack",
        display_name="Trip Context Pack",
        operations=("build",),
        handler=build_generic_skill_handler(
            "trip_context_pack",
            ("oneair", "avomap", "one_min_ai", "ai_magicx"),
            planning_task_type="trip_context_pack",
        ),
        capabilities=("oneair", "avomap", "one_min_ai", "ai_magicx"),
        planning_task_type="trip_context_pack",
    ),
}


def skill_or_raise(skill_key: str) -> SkillContract:
    key = str(skill_key or "").strip().lower()
    if key not in SKILL_REGISTRY:
        raise ValueError(f"unknown_skill:{skill_key}")
    return SKILL_REGISTRY[key]


def list_skills() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in sorted(SKILL_REGISTRY.keys()):
        contract = SKILL_REGISTRY[key]
        capability_rows = []
        for cap_key in contract.capabilities:
            cap = capability_or_raise(cap_key)
            capability_rows.append(
                {
                    "key": cap.key,
                    "display_name": cap.display_name,
                    "invocation_method": cap.invocation_method,
                    "task_types": list(cap.task_types),
                }
            )
        out.append(
            {
                "key": contract.key,
                "display_name": contract.display_name,
                "operations": list(contract.operations),
                "planning_task_type": str(contract.planning_task_type or ""),
                "capabilities": capability_rows,
            }
        )
    return out
