from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


_ALLOWED_SOURCE_TYPES = {
    "source_controlled_ea_docs",
    "approved_security_trust_center",
    "approved_operator_runbook",
}
_SECRET_MARKERS = ("api_key=", "sk_live_", "secret-token")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _contains_secret(value: object) -> bool:
    lowered = str(value or "").lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def build_documentation_ai_publication_packet(
    docs: list[dict[str, object]],
    *,
    site_key: str,
    source_git_head: str,
    llms_txt: str,
    link_check: dict[str, object],
    provider_agent_writeback_enabled: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    normalized_docs = [dict(row or {}) for row in list(docs or [])]
    blocking_reasons: list[str] = []
    approved = True
    for row in normalized_docs:
        source_type = str(row.get("source_type") or "").strip()
        if source_type not in _ALLOWED_SOURCE_TYPES:
            blocking_reasons.append(f"forbidden_source_type_{source_type}")
        if str(row.get("approval_status") or "").strip() != "approved":
            approved = False
        if _contains_secret(row.get("content")):
            blocking_reasons.append("secret_marker_detected")
    if not approved:
        blocking_reasons.append("doc_approval_required")
    if not str(source_git_head or "").strip():
        blocking_reasons.append("source_git_head_required")
    if not str(llms_txt or "").strip():
        blocking_reasons.append("llms_txt_required")
    if str(link_check.get("status") or "").strip() != "pass" or list(link_check.get("broken_links") or []):
        blocking_reasons.append("link_check_failed")
    if provider_agent_writeback_enabled:
        blocking_reasons.append("provider_agent_writeback_enabled")
    source_tree_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "docs": normalized_docs,
                "site_key": str(site_key or "").strip(),
                "source_git_head": str(source_git_head or "").strip(),
                "llms_txt": str(llms_txt or "").strip(),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "contract_name": "ea.documentation_ai_publication.v1",
        "status": "projection_ready" if not blocking_reasons else "blocked",
        "generated_at": (now or _utc_now()).isoformat(),
        "site_key": str(site_key or "").strip(),
        "docs_projection_allowed": not blocking_reasons,
        "provider_agent_writeback_allowed": False,
        "publication_truth_allowed": False,
        "workspace_data_allowed": False,
        "blocking_reasons": blocking_reasons,
        "validation": {
            "documentation_truth_owner": "git",
            "approved_markdown_docs": "pass" if approved else "fail",
            "source_git_head": "pass" if str(source_git_head or "").strip() else "fail",
            "llms_txt": "pass" if str(llms_txt or "").strip() else "fail",
            "link_check": "pass" if "link_check_failed" not in blocking_reasons else "fail",
            "provider_agent_writeback": "fail" if provider_agent_writeback_enabled else "pass",
        },
        "llms_txt": {"present": bool(str(llms_txt or "").strip())},
        "source_tree_fingerprint": source_tree_fingerprint,
        "link_check": dict(link_check or {}),
        "docs": normalized_docs if not blocking_reasons else [],
    }
