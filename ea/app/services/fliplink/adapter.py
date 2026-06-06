from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass
from typing import Protocol

from app.services.fliplink.models import FlipLinkFormat


class FlipLinkAdapter(Protocol):
    def create_publication(self, request: dict[str, object]) -> dict[str, object]:
        ...

    def update_publication(self, publication_id: str, request: dict[str, object]) -> dict[str, object]:
        ...

    def archive_publication(self, publication_id: str) -> None:
        ...

    def fetch_analytics(self, publication_id: str) -> dict[str, object]:
        ...


@dataclass(frozen=True)
class ManualFlipLinkPublication:
    fliplink_url: str
    fliplink_format: FlipLinkFormat
    embed_code: str = ""
    qr_url: str = ""
    lead_capture_enabled: bool = False
    password_required: bool = False
    sale_mode_enabled: bool = False


def _allowed_custom_domains() -> set[str]:
    raw = ",".join(
        value
        for value in (
            os.getenv("FLIPLINK_CUSTOM_DOMAIN") or "",
            os.getenv("FLIPLINK_CUSTOM_DOMAINS") or "",
            "packets.propertyquarry.com,reports.propertyquarry.com,view.propertyquarry.com",
        )
        if value
    )
    return {item.strip().lower().rstrip(".") for item in raw.split(",") if item.strip()}


def _allow_raw_fliplink_domain() -> bool:
    return str(os.getenv("FLIPLINK_ALLOW_RAW_FLIPLINK_DOMAIN") or "0").strip().lower() in {"1", "true", "yes", "on"}


def is_custom_fliplink_domain(value: str) -> bool:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    normalized = str(parsed.hostname or "").strip().lower().rstrip(".")
    return bool(normalized and normalized in _allowed_custom_domains())


def _valid_fliplink_host(host: str) -> bool:
    normalized = str(host or "").strip().lower().rstrip(".")
    if normalized in _allowed_custom_domains():
        return True
    if not _allow_raw_fliplink_domain():
        return False
    return normalized == "fliplink.me" or normalized.endswith(".fliplink.me")


def validate_manual_fliplink_url(value: str) -> str:
    normalized = str(value or "").strip()
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("invalid_fliplink_url")
    if not _valid_fliplink_host(parsed.hostname or ""):
        raise ValueError("invalid_fliplink_url")
    return urllib.parse.urlunparse(parsed._replace(fragment=""))
