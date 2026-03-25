from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def build_product_client(*, principal_id: str = "exec-product-api") -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ.pop("EA_ENABLE_PUBLIC_SIDE_SURFACES", None)
    os.environ.pop("EA_ENABLE_PUBLIC_RESULTS", None)
    os.environ.pop("EA_ENABLE_PUBLIC_TOURS", None)
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def seed_product_state(client: TestClient, *, principal_id: str) -> dict[str, str]:
    from app.domain.models import IntentSpecV3

    container = client.app.state.container
    session = container.orchestrator._ledger.start_session(  # type: ignore[attr-defined]
        IntentSpecV3(
            principal_id=principal_id,
            goal="Run the office loop",
            task_type="office_loop",
            deliverable_type="memo",
            risk_class="medium",
            approval_class="draft",
            budget_class="standard",
        )
    )
    stakeholder = container.memory_runtime.upsert_stakeholder(
        principal_id=principal_id,
        display_name="Sofia N.",
        channel_ref="sofia@example.com",
        authority_level="board",
        importance="high",
        tone_pref="direct",
        open_loops_json={"board_materials": True},
        friction_points_json={"response_speed": "Needs same-day replies"},
        last_interaction_at="2026-03-24T18:00:00+00:00",
    )
    commitment = container.memory_runtime.upsert_commitment(
        principal_id=principal_id,
        title="Send board materials",
        details="Sofia N. asked for board materials after the investor thread.",
        priority="high",
        due_at="2026-03-25T09:00:00+00:00",
        source_json={"source_type": "email", "counterparty": "Sofia N.", "owner": "operator"},
    )
    follow_up = container.memory_runtime.upsert_follow_up(
        principal_id=principal_id,
        stakeholder_ref=stakeholder.stakeholder_id,
        topic="Confirm investor meeting time",
        status="open",
        due_at="2026-03-25T10:00:00+00:00",
        channel_hint="email",
        notes="Waiting on confirmation before lunch.",
    )
    decision = container.memory_runtime.upsert_decision_window(
        principal_id=principal_id,
        title="Choose board memo owner",
        context="Someone needs to own the board memo revision.",
        closes_at="2026-03-25T11:00:00+00:00",
        urgency="high",
        authority_required="principal",
    )
    deadline = container.memory_runtime.upsert_deadline_window(
        principal_id=principal_id,
        title="Board memo delivery window",
        end_at="2026-03-25T15:00:00+00:00",
        priority="high",
        notes="Board expects the revised packet this afternoon.",
    )
    approval = container.orchestrator._approvals.create_request(  # type: ignore[attr-defined]
        session.session_id,
        "step-draft-1",
        "Approve reply to Sofia N.",
        {"action": "delivery.send", "channel": "email", "recipient": "sofia@example.com", "content": "Draft board reply"},
    )
    human_task = container.orchestrator.create_human_task(
        session_id=session.session_id,
        principal_id=principal_id,
        task_type="handoff",
        role_required="operator",
        brief="Prepare board follow-up handoff",
        why_human="Need operator review before closing the loop.",
        priority="high",
        sla_due_at="2026-03-25T12:00:00+00:00",
    )
    return {
        "session_id": session.session_id,
        "approval_id": approval.approval_id,
        "commitment_id": commitment.commitment_id,
        "follow_up_id": follow_up.follow_up_id,
        "stakeholder_id": stakeholder.stakeholder_id,
        "decision_window_id": decision.decision_window_id,
        "deadline_window_id": deadline.window_id,
        "human_task_id": human_task.human_task_id,
    }
