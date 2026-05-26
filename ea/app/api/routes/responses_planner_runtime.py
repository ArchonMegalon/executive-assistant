from __future__ import annotations

import os
import time
from typing import Any, Callable


def history_items_for_request(
    *,
    previous_response_id: str | None,
    parsed_input: Any,
    principal_id: str,
    container: object | None,
    load_response_for_runtime: Callable[..., Any],
    response_failure_message: Callable[[dict[str, object]], str],
    http_exception_type: type[Exception],
) -> list[dict[str, object]]:
    history: list[dict[str, object]] = []
    if previous_response_id:
        stored = load_response_for_runtime(
            response_id=previous_response_id,
            principal_id=principal_id,
            container=container,
        )
        previous_status = str(stored.response.get("status") or "").strip().lower()
        if previous_status == "in_progress":
            raise http_exception_type(status_code=409, detail="previous_response_in_progress")
        if previous_status == "failed":
            failure_message = response_failure_message(dict(stored.response))
            detail = "previous_response_failed"
            if failure_message:
                detail = f"{detail}:{failure_message}"
            raise http_exception_type(status_code=409, detail=detail)
        history.extend(dict(item) for item in stored.history_items)
    history.extend(dict(item) for item in parsed_input.input_items)
    return history


def tool_shim_transcript_max_chars() -> int:
    raw = str(os.environ.get("EA_TOOL_SHIM_TRANSCRIPT_MAX_CHARS") or "4000").strip() or "4000"
    try:
        return max(800, min(32000, int(raw)))
    except Exception:
        return 4000


def tool_shim_transcript_part_max_chars() -> int:
    raw = str(os.environ.get("EA_TOOL_SHIM_TRANSCRIPT_PART_MAX_CHARS") or "1200").strip() or "1200"
    try:
        return max(200, min(8000, int(raw)))
    except Exception:
        return 1200


def build_tool_shim_planner_model(
    *,
    fast_public_model: str,
    hard_batch_public_model: str,
    hard_rescue_public_model: str,
    review_light_public_model: str,
    groundwork_public_model: str,
    survival_public_model: str,
    onemin_public_model: str,
    is_staged_local_orientation_prompt: Callable[[str], bool],
    is_operator_fleet_unblock_prompt: Callable[[str], bool],
    is_operator_gap_fix_prompt: Callable[[str], bool],
    is_operator_gap_audit_prompt: Callable[[str], bool],
    is_operator_readiness_remedy_prompt: Callable[[str], bool],
    is_package_work_prompt: Callable[[str], bool],
) -> Callable[..., str]:
    def tool_shim_planner_model(model: str, *, prompt: str | None = None) -> str:
        configured = str(os.environ.get("EA_TOOL_SHIM_PLANNER_MODEL") or "").strip()
        if configured:
            return configured
        normalized_prompt = str(prompt or "").strip()
        if (
            is_staged_local_orientation_prompt(normalized_prompt)
            or is_operator_fleet_unblock_prompt(normalized_prompt)
            or is_operator_gap_fix_prompt(normalized_prompt)
            or is_operator_gap_audit_prompt(normalized_prompt)
            or is_operator_readiness_remedy_prompt(normalized_prompt)
            or is_package_work_prompt(normalized_prompt)
        ):
            fast_planner = str(fast_public_model or "").strip() or "ea-coder-fast"
            if fast_planner:
                return fast_planner
        normalized = str(model or "").strip().lower()
        if not normalized:
            return "onemin:gpt-4.1-nano"
        managed_lane_models = {
            str(hard_batch_public_model or "").strip().lower(): str(hard_batch_public_model or "").strip(),
            str(hard_rescue_public_model or "").strip().lower(): str(hard_rescue_public_model or "").strip(),
            str(review_light_public_model or "").strip().lower(): str(review_light_public_model or "").strip(),
            str(groundwork_public_model or "").strip().lower(): str(groundwork_public_model or "").strip(),
            str(survival_public_model or "").strip().lower(): str(survival_public_model or "").strip(),
            "ea-coder-hard": "ea-coder-hard",
            "ea-coder-hard-batch": str(hard_batch_public_model or "").strip() or "ea-coder-hard-batch",
            "ea-coder-hard-rescue": str(hard_rescue_public_model or "").strip() or "ea-coder-hard-rescue",
            "ea-audit-jury": "ea-audit-jury",
            "ea-review-light": str(review_light_public_model or "").strip() or "ea-review-light",
            "ea-groundwork-gemini": str(groundwork_public_model or "").strip() or "ea-groundwork-gemini",
            "ea-coder-survival": str(survival_public_model or "").strip() or "ea-coder-survival",
        }
        managed_match = str(managed_lane_models.get(normalized) or "").strip()
        if managed_match:
            return managed_match
        if normalized == str(onemin_public_model or "").strip().lower() or normalized.startswith("onemin:"):
            return "onemin:gpt-4.1-nano"
        if normalized.startswith("ea-"):
            return "onemin:gpt-4.1-nano"
        return model

    tool_shim_planner_model.__name__ = "tool_shim_planner_model"
    tool_shim_planner_model.__qualname__ = "tool_shim_planner_model"
    return tool_shim_planner_model


def tool_shim_planner_max_output_tokens(max_output_tokens: int | None) -> int:
    if max_output_tokens is None:
        return 256
    try:
        value = int(max_output_tokens)
    except Exception:
        return 256
    return max(96, min(256, value))


def build_tool_shim_planner_deadline_monotonic(
    *,
    is_package_work_prompt: Callable[[str], bool],
    is_staged_local_orientation_prompt: Callable[[str], bool],
    is_operator_fleet_unblock_prompt: Callable[[str], bool],
    is_operator_gap_fix_prompt: Callable[[str], bool],
    is_operator_gap_audit_prompt: Callable[[str], bool],
    is_operator_readiness_remedy_prompt: Callable[[str], bool],
) -> Callable[..., float | None]:
    def _configured_default_budget_seconds() -> float:
        raw = str(os.environ.get("EA_TOOL_SHIM_PLANNER_DEADLINE_SECONDS_DEFAULT") or "").strip()
        if not raw:
            return 0.0
        try:
            return max(0.0, min(600.0, float(raw)))
        except Exception:
            return 0.0

    def tool_shim_planner_deadline_monotonic(
        request_deadline_monotonic: float | None,
        *,
        prompt: str | None = None,
    ) -> float | None:
        if request_deadline_monotonic is None:
            return None
        normalized_prompt = str(prompt or "").strip()
        if not normalized_prompt:
            return request_deadline_monotonic
        deadline_budget_seconds = 0.0
        if is_package_work_prompt(normalized_prompt):
            deadline_budget_seconds = 75.0
        elif (
            is_staged_local_orientation_prompt(normalized_prompt)
            or is_operator_fleet_unblock_prompt(normalized_prompt)
            or is_operator_gap_fix_prompt(normalized_prompt)
            or is_operator_gap_audit_prompt(normalized_prompt)
            or is_operator_readiness_remedy_prompt(normalized_prompt)
        ):
            deadline_budget_seconds = 30.0
        else:
            deadline_budget_seconds = _configured_default_budget_seconds()
        if deadline_budget_seconds <= 0:
            return request_deadline_monotonic
        return min(request_deadline_monotonic, time.monotonic() + deadline_budget_seconds)

    tool_shim_planner_deadline_monotonic.__name__ = "tool_shim_planner_deadline_monotonic"
    tool_shim_planner_deadline_monotonic.__qualname__ = "tool_shim_planner_deadline_monotonic"
    return tool_shim_planner_deadline_monotonic
