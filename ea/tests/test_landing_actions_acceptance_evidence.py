from __future__ import annotations

import json
import sys
from pathlib import Path

from app.api.routes import landing_actions


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from verify_executive_assistant_acceptance_evidence import (  # noqa: E402
    verify_executive_assistant_acceptance_evidence,
)
import materialize_executive_assistant_acceptance_evidence as acceptance_materializer  # noqa: E402
from verify_executive_assistant_quality_readiness import (  # noqa: E402
    verify_executive_assistant_quality_readiness,
)
from verify_whole_project_signal_to_decision_receipt import (  # noqa: E402
    verify_whole_project_signal_to_decision_receipt,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_landing_acceptance_receipt_refresh_matches_verifier_contract(tmp_path: Path) -> None:
    receipt = landing_actions._default_acceptance_receipt()  # noqa: SLF001
    rows = dict(receipt.get("acceptance_keys") or {})
    row = dict(rows["real_daily_morning_brief_accepted"])
    row.update(
        {
            "accepted": True,
            "status": "accepted_redacted",
            "source_kind": "operator_admin",
            "recorded_at": "2026-06-30T00:00:00Z",
            "evidence_sha256": "evidence-hash",
            "actor_sha256": "actor-hash",
            "object_ref_sha256": "object-hash",
            "raw_evidence_exposed": False,
            "raw_actor_exposed": False,
            "raw_object_ref_exposed": False,
        }
    )
    rows["real_daily_morning_brief_accepted"] = row

    landing_actions._refresh_acceptance_receipt_summary(receipt, rows)  # noqa: SLF001
    receipt_path = tmp_path / "acceptance.json"
    _write_json(receipt_path, receipt)

    verification = verify_executive_assistant_acceptance_evidence(receipt_path)
    assert verification["status"] == "pass"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["source_git_head"]
    assert receipt["source_state_fingerprint"]
    assert receipt["next_action_proof_key"] == "real_decision_cleared"
    assert receipt["real_principal_acceptance_verified"] is True


def test_acceptance_materializer_derives_decision_from_proactive_ooda_gold_only(
    tmp_path: Path,
) -> None:
    gold_path = tmp_path / "ooda-gold.json"
    _write_json(
        gold_path,
        {
            "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
            "status": "pass",
            "gold_claim_allowed": True,
            "generated_at": "2026-06-30T00:10:00Z",
            "proofs": {
                "approval_outcome": {
                    "accepted": True,
                    "approval_outcome_recorded": True,
                    "status": "accepted_redacted",
                    "recorded_at": "2026-06-30T00:09:00Z",
                    "evidence_sha256": "e" * 64,
                    "actor_sha256": "a" * 64,
                    "packet_ref_sha256": "p" * 64,
                    "staged_artifact_sha256": "s" * 64,
                    "raw_evidence_exposed": False,
                    "raw_actor_exposed": False,
                    "raw_packet_ref_exposed": False,
                    "raw_staged_artifact_exposed": False,
                }
            },
        },
    )

    receipt_path = tmp_path / "acceptance.json"
    receipt = acceptance_materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=receipt_path,
        preserve_existing=False,
        proactive_ooda_gold_receipt_path=gold_path,
    )

    verification = verify_executive_assistant_acceptance_evidence(receipt_path)
    assert verification["status"] == "pass"
    assert "real_decision_cleared" in receipt["accepted_keys"]
    assert "real_commitment_recovered_or_closed" in receipt["blocked_keys"]
    assert "real_approved_action_audited" in receipt["blocked_keys"]
    assert "real_provider_failure_recovered" in receipt["blocked_keys"]
    decision = dict(dict(receipt["acceptance_keys"])["real_decision_cleared"])
    assert decision["source_kind"] == "proactive_ooda_gold_acceptance"
    assert decision["claim_boundary"] == "proves_a_real_proactive_packet_decision_only"
    assert decision["raw_evidence_exposed"] is False


def test_acceptance_materializer_derives_google_workspace_auth_approved_action(
    tmp_path: Path,
) -> None:
    recipient_email = "work@example.test"
    principal_id = "cf-email:owner@example.test"
    receipt_path = tmp_path / "acceptance.json"

    receipt = acceptance_materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=receipt_path,
        preserve_existing=False,
        google_workspace_auth_action_bundle={
            "principal_id": principal_id,
            "recipient_email": recipient_email,
            "observations": [
                {
                    "event_type": "google_connect_email_sent",
                    "created_at": "2026-07-01T06:06:23Z",
                    "payload": {
                        "recipient_email": recipient_email,
                        "scope_bundle": "full_workspace",
                        "provider": "emailit",
                        "access_session_id": "session-123",
                    },
                },
                {
                    "event_type": "workspace_access_session_issued",
                    "created_at": "2026-07-01T06:06:22Z",
                    "payload": {
                        "email": recipient_email,
                        "source_kind": "google_connect_email",
                        "session_id": "session-123",
                    },
                },
            ],
            "preference_evidence_events": [
                {
                    "event_type": "explicit_work_google_workspace_intake_requested",
                    "recorded_at": "2026-07-01T06:08:33Z",
                    "domain": "office_routing",
                    "object_type": "google_workspace_account",
                    "object_id": recipient_email,
                    "interpreted_signal_json": {"account_email": recipient_email},
                }
            ],
            "preference_nodes": [
                {
                    "domain": "office_routing",
                    "category": "constraint",
                    "key": "primary_work_google_workspace_email",
                    "value_json": {"account_email": recipient_email},
                    "updated_at": "2026-07-01T06:08:36Z",
                },
                {
                    "domain": "office_routing",
                    "category": "soft_preference",
                    "key": "work_inbox_signal_policy",
                    "value_json": {"calendar_writes": "approval_required"},
                    "updated_at": "2026-07-01T06:08:36Z",
                },
            ],
        },
    )

    verification = verify_executive_assistant_acceptance_evidence(receipt_path)
    assert verification["status"] == "pass"
    assert "real_approved_action_audited" in receipt["accepted_keys"]
    row = dict(dict(receipt["acceptance_keys"])["real_approved_action_audited"])
    assert row["source_kind"] == "google_workspace_auth_action_live_observation"
    assert row["claim_boundary"] == "proves_google_workspace_auth_email_action_was_delivered_and_audited_only"
    assert row["scope_bundle"] == "full_workspace"
    assert row["provider"] == "emailit"
    assert row["policy_node_keys"] == ["primary_work_google_workspace_email", "work_inbox_signal_policy"]
    assert row["raw_email_exposed"] is False
    assert row["raw_payload_exposed"] is False
    receipt_text = receipt_path.read_text(encoding="utf-8")
    assert recipient_email not in receipt_text
    assert principal_id not in receipt_text
    assert "session-123" not in receipt_text


def test_acceptance_materializer_does_not_derive_google_auth_action_without_request(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "acceptance.json"

    receipt = acceptance_materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=receipt_path,
        preserve_existing=False,
        google_workspace_auth_action_bundle={
            "principal_id": "cf-email:owner@example.test",
            "recipient_email": "work@example.test",
            "observations": [
                {
                    "event_type": "google_connect_email_sent",
                    "created_at": "2026-07-01T06:06:23Z",
                    "payload": {
                        "recipient_email": "work@example.test",
                        "scope_bundle": "full_workspace",
                        "provider": "emailit",
                        "access_session_id": "session-123",
                    },
                },
                {
                    "event_type": "workspace_access_session_issued",
                    "created_at": "2026-07-01T06:06:22Z",
                    "payload": {
                        "email": "work@example.test",
                        "source_kind": "google_connect_email",
                        "session_id": "session-123",
                    },
                },
            ],
            "preference_evidence_events": [],
        },
    )

    verification = verify_executive_assistant_acceptance_evidence(receipt_path)
    assert verification["status"] == "pass"
    assert "real_approved_action_audited" not in receipt["accepted_keys"]
    row = dict(dict(receipt["acceptance_keys"])["real_approved_action_audited"])
    assert row["accepted"] is False


def test_acceptance_materializer_derives_commitment_closure_from_redacted_receipt(
    tmp_path: Path,
) -> None:
    principal_id = "cf-email:owner@example.test"
    commitment_id = "commitment-123"
    source_ref = "ea-liveops:google-workspace-auth:work-inbox:20260701"
    receipt_path = tmp_path / "acceptance.json"

    receipt = acceptance_materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=receipt_path,
        preserve_existing=False,
        commitment_closure_bundle={
            "principal_id": principal_id,
            "commitments": [
                {
                    "commitment_id": commitment_id,
                    "title": "Send Google Full Workspace auth request to the work inbox",
                    "status": "completed",
                    "source_json": {
                        "source_type": "operator_commitment",
                        "source_ref": source_ref,
                        "resolution_code": "completed",
                    },
                    "updated_at": "2026-07-01T07:04:00Z",
                }
            ],
            "observations": [
                {
                    "event_type": "commitment_created",
                    "created_at": "2026-07-01T07:00:00Z",
                    "source_id": commitment_id,
                    "payload": {"kind": "commitment", "title": "Send Google auth"},
                },
                {
                    "event_type": "commitment_closed",
                    "created_at": "2026-07-01T07:04:00Z",
                    "source_id": commitment_id,
                    "payload": {
                        "item_ref": f"commitment:{commitment_id}",
                        "action": "close",
                        "actor": "operator",
                        "reason": "Auth request sent and audited.",
                        "reason_code": "completed",
                    },
                },
                {
                    "event_type": "commitment_closure_evidence_receipt_recorded",
                    "created_at": "2026-07-01T07:04:02Z",
                    "source_id": commitment_id,
                    "payload": {
                        "contract_name": acceptance_materializer.COMMITMENT_CLOSURE_RECEIPT_CONTRACT,
                        "item_ref": f"commitment:{commitment_id}",
                        "source_ref": source_ref,
                        "evidence_event_types": [
                            "explicit_work_google_workspace_intake_requested",
                            "workspace_access_session_issued",
                            "google_connect_email_sent",
                        ],
                        "raw_private_context_exposed": False,
                    },
                },
            ],
        },
    )

    verification = verify_executive_assistant_acceptance_evidence(receipt_path)
    assert verification["status"] == "pass"
    assert "real_commitment_recovered_or_closed" in receipt["accepted_keys"]
    row = dict(dict(receipt["acceptance_keys"])["real_commitment_recovered_or_closed"])
    assert row["source_kind"] == "commitment_closure_live_observation"
    assert row["claim_boundary"] == "proves_one_real_internal_commitment_was_closed_with_redacted_evidence_receipt_only"
    assert row["derived_from_contract"] == "ea.commitment_closure_observations.v1"
    assert row["raw_commitment_text_exposed"] is False
    assert row["raw_private_context_exposed"] is False
    receipt_text = receipt_path.read_text(encoding="utf-8")
    assert principal_id not in receipt_text
    assert commitment_id not in receipt_text
    assert source_ref not in receipt_text
    assert "Send Google Full Workspace auth request" not in receipt_text


def test_acceptance_materializer_does_not_derive_commitment_closure_without_receipt(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "acceptance.json"

    receipt = acceptance_materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=receipt_path,
        preserve_existing=False,
        commitment_closure_bundle={
            "principal_id": "cf-email:owner@example.test",
            "commitments": [
                {
                    "commitment_id": "commitment-123",
                    "status": "completed",
                    "source_json": {"source_ref": "source-ref"},
                    "updated_at": "2026-07-01T07:04:00Z",
                }
            ],
            "observations": [
                {
                    "event_type": "commitment_closed",
                    "created_at": "2026-07-01T07:04:00Z",
                    "source_id": "commitment-123",
                    "payload": {
                        "item_ref": "commitment:commitment-123",
                        "action": "close",
                        "actor": "operator",
                    },
                }
            ],
        },
    )

    verification = verify_executive_assistant_acceptance_evidence(receipt_path)
    assert verification["status"] == "pass"
    assert "real_commitment_recovered_or_closed" in receipt["blocked_keys"]


def test_acceptance_materializer_derives_provider_runtime_recovery_from_receipt_pair(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "acceptance.json"

    receipt = acceptance_materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=receipt_path,
        preserve_existing=False,
        provider_runtime_recovery_bundle={
            "before_operator_status": {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_recovery_action",
                "generated_at": "2026-07-01T06:40:00Z",
                "next_action": "repair_proactive_safe_work_audit",
                "operator_action_state": "recovery_required",
                "suppressed_projection": {
                    "requires_recovery": True,
                    "privacy": {
                        "raw_candidate_exposed": False,
                        "raw_draft_text_exposed": False,
                        "raw_packet_text_exposed": False,
                        "raw_private_link_exposed": False,
                    },
                },
            },
            "after_operator_status": {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_live_receipt",
                "generated_at": "2026-07-01T06:52:44Z",
                "next_action": "maintain_proactive_ooda_runtime",
                "operator_action_state": "clear",
                "suppressed_projection": {
                    "requires_recovery": False,
                    "privacy": {
                        "raw_candidate_exposed": False,
                        "raw_draft_text_exposed": False,
                        "raw_packet_text_exposed": False,
                        "raw_private_link_exposed": False,
                    },
                },
            },
            "before_gold_acceptance": {
                "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
                "status": "blocked_operator_runtime_posture",
                "generated_at": "2026-07-01T06:40:10Z",
                "next_action": "repair_proactive_safe_work_audit",
                "remaining_external_proofs": ["healthy operator runtime posture across approved proactive sources"],
            },
            "after_gold_acceptance": {
                "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
                "status": "pass",
                "generated_at": "2026-07-01T06:52:51Z",
                "gold_claim_allowed": True,
                "next_action": "maintain_proactive_ooda_gold_acceptance_evidence",
                "remaining_external_proofs": [],
            },
        },
    )

    verification = verify_executive_assistant_acceptance_evidence(receipt_path)
    assert verification["status"] == "pass"
    assert "real_provider_failure_recovered" in receipt["accepted_keys"]
    row = dict(dict(receipt["acceptance_keys"])["real_provider_failure_recovered"])
    assert row["source_kind"] == "proactive_runtime_recovery_receipt_pair"
    assert row["claim_boundary"] == "proves_recovery_of_one_proactive_runtime_operator_posture_blocker_only"
    assert row["before_status"] == "ready_with_recovery_action"
    assert row["after_status"] == "ready_with_live_receipt"
    assert row["before_gold_status"] == "blocked_operator_runtime_posture"
    assert row["after_gold_status"] == "pass"
    assert row["raw_private_context_exposed"] is False


def test_acceptance_materializer_does_not_derive_provider_recovery_without_clear_after_state(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "acceptance.json"

    receipt = acceptance_materializer.materialize_executive_assistant_acceptance_evidence(
        receipt_path=receipt_path,
        preserve_existing=False,
        provider_runtime_recovery_bundle={
            "before_operator_status": {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_recovery_action",
                "next_action": "repair_proactive_safe_work_audit",
                "operator_action_state": "recovery_required",
                "suppressed_projection": {"requires_recovery": True},
            },
            "after_operator_status": {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_recovery_action",
                "next_action": "repair_proactive_safe_work_audit",
                "operator_action_state": "recovery_required",
                "suppressed_projection": {"requires_recovery": True},
            },
            "before_gold_acceptance": {
                "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
                "status": "blocked_operator_runtime_posture",
                "next_action": "repair_proactive_safe_work_audit",
            },
            "after_gold_acceptance": {
                "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
                "status": "blocked_operator_runtime_posture",
                "gold_claim_allowed": False,
                "remaining_external_proofs": ["healthy operator runtime posture across approved proactive sources"],
            },
        },
    )

    verification = verify_executive_assistant_acceptance_evidence(receipt_path)
    assert verification["status"] == "pass"
    assert "real_provider_failure_recovered" in receipt["blocked_keys"]


def test_landing_quality_receipt_refresh_preserves_acceptance_capture_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    quality_path = tmp_path / "quality.json"
    acceptance_path = tmp_path / "acceptance.json"
    monkeypatch.setattr(landing_actions, "EA_QUALITY_READINESS_RECEIPT", quality_path)
    monkeypatch.setattr(
        landing_actions,
        "EA_ACCEPTANCE_EVIDENCE_RECEIPT",
        acceptance_path,
    )

    receipt = landing_actions._default_acceptance_receipt()  # noqa: SLF001
    acceptance_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    landing_actions._update_quality_receipt_from_acceptance(receipt)  # noqa: SLF001

    verification = verify_executive_assistant_quality_readiness(quality_path)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    assert verification["status"] == "pass"
    assert quality["status"] == "blocked_real_world_acceptance"
    assert quality["head_semantics"] == "source_state"
    assert quality["source_git_head"]
    assert quality["source_state_fingerprint"]
    assert quality["next_action_href"] == "/admin/actions/acceptance-evidence"
    assert quality["next_action_label"] == "Record a real-use outcome"
    assert (
        quality["next_action_form_href"]
        == "/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key=real_daily_morning_brief_accepted"
    )
    assert quality["next_action_form_method"] == "get"
    assert quality["next_action_proof_key"] == "real_daily_morning_brief_accepted"
    context = dict(quality.get("next_action_context") or {})
    assert context["kind"] == "redacted_acceptance_capture"
    assert context["proof_key"] == "real_daily_morning_brief_accepted"
    assert context["proof_label"] == "real daily morning brief acceptance"
    assert context["capture_path"] == "/admin/actions/acceptance-evidence"
    assert (
        context["form_href"]
        == "/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key=real_daily_morning_brief_accepted"
    )
    assert context["stored_evidence_shape"] == "sha256_only"
    assert context["raw_acceptance_text_persisted"] is False
    assert "acceptance_capture_requirements" in quality


def test_landing_acceptance_capture_path_writes_complete_receipts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    acceptance_path = tmp_path / "acceptance.json"
    quality_path = tmp_path / "quality.json"
    scope_gap_path = tmp_path / "scope-gap.json"
    signal_path = tmp_path / "signal.json"
    monkeypatch.setattr(landing_actions, "EA_ACCEPTANCE_EVIDENCE_RECEIPT", acceptance_path)
    monkeypatch.setattr(landing_actions, "EA_QUALITY_READINESS_RECEIPT", quality_path)
    monkeypatch.setattr(landing_actions, "EA_SCOPE_GAP_AUDIT_RECEIPT", scope_gap_path)
    monkeypatch.setattr(landing_actions, "EA_SIGNAL_TO_DECISION_RECEIPT", signal_path)

    receipt = landing_actions._record_acceptance_evidence_receipt(  # noqa: SLF001
        proof_key="real_daily_morning_brief_accepted",
        source_kind="operator_admin",
        evidence="The morning brief was useful and worth reading.",
        object_ref="morning-brief:2026-06-30",
        actor="operator:test",
    )

    acceptance_verification = verify_executive_assistant_acceptance_evidence(acceptance_path)
    quality_verification = verify_executive_assistant_quality_readiness(quality_path)
    assert acceptance_verification["status"] == "pass"
    assert quality_verification["status"] == "pass"
    assert receipt["status"] == "partial_real_world_acceptance_evidence"
    assert receipt["next_action"] == "collect_redacted_real_world_acceptance_evidence"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["source_git_head"]
    assert receipt["source_state_fingerprint"]
    assert receipt["next_action_proof_key"] == "real_decision_cleared"
    assert receipt["real_principal_acceptance_verified"] is True
    assert receipt["real_daily_use_verified"] is False
    row = dict(dict(receipt.get("acceptance_keys") or {})["real_daily_morning_brief_accepted"])
    assert row["evidence_sha256"]
    assert row["actor_sha256"]
    assert row["object_ref_sha256"]
    assert row["raw_evidence_exposed"] is False
    assert "The morning brief was useful" not in acceptance_path.read_text(encoding="utf-8")


def test_acceptance_verifier_fails_when_source_state_is_missing(tmp_path: Path) -> None:
    receipt = landing_actions._default_acceptance_receipt()  # noqa: SLF001
    rows = dict(receipt.get("acceptance_keys") or {})
    landing_actions._refresh_acceptance_receipt_summary(receipt, rows)  # noqa: SLF001
    receipt.pop("source_git_head", None)
    receipt.pop("source_state_fingerprint", None)
    receipt_path = tmp_path / "acceptance.json"
    _write_json(receipt_path, receipt)

    verification = verify_executive_assistant_acceptance_evidence(receipt_path)

    assert verification["status"] == "fail"
    assert "ea_acceptance_source_git_head_missing" in verification["issues"]
    assert "ea_acceptance_source_state_fingerprint_missing" in verification["issues"]


def test_landing_signal_receipt_refresh_matches_source_state_contract(tmp_path: Path) -> None:
    receipt = landing_actions._default_signal_receipt()  # noqa: SLF001
    receipt["operator_review"] = {
        "accepted": True,
        "status": "accepted_redacted",
        "source_kind": "operator_admin",
        "recorded_at": "2026-06-30T00:00:00Z",
        "review_sha256": "review-hash",
        "actor_sha256": "actor-hash",
        "packet_ref_sha256": "packet-hash",
        "raw_review_exposed": False,
        "raw_actor_exposed": False,
        "raw_packet_ref_exposed": False,
    }
    receipt["real_weekly_operator_review_accepted"] = True
    landing_actions._refresh_signal_evidence_contract(receipt)  # noqa: SLF001
    receipt_path = tmp_path / "signal.json"
    _write_json(receipt_path, receipt)

    verification = verify_whole_project_signal_to_decision_receipt(receipt_path)

    assert verification["status"] == "pass"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["source_git_head"]
    assert receipt["source_state_fingerprint"]


def test_signal_verifier_fails_when_source_state_is_missing(tmp_path: Path) -> None:
    receipt = landing_actions._default_signal_receipt()  # noqa: SLF001
    landing_actions._refresh_signal_evidence_contract(receipt)  # noqa: SLF001
    receipt.pop("source_git_head", None)
    receipt.pop("source_state_fingerprint", None)
    receipt_path = tmp_path / "signal.json"
    _write_json(receipt_path, receipt)

    verification = verify_whole_project_signal_to_decision_receipt(receipt_path)

    assert verification["status"] == "fail"
    assert "signal_decision_source_git_head_missing" in verification["issues"]
    assert "signal_decision_source_state_fingerprint_missing" in verification["issues"]
