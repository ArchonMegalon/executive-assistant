from __future__ import annotations

import os


def assistant_property_lane_enabled() -> bool:
    # Property search belongs to PropertyQuarry. EA should stay out of that lane
    # unless a dedicated runtime explicitly enables it again.
    normalized = str(os.getenv("EA_ASSISTANT_PROPERTY_LANE_ENABLED") or "").strip().lower()
    return normalized in {"1", "true", "yes", "on", "enabled", "y"}
