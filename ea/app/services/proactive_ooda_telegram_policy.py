from __future__ import annotations

from typing import Any, Mapping


INTERNAL_TELEGRAM_NOISE_MARKERS = (
    "proof packet",
    "live proof packet",
    "canonical live check",
    "preserve this proof",
    "record that proactive ooda decision",
    "proactive ooda decision",
    "operator status",
    "materialization",
    "materialize proactive",
    "teable projection",
    "flat search",
    "flat search disabled",
    "flat_search_disabled",
    "flat_provider_search_blocked",
    "run ranking",
    "ranking receipt",
    "runtime receipt",
    "gold acceptance",
)


LOW_VALUE_APPROVAL_PROMPT_MARKERS = (
    "research, compare, or draft only",
    "require explicit approval before purchase",
    "staged result",
)


def telegram_ooda_text_is_internal_noise(*values: Any) -> bool:
    normalized = " ".join(" ".join(str(value or "").strip().lower().split()) for value in values if str(value or "").strip())
    if not normalized:
        return False
    return any(marker in normalized for marker in INTERNAL_TELEGRAM_NOISE_MARKERS)


def telegram_ooda_approval_is_low_value_research_prompt(*values: Any) -> bool:
    normalized = " ".join(" ".join(str(value or "").strip().lower().split()) for value in values if str(value or "").strip())
    if not normalized:
        return False
    return any(marker in normalized for marker in LOW_VALUE_APPROVAL_PROMPT_MARKERS)


def approval_request_needs_telegram_user_action(approval_request: Mapping[str, Any] | None) -> bool:
    request = dict(approval_request or {})
    if not str(request.get("packet_ref") or "").strip():
        return False
    if not str(request.get("staged_artifact_ref") or "").strip():
        return False
    prompt = str(request.get("approval_prompt") or "").strip()
    staged_action_url = str(request.get("staged_action_url") or "").strip()
    approved_execution_mode = str(request.get("approved_execution_mode") or "").strip()
    approved_action = str(request.get("approved_action") or "").strip()
    if not any((prompt, staged_action_url, approved_execution_mode, approved_action)):
        return False
    if telegram_ooda_approval_is_low_value_research_prompt(prompt):
        return bool(approved_execution_mode or approved_action)
    if telegram_ooda_text_is_internal_noise(prompt):
        return bool(approved_execution_mode or approved_action) and not telegram_ooda_text_is_internal_noise(
            approved_execution_mode,
            approved_action,
        )
    return True
