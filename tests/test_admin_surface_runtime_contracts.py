from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from tests.product_test_helpers import build_product_client, seed_product_state, start_workspace


def _operator_client(*, principal_id: str = "exec-admin-surface") -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = "test-token"
    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    os.environ["EA_OPERATOR_PRINCIPAL_IDS"] = principal_id
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"Authorization": "Bearer test-token", "X-EA-Principal-ID": principal_id})
    return client


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
        why_human="Seed a returned handoff for the operator control plane.",
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
    assert "Organizer / Community" in community.text
    assert "What participation and release currently look like" in community.text
    assert "operator-community@example.com" in community.text
    assert "principal-community@example.com" in community.text
    assert "community-access@example.com" in community.text
    assert "Release and support" in community.text
    assert "Launch readiness" in community.text
    assert "Support fallout" in community.text
    assert "Public guide freshness" in community.text
    assert "Support verification" in community.text

    diagnostics = client.get("/admin/api")
    assert diagnostics.status_code == 200
    assert "Diagnostics" in diagnostics.text
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
    assert "Blocked send follow-ups" in diagnostics.text
    assert "Send follow-ups closed" in diagnostics.text
    assert "Export support-ready workspace bundle" in diagnostics.text
    assert "Open bundle" in diagnostics.text
    assert "Recent product events" in diagnostics.text

    bundle = client.get("/app/api/diagnostics/export")
    assert bundle.status_code == 200
    diagnostics_api = client.get("/app/api/diagnostics")
    assert diagnostics_api.status_code == 200
    assert int(diagnostics_api.json()["analytics"]["counts"].get("support_bundle_opened") or 0) >= 1


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
