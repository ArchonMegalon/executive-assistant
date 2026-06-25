from __future__ import annotations

import os


EA_PUBLIC_APP_DEFAULT_URL = "https://myexternalbrain.com"
PROPERTYQUARRY_PUBLIC_DEFAULT_URL = "https://propertyquarry.com"


def normalized_public_url(value: object, *, default: str = "") -> str:
    candidate = str(value or "").strip().rstrip("/")
    if candidate:
        return candidate
    return str(default or "").strip().rstrip("/")


def ea_public_app_base_url() -> str:
    return normalized_public_url(os.getenv("EA_PUBLIC_APP_BASE_URL"), default=EA_PUBLIC_APP_DEFAULT_URL)


def propertyquarry_public_base_url() -> str:
    return normalized_public_url(
        os.getenv("PROPERTYQUARRY_PUBLIC_BASE_URL"),
        default=PROPERTYQUARRY_PUBLIC_DEFAULT_URL,
    )


def propertyquarry_public_tour_base_url() -> str:
    explicit = normalized_public_url(os.getenv("PROPERTYQUARRY_PUBLIC_TOUR_BASE_URL"))
    if explicit:
        return explicit
    return f"{propertyquarry_public_base_url()}/tours"
