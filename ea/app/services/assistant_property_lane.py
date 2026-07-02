from __future__ import annotations

import os
from typing import Any

_PROPERTY_RUNTIME_PROFILES = {"property_only", "property-only", "property"}
ASSISTANT_HIDDEN_PROPERTY_TASK_TYPES = (
    "property_alert_review",
    "property_market_bootstrap",
    "property_tour_followup",
)
_ASSISTANT_PROPERTY_SIGNAL_MARKERS = (
    "apartment alert",
    "property alert",
    "property candidate",
    "property candidates",
    "property scout",
    "property search",
    "review apartment alert",
    "review property alert",
    "willhaben",
    "immobilienscout",
)


def _env_truthy(name: str) -> bool:
    normalized = str(os.getenv(name) or "").strip().lower()
    return normalized in {"1", "true", "yes", "on", "enabled", "y"}


def _property_runtime_profile_enabled() -> bool:
    for env_name in ("PROPERTYQUARRY_SCHEDULER_PROFILE", "PROPERTYQUARRY_WORKER_PROFILE"):
        normalized = str(os.getenv(env_name) or "").strip().lower()
        if normalized in _PROPERTY_RUNTIME_PROFILES:
            return True
    return False


def assistant_property_lane_enabled() -> bool:
    # Property work belongs to PropertyQuarry. Keep it out of the EA assistant
    # unless a dedicated PropertyQuarry runtime opts into it explicitly.
    if not _env_truthy("EA_ASSISTANT_PROPERTY_LANE_ENABLED"):
        return False
    return _property_runtime_profile_enabled()


def assistant_property_task_hidden_from_ea(task_type: str) -> bool:
    return str(task_type or "").strip() in ASSISTANT_HIDDEN_PROPERTY_TASK_TYPES


def assistant_property_signal_present(*values: Any) -> bool:
    normalized = " ".join(
        " ".join(str(value or "").strip().lower().split())
        for value in values
        if str(value or "").strip()
    )
    if not normalized:
        return False
    return any(marker in normalized for marker in _ASSISTANT_PROPERTY_SIGNAL_MARKERS)
