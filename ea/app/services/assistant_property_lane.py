from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from app.services.proactive_ooda_flat_search_policy import material_mentions_flat_property_search

_PROPERTY_RUNTIME_PROFILES = {"property_only", "property-only", "property"}
_PROPERTY_DEPLOY_MODES = {"property", "propertyquarry"}
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


def _propertyquarry_default_brand_enabled() -> bool:
    normalized = str(os.getenv("PROPERTYQUARRY_DEFAULT_BRAND") or "").strip().lower()
    return normalized not in {"", "0", "false", "no", "off"}


def _normalized_mode_tokens(raw: str) -> tuple[str, ...]:
    values = [
        part.strip().lower()
        for chunk in str(raw or "").replace(";", ",").split(",")
        for part in chunk.split()
        if part.strip()
    ]
    return tuple(dict.fromkeys(values))


def _property_deploy_mode_enabled() -> bool:
    for env_name in ("EA_DEPLOY_PRIMARY_MODE", "EA_DEPLOY_PROJECT_MODE"):
        primary_modes = _normalized_mode_tokens(str(os.getenv(env_name) or ""))
        if primary_modes:
            return all(mode in _PROPERTY_DEPLOY_MODES for mode in primary_modes)
    enabled_modes = _normalized_mode_tokens(str(os.getenv("EA_DEPLOY_ENABLED_MODES") or ""))
    if enabled_modes:
        return all(mode in _PROPERTY_DEPLOY_MODES for mode in enabled_modes)
    return False


def assistant_property_lane_enabled() -> bool:
    # Property discovery and apartment-search OODA no longer run inside the EA
    # assistant. PropertyQuarry owns that lane end to end.
    return False


def assistant_property_task_hidden_from_ea(task_type: str) -> bool:
    return str(task_type or "").strip() in ASSISTANT_HIDDEN_PROPERTY_TASK_TYPES


def _material_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(_material_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_material_text(item) for item in value)
    return str(value or "")


def assistant_property_signal_present(*values: Any) -> bool:
    normalized = " ".join(
        " ".join(_material_text(value).strip().lower().split())
        for value in values
        if _material_text(value).strip()
    )
    if not normalized:
        return False
    if any(marker in normalized for marker in _ASSISTANT_PROPERTY_SIGNAL_MARKERS):
        return True
    return material_mentions_flat_property_search(*values)
