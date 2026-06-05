from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class PropertyPacketKind(str, Enum):
    OWNER_REVIEW = "owner_review"
    FAMILY_REVIEW = "family_review"
    AGENT_BRIEF = "agent_brief"
    SHORTLIST_BROCHURE = "shortlist_brochure"
    PAID_MARKET_REPORT = "paid_market_report"
    OPEN_HOUSE_QR = "open_house_qr"


class FlipLinkFormat(str, Enum):
    SMART_DOCUMENT = "smart_document"
    FLIPBOOK_3D = "flipbook_3d"


class PacketPrivacyMode(str, Enum):
    OWNER_PRIVATE = "owner_private"
    FAMILY_REVIEW = "family_review"
    AGENT_SHARE = "agent_share"
    ANONYMOUS_PUBLIC = "anonymous_public"
    PAID_CUSTOMER = "paid_customer"


def normalize_packet_kind(value: object) -> PropertyPacketKind:
    raw = value.value if isinstance(value, PropertyPacketKind) else str(value or "").strip().lower()
    for item in PropertyPacketKind:
        if raw == item.value:
            return item
    return PropertyPacketKind.OWNER_REVIEW


def normalize_fliplink_format(value: object, *, packet_kind: PropertyPacketKind | None = None) -> FlipLinkFormat:
    raw = value.value if isinstance(value, FlipLinkFormat) else str(value or "").strip().lower()
    for item in FlipLinkFormat:
        if raw == item.value:
            return item
    if packet_kind in {
        PropertyPacketKind.FAMILY_REVIEW,
        PropertyPacketKind.SHORTLIST_BROCHURE,
        PropertyPacketKind.OPEN_HOUSE_QR,
        PropertyPacketKind.PAID_MARKET_REPORT,
    }:
        default_raw = str(os.getenv("FLIPLINK_DEFAULT_FORMAT") or "").strip().lower()
        if default_raw == FlipLinkFormat.FLIPBOOK_3D.value and packet_kind != PropertyPacketKind.AGENT_BRIEF:
            return FlipLinkFormat.FLIPBOOK_3D
        if packet_kind in {PropertyPacketKind.SHORTLIST_BROCHURE, PropertyPacketKind.OPEN_HOUSE_QR}:
            return FlipLinkFormat.FLIPBOOK_3D
    return FlipLinkFormat.SMART_DOCUMENT


def normalize_privacy_mode(value: object, *, packet_kind: PropertyPacketKind | None = None) -> PacketPrivacyMode:
    raw = value.value if isinstance(value, PacketPrivacyMode) else str(value or "").strip().lower()
    for item in PacketPrivacyMode:
        if raw == item.value:
            return item
    if packet_kind == PropertyPacketKind.AGENT_BRIEF:
        return PacketPrivacyMode.AGENT_SHARE
    if packet_kind in {PropertyPacketKind.FAMILY_REVIEW, PropertyPacketKind.SHORTLIST_BROCHURE, PropertyPacketKind.OPEN_HOUSE_QR}:
        return PacketPrivacyMode.FAMILY_REVIEW
    if packet_kind == PropertyPacketKind.PAID_MARKET_REPORT:
        return PacketPrivacyMode.PAID_CUSTOMER
    return PacketPrivacyMode.OWNER_PRIVATE


@dataclass(frozen=True)
class FlipLinkSettings:
    login_email: str = ""
    login_password_present: bool = False
    account_tier: int = 10
    active_publication_cap: int = 1000
    custom_domain: str = "packets.propertyquarry.com"
    webhook_secret: str = ""
    webhook_allowed: bool = True
    browseract_enabled: bool = False


def _to_int(raw: object, default: int) -> int:
    try:
        return int(raw)
    except Exception:
        return default


def fliplink_settings_from_env() -> FlipLinkSettings:
    login_email = (
        str(os.getenv("FLIPLINK_LOGIN_EMAIL") or "").strip()
        or str(os.getenv("EA_FLIPLINK_LOGIN_EMAIL") or "").strip()
    )
    login_password = (
        str(os.getenv("FLIPLINK_LOGIN_PASSWORD") or "").strip()
        or str(os.getenv("EA_FLIPLINK_LOGIN_PASSWORD") or "").strip()
    )
    return FlipLinkSettings(
        login_email=login_email,
        login_password_present=bool(login_password),
        account_tier=max(1, _to_int(os.getenv("FLIPLINK_ACCOUNT_TIER") or "10", 10)),
        active_publication_cap=max(1, _to_int(os.getenv("FLIPLINK_ACTIVE_PUBLICATION_CAP") or "1000", 1000)),
        custom_domain=str(os.getenv("FLIPLINK_CUSTOM_DOMAIN") or "packets.propertyquarry.com").strip().lower().rstrip("."),
        webhook_secret=str(os.getenv("FLIPLINK_WEBHOOK_SECRET") or "").strip(),
        webhook_allowed=str(os.getenv("FLIPLINK_WEBHOOK_ALLOWED") or "1").strip().lower() not in {"0", "false", "no", "off"},
        browseract_enabled=str(os.getenv("FLIPLINK_BROWSERACT_ENABLED") or "0").strip().lower() in {"1", "true", "yes", "on"},
    )
