from __future__ import annotations

import html
import json
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from tests.product_test_helpers import build_operator_product_client, build_product_client, seed_product_state, start_workspace


def _operator_client(*, principal_id: str = "exec-admin-surface") -> TestClient:
    return build_operator_product_client(principal_id=principal_id, operator_id="operator-admin-1")


def _seed_admin_state(client: TestClient, *, principal_id: str) -> None:
    from app.domain.models import IntentSpecV3

    container = client.app.state.container
    session = container.orchestrator._ledger.start_session(  # type: ignore[attr-defined]
        IntentSpecV3(
            principal_id=principal_id,
            goal="Run admin audit checks",
            task_type="office_loop",
            deliverable_type="memo",
            risk_class="medium",
            approval_class="draft",
            budget_class="standard",
        )
    )
    container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id="operator-admin-1",
        display_name="Tibor Ops",
        roles=("operator", "reviewer"),
        trust_tier="trusted",
        status="active",
        notes="Seeded for admin surface contracts.",
    )
    container.orchestrator.create_human_task(
        session_id=session.session_id,
        principal_id=principal_id,
        task_type="draft_review",
        role_required="operator",
        brief="Review the executive follow-up before send",
        why_human="The operator should confirm the final phrasing.",
        priority="high",
        sla_due_at="2026-03-25T12:00:00+00:00",
    )
    delivery_task = container.orchestrator.create_human_task(
        session_id=session.session_id,
        principal_id=principal_id,
        task_type="delivery_followup",
        role_required="operator",
        brief="Send approved reply to Sofia N.",
        why_human="Automatic send did not complete (google_oauth_binding_not_found). Finish delivery manually.",
        priority="high",
        sla_due_at="2026-03-25T13:00:00+00:00",
        input_json={
            "draft_ref": "approval:delivery-followup-admin",
            "recipient_email": "sofia@example.com",
            "subject": "Re: Board packet follow-up",
            "reason": "google_oauth_binding_not_found",
        },
    )
    container.orchestrator.assign_human_task(
        delivery_task.human_task_id,
        principal_id=principal_id,
        operator_id="operator-admin-1",
        assignment_source="seed",
        assigned_by_actor_id="fixture",
    )
    returned_task = container.orchestrator.create_human_task(
        session_id=session.session_id,
        principal_id=principal_id,
        task_type="handoff",
        role_required="operator",
        brief="Close investor dinner handoff",
        why_human="Seed a returned handoff for the operator center.",
        priority="medium",
        sla_due_at="2026-03-25T16:00:00+00:00",
    )
    container.orchestrator.assign_human_task(
        returned_task.human_task_id,
        principal_id=principal_id,
        operator_id="operator-admin-1",
        assignment_source="seed",
        assigned_by_actor_id="fixture",
    )
    container.orchestrator.return_human_task(
        returned_task.human_task_id,
        principal_id=principal_id,
        operator_id="operator-admin-1",
        resolution="completed",
        returned_payload_json={"source": "fixture"},
        provenance_json={"source": "fixture"},
    )
    container.orchestrator._approvals.create_request(  # type: ignore[attr-defined]
        session.session_id,
        "step-approval-1",
        "Approve the board reply",
        {"action": "delivery.send", "channel": "email", "recipient": "sofia@example.com"},
    )
    created = client.post(
        "/v1/providers/bindings",
        json={
            "provider_key": "browseract",
            "status": "enabled",
            "priority": 10,
            "scope_json": {"allowed_tools": ["browseract.extract_account_inventory"]},
            "probe_state": "ready",
            "probe_details_json": {"last_check": "seed"},
        },
    )
    assert created.status_code == 200
    queued = client.post(
        "/v1/delivery/outbox",
        json={
            "channel": "email",
            "recipient": "sofia@example.com",
            "content": "Draft board reply",
            "metadata": {"kind": "seed"},
        },
    )
    assert queued.status_code == 200
    pending_invite = client.post(
        "/app/api/invitations",
        json={
            "email": "operator-community@example.com",
            "role": "operator",
            "display_name": "Community Operator",
            "note": "Hold backup organizer access for launch week.",
            "expires_in_days": 7,
        },
    )
    assert pending_invite.status_code == 200
    accepted_invite = client.post(
        "/app/api/invitations",
        json={
            "email": "principal-community@example.com",
            "role": "principal",
            "display_name": "Principal Community",
            "note": "Join the live support loop.",
            "expires_in_days": 7,
        },
    )
    assert accepted_invite.status_code == 200
    accepted = client.post(
        "/app/api/invitations/accept",
        json={"token": accepted_invite.json()["invite_token"], "display_name": "Principal Community"},
    )
    assert accepted.status_code == 200
    active_access = client.post(
        "/app/api/access-sessions",
        json={
            "email": "community-access@example.com",
            "role": "principal",
            "display_name": "Community Access",
            "expires_in_hours": 24,
        },
    )
    assert active_access.status_code == 200
    revoked_access = client.post(
        "/app/api/access-sessions",
        json={
            "email": "revoked-community@example.com",
            "role": "principal",
            "display_name": "Revoked Community",
            "expires_in_hours": 24,
        },
    )
    assert revoked_access.status_code == 200
    revoked = client.post(f"/app/api/access-sessions/{revoked_access.json()['session_id']}/revoke")
    assert revoked.status_code == 200


def test_admin_surfaces_render_live_runtime_state() -> None:
    principal_id = "exec-admin-surface"
    client = _operator_client(principal_id=principal_id)
    _seed_admin_state(client, principal_id=principal_id)
    client.headers.update({"X-EA-Operator-ID": "operator-admin-1"})

    policies = client.get("/admin/policies")
    assert policies.status_code == 200
    assert "Draft approvals" in policies.text
    assert "Approve the board reply" in policies.text
    assert "Review the executive follow-up before send" in policies.text

    providers = client.get("/admin/providers")
    assert providers.status_code == 200
    assert "Configured providers" in providers.text
    assert "browseract" in providers.text.lower()
    assert "Runtime readiness" in providers.text
    assert "Core batch lane" in providers.text

    audit = client.get("/admin/audit-trail")
    assert audit.status_code == 200
    assert "Pending delivery" in audit.text
    assert "sofia@example.com" in audit.text

    operators = client.get("/admin/operators")
    assert operators.status_code == 200
    assert "Tibor Ops" in operators.text
    assert "Review the executive follow-up before send" in operators.text
    assert "Send approved reply to Sofia N." in operators.text
    assert "Mark sent" in operators.text
    assert "Needs reauth" in operators.text
    assert "Returned handoffs" in operators.text
    assert "Close investor dinner handoff" in operators.text

    community = client.get("/admin/community")
    assert community.status_code == 200
    assert "Access" in community.text
    assert "Workspace access and rollout posture" in community.text
    assert "operator-community@example.com" in community.text
    assert "principal-community@example.com" in community.text
    assert "community-access@example.com" in community.text
    assert "Rollout and support" in community.text
    assert "Launch readiness" in community.text
    assert "Support fallout" in community.text
    assert "Public guide freshness" in community.text
    assert "Support verification" in community.text

    diagnostics = client.get("/admin/api")
    assert diagnostics.status_code == 200
    assert "Runtime" in diagnostics.text
    assert "Workspace plan" in diagnostics.text
    assert "Operator seats" in diagnostics.text
    assert "Seats used" in diagnostics.text
    assert "Feature flags" in diagnostics.text

    assert "Billing state" in diagnostics.text
    assert "Support tier" in diagnostics.text
    assert "Renewal owner" in diagnostics.text
    assert "Configured providers" in diagnostics.text
    assert "Queue state" in diagnostics.text
    assert "SLA breaches" in diagnostics.text
    assert "Unclaimed handoffs" in diagnostics.text
    assert "Retrying delivery" in diagnostics.text
    assert "Load score" in diagnostics.text
    assert "Provider risk" in diagnostics.text
    assert "Fallback lanes" in diagnostics.text
    assert "Active product wave" in diagnostics.text
    assert "Journey gate health" in diagnostics.text
    assert "Launch readiness" in diagnostics.text
    assert "Support fallout" in diagnostics.text
    assert "Public guide freshness" in diagnostics.text
    assert "Fix verification" in diagnostics.text
    assert "Channel receipt" in diagnostics.text
    assert "Release authority" in diagnostics.text
    assert "Authority posture" in diagnostics.text
    assert "Release next action" in diagnostics.text
    assert "Runtime supply chain" in diagnostics.text
    assert "Supply-chain next action" in diagnostics.text
    assert "Supply-chain issues" in diagnostics.text
    assert "Release label" in diagnostics.text
    assert "Deployment ID" in diagnostics.text
    assert "Deployment source" in diagnostics.text
    assert "Deploy context at" in diagnostics.text
    assert "Deploy context ref" in diagnostics.text
    assert "Deploy context commit" in diagnostics.text
    assert "Release branch" in diagnostics.text
    assert "Tracking branch" in diagnostics.text
    assert "Release commit" in diagnostics.text
    assert "Worktree" in diagnostics.text
    assert "Primary plane" in diagnostics.text
    assert "Enabled planes" in diagnostics.text
    assert "Artifact count" in diagnostics.text
    assert "Public origin" in diagnostics.text
    assert "Origin source" in diagnostics.text
    assert "Authority basis" in diagnostics.text
    assert "Blocked delivery handoffs" in diagnostics.text
    assert "Delivery handoffs closed" in diagnostics.text
    assert "Export support-ready workspace bundle" in diagnostics.text
    assert "Open bundle" in diagnostics.text
    assert "Download JSON" in diagnostics.text
    assert "Recent workspace events" in diagnostics.text

    bundle = client.get("/app/api/diagnostics/export")
    assert bundle.status_code == 200
    diagnostics_api = client.get("/app/api/diagnostics")
    assert diagnostics_api.status_code == 200
    assert int(diagnostics_api.json()["analytics"]["counts"].get("support_bundle_opened") or 0) >= 1


def test_admin_goal_evidence_surface_shows_receipts_without_completion_overclaim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    principal_id = "exec-admin-goal-evidence"
    client = _operator_client(principal_id=principal_id)
    from app.api.routes import admin_view_models

    office_receipt = tmp_path / "ea_office_loop_goal.generated.json"
    acceptance_receipt = tmp_path / "ea_executive_assistant_acceptance_evidence.generated.json"
    active_media_receipt = tmp_path / "active_media_ltd_goal_bundle.generated.json"
    signal_receipt = tmp_path / "ea_whole_project_signal_to_decision.generated.json"
    scope_audit_receipt = tmp_path / "ea_whole_project_scope_gap_audit.generated.json"
    proactive_receipt = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    proactive_gold_receipt = tmp_path / "ea_proactive_ooda_gold_acceptance.generated.json"
    office_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.office_loop_goal_receipt.v1",
                "status": "ready_local_evidence",
                "goal_completion_claim_allowed": False,
                "next_action": "collect_real_daily_office_loop_acceptance_evidence",
                "additional_goals": [
                    {
                        "key": "whole_project_product_governor_loop",
                        "label": "Whole-project product governor loop",
                        "status": "active_local_goal",
                        "claim_limit": "local_goal_set_not_external_completion",
                        "requires": [
                            "journey_or_release_gate_mapping",
                            "owning_truth_plane",
                            "local_evidence_receipt",
                        ],
                        "protected_pressures": [
                            "ready_tonight",
                            "no_desktop_onboarding",
                            "role_kits",
                        ],
                    },
                    {
                        "key": "whole_project_scope_gap_audit",
                        "label": "Whole-project scope gap audit",
                        "status": "active_local_goal",
                        "claim_limit": "local_scope_audit_not_canonical_product_truth",
                        "requires": [
                            "core_product_loop_mapping",
                            "privacy_retention_support_telemetry_check",
                            "next_external_or_human_proof",
                        ],
                        "protected_scope_axes": [
                            "build_character_and_rules",
                            "run_session",
                            "privacy_retention",
                            "support_recovery",
                        ],
                    },
                    {
                        "key": "whole_project_signal_to_decision_closure",
                        "label": "Whole-project signal-to-decision closure",
                        "status": "active_local_goal",
                        "claim_limit": "local_signal_synthesis_not_canonical_queue_or_release_truth",
                        "requires": [
                            "cross_surface_signal_intake",
                            "weekly_operator_decision_packet",
                            "closed_loop_followthrough_receipt",
                        ],
                        "protected_signal_sources": [
                            "real_usage_telemetry",
                            "provider_runtime_failures",
                            "release_install_update_friction",
                        ],
                    },
                ],
                "remaining_external_proofs": [
                    "real daily morning brief acceptance",
                    "real approved outbound action with audit trail",
                ],
            }
        ),
        encoding="utf-8",
    )
    signal_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.whole_project_signal_to_decision_receipt.v1",
                "status": "ready_local_packet_pending_operator_acceptance",
                "goal_completion_claim_allowed": False,
                "next_action": "review_weekly_signal_to_decision_packet_with_operator",
                "remaining_external_proofs": [
                    "real weekly signal-to-decision review accepted by the operator",
                    "closed-loop signal-to-decision follow-through receipt accepted by the operator",
                ],
            }
        ),
        encoding="utf-8",
    )
    active_media_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.active_media_ltd_goal_bundle.v1",
                "status": "ready_local_evidence",
                "goal_completion_claim_allowed": False,
                "provider_ready": False,
                "live_provider_runtime_verified": False,
                "verified_provider_claim_allowed": False,
                "public_route_deployment_verified": False,
                "public_route_claim_allowed": False,
                "gold_claim_allowed": False,
                "next_action": "collect_external_provider_and_public_route_proofs_before_any_gold_or_live_provider_claim",
                "remaining_external_proofs": [
                    "ChatLab live runtime probe receipt",
                    "deployed public promo route browser proof",
                    "real Manfred spoken-conversation STT/TTS roundtrip evidence",
                ],
                "verifications": {
                    "audiobook_quality": {"status": "pass", "issues": [], "receipt": {"path": "audiobook.json"}},
                    "audiobook_m4b_structure": {"status": "pass", "issues": [], "receipt": {"path": "m4b.json"}},
                    "chatlab_contract": {"status": "pass", "issues": [], "receipt": {"path": "chatlab-contract.json"}},
                    "chatlab_runtime_preflight": {"status": "pass", "issues": [], "receipt": {"path": "chatlab-runtime.json"}},
                    "chatlab_route_surface": {"status": "pass", "issues": [], "receipt": {"path": "chatlab-route.json"}},
                    "cinematic_continuity_demo": {"status": "pass", "issues": [], "receipt": {"path": "cinematic.json"}},
                    "promo_review_bundle": {"status": "pass", "issues": [], "receipt": {"path": "promo-review.json"}},
                    "promo_quality_rubric": {"status": "pass", "issues": [], "receipt": {"path": "promo-quality.json"}},
                    "promo_public_route_surface": {"status": "pass", "issues": [], "receipt": {"path": "promo-route.json"}},
                },
                "external_proof_posture": {
                    "manfred_spoken_conversation": {
                        "status": "blocked_external_proof",
                        "next_action": "collect_real_room_audio_attestation",
                        "blocking_actions": [
                            "rerun_operator_local_full_text_benchmark_or_correct_ground_truth_transcript",
                            "collect_real_room_audio_attestation",
                        ],
                        "stt": {
                            "status": "pass",
                            "provider_label": "cartesia/ink-whisper+enhanced_wav",
                            "passed_samples": 4,
                            "sample_count": 4,
                            "real_captured_fixture_required": True,
                        },
                        "tts": {
                            "premium_status": "blocked",
                            "room_audio_receipt": "blocked",
                            "next_action": "collect_real_room_audio_attestation",
                        },
                        "room_audio_attestation_packet": {
                            "status": "ready",
                            "operator_command": "make materialize-memorial-room-audio-gold-clean",
                        },
                        "captured_candidate_diagnostic": {
                            "status": "blocked",
                            "next_action": "rerun_operator_local_full_text_benchmark_or_correct_ground_truth_transcript",
                            "row_failure_codes": ["transcript_hash_mismatch"],
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    acceptance_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.executive_assistant_acceptance_evidence.v1",
                "status": "blocked_missing_real_world_acceptance_evidence",
                "goal_completion_claim_allowed": False,
                "next_action": "collect_redacted_real_world_acceptance_evidence",
                "accepted_keys": [],
                "blocked_keys": [
                    "real_daily_morning_brief_accepted",
                    "real_decision_cleared",
                    "real_commitment_recovered_or_closed",
                    "real_approved_action_audited",
                    "real_provider_failure_recovered",
                ],
                "acceptance_keys": {
                    "real_daily_morning_brief_accepted": {
                        "accepted": False,
                        "status": "missing_or_invalid",
                        "source_kind": "unknown",
                        "evidence_sha256": "",
                        "actor_sha256": "",
                        "object_ref_sha256": "",
                        "raw_evidence_exposed": False,
                        "raw_actor_exposed": False,
                        "raw_object_ref_exposed": False,
                    },
                    "real_decision_cleared": {
                        "accepted": False,
                        "status": "missing_or_invalid",
                        "source_kind": "unknown",
                        "evidence_sha256": "",
                        "actor_sha256": "",
                        "object_ref_sha256": "",
                        "raw_evidence_exposed": False,
                        "raw_actor_exposed": False,
                        "raw_object_ref_exposed": False,
                    },
                    "real_commitment_recovered_or_closed": {
                        "accepted": False,
                        "status": "missing_or_invalid",
                        "source_kind": "unknown",
                        "evidence_sha256": "",
                        "actor_sha256": "",
                        "object_ref_sha256": "",
                        "raw_evidence_exposed": False,
                        "raw_actor_exposed": False,
                        "raw_object_ref_exposed": False,
                    },
                    "real_approved_action_audited": {
                        "accepted": False,
                        "status": "missing_or_invalid",
                        "source_kind": "unknown",
                        "evidence_sha256": "",
                        "actor_sha256": "",
                        "object_ref_sha256": "",
                        "raw_evidence_exposed": False,
                        "raw_actor_exposed": False,
                        "raw_object_ref_exposed": False,
                    },
                    "real_provider_failure_recovered": {
                        "accepted": False,
                        "status": "missing_or_invalid",
                        "source_kind": "unknown",
                        "evidence_sha256": "",
                        "actor_sha256": "",
                        "object_ref_sha256": "",
                        "raw_evidence_exposed": False,
                        "raw_actor_exposed": False,
                        "raw_object_ref_exposed": False,
                    },
                },
                "privacy": {
                    "raw_private_context_exposed": False,
                    "raw_acceptance_text_exposed": False,
                    "raw_actor_identity_exposed": False,
                    "raw_object_reference_exposed": False,
                    "credential_values_exposed": False,
                },
                "remaining_external_proofs": [
                    "real daily morning brief acceptance",
                    "real decision cleared by the principal or operator",
                    "real commitment recovered or closed with an evidence receipt",
                    "real approved outbound action with audit trail",
                    "real provider failure recovered with operator-grade reason",
                ],
            }
        ),
        encoding="utf-8",
    )
    scope_audit_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.whole_project_scope_gap_audit.v1",
                "status": "ready_local_audit",
                "goal_completion_claim_allowed": False,
                "next_action": "review_scope_gap_audit_against_current_product_spine_with_a_human_operator",
                "remaining_external_proofs": [
                    "real whole-project scope gap audit reviewed against the current product spine",
                    "ChatLab live runtime probe receipt",
                ],
            }
        ),
        encoding="utf-8",
    )
    proactive_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_with_recovery_action",
                "goal_completion_claim_allowed": False,
                "live_delivery_claim_allowed": False,
                "summary": "Proactive OODA can still route, but a preferred delivery path needs recovery: whatsapp_web_session_not_ready:qr_required.",
                "next_action": "scan_whatsapp_web_qr",
                "operator_action_state": "recovery_required",
                "delivery_route_error": "whatsapp_web_session_not_ready:qr_required",
                "delivery_recovery_hint": "Scan the WhatsApp Web QR code and re-activate the session before preferring WhatsApp again.",
            }
        ),
        encoding="utf-8",
    )
    proactive_gold_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
                "status": "ready_for_approval_outcome_capture",
                "gold_claim_allowed": False,
                "summary": "A proactive OODA packet has local gold-proof runtime evidence; capture the redacted approval outcome next.",
                "next_action": "record_proactive_ooda_approval_outcome",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_view_models, "OFFICE_LOOP_GOAL_RECEIPT", office_receipt)
    monkeypatch.setattr(admin_view_models, "EXECUTIVE_ASSISTANT_ACCEPTANCE_EVIDENCE_RECEIPT", acceptance_receipt)
    monkeypatch.setattr(admin_view_models, "ACTIVE_MEDIA_LTD_GOAL_RECEIPT", active_media_receipt)
    monkeypatch.setattr(admin_view_models, "WHOLE_PROJECT_SIGNAL_TO_DECISION_RECEIPT", signal_receipt)
    monkeypatch.setattr(admin_view_models, "WHOLE_PROJECT_SCOPE_GAP_AUDIT_RECEIPT", scope_audit_receipt)
    monkeypatch.setattr(admin_view_models, "PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT", proactive_receipt)
    monkeypatch.setattr(admin_view_models, "PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT", proactive_gold_receipt)

    goals = client.get("/admin/goals")

    assert goals.status_code == 200
    assert "Goal Status" in goals.text
    assert "What is ready locally" in goals.text
    assert "Office-loop receipt" in goals.text
    assert "Active media/LTD bundle" in goals.text
    assert "Signal-to-decision receipt" in goals.text
    assert "Whole-project scope-gap audit" in goals.text
    assert "Proactive OODA operator status" in goals.text
    assert "Proactive OODA gold acceptance" in goals.text
    assert "What still needs real use" in goals.text
    assert "Real-use outcomes" in goals.text
    assert "Signal review and follow-through" in goals.text
    assert "Proactive delivery recovery" in goals.text
    assert "Proactive OODA approval outcome" in goals.text
    assert "Weekly operator review" in goals.text
    assert "Closed-loop follow-through" in goals.text
    assert "scan_whatsapp_web_qr" in goals.text
    assert "preferred delivery path needs recovery" in goals.text
    assert "Record a signal-loop outcome" in goals.text
    assert "/admin/actions/signal-to-decision-evidence" in goals.text
    assert "Open approval capture" in goals.text
    assert "/admin/proactive-ooda/approval" in goals.text
    assert "Acceptance evidence receipt" in goals.text
    assert "Morning brief accepted" in goals.text
    assert "Real decision cleared" in goals.text
    assert "Commitment recovered or closed" in goals.text
    assert "Approved action audited" in goals.text
    assert "Provider failure recovered" in goals.text
    assert "Redaction posture" in goals.text
    assert "private-safe signal" in goals.text
    assert "Scope goals and protected project axes" in goals.text
    assert "Whole-project scope gap audit" in goals.text
    assert "Whole-project signal-to-decision closure" in goals.text
    assert "local_scope_audit_not_canonical_product_truth" in goals.text
    assert "local_signal_synthesis_not_canonical_queue_or_release_truth" in goals.text
    assert "privacy_retention_support_telemetry_check" in goals.text
    assert "provider_runtime_failures" in goals.text
    assert "run_session" in goals.text
    assert "Scope goals" in goals.text
    assert "ChatLab live runtime probe receipt" in goals.text
    assert "closed-loop signal-to-decision follow-through receipt accepted by the operator" in goals.text
    assert "/memorials/manfred/chatlab/status" in goals.text
    assert "Open ChatLab status" in goals.text
    assert "/ledger/factions/ashline-circle/promo" in goals.text
    assert "Open promo page" in goals.text
    assert "real Manfred spoken-conversation STT/TTS roundtrip evidence" in goals.text
    assert "/admin/memorials/manfred/gold" in goals.text
    assert "Open voice gold" in goals.text
    assert "/memorials/manfred/voice-config" in goals.text
    assert "Spoken conversation proof" in goals.text
    assert "collect_real_room_audio_attestation" in goals.text
    assert "Open Today" in goals.text
    assert "Open approvals" in goals.text
    assert "Audiobook, ChatLab, cinematic, and promo local checks" in goals.text
    assert "Completion remains blocked" in goals.text
    assert "does not create canonical product, release, support, or memory truth" in goals.text


def test_admin_goal_evidence_surface_exposes_proactive_google_reauth_links(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    principal_id = "exec-admin-goal-reauth-links"
    client = _operator_client(principal_id=principal_id)
    from app.api.routes import admin_view_models

    reconnect_href = (
        "https://myexternalbrain.com/app/actions/google/connect?"
        "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
    )
    proactive_receipt = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    proactive_gold_receipt = tmp_path / "ea_proactive_ooda_gold_acceptance.generated.json"
    proactive_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "blocked_local_runtime",
                "summary": "Proactive OODA routing is available, but Google workspace needs reauthorization before EA can rely on that source (google_oauth_invalid_grant).",
                "next_action": "reauthorize_google_workspace_binding",
                "next_action_href": reconnect_href,
                "next_action_label": "Reconnect Google workspace",
                "next_action_method": "get",
                "operator_action_state": "recovery_required",
            }
        ),
        encoding="utf-8",
    )
    proactive_gold_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_gold_acceptance.v1",
                "status": "blocked_operator_runtime_posture",
                "gold_claim_allowed": False,
                "summary": "The proactive OODA packet proofs exist, but operator runtime posture is blocked and gold cannot be claimed until approved source health is restored.",
                "next_action": "reauthorize_google_workspace_binding",
                "next_action_href": reconnect_href,
                "next_action_label": "Reconnect Google workspace",
                "next_action_method": "get",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_view_models, "PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT", proactive_receipt)
    monkeypatch.setattr(admin_view_models, "PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT", proactive_gold_receipt)

    goals = client.get("/admin/goals")

    assert goals.status_code == 200
    assert "Reconnect Google workspace" in goals.text
    assert reconnect_href in html.unescape(goals.text)
    assert "/admin/proactive-ooda/approval" in goals.text


def test_admin_acceptance_capture_records_redacted_goal_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    principal_id = "exec-admin-acceptance-capture"
    client = _operator_client(principal_id=principal_id)
    client.headers.update({"X-EA-Operator-ID": "operator-admin-1"})
    from app.api.routes import admin_view_models, landing_actions

    office_receipt = tmp_path / "ea_office_loop_goal.generated.json"
    acceptance_receipt = tmp_path / "ea_executive_assistant_acceptance_evidence.generated.json"
    quality_receipt = tmp_path / "ea_executive_assistant_quality_readiness.generated.json"
    active_media_receipt = tmp_path / "active_media_ltd_goal_bundle.generated.json"
    signal_receipt = tmp_path / "ea_whole_project_signal_to_decision.generated.json"
    scope_audit_receipt = tmp_path / "ea_whole_project_scope_gap_audit.generated.json"
    proactive_receipt = tmp_path / "ea_proactive_ooda_operator_status.generated.json"
    office_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.office_loop_goal_receipt.v1",
                "status": "ready_local_evidence",
                "goal_completion_claim_allowed": False,
                "live_daily_use_verified": False,
                "real_operator_acceptance_verified": False,
                "external_provider_runtime_verified": False,
                "components": {
                    key: {"status": "pass"}
                    for key in (
                        "command_brief",
                        "decision_queue",
                        "commitment_ledger",
                        "approved_action_workflow",
                        "evidence_audit_trail",
                        "support_recovery",
                        "operator_control",
                        "goal_evidence",
                    )
                },
                "diagnostics_summary": {
                    "analytics_counts_present": True,
                    "channel_loop_digest_keys": ["memo", "approvals", "operator"],
                },
                "boundary_posture": {
                    "ea_is_product_truth": False,
                    "ea_is_memory_truth": False,
                    "ea_owns_canonical_queue_truth": False,
                    "ea_owns_release_authority": False,
                    "assistant_local_prompts_are_canon": False,
                    "provider_telemetry_is_product_authority": False,
                },
                "additional_goals": [
                    {
                        "key": "whole_project_scope_gap_audit",
                        "label": "Whole-project scope gap audit",
                        "status": "active_local_goal",
                    }
                ],
                "remaining_external_proofs": [
                    "real daily morning brief acceptance",
                    "real decision cleared by the principal or operator",
                    "real commitment recovered or closed with an evidence receipt",
                    "real approved outbound action with audit trail",
                    "real provider failure recovered with operator-grade reason",
                ],
            }
        ),
        encoding="utf-8",
    )
    active_media_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.active_media_ltd_goal_bundle.v1",
                "status": "ready_local_evidence",
                "goal_completion_claim_allowed": False,
                "provider_ready": False,
                "live_provider_runtime_verified": False,
                "verified_provider_claim_allowed": False,
                "public_route_deployment_verified": False,
                "public_route_claim_allowed": False,
                "gold_claim_allowed": False,
                "remaining_external_proofs": ["named provider runtime/account proof"],
            }
        ),
        encoding="utf-8",
    )
    proactive_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.proactive_ooda_operator_status.v1",
                "status": "ready_local_runtime",
                "goal_completion_claim_allowed": False,
                "live_delivery_claim_allowed": False,
                "summary": "Proactive OODA route and packet runtime are locally ready; mirror a host-visible live receipt when the next real packet is sent.",
                "next_action": "run_or_mirror_live_proactive_ooda_receipt",
                "operator_action_state": "live_proof_pending",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_view_models, "OFFICE_LOOP_GOAL_RECEIPT", office_receipt)
    monkeypatch.setattr(admin_view_models, "EXECUTIVE_ASSISTANT_ACCEPTANCE_EVIDENCE_RECEIPT", acceptance_receipt)
    monkeypatch.setattr(admin_view_models, "ACTIVE_MEDIA_LTD_GOAL_RECEIPT", active_media_receipt)
    monkeypatch.setattr(admin_view_models, "WHOLE_PROJECT_SIGNAL_TO_DECISION_RECEIPT", signal_receipt)
    monkeypatch.setattr(admin_view_models, "WHOLE_PROJECT_SCOPE_GAP_AUDIT_RECEIPT", scope_audit_receipt)
    monkeypatch.setattr(admin_view_models, "PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT", proactive_receipt)
    monkeypatch.setattr(landing_actions, "EA_OFFICE_LOOP_GOAL_RECEIPT", office_receipt)
    monkeypatch.setattr(landing_actions, "EA_ACCEPTANCE_EVIDENCE_RECEIPT", acceptance_receipt)
    monkeypatch.setattr(landing_actions, "EA_QUALITY_READINESS_RECEIPT", quality_receipt)
    monkeypatch.setattr(landing_actions, "EA_ACTIVE_MEDIA_LTD_GOAL_RECEIPT", active_media_receipt)
    monkeypatch.setattr(landing_actions, "EA_SIGNAL_TO_DECISION_RECEIPT", signal_receipt)
    monkeypatch.setattr(landing_actions, "EA_SCOPE_GAP_AUDIT_RECEIPT", scope_audit_receipt)

    goals_before = client.get("/admin/goals")
    assert goals_before.status_code == 200
    assert "Record a real-use outcome" in goals_before.text
    assert "/admin/actions/acceptance-evidence" in goals_before.text
    assert "Record a signal-loop outcome" in goals_before.text
    assert "/admin/actions/signal-to-decision-evidence" in goals_before.text
    assert "Proactive delivery recovery" in goals_before.text

    raw_note = "Morning brief genuinely helped avoid missing the private board prep thread."
    raw_object_ref = "telegram-message-private-board-prep-123"
    recorded = client.post(
        "/admin/actions/acceptance-evidence",
        data={
            "proof_key": "real_daily_morning_brief_accepted",
            "source_kind": "principal",
            "evidence": raw_note,
            "object_ref": raw_object_ref,
        },
        follow_redirects=False,
    )

    assert recorded.status_code == 303
    assert recorded.headers["location"] == "/admin/goals?acceptance_status=recorded"
    acceptance = json.loads(acceptance_receipt.read_text(encoding="utf-8"))
    assert acceptance["status"] == "partial_real_world_acceptance_evidence"
    assert acceptance["accepted_keys"] == ["real_daily_morning_brief_accepted"]
    assert acceptance["acceptance_keys"]["real_daily_morning_brief_accepted"]["accepted"] is True
    assert acceptance["acceptance_keys"]["real_daily_morning_brief_accepted"]["status"] == "accepted_redacted"
    assert acceptance["acceptance_keys"]["real_daily_morning_brief_accepted"]["source_kind"] == "principal"
    assert acceptance["acceptance_capture_surface"]["path"] == "/admin/actions/acceptance-evidence"
    requirements = {item["key"]: item for item in acceptance["acceptance_capture_requirements"]}
    assert requirements["real_daily_morning_brief_accepted"]["status"] == "accepted_redacted"
    assert requirements["real_decision_cleared"]["status"] == "pending_real_world_evidence"
    assert requirements["real_decision_cleared"]["raw_input_not_persisted"] is True
    assert acceptance["privacy"]["raw_acceptance_text_exposed"] is False
    acceptance_text = acceptance_receipt.read_text(encoding="utf-8")
    assert raw_note not in acceptance_text
    assert raw_object_ref not in acceptance_text
    assert "operator-admin-1" not in acceptance_text

    quality = json.loads(quality_receipt.read_text(encoding="utf-8"))
    assert quality["status"] == "blocked_real_world_acceptance"
    assert "real_daily_morning_brief_accepted" not in quality["external_acceptance_blockers"]
    assert "real_decision_cleared" in quality["external_acceptance_blockers"]

    signal = json.loads(signal_receipt.read_text(encoding="utf-8"))
    assert signal["status"] == "ready_local_packet_pending_operator_acceptance"
    assert signal["goal_completion_claim_allowed"] is False
    assert "real weekly signal-to-decision review accepted by the operator" in signal["remaining_external_proofs"]

    raw_review = "Operator accepted the weekly packet after checking private channel and provider signals."
    raw_packet_ref = "weekly-signal-private-packet-123"
    signal_review = client.post(
        "/admin/actions/signal-to-decision-evidence",
        data={
            "evidence_part": "review",
            "source_kind": "operator",
            "evidence": raw_review,
            "packet_ref": raw_packet_ref,
        },
        follow_redirects=False,
    )

    assert signal_review.status_code == 303
    assert signal_review.headers["location"] == "/admin/goals?signal_status=recorded"
    signal = json.loads(signal_receipt.read_text(encoding="utf-8"))
    assert signal["status"] == "partial_real_signal_to_decision_closure"
    assert signal["real_weekly_operator_review_accepted"] is True
    assert signal["closed_loop_followthrough_receipt_verified"] is False
    assert signal["operator_review"]["status"] == "accepted_redacted"
    assert signal["operator_review"]["raw_review_exposed"] is False
    assert signal["signal_evidence_capture_surface"]["path"] == "/admin/actions/signal-to-decision-evidence"
    signal_requirements = {item["evidence_part"]: item for item in signal["signal_evidence_capture_requirements"]}
    assert signal_requirements["review"]["status"] == "accepted_redacted"
    assert signal_requirements["followthrough"]["status"] == "pending_real_world_evidence"
    assert signal_requirements["followthrough"]["raw_input_not_persisted"] is True
    signal_text = signal_receipt.read_text(encoding="utf-8")
    assert raw_review not in signal_text
    assert raw_packet_ref not in signal_text
    assert "operator-admin-1" not in signal_text

    raw_followthrough = "Provider recovery was routed to its owning plane and the decision loop was closed."
    raw_followthrough_ref = "owner-followthrough-private-456"
    signal_followthrough = client.post(
        "/admin/actions/signal-to-decision-evidence",
        data={
            "evidence_part": "followthrough",
            "source_kind": "product_governor",
            "evidence": raw_followthrough,
            "packet_ref": raw_followthrough_ref,
        },
        follow_redirects=False,
    )

    assert signal_followthrough.status_code == 303
    assert signal_followthrough.headers["location"] == "/admin/goals?signal_status=recorded"
    signal = json.loads(signal_receipt.read_text(encoding="utf-8"))
    assert signal["status"] == "ready_real_signal_to_decision_closure"
    assert signal["real_weekly_operator_review_accepted"] is True
    assert signal["closed_loop_followthrough_receipt_verified"] is True
    assert signal["operator_review"]["review_sha256"]
    assert signal["followthrough_receipt"]["followthrough_sha256"]
    assert signal["followthrough_receipt"]["status"] == "accepted_redacted"
    signal_requirements = {item["evidence_part"]: item for item in signal["signal_evidence_capture_requirements"]}
    assert signal_requirements["review"]["status"] == "accepted_redacted"
    assert signal_requirements["followthrough"]["status"] == "accepted_redacted"
    signal_text = signal_receipt.read_text(encoding="utf-8")
    assert raw_review not in signal_text
    assert raw_packet_ref not in signal_text
    assert raw_followthrough not in signal_text
    assert raw_followthrough_ref not in signal_text
    assert "operator-admin-1" not in signal_text
    assert "real weekly signal-to-decision review accepted by the operator" not in signal["remaining_external_proofs"]
    assert "closed-loop signal-to-decision follow-through receipt accepted by the operator" not in signal["remaining_external_proofs"]

    scope_audit = json.loads(scope_audit_receipt.read_text(encoding="utf-8"))
    assert scope_audit["evidence_receipts"]["executive_assistant_acceptance_evidence"]["status"] == "partial_real_world_acceptance_evidence"
    assert scope_audit["evidence_receipts"]["signal_to_decision"]["status"] == "ready_real_signal_to_decision_closure"
    assert scope_audit["goal_completion_claim_allowed"] is False

    goals_after = client.get("/admin/goals")
    assert goals_after.status_code == 200
    assert "Morning brief accepted" in goals_after.text
    assert "Weekly operator review" in goals_after.text
    assert "Closed-loop follow-through" in goals_after.text
    assert "Proactive delivery recovery" in goals_after.text
    assert "Accepted" in goals_after.text
    assert "private-safe signal" in goals_after.text


def test_admin_proactive_ooda_capture_records_redacted_gold_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    principal_id = "exec-admin-proactive-ooda-capture"
    client = _operator_client(principal_id=principal_id)
    client.headers.update({"X-EA-Operator-ID": "operator-admin-1"})
    from app.api.routes import landing_actions
    from scripts import materialize_proactive_ooda_gold_acceptance as proactive_gold_materializer

    proactive_gold_receipt = tmp_path / "ea_proactive_ooda_gold_acceptance.generated.json"
    monkeypatch.setattr(landing_actions, "EA_PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT", proactive_gold_receipt)
    monkeypatch.setattr(
        proactive_gold_materializer,
        "load_runtime_artifact_bundle",
        lambda **_kwargs: {
            "run_receipt": {"notification_status": "sent"},
            "stage_packet": {"packet_ref": "stage_packet:private-packet-123"},
            "safe_work_result": {"result_ref": "safe_work_result:private-artifact-456"},
            "approval_outcome": {},
        },
    )

    raw_note = "Approved the staged shortlist after reviewing the live comparison."
    raw_packet_ref = "stage_packet:private-packet-123"
    raw_artifact_ref = "safe_work_result:private-artifact-456"
    recorded = client.post(
        "/admin/actions/proactive-ooda-evidence",
        data={
            "outcome": "approved",
            "source_kind": "operator",
            "evidence": raw_note,
            "packet_ref": raw_packet_ref,
            "staged_artifact_ref": raw_artifact_ref,
        },
        follow_redirects=False,
    )

    assert recorded.status_code == 303
    assert recorded.headers["location"] == "/admin/goals?proactive_ooda_status=recorded"
    receipt = json.loads(proactive_gold_receipt.read_text(encoding="utf-8"))
    assert receipt["goal_completion_claim_allowed"] is False
    approval = receipt["proofs"]["approval_outcome"]
    assert approval["accepted"] is True
    assert approval["source_kind"] == "operator"
    assert approval["evidence_sha256"]
    assert approval["packet_ref_sha256"]
    assert approval["staged_artifact_sha256"]
    receipt_text = proactive_gold_receipt.read_text(encoding="utf-8")
    assert raw_note not in receipt_text
    assert raw_packet_ref not in receipt_text
    assert raw_artifact_ref not in receipt_text
    assert "operator-admin-1" not in receipt_text


def test_admin_proactive_ooda_capture_writes_runtime_approval_artifact_and_syncs_teable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    principal_id = "exec-admin-proactive-ooda-runtime-artifact"
    client = _operator_client(principal_id=principal_id)
    client.headers.update({"X-EA-Operator-ID": "operator-admin-1"})
    from app.api.routes import landing_actions

    proactive_gold_receipt = tmp_path / "ea_proactive_ooda_gold_acceptance.generated.json"
    approval_outcome_receipt = tmp_path / "state" / "proactive_ooda_latest_approval_outcome.generated.json"
    sync_calls: list[dict[str, object]] = []
    monkeypatch.setattr(landing_actions, "EA_PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT", proactive_gold_receipt)
    monkeypatch.setattr(landing_actions, "EA_PROACTIVE_OODA_APPROVAL_OUTCOME_RECEIPT", approval_outcome_receipt)
    monkeypatch.setattr(landing_actions, "teable_sync_enabled", lambda: True)
    monkeypatch.setattr(
        landing_actions,
        "load_runtime_artifact_bundle",
        lambda **_kwargs: {
            "run_receipt": {"notification_status": "sent"},
            "safe_work_result": {"result_ref": "safe_work_result:private-artifact-456", "status": "staged_for_user_decision"},
        },
    )
    monkeypatch.setattr(
        landing_actions,
        "sync_proactive_ooda_approval_outcome_to_teable",
        lambda **kwargs: sync_calls.append(dict(kwargs)) or {"status": "synced", "sync_attempted": True},
    )

    raw_note = "Approved the staged shortlist after reviewing the live comparison."
    raw_packet_ref = "stage_packet:private-packet-123"
    raw_artifact_ref = "safe_work_result:private-artifact-456"
    recorded = client.post(
        "/admin/actions/proactive-ooda-evidence",
        data={
            "outcome": "approved",
            "source_kind": "operator",
            "evidence": raw_note,
            "packet_ref": raw_packet_ref,
            "staged_artifact_ref": raw_artifact_ref,
        },
        follow_redirects=False,
    )

    assert recorded.status_code == 303
    artifact = json.loads(approval_outcome_receipt.read_text(encoding="utf-8"))
    artifact_text = approval_outcome_receipt.read_text(encoding="utf-8")
    assert artifact["schema"] == "ea.proactive_ooda_approval_outcome.v1"
    assert artifact["accepted"] is True
    assert artifact["source_kind"] == "operator"
    assert artifact["packet_ref_sha256"]
    assert artifact["staged_artifact_sha256"]
    assert raw_note not in artifact_text
    assert raw_packet_ref not in artifact_text
    assert raw_artifact_ref not in artifact_text
    assert "operator-admin-1" not in artifact_text
    assert proactive_gold_receipt.exists()
    assert sync_calls
    assert sync_calls[0]["receipt"]["notification_status"] == "sent"
    assert sync_calls[0]["safe_work_result"]["result_ref"] == "safe_work_result:private-artifact-456"
    assert dict(sync_calls[0]["approval_outcome"])["outcome_id"] == artifact["outcome_id"]


def test_admin_provider_surface_shows_contract_receipts_without_live_overclaim(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-admin-provider-contracts"
    client = _operator_client(principal_id=principal_id)
    from app.api.routes import admin_view_models

    monkeypatch.setattr(
        admin_view_models,
        "build_provider_contract_status",
        lambda: {
            "contract_name": "ea.provider_contract_status",
            "status": "pass",
            "operator_label": "Provider contract layer is exercised; live provider receipts and E2E proof are still pending.",
            "rows": [
                {
                    "key": "hedy_meeting_evidence",
                    "title": "Hedy meeting evidence",
                    "path": "_completion/ea_provider_contracts/HEDY_MEETING_EVIDENCE_CONTRACT.generated.json",
                    "status": "contract_pass",
                    "issues": [],
                    "live_provider_runtime_verified": False,
                    "required_next_receipts": ["_completion/hedy/HEDY_PROVIDER_CAPABILITY.generated.json"],
                }
            ],
        },
    )

    response = client.get("/admin/providers")

    assert response.status_code == 200
    assert "Provider capability" in response.text
    assert "Local capability status is separate from live runtime status" in response.text
    assert "Contract layer summary" in response.text
    assert "Provider contract layer is exercised" in response.text
    assert "Hedy meeting evidence" in response.text
    assert "Live provider proof pending" in response.text
    assert "Live provider proof verified" not in response.text


def test_admin_loopback_surface_defaults_to_first_operator_for_handoff_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-admin-loopback"
    monkeypatch.setenv("EA_ALLOW_LOOPBACK_NO_AUTH", "1")
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", principal_id)

    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="executive_ops")
    seeded = seed_product_state(client, principal_id=principal_id)

    operators = client.get("/admin/operators")
    assert operators.status_code == 200
    assert "Prepare board follow-up handoff" in operators.text
    assert "Claim" in operators.text

    claimed = client.post(
        f"/app/actions/handoffs/human_task:{seeded['human_task_id']}/assign",
        data={"return_to": "/admin/operators"},
        follow_redirects=False,
    )
    assert claimed.status_code == 303
    assert claimed.headers["location"] == "/admin/operators"

    operators_after_claim = client.get("/admin/operators")
    assert operators_after_claim.status_code == 200
    assert "Prepare board follow-up handoff" in operators_after_claim.text
    assert "Complete" in operators_after_claim.text


def test_admin_loopback_surface_requires_operator_profile_for_operator_access(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-admin-loopback-denied"
    monkeypatch.setenv("EA_ALLOW_LOOPBACK_NO_AUTH", "1")
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", principal_id)

    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="executive_ops")

    response = client.get("/admin/providers", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/bootstrap-operator?return_to=%2Fadmin%2Fproviders"

    bootstrap = client.get(response.headers["location"])

    assert bootstrap.status_code == 200
    assert "Create the first operator profile" in bootstrap.text
    assert "Create operator profile" in bootstrap.text


def test_admin_bootstrap_operator_creates_first_profile_and_unblocks_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-admin-bootstrap"
    monkeypatch.setenv("EA_ALLOW_LOOPBACK_NO_AUTH", "1")
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", principal_id)

    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="executive_ops")

    created = client.post(
        "/admin/actions/bootstrap-operator",
        data={
            "display_name": "Tibor Ops",
            "operator_id": "operator-tibor",
            "return_to": "/admin/goals",
        },
        follow_redirects=False,
    )

    assert created.status_code == 303
    assert created.headers["location"] == "/admin/goals?operator_bootstrap=ready"

    rows = client.app.state.container.orchestrator.list_operator_profiles(
        principal_id=principal_id,
        status="active",
        limit=25,
    )
    assert len(rows) == 1
    assert rows[0].operator_id == "operator-tibor"
    assert rows[0].display_name == "Tibor Ops"
    assert tuple(rows[0].roles) == ("operator", "reviewer")

    goals = client.get("/admin/goals")
    assert goals.status_code == 200
    assert "Goal Status" in goals.text


def test_workspace_access_operator_link_auto_provisions_profile_and_opens_proactive_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-admin-proactive-access-session"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="executive_ops")
    from app.api.routes import landing_console_support

    monkeypatch.setattr(
        landing_console_support,
        "resolve_proactive_ooda_capture_bundle",
        lambda **_kwargs: {
            "bundle": {
                "run_receipt": {"notification_status": "sent"},
                "run_receipt_path": "state/proactive_ooda_latest_run.generated.json",
                "stage_packet_path": "state/proactive_ooda_stage_packets/packet-1.json",
                "safe_work_result_path": "state/proactive_ooda_safe_work_results/result-1.json",
                "approval_outcome_path": "state/proactive_ooda_latest_approval_outcome.generated.json",
                "stage_packet": {"packet_ref": "stage_packet:access-session"},
                "safe_work_result": {
                    "result_ref": "safe_work_result:access-session",
                    "status": "staged_for_user_decision",
                    "approval": {"required": True},
                    "staged_action_url": "https://example.test/approve",
                    "recommended_option_or_draft": {
                        "kind": "shortlist_candidate",
                        "value": {"label": "Option A", "url": "https://example.test/a"},
                    },
                },
                "approval_outcome": {},
                "current_packet_live_pending_count": 1,
            },
            "bundle_source": "live_runtime",
            "host_fallback_used": False,
            "fallback_reason": "",
            "live_report": {"status": "ok"},
            "approval_selection": {
                "approval_outcome": {},
                "stale_saved_approval_outcome_present": False,
                "source": "",
            },
        },
    )
    monkeypatch.setattr(landing_console_support, "_load_proactive_ooda_control_receipts", lambda: ({}, {}))

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "ops-proactive@example.com",
            "role": "operator",
            "display_name": "Ops Proactive",
            "expires_in_hours": 24,
        },
    )

    assert access_session.status_code == 200
    access_body = access_session.json()
    rows = client.app.state.container.orchestrator.list_operator_profiles(
        principal_id=principal_id,
        status="active",
        limit=25,
    )
    assert len(rows) == 1
    assert rows[0].operator_id == access_body["operator_id"]
    assert rows[0].display_name == "Ops Proactive"
    assert "operator" in tuple(rows[0].roles)

    client.headers.pop("X-EA-Principal-ID", None)
    opened = client.get(
        access_body["access_url"],
        params={"return_to": "/admin/proactive-ooda/approval"},
        follow_redirects=False,
    )

    assert opened.status_code == 303
    assert opened.headers["location"] == "/admin/proactive-ooda/approval"
    assert "ea_workspace_session=" in str(opened.headers.get("set-cookie") or "")

    approval = client.get("/admin/proactive-ooda/approval", follow_redirects=False)
    assert approval.status_code == 200
    assert "Record proactive OODA outcome" in approval.text
    assert "Create the first operator profile" not in approval.text


def test_admin_proactive_ooda_approval_page_prefills_runtime_artifact_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-admin-proactive-approval-page"
    client = _operator_client(principal_id=principal_id)
    from app.api.routes import landing_console_support

    monkeypatch.setattr(
        landing_console_support,
        "resolve_proactive_ooda_capture_bundle",
        lambda **_kwargs: {
            "bundle": {
                "run_receipt": {"notification_status": "sent"},
                "run_receipt_path": "state/proactive_ooda_latest_run.generated.json",
                "stage_packet_path": "state/proactive_ooda_stage_packets/packet-1.json",
                "safe_work_result_path": "state/proactive_ooda_safe_work_results/result-1.json",
                "approval_outcome_path": "state/proactive_ooda_latest_approval_outcome.generated.json",
                "stage_packet": {"packet_ref": "stage_packet:private-packet-123"},
                "safe_work_result": {
                    "result_ref": "safe_work_result:private-artifact-456",
                    "status": "staged_for_user_decision",
                    "approval": {"required": True},
                    "staged_action_url": "https://example.test/approve",
                    "recommended_option_or_draft": {
                        "kind": "shortlist_candidate",
                        "value": {"label": "Option A", "url": "https://example.test/a"},
                    },
                    "evidence_refs": [
                        {
                            "kind": "candidate",
                            "label": "Option A",
                            "url": "https://example.test/a",
                            "page_title": "Option A listing",
                            "reachable": True,
                        }
                    ],
                },
                "approval_outcome": {},
                "current_packet_live_pending_count": 1,
            },
            "bundle_source": "live_runtime",
            "host_fallback_used": False,
            "fallback_reason": "",
            "live_report": {"status": "ok"},
            "approval_selection": {
                "approval_outcome": {},
                "stale_saved_approval_outcome_present": False,
                "source": "",
            },
        },
    )
    monkeypatch.setattr(landing_console_support, "_load_proactive_ooda_control_receipts", lambda: ({}, {}))

    response = client.get("/admin/proactive-ooda/approval")

    assert response.status_code == 200
    assert "Record proactive OODA outcome" in response.text
    assert 'action="/admin/actions/proactive-ooda-evidence"' in response.text
    assert 'name="packet_ref"' in response.text
    assert "stage_packet:private-packet-123" in response.text
    assert 'name="staged_artifact_ref"' in response.text
    assert "safe_work_result:private-artifact-456" in response.text
    assert "https://example.test/approve" in response.text
    assert 'name="return_to" value="/admin/proactive-ooda/approval"' in response.text
    assert 'name="dry_run"' in response.text


def test_admin_proactive_ooda_approval_page_marks_mismatched_saved_approval_as_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-admin-proactive-approval-stale"
    client = _operator_client(principal_id=principal_id)
    from app.api.routes import landing_console_support

    monkeypatch.setattr(
        landing_console_support,
        "resolve_proactive_ooda_capture_bundle",
        lambda **_kwargs: {
            "bundle": {
                "run_receipt": {"notification_status": "sent"},
                "run_receipt_path": "state/proactive_ooda_latest_run.generated.json",
                "stage_packet_path": "state/proactive_ooda_stage_packets/current.json",
                "safe_work_result_path": "state/proactive_ooda_safe_work_results/current.json",
                "approval_outcome_path": "state/proactive_ooda_latest_approval_outcome.generated.json",
                "stage_packet": {"packet_ref": "stage_packet:current"},
                "safe_work_result": {
                    "result_ref": "safe_work_result:current",
                    "status": "staged_for_user_decision",
                    "approval": {"required": True},
                    "staged_action_url": "https://example.test/current",
                    "recommended_option_or_draft": {
                        "kind": "shortlist_candidate",
                        "value": {"label": "Current option", "url": "https://example.test/current"},
                    },
                },
                "approval_outcome": {
                    "approval_outcome_recorded": True,
                    "status": "accepted_redacted",
                    "outcome": "approved",
                    "packet_ref_sha256": "a" * 64,
                    "staged_artifact_sha256": "b" * 64,
                },
                "current_packet_live_pending_count": 0,
            },
            "bundle_source": "live_runtime",
            "host_fallback_used": False,
            "fallback_reason": "",
            "live_report": {"status": "ok"},
            "approval_selection": {
                "approval_outcome": {},
                "stale_saved_approval_outcome_present": True,
                "source": "",
            },
        },
    )
    monkeypatch.setattr(landing_console_support, "_load_proactive_ooda_control_receipts", lambda: ({}, {}))

    response = client.get("/admin/proactive-ooda/approval")

    assert response.status_code == 200
    assert "stale_not_current" in response.text
    assert "accepted_redacted" not in response.text
    assert "saved approval artifacts only count when their hashes match the current packet" in response.text


def test_admin_proactive_ooda_approval_page_shows_runtime_recovery_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-admin-proactive-approval-recovery"
    client = _operator_client(principal_id=principal_id)
    from app.api.routes import landing_console_support

    reconnect_href = (
        "https://myexternalbrain.com/app/actions/google/connect?"
        "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
    )
    monkeypatch.setattr(
        landing_console_support,
        "resolve_proactive_ooda_capture_bundle",
        lambda **_kwargs: {
            "bundle": {
                "run_receipt": {"notification_status": "sent"},
                "run_receipt_path": "state/proactive_ooda_latest_run.generated.json",
                "stage_packet_path": "state/proactive_ooda_stage_packets/packet-1.json",
                "safe_work_result_path": "state/proactive_ooda_safe_work_results/result-1.json",
                "approval_outcome_path": "state/proactive_ooda_latest_approval_outcome.generated.json",
                "stage_packet": {"packet_ref": "stage_packet:private-packet-123"},
                "safe_work_result": {
                    "result_ref": "safe_work_result:private-artifact-456",
                    "status": "staged_for_user_decision",
                    "approval": {"required": True},
                    "staged_action_url": "https://example.test/approve",
                    "recommended_option_or_draft": {
                        "kind": "shortlist_candidate",
                        "value": {"label": "Option A", "url": "https://example.test/a"},
                    },
                },
                "approval_outcome": {},
                "current_packet_live_pending_count": 1,
            },
            "bundle_source": "live_runtime",
            "host_fallback_used": False,
            "fallback_reason": "",
            "live_report": {"status": "ok"},
            "approval_selection": {
                "approval_outcome": {},
                "stale_saved_approval_outcome_present": False,
                "source": "",
            },
        },
    )
    monkeypatch.setattr(
        landing_console_support,
        "_load_proactive_ooda_control_receipts",
        lambda: (
            {
                "status": "blocked_local_runtime",
                "summary": "Proactive OODA routing is available, but Google workspace needs reauthorization before EA can rely on that source (google_oauth_invalid_grant).",
                "next_action": "reauthorize_google_workspace_binding",
                "next_action_href": reconnect_href,
                "next_action_label": "Reconnect Google workspace",
                "next_action_method": "get",
                "operator_action_state": "recovery_required",
                "approval_capture_surface": {
                    "ready": True,
                    "selected_channel": "telegram",
                    "current_packet_live_pending_count": 1,
                    "current_packet_callback_latest_status": "pending",
                },
            },
            {
                "status": "blocked_operator_runtime_posture",
                "summary": "The proactive OODA packet proofs exist, but operator runtime posture is blocked and gold cannot be claimed until approved source health is restored.",
                "next_action": "reauthorize_google_workspace_binding",
                "next_action_href": reconnect_href,
                "next_action_label": "Reconnect Google workspace",
                "next_action_method": "get",
            },
        ),
    )

    response = client.get("/admin/proactive-ooda/approval")

    assert response.status_code == 200
    assert "Runtime and approval controls" in response.text
    assert "Operator runtime posture" in response.text
    assert "Gold proof posture" in response.text
    assert "Telegram approval surface" in response.text
    assert "Reconnect Google workspace" in response.text
    assert reconnect_href in html.unescape(response.text)
    assert "pending 1" in response.text
