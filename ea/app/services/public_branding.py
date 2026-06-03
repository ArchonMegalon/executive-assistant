from __future__ import annotations

import os
from typing import Any

from app.services.public_clickrank import request_hostname


def _normalized_hosts_from_env(name: str, *, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = str(os.getenv(name) or "").strip()
    values = [entry.strip().lower().rstrip(".") for entry in raw.split(",") if entry.strip()]
    if values:
        return tuple(dict.fromkeys(values))
    return default


PROPERTYQUARRY_HOSTS = _normalized_hosts_from_env(
    "PROPERTYQUARRY_PUBLIC_HOSTS",
    default=("propertyquarry.com", "www.propertyquarry.com"),
)


def brand_from_hostname(hostname: str | None) -> dict[str, str]:
    normalized = str(hostname or "").strip().lower().rstrip(".")
    if normalized in PROPERTYQUARRY_HOSTS:
        return {
            "key": "propertyquarry",
            "name": "PropertyQuarry",
            "mark": "PQ",
            "create_label": "Create account",
            "sign_in_label": "Sign in",
            "workspace_label": "Property research workspace",
            "repo_url": "https://github.com/ArchonMegalon/propertyquarry",
        }
    return {
        "key": "ea",
        "name": "Executive Assistant",
        "mark": "EA",
        "create_label": "Create personal workspace",
        "sign_in_label": "Sign in",
        "workspace_label": "Assistant workspace",
        "repo_url": "https://github.com/ArchonMegalon/executive-assistant/blob/main/ARCHITECTURE_MAP.md",
    }


def request_brand(request: Any) -> dict[str, str]:
    return brand_from_hostname(request_hostname(request))
