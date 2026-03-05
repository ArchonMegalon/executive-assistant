from __future__ import annotations

from typing import Any

from app.planner.task_registry import task_or_none


def _step(
    step_key: str,
    step_title: str,
    *,
    preconditions: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    task_type: str = "",
    provider_candidates: tuple[str, ...] = (),
    output_artifact_type: str = "",
    budget_policy: str = "",
    approval_default: str = "",
) -> dict[str, Any]:
    return {
        "step_key": str(step_key or "").strip(),
        "step_title": str(step_title or "").strip(),
        "preconditions_json": dict(preconditions or {}),
        "evidence_json": dict(evidence or {}),
        "task_type": str(task_type or "").strip().lower(),
        "provider_candidates": [str(x) for x in provider_candidates if str(x or "").strip()],
        "output_artifact_type": str(output_artifact_type or "").strip(),
        "budget_policy": str(budget_policy or "").strip(),
        "approval_default": str(approval_default or "").strip(),
    }


def build_task_plan_steps(*, intent_spec: dict[str, Any]) -> list[dict[str, Any]]:
    spec = dict(intent_spec or {})
    has_url = bool(spec.get("has_url"))
    autonomy = str(spec.get("autonomy_level") or "").strip().lower()
    domain = str(spec.get("domain") or "").strip().lower()
    task_type = str(spec.get("task_type") or "").strip().lower()
    task_contract = task_or_none(task_type)

    steps: list[dict[str, Any]] = [_step("compile_intent", "Compile Intent")]

    if has_url:
        steps.append(
            _step(
                "gather_evidence",
                "Gather URL Evidence",
                preconditions={"requires_url": True},
            )
        )

    if task_type == "collect_structured_intake":
        steps.append(
            _step(
                "collect_intake_context",
                "Collect Intake Context",
                preconditions={"requires_structured_input": True},
                evidence={"sources": ["intake_form", "chat_context"]},
                task_type="collect_structured_intake",
            )
        )
    elif task_type == "compile_prompt_pack":
        steps.append(
            _step(
                "compile_prompt_pack",
                "Compile Prompt Pack",
                preconditions={"requires_prompt_goal": True},
                evidence={"sources": ["request_notes", "context_summary"]},
                task_type="compile_prompt_pack",
            )
        )
    elif task_type == "polish_human_tone":
        steps.append(
            _step(
                "prepare_draft_context",
                "Prepare Draft Context",
                preconditions={"requires_draft_text": True},
                evidence={"sources": ["draft_text", "style_profile"]},
                task_type="polish_human_tone",
            )
        )
    elif task_type == "generate_multimodal_support_asset":
        steps.append(
            _step(
                "prepare_multimodal_context",
                "Prepare Multimodal Context",
                preconditions={"requires_asset_goal": True},
                evidence={"sources": ["prompt_pack", "asset_constraints"]},
                task_type="generate_multimodal_support_asset",
            )
        )
    elif task_type in {"travel_rescue", "trip_context_pack"} or domain == "travel":
        steps.append(
            _step(
                "analyze_trip_commitment",
                "Analyze Trip Commitment",
                preconditions={"requires_domain": "travel"},
                evidence={"sources": ["calendar", "mail", "travel_dossier"]},
                task_type="travel_rescue" if task_type == "travel_rescue" else "trip_context_pack",
            )
        )
        steps.append(
            _step(
                "compare_travel_options",
                "Compare Travel Options",
                preconditions={"trip_context_ready": True},
                task_type="travel_rescue" if task_type == "travel_rescue" else "trip_context_pack",
            )
        )
    elif domain == "finance":
        steps.append(
            _step(
                "verify_payment_context",
                "Verify Payment Context",
                preconditions={"requires_domain": "finance"},
                evidence={"sources": ["billing", "approvals", "ledger"]},
                task_type="typed_safe_action" if task_type in {"typed_safe_action", "payments"} else "free_text",
            )
        )
    elif domain == "project":
        steps.append(
            _step(
                "gather_project_context",
                "Gather Project Context",
                preconditions={"requires_domain": "project"},
                evidence={"sources": ["calendar", "mail", "project_dossier"]},
                task_type="free_text",
            )
        )
    elif domain == "health":
        steps.append(
            _step(
                "review_health_context",
                "Review Health Context",
                preconditions={"requires_domain": "health"},
                evidence={"sources": ["appointments", "health_dossier"]},
                task_type="free_text",
            )
        )

    if autonomy == "approval_required":
        steps.append(
            _step(
                "safety_gate",
                "Safety Gate",
                preconditions={"approval_required": True},
            )
        )

    steps.extend(
        [
            _step(
                "execute_intent",
                "Execute Intent",
                task_type=task_type or "free_text_response",
                provider_candidates=tuple(task_contract.provider_priority) if task_contract else (),
                output_artifact_type=str(task_contract.output_artifact_type) if task_contract else "chat_response",
                budget_policy=str(task_contract.budget_policy) if task_contract else "",
                approval_default=str(task_contract.approval_default) if task_contract else "",
            ),
            _step("render_reply", "Render Reply"),
        ]
    )
    return steps


__all__ = ["build_task_plan_steps"]
