from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.api.routes.proactive_ooda_approval_support import (
    approval_surface_fallback_operator_action,
    build_proactive_ooda_approval_surface,
    current_packet_fallback_operator_action,
)
from app.services import proactive_ooda_approval_capture


def test_finalize_proactive_ooda_approval_outcome_persists_bundle_snapshot(tmp_path: Path) -> None:
    approval_outcome_path = tmp_path / "provider-ledger" / "proactive_ooda_latest_approval_outcome.generated.json"
    operator_status_path = tmp_path / ".codex-studio" / "published" / "operator.json"
    gold_acceptance_path = tmp_path / ".codex-studio" / "published" / "gold.json"
    bundle = {
        "run_receipt_path": tmp_path / "provider-ledger" / "proactive_ooda_run_receipts" / "run.json",
        "run_receipt": {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": ["packet-hash"],
            "safe_work_result_ref_hashes": ["safe-hash"],
        },
        "stage_packet_path": tmp_path / "provider-ledger" / "proactive_ooda_stage_packets" / "stage.json",
        "stage_packet": {
            "packet_ref": "stage_packet:packet-1",
            "stage": {"kind": "research_packet", "payload": {"work_type": "compare_options"}},
        },
        "safe_work_result_path": tmp_path / "provider-ledger" / "proactive_ooda_safe_work_results" / "safe.json",
        "safe_work_result": {
            "result_ref": "safe_work_result:result-1",
            "status": "staged_for_user_decision",
            "work_type": "compare_options",
            "audit": {"status": "pass", "issues": []},
        },
    }

    result = proactive_ooda_approval_capture.finalize_proactive_ooda_approval_outcome(
        principal_id="principal-1",
        outcome="approved",
        evidence="operator reviewed the staged packet",
        actor="operator@example.com",
        packet_ref="stage_packet:packet-1",
        staged_artifact_ref="safe_work_result:result-1",
        source_kind="operator_manual",
        recorded_at="2026-07-05T09:12:00Z",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        approval_outcome_path=approval_outcome_path,
        operator_status_path=operator_status_path,
        gold_acceptance_path=gold_acceptance_path,
        runtime_artifact_loader=lambda **_kwargs: bundle,
        teable_sync_decider=lambda: False,
        operator_status_materializer=lambda **_kwargs: None,
        gold_materializer=lambda **_kwargs: None,
    )

    stored = json.loads(approval_outcome_path.read_text(encoding="utf-8"))
    snapshot = dict(stored.get("bundle_snapshot") or {})

    assert result["approval_outcome"]["accepted"] is True
    assert snapshot["schema"] == "ea.proactive_ooda.approved_bundle_snapshot.v1"
    assert snapshot["recorded_at"] == "2026-07-05T09:12:00Z"
    assert snapshot["run_receipt"]["notification_status"] == "sent"
    assert snapshot["stage_packet"]["packet_ref_sha256"] == hashlib.sha256("stage_packet:packet-1".encode("utf-8")).hexdigest()
    assert snapshot["stage_packet"]["packet_ref_kind"] == "stage_packet"
    assert snapshot["safe_work_result"]["result_ref_sha256"] == hashlib.sha256("safe_work_result:result-1".encode("utf-8")).hexdigest()
    assert snapshot["safe_work_result"]["result_ref_kind"] == "safe_work_result"
    assert snapshot["privacy"]["raw_credentials_stored"] is False
    stored_text = approval_outcome_path.read_text(encoding="utf-8")
    assert "stage_packet:packet-1" not in stored_text
    assert "safe_work_result:result-1" not in stored_text


def test_build_proactive_ooda_approval_surface_explains_self_capture_without_runtime_noise() -> None:
    surface = build_proactive_ooda_approval_surface(
        safe_work_result={
            "work_type": "record_internal_action",
            "summary": "Action needed: Proactive OODA packet approval outcome.",
            "approval_prompt": "Open Google setup, add the work account as a test user, then retry Full Workspace auth.",
            "staged_action_url": "https://myexternalbrain.com/admin/proactive-ooda/approval",
            "recommended_option_or_draft": {"kind": "link", "value": {"label": "Record packet verdict"}},
        },
        stage_packet={
            "packet_ref": "stage_packet:packet-1",
            "stage": {"payload": {"request_text": "Fallback internal action detail."}},
        },
        approval_outcome={},
        approval_status="missing",
        approval_source="",
        packet_ref="stage_packet:packet-1",
        staged_artifact_ref="safe_work_result:result-1",
        staged_action_url="https://myexternalbrain.com/admin/proactive-ooda/approval",
        operator_context=False,
    )

    rows = list(surface["object_ooda_rows"])
    assert surface["console_title"] == "Review proactive packet"
    assert surface["object_title"] == "No external approval pending"
    assert "No external approval is pending here." in surface["console_summary"]
    assert rows[0]["title"] == "Actual next step"
    assert rows[0]["detail"] == "Open Google setup, add the work account as a test user, then retry Full Workspace auth."
    assert rows[0]["href"] == "https://myexternalbrain.com/admin/proactive-ooda/approval"
    assert rows[1]["title"] == "What this page records"
    assert "No purchase, booking, send, post, cancellation, or commitment will happen from this page." in rows[1]["detail"]
    assert rows[2]["title"] == "How to mark it"
    assert "Dismissed means noise." in rows[2]["detail"]
    assert surface["object_meta"] == [{"label": "Current verdict", "value": "Not recorded yet"}]
    assert surface["object_sidebar_form"]["title"] == "Mark useful or noise"
    assert surface["object_sidebar_form"]["submit_label"] == "Save packet verdict"

    fields = list(surface["object_sidebar_form"]["fields"])
    assert {field["name"] for field in fields} >= {"return_to", "outcome", "evidence", "source_kind", "packet_ref", "staged_artifact_ref"}
    assert next(field for field in fields if field["name"] == "source_kind")["type"] == "hidden"
    assert next(field for field in fields if field["name"] == "packet_ref")["type"] == "hidden"
    assert next(field for field in fields if field["name"] == "staged_artifact_ref")["type"] == "hidden"
    outcome_field = next(field for field in fields if field["name"] == "outcome")
    selected_values = {option["value"] for option in outcome_field["options"] if option.get("selected")}
    assert selected_values == {"deferred"}
    assert any(option["label"] == "Dismissed / noise" for option in outcome_field["options"])


def test_build_proactive_ooda_approval_surface_shows_packet_summary_for_real_packet() -> None:
    surface = build_proactive_ooda_approval_surface(
        safe_work_result={
            "work_type": "draft",
            "summary": "Draft email to the electrician is ready for review.",
            "staged_action_url": "https://myexternalbrain.com/app/queue",
            "recommended_option_or_draft": {
                "kind": "draft",
                "value": {"title": "Email draft", "url": "https://myexternalbrain.com/app/queue"},
            },
            "evidence_refs": [
                {
                    "label": "Electrician site",
                    "kind": "web",
                    "page_title": "Elektriker Wien",
                    "url": "https://example.com/elektriker",
                    "reachable": True,
                }
            ],
        },
        stage_packet={"packet_ref": "stage_packet:packet-2"},
        approval_outcome={"approval_outcome_recorded": True, "outcome": "approved"},
        approval_status="accepted_redacted",
        approval_source="channel_link",
        packet_ref="stage_packet:packet-2",
        staged_artifact_ref="safe_work_result:result-2",
        staged_action_url="https://myexternalbrain.com/app/queue",
        operator_context=True,
    )

    rows = list(surface["object_ooda_rows"])
    assert rows[0]["title"] == "Packet summary"
    assert rows[0]["detail"] == "Draft email to the electrician is ready for review."
    assert rows[1]["title"] == "Suggested next step"
    assert "draft: Email draft" in rows[1]["detail"]
    assert rows[2]["title"] == "Open staged packet"
    assert rows[2]["href"] == "https://myexternalbrain.com/app/queue"
    assert surface["object_meta"] == [
        {"label": "Current verdict", "value": "Approved"},
        {"label": "Saved from", "value": "channel link"},
    ]
    assert surface["object_sections"][0]["title"] == "What this packet was based on"
    outcome_field = next(field for field in surface["object_sidebar_form"]["fields"] if field["name"] == "outcome")
    selected_values = {option["value"] for option in outcome_field["options"] if option.get("selected")}
    assert selected_values == {"approved"}


def test_build_proactive_ooda_approval_surface_hides_latest_packet_when_no_live_approval_is_pending() -> None:
    surface = build_proactive_ooda_approval_surface(
        safe_work_result={
            "work_type": "record_internal_action",
            "summary": "Action needed: Google Workspace OAuth test-user setup.",
            "approval_prompt": "Open Google setup and add the work account as a test user.",
            "staged_action_url": "https://myexternalbrain.com/integrations/google",
        },
        stage_packet={
            "packet_ref": "stage_packet:packet-3",
            "stage": {"payload": {"request_text": "Internal setup action that should stay off the approval page."}},
        },
        approval_outcome={},
        approval_surface_pending=False,
        approval_status="missing",
        approval_source="",
        packet_ref="stage_packet:packet-3",
        staged_artifact_ref="safe_work_result:result-3",
        staged_action_url="https://myexternalbrain.com/integrations/google",
        operator_context=False,
    )

    assert surface["console_title"] == "Nothing to approve"
    assert surface["object_title"] == "No approval pending"
    assert surface["object_meta"] == [{"label": "Pending approvals", "value": "0"}]
    assert surface["object_ooda_rows"][0]["detail"] == "Nothing needs approval right now."
    assert surface["object_sidebar_title"] == "No approval pending"
    assert surface["object_sidebar_form"] == {}


def test_build_proactive_ooda_approval_surface_leads_with_action_when_no_approval_is_pending() -> None:
    surface = build_proactive_ooda_approval_surface(
        safe_work_result={
            "work_type": "record_internal_action",
            "summary": "Action needed: Google Workspace OAuth setup.",
            "approval_prompt": "Open Google setup and retry full workspace auth.",
            "staged_action_url": "https://myexternalbrain.com/integrations/google",
        },
        stage_packet={
            "packet_ref": "stage_packet:packet-operator-action",
            "stage": {"payload": {"request_text": "Internal setup action."}},
        },
        approval_outcome={},
        fallback_operator_action={
            "user_action_required": True,
            "next_action_label": "Retry Google auth",
            "next_action_href": "/integrations/google",
            "instruction": (
                "Google Workspace auth needs reauthorization before EA can rely on that source. "
                "Retry the Full Workspace auth link with the approved work Google account."
            ),
        },
        approval_surface_pending=False,
        approval_status="missing",
        approval_source="",
        packet_ref="stage_packet:packet-operator-action",
        staged_artifact_ref="safe_work_result:operator-action",
        staged_action_url="https://myexternalbrain.com/integrations/google",
        operator_context=False,
    )

    assert surface["console_title"] == "No approval pending"
    assert surface["console_summary"] == "Nothing needs approval here. Current action: Retry Google auth."
    assert surface["object_title"] == "Current action: Retry Google auth"
    assert surface["object_summary"] == "Open the action below. This page does not record or accept an approval."
    assert surface["object_ooda_title"] == "Do this"
    assert surface["object_ooda_copy"] == "Complete the action below if you want EA unstuck. Nothing on this page needs approval."
    assert surface["object_ooda_rows"][0]["title"] == "Do this"
    assert surface["object_ooda_rows"][0]["tag"] == "Retry Google auth"
    assert "reauthorization" in surface["object_ooda_rows"][0]["detail"]
    assert surface["object_ooda_rows"][0]["href"] == "/integrations/google"
    assert surface["object_ooda_rows"][1]["title"] == "Approval state"
    assert surface["object_ooda_rows"][1]["detail"] == "No proactive packet needs approval right now."
    assert surface["object_sidebar_title"] == "No approval pending"
    assert surface["object_sidebar_form"] == {}


def test_current_packet_fallback_operator_action_uses_internal_action_as_real_next_step() -> None:
    action = current_packet_fallback_operator_action(
        safe_work_result={
            "work_type": "record_internal_action",
            "summary": "Action needed: Google Workspace OAuth test-user setup.",
            "approval_prompt": "Open Google setup and add the work account as a test user.",
            "staged_action_url": "https://myexternalbrain.com/integrations/google",
            "recommended_option_or_draft": {
                "kind": "internal_action",
                "value": {
                    "label": "Open Google setup",
                    "url": "https://myexternalbrain.com/integrations/google",
                },
            },
            "approval": {"required": True},
            "status": "staged_for_user_decision",
            "result_ref": "safe_work_result:result-4",
        },
        stage_packet={
            "packet_ref": "stage_packet:packet-4",
            "approval": {"required": True},
            "stage": {
                "kind": "internal_action",
                "payload": {
                    "work_type": "record_internal_action",
                    "request_text": "Open Google setup and add the work account as a test user.",
                },
            },
        },
        staged_action_url="https://myexternalbrain.com/integrations/google",
    )

    assert action == {
        "user_action_required": True,
        "next_action_label": "Open Google setup",
        "next_action_href": "https://myexternalbrain.com/integrations/google",
        "instruction": "Open Google setup and add the work account as a test user.",
    }


def test_approval_surface_fallback_operator_action_prefers_live_operator_head_when_no_approval_is_pending() -> None:
    action = approval_surface_fallback_operator_action(
        safe_work_result={
            "work_type": "record_internal_action",
            "summary": "Action needed: Google Workspace OAuth test-user setup.",
            "approval_prompt": "Open Google setup and add the work account as a test user.",
            "staged_action_url": "https://myexternalbrain.com/integrations/google",
            "recommended_option_or_draft": {
                "kind": "internal_action",
                "value": {
                    "label": "Open Google setup",
                    "url": "https://myexternalbrain.com/integrations/google",
                },
            },
            "approval": {"required": True},
            "status": "staged_for_user_decision",
            "result_ref": "safe_work_result:result-5",
        },
        stage_packet={
            "packet_ref": "stage_packet:packet-5",
            "approval": {"required": True},
            "stage": {
                "kind": "internal_action",
                "payload": {
                    "work_type": "record_internal_action",
                    "request_text": "Open Google setup and add the work account as a test user.",
                },
            },
        },
        staged_action_url="https://myexternalbrain.com/integrations/google",
        approval_surface_pending=False,
        goal_posture={
            "operator_action_queue": [
                {
                    "user_action_required": True,
                    "next_action_label": "Retry Google auth",
                    "next_action_href": "/integrations/google",
                    "instruction": (
                        "Google Workspace auth needs reauthorization before EA can rely on that source. "
                        "Retry the Full Workspace auth link with the approved work Google account."
                    ),
                }
            ]
        },
    )

    assert action == {
        "user_action_required": True,
        "next_action_label": "Retry Google auth",
        "next_action_href": "/integrations/google",
        "instruction": (
            "Google Workspace auth needs reauthorization before EA can rely on that source. "
            "Retry the Full Workspace auth link with the approved work Google account."
        ),
    }


def test_approval_surface_fallback_operator_action_prefers_digest_notification_action() -> None:
    action = approval_surface_fallback_operator_action(
        safe_work_result={
            "work_type": "record_internal_action",
            "summary": "Action needed: Google Workspace OAuth test-user setup.",
            "approval_prompt": "Open Google setup and add the work account as a test user.",
            "staged_action_url": "https://myexternalbrain.com/integrations/google",
            "approval": {"required": True},
            "status": "staged_for_user_decision",
            "result_ref": "safe_work_result:result-6",
        },
        stage_packet={
            "packet_ref": "stage_packet:packet-6",
            "approval": {"required": True},
            "stage": {
                "kind": "internal_action",
                "payload": {
                    "work_type": "record_internal_action",
                    "request_text": "Open Google setup and add the work account as a test user.",
                },
            },
        },
        staged_action_url="https://myexternalbrain.com/integrations/google",
        approval_surface_pending=False,
        goal_posture={
            "operator_action_queue": [
                {
                    "key": "google_workspace_oauth_setup",
                    "user_action_required": True,
                    "next_action_label": "Retry Google auth",
                    "next_action_href": "/integrations/google",
                    "instruction": "Retry the Full Workspace auth link with the approved work Google account.",
                }
            ]
        },
        digest_receipt={
            "notification_items": [
                {
                    "key": "pushbullet_delivery_setup",
                    "title": "Pushbullet delivery setup",
                    "next_action_form_label": "Open Pushbullet account settings",
                    "next_action_form_href": "https://www.pushbullet.com/#settings/account",
                    "instruction": "Create missing Pushbullet access tokens for configured delivery clients, then rerun readiness.",
                }
            ]
        },
    )

    assert action == {
        "user_action_required": True,
        "next_action_label": "Open Pushbullet account settings",
        "next_action_href": "https://www.pushbullet.com/#settings/account",
        "instruction": "Create missing Pushbullet access tokens for configured delivery clients, then rerun readiness.",
    }
