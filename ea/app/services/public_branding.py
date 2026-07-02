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

EA_PUBLIC_HOSTS = _normalized_hosts_from_env(
    "EA_PUBLIC_HOSTS",
    default=("myexternalbrain.com", "www.myexternalbrain.com"),
)


def _propertyquarry_default_enabled() -> bool:
    raw = str(os.getenv("PROPERTYQUARRY_DEFAULT_BRAND") or "0").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _propertyquarry_brand() -> dict[str, str]:
    return {
        "key": "propertyquarry",
        "name": "PropertyQuarry",
        "mark": "PQ",
        "create_label": "Create account",
        "sign_in_label": "Sign in",
        "workspace_label": "Property research workspace",
        "app_home": "/app/properties",
        "public_base_url": str(
            os.getenv("PROPERTY_PUBLIC_BASE_URL")
            or os.getenv("PROPERTYQUARRY_PUBLIC_BASE_URL")
            or "https://propertyquarry.com"
        ).strip().rstrip("/"),
        "repo_url": "https://github.com/ArchonMegalon/property",
    }


def brand_from_hostname(hostname: str | None) -> dict[str, str]:
    normalized = str(hostname or "").strip().lower().rstrip(".")
    if normalized in EA_PUBLIC_HOSTS:
        return {
            "key": "ea",
            "name": "Executive Assistant",
            "mark": "EA",
            "create_label": "Create personal workspace",
            "sign_in_label": "Sign in",
            "workspace_label": "Assistant workspace",
            "app_home": "/app/today",
            "public_base_url": str(os.getenv("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/"),
            "repo_url": "https://github.com/ArchonMegalon/executive-assistant/blob/main/ARCHITECTURE_MAP.md",
        }
    if normalized in PROPERTYQUARRY_HOSTS or _propertyquarry_default_enabled():
        return _propertyquarry_brand()
    return {
        "key": "ea",
        "name": "Executive Assistant",
        "mark": "EA",
        "create_label": "Create personal workspace",
        "sign_in_label": "Sign in",
        "workspace_label": "Assistant workspace",
        "app_home": "/app/today",
        "public_base_url": str(os.getenv("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/"),
        "repo_url": "https://github.com/ArchonMegalon/executive-assistant/blob/main/ARCHITECTURE_MAP.md",
    }


def request_brand(request: Any) -> dict[str, str]:
    return brand_from_hostname(request_hostname(request))
