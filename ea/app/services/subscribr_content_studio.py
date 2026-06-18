from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Mapping


SOURCE_PACKET_CONTRACT = "ea.video_source_packet.v1"
SCRIPT_RECEIPT_CONTRACT = "ea.subscribr_script_draft.v1"

CONTENT_MODES = {
    "STRICT_CANON",
    "EDITORIAL_RESEARCH",
    "TUTORIAL",
    "NARRATIVE_DOSSIER",
    "MARKETING_EXPERIMENT",
    "PUBLIC_PRODUCT",
    "RELEASE_EXPLAINER",
    "INTEGRATION_TUTORIAL",
    "OPERATOR_TRAINING",
    "THOUGHT_LEADERSHIP",
    "MARKETING_RESEARCH",
}
FUTURE_ONLY_MODES = {"PRIVATE_VIDEO_BRIEF_BETA"}
AGENT_MODE_ALLOWED = {"EDITORIAL_RESEARCH", "MARKETING_EXPERIMENT", "THOUGHT_LEADERSHIP", "MARKETING_RESEARCH"}
PROVIDED_SOURCE_ONLY_MODES = {"STRICT_CANON", "TUTORIAL", "PUBLIC_PRODUCT", "RELEASE_EXPLAINER", "INTEGRATION_TUTORIAL"}
CHANNEL_KEYS = {
    "chummer-official",
    "chummer-academy",
    "black-ledger-newsroom",
    "chummer-gm-foundry",
    "runner-stories",
    "chummer-devlog",
    "chummer-de",
    "integration-lab",
    "ea-official",
    "ea-academy",
    "ea-trust-security",
    "ea-integrations",
    "ea-release-explainers",
    "ea-operator-training",
    "myexternalbrain-editorial",
    "ea-content-lab",
}
ALLOWED_CLASSIFICATIONS = {"public", "approved_public", "sanitized", "sanitized_internal", "operator_sanitized"}
FORBIDDEN_SOURCE_TYPES = {
    "raw_gmail",
    "raw_calendar",
    "workspace_attachment",
    "people_memory",
    "private_commitment",
    "private_decision",
    "customer_draft",
    "customer_support_conversation",
    "private_workspace_snapshot",
    "confidential_workspace_rule",
    "sourcebook_pdf",
    "copied_rulebook_prose",
    "private_campaign_data",
    "gm_only_secret",
    "entitlement_truth",
    "direct_publish",
    "secret",
}
ALLOWED_SOURCE_TYPES = {
    "approved_public_ea_docs",
    "approved_release_receipt",
    "current_release_receipt",
    "synthetic_demo_snapshot",
    "approved_operator_note",
    "approved_executive_note",
    "approved_security_trust_doc",
    "approved_ui_screenshot",
    "current_ui_route",
    "public_video_transcript",
    "public_research_source",
    "approved_public_source_packet",
    "public_release_receipt",
    "sanitized_explanation_packet",
    "deterministic_rule_explanation_packet",
    "approved_editorial_brief",
    "approved_origin_canon",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(value: object) -> str:
    return str(value or "").strip()


def _normalize_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _normalize(value).lower()).strip("_")


def _mode(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", _normalize(value).upper()).strip("_")


def _slug(value: object, *, fallback: str = "packet") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", _normalize(value).lower()).strip("-")
    return slug or fallback


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: object) -> str:
    return _sha256_bytes(_normalize(value).encode("utf-8"))


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _parse_time(value: object) -> datetime | None:
    raw = _normalize(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _text_has_secret_marker(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "api_key=",
            "api-key:",
            "secret=",
            "bearer sk_",
            "password=",
            "private_key",
            "subscribr_api_token",
        )
    )


def _text_has_private_email(text: str) -> bool:
    return bool(re.search(r"\b[A-Z0-9._%+-]+@(?!example\.invalid\b)[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.IGNORECASE))


def _claim_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", _normalize(value).lower())


def _claim_present(text: str, claim: object) -> bool:
    return _claim_key(claim) in _claim_key(text)


def _source_hash(source: Mapping[str, object]) -> str:
    explicit = _normalize(source.get("sha256"))
    if explicit:
        return explicit
    content = _normalize(source.get("content") or source.get("markdown") or source.get("text"))
    if content:
        return _sha256_text(content)
    return ""


def _source_type(source: Mapping[str, object]) -> str:
    return _normalize_key(source.get("source_type") or source.get("type") or source.get("authority"))


def _normalize_source(source: Mapping[str, object], *, ordinal: int) -> dict[str, object]:
    content = _normalize(source.get("content") or source.get("markdown") or source.get("text"))
    return {
        "ordinal": ordinal,
        "path": _normalize(source.get("path") or source.get("url") or source.get("title")),
        "authority": _normalize(source.get("authority") or source.get("source_type")),
        "source_type": _source_type(source),
        "sha256": _source_hash(source),
        "bytes": len(content.encode("utf-8")) if content else int(source.get("bytes") or 0),
        "data_classification": _normalize_key(source.get("data_classification") or "public"),
        "content_preview_sha256": _sha256_text(content[:500]) if content else "",
    }


def build_ea_video_source_packet(
    *,
    packet_id: str,
    content_mode: str,
    subscribr_channel_key: str,
    title: str,
    audience: str,
    sources: list[Mapping[str, object]] | tuple[Mapping[str, object], ...],
    required_claims: list[str] | tuple[str, ...],
    forbidden_claims: list[str] | tuple[str, ...],
    source_git_head: str,
    language: str = "en-US",
    target_words: int = 1400,
    template: str = "Educational",
    claim_scope: str = "",
    data_classification: str = "public",
    research_policy: str = "",
    human_review_required: bool = True,
    publication_allowed: bool = False,
    direct_publish_allowed: bool = False,
    provider_agent_mode_enabled: bool = False,
    privacy_retention_proof: Mapping[str, object] | None = None,
    expires_at: str = "",
    now: datetime | None = None,
) -> dict[str, object]:
    checked_at = now or _utc_now()
    normalized_sources = [
        _normalize_source(dict(source), ordinal=index)
        for index, source in enumerate(list(sources), start=1)
        if isinstance(source, Mapping)
    ]
    mode = _mode(content_mode)
    default_research_policy = "provided_sources_only" if mode in PROVIDED_SOURCE_ONLY_MODES else "external_research_allowed_with_sources"
    expiry = _normalize(expires_at) or (checked_at + timedelta(days=7)).isoformat()
    packet = {
        "contract_name": SOURCE_PACKET_CONTRACT,
        "packet_id": _slug(packet_id, fallback="ea-video-source-packet"),
        "content_mode": mode,
        "subscribr_channel_key": _normalize(subscribr_channel_key),
        "title": _normalize(title),
        "audience": _normalize(audience),
        "language": _normalize(language) or "en-US",
        "target_words": int(target_words or 0),
        "template": _normalize(template) or "Educational",
        "claim_scope": _normalize(claim_scope),
        "source_git_head": _normalize(source_git_head),
        "sources": normalized_sources,
        "required_claims": [_normalize(item) for item in required_claims if _normalize(item)],
        "forbidden_claims": [_normalize(item) for item in forbidden_claims if _normalize(item)],
        "data_classification": _normalize_key(data_classification or "public"),
        "research_policy": _normalize_key(research_policy or default_research_policy),
        "provider_agent_mode_enabled": bool(provider_agent_mode_enabled),
        "human_review_required": bool(human_review_required),
        "publication_allowed": bool(publication_allowed),
        "direct_publish_allowed": bool(direct_publish_allowed),
        "privacy_retention_proof": dict(privacy_retention_proof or {}),
        "expires_at": expiry,
        "created_at": checked_at.isoformat(),
    }
    validation = validate_ea_video_source_packet(packet, now=checked_at)
    packet["validation"] = validation
    packet["status"] = "source_packet_approved" if validation["status"] == "pass" else "blocked"
    packet["source_packet_sha256"] = _sha256_bytes(_json_bytes({key: value for key, value in packet.items() if key not in {"validation", "status", "source_packet_sha256"}}))
    return packet


def validate_ea_video_source_packet(packet: Mapping[str, object], *, now: datetime | None = None) -> dict[str, object]:
    checked_at = now or _utc_now()
    issues: list[str] = []
    mode = _mode(packet.get("content_mode"))
    if packet.get("contract_name") != SOURCE_PACKET_CONTRACT:
        issues.append("source_packet_contract_invalid")
    if mode in FUTURE_ONLY_MODES:
        issues.append("content_mode_future_only")
    elif mode not in CONTENT_MODES:
        issues.append("content_mode_invalid")
    if _normalize(packet.get("subscribr_channel_key")) not in CHANNEL_KEYS:
        issues.append("subscribr_channel_invalid")
    if not _normalize(packet.get("title")):
        issues.append("title_required")
    if not _normalize(packet.get("audience")):
        issues.append("audience_required")
    if not _normalize(packet.get("source_git_head")):
        issues.append("source_git_head_required")
    classification = _normalize_key(packet.get("data_classification") or "public")
    if classification not in ALLOWED_CLASSIFICATIONS:
        issues.append("classification_not_publishable")
    if packet.get("human_review_required") is not True:
        issues.append("human_review_required")
    if packet.get("publication_allowed") is not False:
        issues.append("publication_must_start_blocked")
    if packet.get("direct_publish_allowed") is not False:
        issues.append("direct_publish_forbidden")

    research_policy = _normalize_key(packet.get("research_policy"))
    if mode in PROVIDED_SOURCE_ONLY_MODES and research_policy != "provided_sources_only":
        issues.append("provided_sources_only_required")
    if packet.get("provider_agent_mode_enabled") is True and mode not in AGENT_MODE_ALLOWED:
        issues.append("agent_mode_not_allowed_for_mode")

    expiry = _parse_time(packet.get("expires_at"))
    if expiry is None:
        issues.append("expires_at_required")
    elif expiry <= checked_at:
        issues.append("source_packet_expired")

    sources = [_mapping(item) for item in _sequence(packet.get("sources")) if isinstance(item, Mapping)]
    if not sources:
        issues.append("sources_required")
    source_types = {_source_type(source) for source in sources}
    for source in sources:
        source_type = _source_type(source)
        if source_type in FORBIDDEN_SOURCE_TYPES:
            issues.append("forbidden_source_type_" + source_type)
        elif source_type not in ALLOWED_SOURCE_TYPES:
            issues.append("unapproved_source_type_" + (source_type or "missing"))
        if not _normalize(source.get("path")):
            issues.append("source_path_required")
        if not _normalize(source.get("sha256")):
            issues.append("source_sha256_required")
        source_classification = _normalize_key(source.get("data_classification") or "public")
        if source_classification not in ALLOWED_CLASSIFICATIONS:
            issues.append("source_classification_not_publishable")
        rendered = json.dumps(source, sort_keys=True)
        if _text_has_secret_marker(rendered):
            issues.append("secret_marker_detected")
        if _text_has_private_email(rendered):
            issues.append("private_email_detected")

    if mode == "RELEASE_EXPLAINER" and not ({"current_release_receipt", "approved_release_receipt"} & source_types):
        issues.append("release_receipt_required")
    if mode == "INTEGRATION_TUTORIAL" and not ({"approved_ui_screenshot", "current_ui_route"} & source_types):
        issues.append("current_ui_source_required")
    if mode == "OPERATOR_TRAINING":
        proof = _mapping(packet.get("privacy_retention_proof"))
        if _normalize_key(proof.get("status")) not in {"pass", "passed", "approved"}:
            issues.append("operator_training_privacy_retention_proof_required")

    if not _sequence(packet.get("required_claims")):
        issues.append("required_claims_required")
    if not _sequence(packet.get("forbidden_claims")):
        issues.append("forbidden_claims_required")

    return {
        "status": "pass" if not issues else "fail",
        "issues": sorted(set(issues)),
        "mode": mode,
        "channel_key": _normalize(packet.get("subscribr_channel_key")),
        "source_count": len(sources),
        "research_policy": research_policy,
        "agent_mode_allowed": mode in AGENT_MODE_ALLOWED,
        "human_review_required": packet.get("human_review_required") is True,
        "publication_allowed": False,
    }


def build_subscribr_script_receipt(
    source_packet: Mapping[str, object],
    *,
    script_markdown: str,
    provider_job: Mapping[str, object] | None = None,
    current_source_git_head: str = "",
    human_review: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    checked_at = now or _utc_now()
    packet = dict(source_packet)
    packet_validation = validate_ea_video_source_packet(packet, now=checked_at)
    script = _normalize(script_markdown)
    issues = list(packet_validation.get("issues") or [])
    if not script:
        issues.append("script_markdown_required")
    if _text_has_secret_marker(script):
        issues.append("script_secret_marker_detected")
    if _text_has_private_email(script):
        issues.append("script_private_email_detected")
    for claim in _sequence(packet.get("required_claims")):
        if not _claim_present(script, claim):
            issues.append("required_claim_missing_" + _slug(claim))
    for claim in _sequence(packet.get("forbidden_claims")):
        if _claim_present(script, claim):
            issues.append("forbidden_claim_present_" + _slug(claim))
    current_head = _normalize(current_source_git_head)
    source_head = _normalize(packet.get("source_git_head"))
    if current_head and source_head and current_head != source_head:
        issues.append("source_stale")

    review = dict(human_review or {})
    review_status = _normalize_key(review.get("status") or "pending")
    status = "review_required" if not issues else "blocked"
    packet_id = _normalize(packet.get("packet_id") or "ea-video-source-packet")
    job = dict(provider_job or {})
    script_hash = _sha256_text(script)
    draft_id = f"draft:video-script:{_slug(packet_id)}" if status == "review_required" else ""
    decision_id = f"decision:approve-video-script:{_slug(packet_id)}" if status == "review_required" else ""
    evidence_ids = (
        [
            f"evidence:source-packet:{_slug(packet_id)}",
            f"evidence:provider-export:{script_hash[:16]}",
        ]
        if status == "review_required"
        else []
    )
    return {
        "contract_name": SCRIPT_RECEIPT_CONTRACT,
        "status": status,
        "provider": "subscribr",
        "account_tier": "AppSumo Tier 7 / Scale 3",
        "packet_id": packet_id,
        "content_mode": _mode(packet.get("content_mode")),
        "channel_key": _normalize(packet.get("subscribr_channel_key")),
        "provider_channel_id": _normalize(job.get("channel_id") or job.get("provider_channel_id")),
        "provider_idea_id": _normalize(job.get("idea_id") or job.get("provider_idea_id")),
        "provider_script_id": _normalize(job.get("script_id") or job.get("provider_script_id")),
        "source_packet_sha256": _normalize(packet.get("source_packet_sha256")) or _sha256_bytes(_json_bytes(packet)),
        "source_git_head": _normalize(packet.get("source_git_head")),
        "current_source_git_head": current_head,
        "export_format": "markdown",
        "script_sha256": script_hash if script else "",
        "created_at": checked_at.isoformat(),
        "blocking_reasons": sorted(set(issues)),
        "validation": {
            "classification": "pass" if "classification_not_publishable" not in issues else "fail",
            "privacy": "pass"
            if not any(issue in issues for issue in ("private_email_detected", "secret_marker_detected", "script_private_email_detected", "script_secret_marker_detected"))
            else "fail",
            "source_binding": "pass" if not any(issue.startswith("required_claim_missing_") for issue in issues) else "fail",
            "freshness": "pass" if "source_stale" not in issues else "fail",
            "claims": "pass"
            if not any(issue.startswith("forbidden_claim_present_") or issue.startswith("required_claim_missing_") for issue in issues)
            else "fail",
            "copyright": "pass" if not any(issue.startswith("forbidden_source_type_") for issue in issues) else "fail",
            "brand_voice": "pass" if script else "fail",
            "source_packet": packet_validation["status"],
            "direct_publish": "blocked",
            "provider_board_status_can_publish": "blocked",
        },
        "ea_objects": {
            "draft_id": draft_id,
            "decision_id": decision_id,
            "evidence_ids": evidence_ids,
            "commitment_id": f"commitment:produce-approved-video:{_slug(packet_id)}" if review_status == "approved" and status == "review_required" else "",
        },
        "human_review": {
            "status": review_status if review_status in {"pending", "approved", "rejected", "changes_requested"} else "pending",
            "reviewer": _normalize(review.get("reviewer")),
            "reviewed_at": _normalize(review.get("reviewed_at")),
        },
        "provider_agent_mode_allowed": _mode(packet.get("content_mode")) in AGENT_MODE_ALLOWED,
        "publication_allowed": False,
        "direct_publish_allowed": False,
        "production_handoff_allowed": review_status == "approved" and status == "review_required",
        "provider_truth_allowed": False,
        "provider_board_status_allowed_to_publish": False,
    }


class SubscribrContentJobLedger:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, object]] = {}

    def create_or_get_job(self, source_packet: Mapping[str, object], provider_job: Mapping[str, object]) -> dict[str, object]:
        packet_id = _normalize(source_packet.get("packet_id"))
        if not packet_id:
            raise ValueError("packet_id_required")
        if packet_id in self._jobs:
            return {"status": "existing", "duplicate": True, "job": dict(self._jobs[packet_id])}
        job = {
            "packet_id": packet_id,
            "provider": "subscribr",
            "provider_channel_id": _normalize(provider_job.get("channel_id") or provider_job.get("provider_channel_id")),
            "provider_idea_id": _normalize(provider_job.get("idea_id") or provider_job.get("provider_idea_id")),
            "provider_script_id": _normalize(provider_job.get("script_id") or provider_job.get("provider_script_id")),
            "created_at": _utc_now().isoformat(),
            "direct_publish_allowed": False,
        }
        self._jobs[packet_id] = job
        return {"status": "created", "duplicate": False, "job": dict(job)}
