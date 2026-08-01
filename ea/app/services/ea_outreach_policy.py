from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.domain.outreach.recipient_basis import (
    ALLOWED_RECIPIENT_BASIS,
    FORBIDDEN_RECIPIENT_BASIS,
    validate_recipient_basis,
)


FORBIDDEN_CLAIM_MARKERS = (
    "sends autonomously",
    "autonomous send",
    "directly sends without review",
    "no human review",
    "no review needed",
    "replaces your assistant",
    "replace your assistant",
    "replaces the executive",
    "reads everything",
    "reads all systems",
    "connects every tool",
    "guarantees inbox zero",
    "never miss anything again",
    "broad autonomous agent platform",
)

ALLOWED_CLAIM_MARKERS = (
    "morning brief",
    "queue",
    "commitment",
    "draft",
    "evidence",
    "rules",
    "review",
    "gmail",
    "calendar",
)

PRIVATE_DATA_MARKERS = (
    "raw_gmail",
    "raw gmail",
    "raw_calendar",
    "raw calendar",
    "private contact list",
    "people_memory",
    "people memory",
    "private_commitment",
    "private commitment",
    "private_decision",
    "private decision",
    "customer_draft",
    "draft reply from a real workspace",
    "workspace_attachment",
    "attachment",
    "private_evidence",
    "customer support conversation",
    "oauth token",
    "api token",
    "billing",
    "likeness/private",
)


def _flatten_strings(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_flatten_strings(item))
        return strings
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        strings = []
        for item in value:
            strings.extend(_flatten_strings(item))
        return strings
    return [str(value)]


def _contains_any(texts: Iterable[str], markers: Iterable[str]) -> bool:
    joined = "\n".join(texts).lower()
    return any(marker in joined for marker in markers)


def validate_sendr_claims(packet: Mapping[str, object]) -> list[str]:
    issues: list[str] = []
    claim_texts = _flatten_strings(packet.get("allowed_claims"))
    claim_texts.extend(_flatten_strings(packet.get("message_copy")))
    claim_texts.extend(_flatten_strings(packet.get("personalized_page_copy")))
    claim_texts.extend(_flatten_strings(packet.get("video_script")))
    if _contains_any(claim_texts, FORBIDDEN_CLAIM_MARKERS):
        issues.append("forbidden_product_claim")
    if not _contains_any(claim_texts, ALLOWED_CLAIM_MARKERS):
        issues.append("no_approved_ea_claim_anchor")
    return issues


def validate_sendr_privacy_boundary(packet: Mapping[str, object]) -> list[str]:
    issues: list[str] = []
    source_texts = []
    for source in packet.get("source_material") or []:
        if isinstance(source, Mapping):
            source_texts.append(str(source.get("path") or ""))
            classification = str(source.get("classification") or "")
            if classification != "approved_public":
                issues.append("source_material_not_approved_public")
        else:
            source_texts.append(str(source))
    source_texts.extend(_flatten_strings(packet.get("allowed_inputs")))
    source_texts.extend(_flatten_strings(packet.get("message_copy")))
    source_texts.extend(_flatten_strings(packet.get("personalized_page_copy")))
    source_texts.extend(_flatten_strings(packet.get("video_script")))
    if _contains_any(source_texts, PRIVATE_DATA_MARKERS):
        issues.append("private_workspace_data_requested")
    if bool(packet.get("private_workspace_data_allowed")):
        issues.append("private_workspace_data_enabled")
    return issues


def validate_sendr_recipient_policy(packet: Mapping[str, object], recipients: Iterable[Mapping[str, object]] = ()) -> list[str]:
    issues: list[str] = []
    policy = packet.get("recipient_policy")
    if not isinstance(policy, Mapping):
        issues.append("recipient_policy_missing")
    else:
        allowed = set(str(value) for value in policy.get("allowed_recipient_basis") or [])
        forbidden = set(str(value) for value in policy.get("forbidden_recipient_basis") or [])
        if not ALLOWED_RECIPIENT_BASIS <= allowed:
            issues.append("recipient_policy_allowed_basis_incomplete")
        if not (FORBIDDEN_RECIPIENT_BASIS - {""}) <= forbidden:
            issues.append("recipient_policy_forbidden_basis_incomplete")
    for index, recipient in enumerate(recipients):
        for issue in validate_recipient_basis(recipient):
            issues.append(f"recipient_{index}_{issue}")
    return issues


def validate_sendr_review_boundary(packet: Mapping[str, object]) -> list[str]:
    issues: list[str] = []
    channels = packet.get("channels") if isinstance(packet.get("channels"), Mapping) else {}
    features = packet.get("sendr_features_allowed") if isinstance(packet.get("sendr_features_allowed"), Mapping) else {}
    if not bool(packet.get("human_review_required")):
        issues.append("human_review_not_required")
    if bool(packet.get("direct_send_allowed")):
        issues.append("direct_send_enabled")
    if bool(packet.get("auto_reply_allowed")):
        issues.append("auto_reply_enabled")
    if bool(channels.get("whatsapp")) or bool(features.get("whatsapp")):
        issues.append("whatsapp_enabled")
    return issues


def validate_sendr_campaign_packet(
    packet: Mapping[str, object],
    *,
    recipients: Iterable[Mapping[str, object]] = (),
) -> dict[str, Any]:
    claim_issues = validate_sendr_claims(packet)
    privacy_issues = validate_sendr_privacy_boundary(packet)
    recipient_issues = validate_sendr_recipient_policy(packet, recipients)
    review_issues = validate_sendr_review_boundary(packet)
    issue_codes = claim_issues + privacy_issues + recipient_issues + review_issues
    validation = {
        "claims": "blocked" if claim_issues else "pass",
        "recipient_basis": "blocked" if recipient_issues else "pass",
        "privacy": "blocked" if privacy_issues else "pass",
        "product_boundary": "blocked" if claim_issues or review_issues else "pass",
        "platform_policy": "blocked" if review_issues else "pass",
        "suppression": "blocked" if any("suppressed" in issue for issue in recipient_issues) else "pass",
        "human_review": "blocked" if review_issues else "pass",
    }
    return {
        "contract_name": "ea.sendr_campaign_validation.v1",
        "packet_id": str(packet.get("packet_id") or ""),
        "campaign_type": str(packet.get("campaign_type") or ""),
        "status": "blocked" if issue_codes else "pass",
        "validation": validation,
        "issues": [{"code": code} for code in issue_codes],
        "direct_send_allowed": bool(packet.get("direct_send_allowed")),
        "auto_reply_allowed": bool(packet.get("auto_reply_allowed")),
    }
