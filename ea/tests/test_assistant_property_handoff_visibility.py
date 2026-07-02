from __future__ import annotations

from types import SimpleNamespace

from app.domain.models import HumanTask
from app.product.service import ProductService


def _task(task_id: str, task_type: str, brief: str) -> HumanTask:
    return HumanTask(
        human_task_id=task_id,
        session_id=f"session-{task_id}",
        step_id=f"step-{task_id}",
        principal_id="principal-1",
        task_type=task_type,
        role_required="operator",
        brief=brief,
        authority_required="",
        why_human="Human review required.",
        quality_rubric_json={},
        input_json={},
        desired_output_json={},
        priority="normal",
        sla_due_at=None,
        status="pending",
        assignment_state="unassigned",
        assigned_operator_id="",
        assignment_source="",
        assigned_at=None,
        assigned_by_actor_id="",
        resolution="",
        created_at="2026-07-02T12:00:00Z",
        updated_at="2026-07-02T12:00:00Z",
    )


def _service(tasks: list[HumanTask]) -> ProductService:
    container = SimpleNamespace(
        preference_profiles=SimpleNamespace(get_profile_bundle=lambda **_kwargs: {"preference_nodes": []}),
        orchestrator=SimpleNamespace(
            list_pending_approvals_for_principal=lambda **_kwargs: [],
            list_approval_history_for_principal=lambda **_kwargs: [],
            list_human_tasks=lambda **_kwargs: list(tasks),
            list_operator_profiles=lambda **_kwargs: [SimpleNamespace(operator_id="operator-1")],
        ),
        memory_runtime=SimpleNamespace(
            list_decision_windows=lambda **_kwargs: [],
            list_deadline_windows=lambda **_kwargs: [],
        ),
        channel_runtime=SimpleNamespace(
            list_pending_delivery=lambda **_kwargs: [],
            list_recent_observations=lambda **_kwargs: [],
        ),
        provider_registry=SimpleNamespace(registry_read_model=lambda **_kwargs: {}),
    )
    service = ProductService(container)
    service.list_commitments = lambda **_kwargs: ()  # type: ignore[method-assign]
    return service


def test_ea_list_handoffs_hides_property_tasks_when_assistant_lane_is_off() -> None:
    service = _service(
        [
            _task("property-1", "property_alert_review", "Review apartment alert"),
            _task("normal-1", "delivery_followup", "Send follow-up"),
        ]
    )

    handoffs = service.list_handoffs(principal_id="principal-1", status="pending")

    assert [row.task_type for row in handoffs] == ["delivery_followup"]


def test_ea_list_queue_hides_property_tasks_when_assistant_lane_is_off() -> None:
    service = _service(
        [
            _task("property-1", "property_alert_review", "Review apartment alert"),
            _task("normal-1", "delivery_followup", "Send follow-up"),
        ]
    )

    queue_items = service.list_queue(principal_id="principal-1")

    assert [row.id for row in queue_items] == ["human_task:normal-1"]


def test_ea_list_office_events_hides_property_events_when_assistant_lane_is_off() -> None:
    service = _service([])
    service._container.channel_runtime.list_recent_observations = lambda **_kwargs: [  # type: ignore[attr-defined]
        SimpleNamespace(
            observation_id="obs-property",
            channel="product",
            event_type="property_alert_review_created",
            created_at="2026-07-02T12:00:00Z",
            source_id="property:1",
            external_id="",
            payload={"summary": "Apartment alert: 2 Zimmer Wohnung in 1200 Wien", "task_type": "property_alert_review"},
        ),
        SimpleNamespace(
            observation_id="obs-normal",
            channel="product",
            event_type="handoff_completed",
            created_at="2026-07-02T12:05:00Z",
            source_id="handoff:1",
            external_id="",
            payload={"summary": "Electrician draft saved."},
        ),
    ]

    events = service.list_office_events(principal_id="principal-1")

    assert [row["observation_id"] for row in events] == ["obs-normal"]


def test_ea_support_bundle_hides_property_human_tasks_when_assistant_lane_is_off() -> None:
    service = _service(
        [
            _task("property-1", "property_alert_review", "Review apartment alert"),
            _task("normal-1", "delivery_followup", "Send follow-up"),
        ]
    )
    service.workspace_diagnostics = lambda **_kwargs: {  # type: ignore[method-assign]
        "workspace": {},
        "selected_channels": [],
        "plan": {},
        "billing": {},
        "entitlements": {},
        "commercial": {},
        "readiness": {},
        "product_control": {},
        "support_verification": {},
        "usage": {},
        "analytics": {},
        "providers": {},
        "queue_health": {"assignment_suggestions": []},
    }
    service.release_authority_summary = lambda: {"gate": {}}  # type: ignore[method-assign]
    service.runtime_supply_chain_summary = lambda: {"gate": {}}  # type: ignore[method-assign]
    service.list_office_events = lambda **_kwargs: ()  # type: ignore[method-assign]

    bundle = service.workspace_support_bundle(principal_id="principal-1")

    assert [row["human_task_id"] for row in bundle["human_tasks"]] == ["normal-1"]


def test_cleanup_hidden_property_tasks_closes_property_tasks_only() -> None:
    service = _service(
        [
            _task("property-1", "property_alert_review", "Review apartment alert"),
            _task("normal-1", "delivery_followup", "Send follow-up"),
        ]
    )
    completed: list[str] = []
    events: list[str] = []

    def _complete_handoff(**kwargs):  # type: ignore[no-untyped-def]
        completed.append(str(kwargs["handoff_ref"]))
        return SimpleNamespace(id=str(kwargs["handoff_ref"]))

    def _record_product_event(**kwargs):  # type: ignore[no-untyped-def]
        events.append(str(kwargs["event_type"]))

    service.complete_handoff = _complete_handoff  # type: ignore[method-assign]
    service._record_product_event = _record_product_event  # type: ignore[method-assign]

    result = service.cleanup_hidden_property_tasks(
        principal_id="principal-1",
        actor="test",
    )

    assert result["closed_total"] == 1
    assert result["skipped_total"] == 0
    assert completed == ["human_task:property-1"]
    assert events == ["assistant_property_task_auto_closed"]


def test_cleanup_hidden_property_tasks_skips_when_no_active_operator_profile_exists() -> None:
    service = _service([
        _task("property-1", "property_alert_review", "Review apartment alert"),
    ])
    service._container.orchestrator.list_operator_profiles = lambda **_kwargs: []  # type: ignore[attr-defined]

    result = service.cleanup_hidden_property_tasks(
        principal_id="principal-1",
        actor="test",
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "no_active_operator_profile"
