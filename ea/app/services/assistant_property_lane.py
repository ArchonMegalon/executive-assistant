from __future__ import annotations

import os

_PROPERTY_RUNTIME_PROFILES = {"property_only", "property-only", "property"}


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
