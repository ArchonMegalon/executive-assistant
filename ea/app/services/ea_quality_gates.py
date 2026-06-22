from __future__ import annotations

from datetime import datetime, timezone


REQUIRED_SECURITY_TARGETS = (
    "webhook_signature_boundary",
    "approval_state_protection",
)
REQUIRED_VISUAL_TARGETS = (
    "expired_approval_links",
    "redacted_source_urls",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _target_failures(required: tuple[str, ...], rows: list[dict[str, object]], source_git_head: str) -> list[str]:
    indexed = {str(row.get("target") or "").strip(): dict(row or {}) for row in rows}
    failures: list[str] = []
    for target in required:
        row = indexed.get(target)
        if row is None:
            failures.append(f"missing:{target}")
            continue
        if str(row.get("status") or "").strip() != "pass":
            failures.append(f"failed:{target}")
        if str(row.get("source_git_head") or "").strip() != str(source_git_head or "").strip():
            failures.append(f"stale:{target}")
    return failures


def build_ea_quality_gate_receipt(
    *,
    source_git_head: str,
    security_results: list[dict[str, object]],
    visual_results: list[dict[str, object]],
    ea_release_receipt_status: str = "",
    provider_claims_release_truth: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    blocking_reasons: list[str] = []
    if not str(source_git_head or "").strip():
        blocking_reasons.append("source_git_head_required")
    if provider_claims_release_truth:
        blocking_reasons.append("provider_release_truth_claim_forbidden")
    blocking_reasons.extend(_target_failures(REQUIRED_SECURITY_TARGETS, list(security_results or []), source_git_head))
    blocking_reasons.extend(_target_failures(REQUIRED_VISUAL_TARGETS, list(visual_results or []), source_git_head))
    if str(ea_release_receipt_status or "").strip() not in {"", "pass"}:
        blocking_reasons.append("ea_release_receipt_not_pass")
    status = "pass" if not blocking_reasons and str(ea_release_receipt_status or "").strip() == "pass" else "blocked"
    return {
        "contract_name": "ea.quality_gates.v1",
        "status": status,
        "generated_at": (now or _utc_now()).isoformat(),
        "source_git_head": str(source_git_head or "").strip(),
        "blocking_reasons": blocking_reasons,
        "release_blocked": status != "pass",
        "release_claim_supported": status == "pass",
        "provider_evidence_can_block_release": True,
        "provider_evidence_can_make_release_green": False,
        "release_truth_owner": "ea_release_receipts_tests_operator_approval",
        "validation": {
            "rafter_security_targets": "pass"
            if not any(reason.startswith(("missing:", "failed:", "stale:")) and reason.split(":", 1)[1] in REQUIRED_SECURITY_TARGETS for reason in blocking_reasons)
            else "fail",
            "pixefy_visual_targets": "pass"
            if not any(reason.startswith(("missing:", "failed:", "stale:")) and reason.split(":", 1)[1] in REQUIRED_VISUAL_TARGETS for reason in blocking_reasons)
            else "fail",
            "provider_release_truth": "fail" if provider_claims_release_truth else "pass",
        },
        "security_results": list(security_results or []),
        "visual_results": list(visual_results or []),
    }
