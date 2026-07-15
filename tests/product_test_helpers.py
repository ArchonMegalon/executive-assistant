from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _build_client(
    *,
    principal_id: str,
    api_token: str = "",
    operator_id: str | None = None,
    base_url: str = "http://testserver",
    host: str | None = None,
) -> TestClient:
    from app.api.app import create_app

    client = TestClient(create_app(), base_url=base_url)
    headers = {"X-EA-Principal-ID": principal_id}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    if operator_id is not None:
        headers["X-EA-Operator-ID"] = operator_id
    if host:
        headers["host"] = host
    client.headers.update(headers)
    return client


def build_product_client(*, principal_id: str = "exec-product-api") -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ["PROPERTYQUARRY_DEFAULT_BRAND"] = "0"
    os.environ.pop("PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES", None)
    os.environ.pop("EA_ENABLE_PUBLIC_SIDE_SURFACES", None)
    os.environ.pop("EA_ENABLE_PUBLIC_RESULTS", None)
    os.environ.pop("EA_ENABLE_PUBLIC_TOURS", None)
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    return _build_client(principal_id=principal_id)


def build_property_client(
    *,
    principal_id: str = "exec-product-api",
    monkeypatch: pytest.MonkeyPatch | None = None,
    public_origin: str | None = None,
) -> TestClient:
    def _setenv(name: str, value: str) -> None:
        if monkeypatch is None:
            os.environ[name] = value
        else:
            monkeypatch.setenv(name, value)

    def _delenv(name: str) -> None:
        if monkeypatch is None:
            os.environ.pop(name, None)
        else:
            monkeypatch.delenv(name, raising=False)

    _setenv("EA_STORAGE_BACKEND", "memory")
    _delenv("EA_LEDGER_BACKEND")
    _setenv("EA_API_TOKEN", "")
    _setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    _delenv("EA_ENABLE_PUBLIC_SIDE_SURFACES")
    _delenv("EA_ENABLE_PUBLIC_RESULTS")
    _delenv("EA_ENABLE_PUBLIC_TOURS")
    _delenv("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER")
    base_url = "https://propertyquarry.com"
    host = "propertyquarry.com"
    if public_origin is not None:
        base_url = str(public_origin).strip().rstrip("/")
        parsed = urlsplit(base_url)
        host = str(parsed.hostname or "").strip().lower().rstrip(".")
        if (
            parsed.scheme != "https"
            or not host
            or parsed.netloc != host
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("property test public_origin must be an HTTPS origin")
        _setenv("PROPERTY_PUBLIC_BASE_URL", base_url)
        _setenv("PROPERTYQUARRY_PUBLIC_BASE_URL", base_url)
        _setenv("PROPERTYQUARRY_PUBLIC_TOUR_BASE_URL", f"{base_url}/tours")
        _setenv("PROPERTYQUARRY_PUBLIC_HOSTS", host)
    return _build_client(
        principal_id=principal_id,
        base_url=base_url,
        host=host,
    )


def build_operator_product_client(*, principal_id: str = "exec-product-api", operator_id: str = "operator-office") -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = "test-token"
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = principal_id
    os.environ["PROPERTYQUARRY_DEFAULT_BRAND"] = "0"
    os.environ.pop("PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES", None)
    os.environ.pop("EA_ENABLE_PUBLIC_SIDE_SURFACES", None)
    os.environ.pop("EA_ENABLE_PUBLIC_RESULTS", None)
    os.environ.pop("EA_ENABLE_PUBLIC_TOURS", None)
    client = _build_client(principal_id=principal_id, api_token="test-token", operator_id=operator_id)
    container = client.app.state.container
    container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id=operator_id,
        display_name="Operator Client",
        roles=("operator", "reviewer"),
        trust_tier="trusted",
        status="active",
        notes="Seeded by build_operator_product_client.",
    )
    return client


def build_property_operator_client(
    *,
    principal_id: str = "exec-product-api",
    operator_id: str = "operator-office",
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> TestClient:
    def _setenv(name: str, value: str) -> None:
        if monkeypatch is None:
            os.environ[name] = value
        else:
            monkeypatch.setenv(name, value)

    def _delenv(name: str) -> None:
        if monkeypatch is None:
            os.environ.pop(name, None)
        else:
            monkeypatch.delenv(name, raising=False)

    _setenv("EA_STORAGE_BACKEND", "memory")
    _delenv("EA_LEDGER_BACKEND")
    _setenv("EA_API_TOKEN", "test-token")
    _setenv("EA_DEFAULT_PRINCIPAL_ID", principal_id)
    _setenv("PROPERTYQUARRY_DEFAULT_BRAND", "1")
    _delenv("EA_ENABLE_PUBLIC_SIDE_SURFACES")
    _delenv("EA_ENABLE_PUBLIC_RESULTS")
    _delenv("EA_ENABLE_PUBLIC_TOURS")
    client = _build_client(
        principal_id=principal_id,
        api_token="test-token",
        operator_id=operator_id,
        base_url="https://propertyquarry.com",
        host="propertyquarry.com",
    )
    container = client.app.state.container
    container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id=operator_id,
        display_name="Property Operator Client",
        roles=("operator", "reviewer"),
        trust_tier="trusted",
        status="active",
        notes="Seeded by build_property_operator_client.",
    )
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
    operator = container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id="operator-office",
        display_name="Office Operator",
        roles=("operator", "reviewer"),
        trust_tier="trusted",
        status="active",
        notes="Seeded for product workflow tests.",
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
        source_json={
            "decision_type": "owner_assignment",
            "options": ["operator-office", "principal"],
            "recommended_option": "operator-office",
            "next_action": "Escalate the current recommendation to the principal and confirm the board packet owner.",
            "commitment_refs": [f"commitment:{commitment.commitment_id}", f"follow_up:{follow_up.follow_up_id}"],
            "people": ["Sofia N."],
            "thread_refs": [session.session_id],
        },
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
        "operator_id": operator.operator_id,
    }


def start_workspace(
    client: TestClient,
    *,
    mode: str,
    workspace_name: str = "Executive Assistant",
    timezone: str = "Europe/Vienna",
    region: str = "AT",
    language: str = "en",
    selected_channels: list[str] | None = None,
) -> None:
    started = client.post(
        "/v1/onboarding/start",
        json={
            "workspace_name": workspace_name,
            "mode": mode,
            "workspace_mode": mode,
            "timezone": timezone,
            "region": region,
            "language": language,
            "selected_channels": list(selected_channels or ["google"]),
        },
    )
    assert started.status_code == 200


def seed_founder_fixture(*, principal_id: str = "fixture-founder") -> tuple[TestClient, dict[str, str]]:
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Founder Office")
    seeded = seed_product_state(client, principal_id=principal_id)
    return client, seeded


def seed_executive_operator_fixture(*, principal_id: str = "fixture-exec-operator") -> tuple[TestClient, dict[str, str]]:
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    start_workspace(client, mode="executive_ops", workspace_name="Executive Office")
    seeded = seed_product_state(client, principal_id=principal_id)
    return client, seeded


def seed_team_fixture(*, principal_id: str = "fixture-team") -> tuple[TestClient, dict[str, str]]:
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    start_workspace(client, mode="team", workspace_name="Team Office", selected_channels=["google", "telegram"])
    seeded = seed_product_state(client, principal_id=principal_id)
    container = client.app.state.container
    container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id="operator-team-2",
        display_name="Team Operator",
        roles=("operator", "reviewer"),
        trust_tier="trusted",
        status="active",
        notes="Seeded for shared team fixture.",
    )
    other_task = container.orchestrator.create_human_task(
        session_id=seeded["session_id"],
        principal_id=principal_id,
        task_type="handoff",
        role_required="operator",
        brief="Coordinate shared follow-up queue",
        why_human="Shared team fixture should surface multiple operator tasks.",
        priority="medium",
        sla_due_at="2026-03-26T09:00:00+00:00",
    )
    container.orchestrator.assign_human_task(
        other_task.human_task_id,
        principal_id=principal_id,
        operator_id="operator-team-2",
        assignment_source="seed",
        assigned_by_actor_id="fixture",
    )
    return client, seeded
