from __future__ import annotations

import re
from typing import Mapping


ALLOWED_RECIPIENT_BASIS = frozenset(
    {
        "public_business_contact",
        "prior_conversation",
        "inbound_lead",
        "opt_in",
        "opt_in_waitlist",
        "existing_customer",
        "trial_user",
        "event_context",
        "manual_partner_shortlist",
        "referral_introduction",
    }
)

FORBIDDEN_RECIPIENT_BASIS = frozenset(
    {
        "raw_gmail_contact",
        "private_calendar_attendee",
        "scraped_private_profile",
        "private_whatsapp_export",
        "purchased_personal_list_without_lawful_basis",
        "unknown",
        "",
    }
)

ALLOWED_CHANNELS = frozenset({"email", "linkedin"})

SUPPRESSION_BLOCKING_STATUSES = frozenset(
    {
        "unsubscribe",
        "unsubscribed",
        "bounce",
        "bounced",
        "negative_response",
        "complaint",
        "manual_suppression",
        "suppressed",
        "unknown_legal_basis",
    }
)


def normalize_token(value: object) -> str:
    lowered = str(value or "").strip().strip("`").lower()
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def validate_recipient_basis(recipient: Mapping[str, object]) -> list[str]:
    issues: list[str] = []
    basis = normalize_token(recipient.get("recipient_basis"))
    if basis not in ALLOWED_RECIPIENT_BASIS or basis in FORBIDDEN_RECIPIENT_BASIS:
        issues.append("recipient_basis_missing_or_forbidden")
    if not str(recipient.get("source_url_or_note") or "").strip():
        issues.append("recipient_source_missing")
    channel = normalize_token(recipient.get("allowed_channel") or recipient.get("channel"))
    if channel not in ALLOWED_CHANNELS:
        issues.append("recipient_channel_not_allowed")
    suppression = normalize_token(recipient.get("suppression_status"))
    if suppression in SUPPRESSION_BLOCKING_STATUSES:
        issues.append("recipient_suppressed")
    if not str(recipient.get("last_verified_at") or "").strip():
        issues.append("recipient_last_verified_at_missing")
    return issues


def recipient_basis_policy() -> dict[str, list[str]]:
    return {
        "allowed_recipient_basis": sorted(ALLOWED_RECIPIENT_BASIS),
        "forbidden_recipient_basis": sorted(FORBIDDEN_RECIPIENT_BASIS - {""}),
        "allowed_channels": sorted(ALLOWED_CHANNELS),
        "blocking_suppression_statuses": sorted(SUPPRESSION_BLOCKING_STATUSES),
    }
