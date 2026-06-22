from __future__ import annotations

from datetime import datetime, timezone

from app.services.ea_quality_gates import (
    REQUIRED_SECURITY_TARGETS,
    REQUIRED_VISUAL_TARGETS,
    build_ea_quality_gate_receipt,
)


NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)
HEAD = "abc123"


def _security_results(head: str = HEAD) -> list[dict[str, object]]:
    return [
        {"target": target, "status": "pass", "evidence_id": f"rafter:{target}", "source_git_head": head}
        for target in REQUIRED_SECURITY_TARGETS
    ]


def _visual_results(head: str = HEAD) -> list[dict[str, object]]:
    return [
        {"target": target, "status": "pass", "evidence_id": f"pixefy:{target}", "source_git_head": head}
        for target in REQUIRED_VISUAL_TARGETS
    ]


def test_quality_gate_passes_when_all_targets_match_current_head() -> None:
    receipt = build_ea_quality_gate_receipt(
        source_git_head=HEAD,
        security_results=_security_results(),
        visual_results=_visual_results(),
        ea_release_receipt_status="pass",
        now=NOW,
    )

    assert receipt["status"] == "pass"
    assert receipt["release_blocked"] is False
    assert receipt["release_claim_supported"] is True
    assert receipt["provider_evidence_can_block_release"] is True
    assert receipt["provider_evidence_can_make_release_green"] is False
    assert receipt["release_truth_owner"] == "ea_release_receipts_tests_operator_approval"
    assert receipt["validation"]["rafter_security_targets"] == "pass"  # type: ignore[index]
    assert receipt["validation"]["pixefy_visual_targets"] == "pass"  # type: ignore[index]


def test_quality_gate_blocks_missing_visual_target() -> None:
    visual = [row for row in _visual_results() if row["target"] != "expired_approval_links"]

    receipt = build_ea_quality_gate_receipt(
        source_git_head=HEAD,
        security_results=_security_results(),
        visual_results=visual,
        ea_release_receipt_status="pass",
        now=NOW,
    )

    assert receipt["status"] == "blocked"
    assert receipt["release_blocked"] is True
    assert "missing:expired_approval_links" in receipt["blocking_reasons"]
    assert receipt["validation"]["pixefy_visual_targets"] == "fail"  # type: ignore[index]
    assert receipt["release_claim_supported"] is False


def test_quality_gate_blocks_security_failure() -> None:
    security = _security_results()
    security[0]["status"] = "fail"

    receipt = build_ea_quality_gate_receipt(
        source_git_head=HEAD,
        security_results=security,
        visual_results=_visual_results(),
        ea_release_receipt_status="pass",
        now=NOW,
    )

    assert receipt["status"] == "blocked"
    assert f"failed:{REQUIRED_SECURITY_TARGETS[0]}" in receipt["blocking_reasons"]
    assert receipt["validation"]["rafter_security_targets"] == "fail"  # type: ignore[index]


def test_quality_gate_blocks_stale_provider_evidence() -> None:
    receipt = build_ea_quality_gate_receipt(
        source_git_head=HEAD,
        security_results=_security_results(head="oldhead"),
        visual_results=_visual_results(),
        ea_release_receipt_status="pass",
        now=NOW,
    )

    assert receipt["status"] == "blocked"
    assert f"stale:{REQUIRED_SECURITY_TARGETS[0]}" in receipt["blocking_reasons"]
    assert receipt["release_claim_supported"] is False


def test_quality_gate_blocks_provider_release_truth_claim_and_missing_head() -> None:
    receipt = build_ea_quality_gate_receipt(
        source_git_head="",
        security_results=_security_results(head=""),
        visual_results=_visual_results(head=""),
        provider_claims_release_truth=True,
        now=NOW,
    )

    assert receipt["status"] == "blocked"
    assert "source_git_head_required" in receipt["blocking_reasons"]
    assert "provider_release_truth_claim_forbidden" in receipt["blocking_reasons"]
    assert receipt["validation"]["provider_release_truth"] == "fail"  # type: ignore[index]
    assert receipt["provider_evidence_can_make_release_green"] is False
