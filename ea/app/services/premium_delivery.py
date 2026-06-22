from __future__ import annotations

import hashlib
from datetime import datetime, timezone


_FORBIDDEN_SOURCE_TYPES = {"raw_gmail", "customer_support_ticket"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_premium_delivery_packet(
    packet: dict[str, object],
    *,
    principal_id: str,
    workspace_id: str = "",
    rendered_artifact_bytes: bytes | None = None,
    rendered_filename: str = "",
    fliplink_publication: dict[str, object] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    normalized = dict(packet or {})
    blocking_reasons: list[str] = []
    validation = {
        "approved_source_packet": "pass",
        "private_redaction_access_policy": "pass",
        "artifact_hash": "pass" if rendered_artifact_bytes and rendered_filename else "fail",
        "direct_publish": "blocked",
    }
    if str(normalized.get("approval_status") or "").strip() != "approved":
        blocking_reasons.append("approved_source_packet_required")
        validation["approved_source_packet"] = "fail"
    for source_ref in list(normalized.get("source_refs") or []):
        source_type = str(dict(source_ref or {}).get("source_type") or "").strip()
        if source_type in _FORBIDDEN_SOURCE_TYPES:
            blocking_reasons.append(f"forbidden_source_type_{source_type}")
            validation["approved_source_packet"] = "fail"
    if bool(normalized.get("direct_publish_allowed")):
        blocking_reasons.append("direct_publish_not_allowed")
    if bool(normalized.get("content_mutation_allowed")):
        blocking_reasons.append("content_mutation_not_allowed")
    classification = str(normalized.get("data_classification") or "").strip().lower()
    if classification in {"board_private", "private"}:
        redaction_policy = dict(normalized.get("redaction_policy") or {})
        access_policy = dict(normalized.get("access_policy") or {})
        if str(redaction_policy.get("status") or "").strip() != "pass":
            blocking_reasons.append("redaction_policy_required")
            validation["private_redaction_access_policy"] = "fail"
        elif not access_policy:
            blocking_reasons.append("access_policy_required")
            validation["private_redaction_access_policy"] = "fail"
    render_request_status = "ready" if not blocking_reasons else "blocked"
    status = "render_ready" if not blocking_reasons else "blocked"
    rendered_artifact = {}
    if rendered_artifact_bytes is not None and rendered_filename:
        rendered_artifact = {
            "filename": str(rendered_filename or "").strip(),
            "sha256": hashlib.sha256(bytes(rendered_artifact_bytes or b"")).hexdigest(),
        }
        validation["artifact_hash"] = "pass"
    presentation = {
        "provider": "fliplink" if fliplink_publication else "",
        "publication": dict(fliplink_publication or {}),
        "owns_truth": False,
    }
    return {
        "contract_name": "ea.premium_delivery.v1",
        "status": status,
        "generated_at": (now or _utc_now()).isoformat(),
        "principal_id": str(principal_id or "").strip(),
        "workspace_id": str(workspace_id or "").strip(),
        "blocking_reasons": blocking_reasons,
        "validation": validation,
        "render_request": {"status": render_request_status},
        "rendered_artifact": rendered_artifact,
        "presentation": presentation,
        "publication_allowed": False,
        "external_delivery_allowed": False,
        "provider_truth_allowed": False,
        "direct_publish_allowed": False,
    }
