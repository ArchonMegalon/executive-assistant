from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from app.services.approvethis_external_approval import (
    ApproveThisExternalApprovalService,
    approvethis_webhook_signature,
    build_approvethis_external_request,
    verify_approvethis_webhook_signature,
)


NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)
SECRET = "test-approvethis-webhook-secret"


def _body(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _signed_headers(body: bytes, *, timestamp: str = "1781784000") -> dict[str, str]:
    return {
        "x-approvethis-timestamp": timestamp,
        "x-approvethis-signature": approvethis_webhook_signature(body, SECRET, timestamp=timestamp),
    }


def _decision() -> dict[str, object]:
    return {
        "decision_id": "decision:board-pack-signoff",
        "title": "Approve the board preparation book?",
        "summary": "External board reviewer should approve the final packet before delivery.",
        "scope": "bounded_decision",
        "options": ["Approve", "Request changes", "Reject"],
    }


def _result_payload() -> dict[str, object]:
    return {
        "event_id": "evt-approval-001",
        "provider_request_id": "provider-request-123",
        "ea_decision_id": "decision:board-pack-signoff",
        "status": "approved",
        "approver": {"name": "External reviewer"},
    }


def test_external_request_requires_bounded_ea_decision() -> None:
    broad = _decision()
    broad["scope"] = "all_workspace"

    request = build_approvethis_external_request(
        broad,
        principal_id="principal-1",
        external_approver_contact="reviewer@example.com",
        now=NOW,
    )

    assert request["status"] == "blocked"
    assert request["blocking_reason"] == "bounded_ea_decision_required"
    assert request["external_transport_allowed"] is False
    assert request["downstream_action_allowed"] is False
    assert request["internal_queue_replaced"] is False


def test_external_request_hashes_approver_and_keeps_ea_as_truth_owner() -> None:
    request = build_approvethis_external_request(
        _decision(),
        principal_id="principal-1",
        workspace_id="workspace-1",
        external_approver_contact="reviewer@example.com",
        now=NOW,
    )

    assert request["status"] == "provider_request_ready"
    assert request["ea_decision_id"] == "decision:board-pack-signoff"
    assert request["provider_request"]["status"] == "ready"  # type: ignore[index]
    assert "reviewer@example.com" not in json.dumps(request)
    assert request["approver_contact_sha256"]
    assert request["provider_content_redacted"] is False
    assert request["provider_request"]["content_redacted"] is False  # type: ignore[index]
    assert request["validation"]["approval_truth_owner"] == "ea"  # type: ignore[index]
    assert request["approval_truth_allowed"] is False
    assert request["downstream_action_allowed"] is False


def test_external_request_blocks_private_or_secret_bearing_decision_payloads() -> None:
    private_decision = _decision()
    private_decision["data_classification"] = "restricted"

    private_request = build_approvethis_external_request(
        private_decision,
        principal_id="principal-1",
        external_approver_contact="reviewer@example.com",
        now=NOW,
    )

    assert private_request["status"] == "blocked"
    assert private_request["blocking_reason"] == "private_decision_not_external_transportable"
    assert private_request["external_transport_allowed"] is False
    assert private_request["provider_content_redacted"] is True
    assert private_request["provider_request"]["content_redacted"] is True  # type: ignore[index]
    assert private_request["options"] == []
    assert private_request["validation"]["external_provider_data_boundary"] == "fail"  # type: ignore[index]

    raw_source_decision = _decision()
    raw_source_decision["source_type"] = "raw_gmail"

    raw_source_request = build_approvethis_external_request(
        raw_source_decision,
        principal_id="principal-1",
        external_approver_contact="reviewer@example.com",
        now=NOW,
    )

    assert raw_source_request["status"] == "blocked"
    assert raw_source_request["blocking_reason"] == "forbidden_decision_source_type_raw_gmail"
    assert raw_source_request["external_transport_allowed"] is False

    secret_decision = _decision()
    secret_decision["summary"] = "Approve vendor exception. API_KEY=sk_live_secret must never leave EA."

    secret_request = build_approvethis_external_request(
        secret_decision,
        principal_id="principal-1",
        external_approver_contact="reviewer@example.com",
        now=NOW,
    )

    assert secret_request["status"] == "blocked"
    assert secret_request["blocking_reason"] == "secret_marker_detected"
    assert secret_request["external_transport_allowed"] is False
    assert secret_request["provider_content_redacted"] is True
    assert secret_request["decision_summary"] == ""
    assert secret_request["options"] == []
    assert "sk_live_secret" not in json.dumps(secret_request)
    assert secret_request["source_sha256"]


def test_signed_callback_maps_provider_result_to_evidence_only() -> None:
    request = build_approvethis_external_request(
        _decision(),
        principal_id="principal-1",
        external_approver_contact="reviewer@example.com",
        now=NOW,
    )
    body = _body(_result_payload())
    service = ApproveThisExternalApprovalService(webhook_secret=SECRET, clock=lambda: NOW)

    result = service.ingest_webhook(body=body, headers=_signed_headers(body), request_packet=request)

    assert result["status"] == "evidence_recorded"
    assert result["provider_status"] == "approved"
    assert result["webhook_verification"]["status"] == "pass"  # type: ignore[index]
    assert result["evidence"]["source_type"] == "approvethis_external_approval"  # type: ignore[index]
    assert result["ea_decision_update"]["status"] == "ready_for_ea_apply"  # type: ignore[index]
    assert result["ea_decision_update"]["requires_final_policy_gate"] is True  # type: ignore[index]
    assert result["approval_truth_allowed"] is False
    assert result["downstream_action_allowed"] is False
    assert result["final_policy_required"] is True


def test_callback_rejects_missing_secret_bad_signature_and_replay_timestamp() -> None:
    body = _body(_result_payload())
    missing = verify_approvethis_webhook_signature(body=body, signature_header="sha256=abc", secret="")
    assert missing.ok is False
    assert missing.reason == "webhook_secret_required"

    request = build_approvethis_external_request(
        _decision(),
        principal_id="principal-1",
        external_approver_contact="reviewer@example.com",
        now=NOW,
    )
    service = ApproveThisExternalApprovalService(webhook_secret=SECRET, clock=lambda: NOW)
    with pytest.raises(PermissionError, match="webhook_signature_mismatch"):
        service.ingest_webhook(
            body=body,
            headers={"x-approvethis-signature": "sha256=bad", "x-approvethis-timestamp": "1781784000"},
            request_packet=request,
        )

    old_timestamp = str(int((NOW - timedelta(minutes=9)).timestamp()))
    with pytest.raises(PermissionError, match="webhook_timestamp_outside_tolerance"):
        service.ingest_webhook(
            body=body,
            headers=_signed_headers(body, timestamp=old_timestamp),
            request_packet=request,
        )


def test_callback_rejects_decision_scope_mismatch() -> None:
    request = build_approvethis_external_request(
        _decision(),
        principal_id="principal-1",
        external_approver_contact="reviewer@example.com",
        now=NOW,
    )
    payload = _result_payload()
    payload["ea_decision_id"] = "decision:other"
    body = _body(payload)
    service = ApproveThisExternalApprovalService(webhook_secret=SECRET, clock=lambda: NOW)

    with pytest.raises(ValueError, match="approvethis_decision_scope_mismatch"):
        service.ingest_webhook(body=body, headers=_signed_headers(body), request_packet=request)


def test_callback_retry_is_idempotent() -> None:
    request = build_approvethis_external_request(
        _decision(),
        principal_id="principal-1",
        external_approver_contact="reviewer@example.com",
        now=NOW,
    )
    body = _body(_result_payload())
    headers = _signed_headers(body)
    service = ApproveThisExternalApprovalService(webhook_secret=SECRET, clock=lambda: NOW)

    first = service.ingest_webhook(body=body, headers=headers, request_packet=request)
    second = service.ingest_webhook(body=body, headers=headers, request_packet=request)

    assert first["result_id"] == second["result_id"]
    assert first["ingest_status"] == "created"
    assert second["ingest_status"] == "duplicate"
    assert second["idempotent_replay"] is True
    assert service.result_count == 1
