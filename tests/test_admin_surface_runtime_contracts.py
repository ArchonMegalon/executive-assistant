from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


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


def test_admin_surfaces_render_live_runtime_state() -> None:
    principal_id = "exec-admin-surface"
    client = _operator_client(principal_id=principal_id)
    _seed_admin_state(client, principal_id=principal_id)

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

    audit = client.get("/admin/audit-trail")
    assert audit.status_code == 200
    assert "Pending delivery" in audit.text
    assert "sofia@example.com" in audit.text

    operators = client.get("/admin/operators")
    assert operators.status_code == 200
    assert "Tibor Ops" in operators.text
    assert "Review the executive follow-up before send" in operators.text
    assert "Returned handoffs" in operators.text
    assert "Close investor dinner handoff" in operators.text

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
    assert "Export support-ready workspace bundle" in diagnostics.text
    assert "Open bundle" in diagnostics.text
    assert "Recent product events" in diagnostics.text

    bundle = client.get("/app/api/diagnostics/export")
    assert bundle.status_code == 200
    diagnostics_api = client.get("/app/api/diagnostics")
    assert diagnostics_api.status_code == 200
    assert int(diagnostics_api.json()["analytics"]["counts"].get("support_bundle_opened") or 0) >= 1
