from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.domain.models import HumanTask
from app.api.routes import admin_view_models
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


def _fake_admin_product() -> object:
    return SimpleNamespace(
        workspace_diagnostics=lambda **_kwargs: {
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
        },
        operator_center=lambda **_kwargs: {
            "queue": {},
            "snapshot": {},
            "recent_runtime": [],
            "next_actions": [],
            "handoffs": [],
            "delivery": {},
            "access": {},
            "sync": {},
        },
        workspace_snapshot=lambda **_kwargs: SimpleNamespace(
            handoffs=(),
            recently_closed_commitments=(),
            completed_handoffs=(),
        ),
        list_workspace_invitations=lambda **_kwargs: [],
        list_workspace_access_sessions=lambda **_kwargs: [],
        release_authority_summary=lambda: {"gate": {}},
        runtime_supply_chain_summary=lambda: {"gate": {}},
    )


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


def test_admin_operator_payload_hides_property_tasks_when_assistant_lane_is_off(monkeypatch) -> None:
    tasks = [
        _task("property-1", "property_alert_review", "Review apartment alert"),
        _task("normal-1", "delivery_followup", "Send follow-up"),
    ]
    container = SimpleNamespace(
        readiness=SimpleNamespace(check=lambda: (True, "Ready")),
        onboarding=SimpleNamespace(status=lambda **_kwargs: {"privacy": {}, "delivery_preferences": {}}),
        orchestrator=SimpleNamespace(
            list_pending_approvals_for_principal=lambda **_kwargs: [],
            list_approval_history_for_principal=lambda **_kwargs: [],
            list_human_tasks=lambda **kwargs: list(tasks) if kwargs.get("status") == "pending" else [],
            summarize_human_task_priorities=lambda **_kwargs: {"counts_json": {"normal": 2}, "total": 2},
            list_operator_profiles=lambda **_kwargs: [
                SimpleNamespace(
                    operator_id="operator-1",
                    display_name="Operator 1",
                    roles=("operator",),
                    trust_tier="",
                    status="active",
                )
            ],
        ),
        channel_runtime=SimpleNamespace(list_pending_delivery=lambda **_kwargs: []),
        provider_registry=SimpleNamespace(registry_read_model=lambda **_kwargs: {"providers": [], "lanes": [], "provider_count": 0}),
    )
    monkeypatch.setattr(admin_view_models, "build_product_service", lambda _container: _fake_admin_product())
    monkeypatch.setattr(admin_view_models, "_provider_lane_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_provider_contract_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_load_receipt", lambda _path: {})

    payload = admin_view_models.build_admin_section_payload(
        "operators",
        container=container,
        principal_id="principal-1",
        operator_id="operator-1",
    )

    pending_rows = payload["cards"][1]["items"]
    assert [row["title"] for row in pending_rows] == ["Send follow-up"]
    assert payload["stats"][2]["label"] == "Human tasks"
    assert payload["stats"][2]["value"] == "1"


def test_admin_goals_payload_hides_property_flavored_proactive_rows_when_assistant_lane_is_off(monkeypatch) -> None:
    container = SimpleNamespace(
        readiness=SimpleNamespace(check=lambda: (True, "Ready")),
        onboarding=SimpleNamespace(status=lambda **_kwargs: {"privacy": {}, "delivery_preferences": {}}),
        orchestrator=SimpleNamespace(
            list_pending_approvals_for_principal=lambda **_kwargs: [],
            list_approval_history_for_principal=lambda **_kwargs: [],
            list_human_tasks=lambda **_kwargs: [],
            summarize_human_task_priorities=lambda **_kwargs: {"counts_json": {}, "total": 0},
            list_operator_profiles=lambda **_kwargs: [],
        ),
        channel_runtime=SimpleNamespace(list_pending_delivery=lambda **_kwargs: []),
        provider_registry=SimpleNamespace(registry_read_model=lambda **_kwargs: {"providers": [], "lanes": [], "provider_count": 0}),
    )

    def _fake_load_receipt(path):  # type: ignore[no-untyped-def]
        if path == admin_view_models.PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT:
            return {
                "status": "ready_with_live_receipt",
                "summary": "Apartment alert: 2 Zimmer Wohnung in 1200 Wien",
                "next_action": "stage_one_chosen_candidate_for_user_decision",
                "next_action_href": "/app/queue",
                "next_action_label": "Open queue",
                "next_action_method": "get",
                "operator_action_state": "ready",
            }
        if path == admin_view_models.PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT:
            return {
                "status": "ready_for_approval_outcome_capture",
                "summary": "Compare the two best property candidates.",
                "next_action": "record_proactive_ooda_approval_outcome",
                "next_action_href": "/admin/proactive-ooda/approval",
                "next_action_label": "Record packet verdict",
                "next_action_method": "get",
            }
        return {}

    monkeypatch.setattr(admin_view_models, "build_product_service", lambda _container: _fake_admin_product())
    monkeypatch.setattr(admin_view_models, "_provider_lane_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_provider_contract_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_load_receipt", _fake_load_receipt)

    payload = admin_view_models.build_admin_section_payload(
        "goals",
        container=container,
        principal_id="principal-1",
        operator_id="operator-1",
    )

    goal_rows = payload["cards"][1]["items"]
    titles = [row["title"] for row in goal_rows]
    assert "Proactive delivery recovery" not in titles
    assert "Proactive OODA approval outcome" not in titles


def test_admin_goals_payload_keeps_signal_proof_capture_out_of_real_use_lane(monkeypatch) -> None:
    container = SimpleNamespace(
        readiness=SimpleNamespace(check=lambda: (True, "Ready")),
        onboarding=SimpleNamespace(status=lambda **_kwargs: {"privacy": {}, "delivery_preferences": {}}),
        orchestrator=SimpleNamespace(
            list_pending_approvals_for_principal=lambda **_kwargs: [],
            list_approval_history_for_principal=lambda **_kwargs: [],
            list_human_tasks=lambda **_kwargs: [],
            summarize_human_task_priorities=lambda **_kwargs: {"counts_json": {}, "total": 0},
            list_operator_profiles=lambda **_kwargs: [],
        ),
        channel_runtime=SimpleNamespace(list_pending_delivery=lambda **_kwargs: []),
        provider_registry=SimpleNamespace(registry_read_model=lambda **_kwargs: {"providers": [], "lanes": [], "provider_count": 0}),
    )

    def _fake_load_receipt(path):  # type: ignore[no-untyped-def]
        if path == admin_view_models.EXECUTIVE_ASSISTANT_ACCEPTANCE_EVIDENCE_RECEIPT:
            return {
                "status": "ready_real_world_acceptance_evidence",
                "acceptance_keys": {},
                "accepted_keys": [],
                "next_action_proof_key": "real_daily_morning_brief_accepted",
            }
        if path == admin_view_models.WHOLE_PROJECT_SIGNAL_TO_DECISION_RECEIPT:
            return {
                "status": "ready_local_packet_pending_operator_acceptance",
                "next_action_evidence_part": "review",
                "signal_evidence_capture_requirements": [
                    {
                        "evidence_part": "review",
                        "status": "pending_real_world_evidence",
                    },
                    {
                        "evidence_part": "followthrough",
                        "status": "pending_real_world_evidence",
                    },
                ],
            }
        return {}

    monkeypatch.setattr(admin_view_models, "build_product_service", lambda _container: _fake_admin_product())
    monkeypatch.setattr(admin_view_models, "_provider_lane_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_provider_contract_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_load_receipt", _fake_load_receipt)

    payload = admin_view_models.build_admin_section_payload(
        "goals",
        container=container,
        principal_id="principal-1",
        operator_id="operator-1",
    )

    real_use_titles = [row["title"] for row in payload["cards"][1]["items"]]
    acceptance_titles = [row["title"] for row in payload["cards"][2]["items"]]
    weekly_review_row = next(row for row in payload["cards"][2]["items"] if row["title"] == "Weekly operator review")

    assert "Signal review and follow-through" not in real_use_titles
    assert "Signal-loop proof capture" in acceptance_titles
    assert "Weekly operator review" in acceptance_titles
    assert "Closed-loop follow-through" in acceptance_titles
    assert weekly_review_row["tag"] == "Local"
    assert "action_href" not in weekly_review_row


def test_admin_goals_payload_hides_stale_proactive_recovery_rows_without_live_pending_surface(monkeypatch) -> None:
    container = SimpleNamespace(
        readiness=SimpleNamespace(check=lambda: (True, "Ready")),
        onboarding=SimpleNamespace(status=lambda **_kwargs: {"privacy": {}, "delivery_preferences": {}}),
        orchestrator=SimpleNamespace(
            list_pending_approvals_for_principal=lambda **_kwargs: [],
            list_approval_history_for_principal=lambda **_kwargs: [],
            list_human_tasks=lambda **_kwargs: [],
            summarize_human_task_priorities=lambda **_kwargs: {"counts_json": {}, "total": 0},
            list_operator_profiles=lambda **_kwargs: [],
        ),
        channel_runtime=SimpleNamespace(list_pending_delivery=lambda **_kwargs: []),
        provider_registry=SimpleNamespace(registry_read_model=lambda **_kwargs: {"providers": [], "lanes": [], "provider_count": 0}),
    )

    def _fake_load_receipt(path):  # type: ignore[no-untyped-def]
        if path == admin_view_models.PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT:
            return {
                "status": "ready_with_live_receipt",
                "summary": "Proactive OODA route, packet runtime, latest host-visible live receipt, Telegram approval, and manual approval outcome capture are ready for operator follow-through.",
                "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
                "next_action_href": "https://myexternalbrain.com/admin/proactive-ooda/approval",
                "next_action_label": "Record packet verdict",
                "next_action_method": "get",
                "operator_action_state": "approval_capture_pending",
            }
        if path == admin_view_models.PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT:
            return {
                "status": "pass",
                "summary": "A proactive OODA packet has routed delivery, live browse evidence, a chosen candidate, a staged reversible artifact, mirrored Teable facts, and a redacted approved outcome.",
                "next_action": "maintain_proactive_ooda_gold_acceptance_evidence",
                "next_action_href": "https://myexternalbrain.com/admin/goals",
                "next_action_label": "Open goals",
                "next_action_method": "get",
            }
        return {}

    monkeypatch.setattr(admin_view_models, "build_product_service", lambda _container: _fake_admin_product())
    monkeypatch.setattr(admin_view_models, "_provider_lane_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_provider_contract_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_load_receipt", _fake_load_receipt)
    monkeypatch.setattr(
        admin_view_models,
        "_load_current_proactive_ooda_runtime_bundle",
        lambda: {
            "current_packet_live_pending_count": 0,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "current_packet_callback_stale_pending_count": 0,
        },
    )

    payload = admin_view_models.build_admin_section_payload(
        "goals",
        container=container,
        principal_id="principal-1",
        operator_id="operator-1",
    )

    titles = [row["title"] for row in payload["cards"][1]["items"]]
    assert "Proactive delivery recovery" not in titles
    assert "Proactive OODA approval outcome" not in titles


def test_admin_goals_payload_keeps_operator_recovery_visible_but_hides_approval_outcome_for_internal_action(monkeypatch) -> None:
    container = SimpleNamespace(
        readiness=SimpleNamespace(check=lambda: (True, "Ready")),
        onboarding=SimpleNamespace(status=lambda **_kwargs: {"privacy": {}, "delivery_preferences": {}}),
        orchestrator=SimpleNamespace(
            list_pending_approvals_for_principal=lambda **_kwargs: [],
            list_approval_history_for_principal=lambda **_kwargs: [],
            list_human_tasks=lambda **_kwargs: [],
            summarize_human_task_priorities=lambda **_kwargs: {"counts_json": {}, "total": 0},
            list_operator_profiles=lambda **_kwargs: [],
        ),
        channel_runtime=SimpleNamespace(list_pending_delivery=lambda **_kwargs: []),
        provider_registry=SimpleNamespace(registry_read_model=lambda **_kwargs: {"providers": [], "lanes": [], "provider_count": 0}),
    )

    def _fake_load_receipt(path):  # type: ignore[no-untyped-def]
        if path == admin_view_models.PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT:
            return {
                "status": "ready_with_recovery_action",
                "summary": "Proactive OODA routing is available, but Google workspace needs reauthorization before EA can rely on that source (google_oauth_invalid_grant).",
                "next_action": "reauthorize_google_workspace_binding",
                "next_action_href": "https://myexternalbrain.com/integrations/google",
                "next_action_label": "Retry Google auth",
                "next_action_method": "get",
                "operator_action_state": "recovery_required",
            }
        if path == admin_view_models.PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT:
            return {
                "status": "blocked_operator_runtime_posture",
                "summary": "The proactive OODA packet proofs exist, but operator runtime posture is blocked and gold cannot be claimed until approved source health is restored.",
                "next_action": "reauthorize_google_workspace_binding",
                "next_action_href": "https://myexternalbrain.com/integrations/google",
                "next_action_label": "Retry Google auth",
                "next_action_method": "get",
                "evidence_receipts": {
                    "approval_capture_surface": {
                        "ready": False,
                        "current_packet_user_action_required": False,
                        "manual_outcome_capture_ready": False,
                        "telegram_approval_surface_ready": False,
                    }
                },
            }
        return {}

    monkeypatch.setattr(admin_view_models, "build_product_service", lambda _container: _fake_admin_product())
    monkeypatch.setattr(admin_view_models, "_provider_lane_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_provider_contract_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_load_receipt", _fake_load_receipt)
    monkeypatch.setattr(
        admin_view_models,
        "_load_current_proactive_ooda_runtime_bundle",
        lambda: {
            "current_packet_live_pending_count": 0,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "current_packet_callback_stale_pending_count": 0,
            "stage_packet": {
                "stage": {
                    "kind": "internal_action",
                    "payload": {"work_type": "record_internal_action"},
                },
                "approval": {"required": True},
                "packet_ref": "stage_packet:google-setup",
            },
            "safe_work_result": {
                "status": "staged_for_user_decision",
                "work_type": "record_internal_action",
                "approval": {"required": True},
                "approval_prompt": "Retry Google auth",
                "staged_action_url": "https://myexternalbrain.com/integrations/google",
                "result_ref": "safe_work_result:google-setup",
            },
        },
    )

    payload = admin_view_models.build_admin_section_payload(
        "goals",
        container=container,
        principal_id="principal-1",
        operator_id="operator-1",
    )

    rows = {row["title"]: row for row in payload["cards"][1]["items"]}
    assert "Proactive delivery recovery" in rows
    assert rows["Proactive delivery recovery"]["action_label"] == "Retry Google auth"
    assert "Proactive OODA approval outcome" not in rows


def test_admin_goals_payload_hides_property_scoped_proactive_rows_when_flat_search_filter_reason_blocks_runtime(monkeypatch) -> None:
    container = SimpleNamespace(
        readiness=SimpleNamespace(check=lambda: (True, "Ready")),
        onboarding=SimpleNamespace(status=lambda **_kwargs: {"privacy": {}, "delivery_preferences": {}}),
        orchestrator=SimpleNamespace(
            list_pending_approvals_for_principal=lambda **_kwargs: [],
            list_approval_history_for_principal=lambda **_kwargs: [],
            list_human_tasks=lambda **_kwargs: [],
            summarize_human_task_priorities=lambda **_kwargs: {"counts_json": {}, "total": 0},
            list_operator_profiles=lambda **_kwargs: [],
        ),
        channel_runtime=SimpleNamespace(list_pending_delivery=lambda **_kwargs: []),
        provider_registry=SimpleNamespace(registry_read_model=lambda **_kwargs: {"providers": [], "lanes": [], "provider_count": 0}),
    )

    def _fake_load_receipt(path):  # type: ignore[no-untyped-def]
        if path == admin_view_models.PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT:
            return {
                "status": "ready_with_live_receipt",
                "summary": "Reviewing live action surface for next operator step.",
                "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
                "next_action_href": "https://myexternalbrain.com/admin/proactive-ooda/approval",
                "next_action_label": "Record packet verdict",
                "next_action_method": "get",
                "operator_action_state": "approval_capture_pending",
            }
        if path == admin_view_models.PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT:
            return {
                "status": "pass",
                "summary": "A proactive OODA packet is in approval workflow.",
                "next_action": "maintain_proactive_ooda_gold_acceptance_evidence",
                "next_action_href": "https://myexternalbrain.com/admin/goals",
                "next_action_label": "Open goals",
                "next_action_method": "get",
            }
        if path == admin_view_models.EXECUTIVE_ASSISTANT_ACCEPTANCE_EVIDENCE_RECEIPT:
            return {
                "status": "ready_real_world_acceptance_evidence",
                "acceptance_keys": {},
                "accepted_keys": [],
                "next_action_proof_key": "real_daily_morning_brief_accepted",
            }
        if path == admin_view_models.WHOLE_PROJECT_SIGNAL_TO_DECISION_RECEIPT:
            return {
                "status": "ready_local_packet_pending_operator_acceptance",
                "next_action_evidence_part": "review",
                "signal_evidence_capture_requirements": [
                    {
                        "evidence_part": "review",
                        "status": "pending_real_world_evidence",
                    },
                    {
                        "evidence_part": "followthrough",
                        "status": "pending_real_world_evidence",
                    },
                ],
            }
        return {}

    monkeypatch.setattr(admin_view_models, "build_product_service", lambda _container: _fake_admin_product())
    monkeypatch.setattr(admin_view_models, "_provider_lane_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_provider_contract_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_load_receipt", _fake_load_receipt)
    monkeypatch.setattr(
        admin_view_models,
        "_load_current_proactive_ooda_runtime_bundle",
        lambda: {
            "artifact_filter_reason": "flat_search_disabled_property_scout",
            "current_packet_live_pending_count": 1,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_stale_pending_count": 1,
            "current_packet_callback_stale_pending_count": 1,
            "run_receipt": {"schema": "proactive_ooda.run_receipt.v1", "status": "approved"},
        },
    )

    payload = admin_view_models.build_admin_section_payload(
        "goals",
        container=container,
        principal_id="principal-1",
        operator_id="operator-1",
    )

    titles = [row["title"] for row in payload["cards"][1]["items"]]
    assert "Proactive delivery recovery" not in titles
    assert "Proactive OODA approval outcome" not in titles


def test_admin_goals_payload_keeps_signal_evidence_rows_local_when_property_scoped_runtime_is_current(monkeypatch) -> None:
    container = SimpleNamespace(
        readiness=SimpleNamespace(check=lambda: (True, "Ready")),
        onboarding=SimpleNamespace(status=lambda **_kwargs: {"privacy": {}, "delivery_preferences": {}}),
        orchestrator=SimpleNamespace(
            list_pending_approvals_for_principal=lambda **_kwargs: [],
            list_approval_history_for_principal=lambda **_kwargs: [],
            list_human_tasks=lambda **_kwargs: [],
            summarize_human_task_priorities=lambda **_kwargs: {"counts_json": {}, "total": 0},
            list_operator_profiles=lambda **_kwargs: [],
        ),
        channel_runtime=SimpleNamespace(list_pending_delivery=lambda **_kwargs: []),
        provider_registry=SimpleNamespace(registry_read_model=lambda **_kwargs: {"providers": [], "lanes": [], "provider_count": 0}),
    )

    def _fake_load_receipt(path):  # type: ignore[no-untyped-def]
        if path == admin_view_models.PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT:
            return {
                "status": "ready_with_live_receipt",
                "summary": "Apartment shortlist still present in stale proactive artifacts.",
            }
        if path == admin_view_models.PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT:
            return {
                "status": "pass",
                "summary": "Property-scoped proactive work is pending.",
            }
        if path == admin_view_models.EXECUTIVE_ASSISTANT_ACCEPTANCE_EVIDENCE_RECEIPT:
            return {
                "status": "ready_real_world_acceptance_evidence",
                "acceptance_keys": {},
                "accepted_keys": [],
                "next_action_proof_key": "real_daily_morning_brief_accepted",
            }
        if path == admin_view_models.WHOLE_PROJECT_SIGNAL_TO_DECISION_RECEIPT:
            return {
                "status": "partial_real_signal_to_decision_closure",
                "real_weekly_operator_review_accepted": True,
                "closed_loop_followthrough_receipt_verified": False,
                "next_action_evidence_part": "followthrough",
                "signal_evidence_capture_requirements": [
                    {"evidence_part": "review", "status": "accepted_redacted"},
                    {"evidence_part": "followthrough", "status": "pending_real_world_evidence"},
                ],
            }
        return {}

    monkeypatch.setattr(admin_view_models, "build_product_service", lambda _container: _fake_admin_product())
    monkeypatch.setattr(admin_view_models, "_provider_lane_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_provider_contract_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_load_receipt", _fake_load_receipt)
    monkeypatch.setattr(
        admin_view_models,
        "_load_current_proactive_ooda_runtime_bundle",
        lambda: {
            "artifact_filter_reason": "flat_search_disabled_property_scout",
            "current_packet_live_pending_count": 1,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_stale_pending_count": 1,
            "current_packet_callback_stale_pending_count": 1,
        },
    )

    payload = admin_view_models.build_admin_section_payload(
        "goals",
        container=container,
        principal_id="principal-1",
        operator_id="operator-1",
    )

    rows = {row["title"]: row for row in payload["cards"][2]["items"]}
    assert rows["Weekly operator review"]["tag"] == "Accepted"
    assert "href" not in rows["Weekly operator review"]
    assert rows["Closed-loop follow-through"]["tag"] == "Local"
    assert "action_href" not in rows["Closed-loop follow-through"]


def test_admin_goals_payload_hides_proactive_rows_when_property_scoped_callback_pending_count_is_present(monkeypatch) -> None:
    container = SimpleNamespace(
        readiness=SimpleNamespace(check=lambda: (True, "Ready")),
        onboarding=SimpleNamespace(status=lambda **_kwargs: {"privacy": {}, "delivery_preferences": {}}),
        orchestrator=SimpleNamespace(
            list_pending_approvals_for_principal=lambda **_kwargs: [],
            list_approval_history_for_principal=lambda **_kwargs: [],
            list_human_tasks=lambda **_kwargs: [],
            summarize_human_task_priorities=lambda **_kwargs: {"counts_json": {}, "total": 0},
            list_operator_profiles=lambda **_kwargs: [],
        ),
        channel_runtime=SimpleNamespace(list_pending_delivery=lambda **_kwargs: []),
        provider_registry=SimpleNamespace(registry_read_model=lambda **_kwargs: {"providers": [], "lanes": [], "provider_count": 0}),
    )

    def _fake_load_receipt(path):  # type: ignore[no-untyped-def]
        if path == admin_view_models.PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT:
            return {
                "status": "ready_with_live_receipt",
                "summary": "Apartment search pending action. ",
                "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
                "next_action_href": "https://myexternalbrain.com/admin/proactive-ooda/approval",
                "next_action_label": "Record packet verdict",
                "next_action_method": "get",
                "operator_action_state": "approval_capture_pending",
            }
        if path == admin_view_models.PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT:
            return {
                "status": "pass",
                "summary": "A property-scoped proactive OODA packet is pending.",
                "next_action": "maintain_proactive_ooda_gold_acceptance_evidence",
                "next_action_href": "https://myexternalbrain.com/admin/goals",
                "next_action_label": "Open goals",
                "next_action_method": "get",
            }
        if path == admin_view_models.EXECUTIVE_ASSISTANT_ACCEPTANCE_EVIDENCE_RECEIPT:
            return {
                "status": "ready_real_world_acceptance_evidence",
                "acceptance_keys": {},
                "accepted_keys": [],
                "next_action_proof_key": "real_daily_morning_brief_accepted",
            }
        if path == admin_view_models.WHOLE_PROJECT_SIGNAL_TO_DECISION_RECEIPT:
            return {
                "status": "ready_local_packet_pending_operator_acceptance",
                "next_action_evidence_part": "review",
                "signal_evidence_capture_requirements": [
                    {"evidence_part": "review", "status": "pending_real_world_evidence"},
                    {"evidence_part": "followthrough", "status": "pending_real_world_evidence"},
                ],
            }
        return {}

    monkeypatch.setattr(admin_view_models, "build_product_service", lambda _container: _fake_admin_product())
    monkeypatch.setattr(admin_view_models, "_provider_lane_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_provider_contract_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_load_receipt", _fake_load_receipt)
    monkeypatch.setattr(
        admin_view_models,
        "_load_current_proactive_ooda_runtime_bundle",
        lambda: {
            "artifact_filter_reason": "",
            "approval_callback_property_scoped_pending_count": 1,
            "current_packet_live_pending_count": 1,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_stale_pending_count": 1,
            "current_packet_callback_stale_pending_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_raw_pending_count": 1,
            "run_receipt": {"schema": "proactive_ooda.run_receipt.v1", "status": "ready"},
        },
    )

    payload = admin_view_models.build_admin_section_payload(
        "goals",
        container=container,
        principal_id="principal-1",
        operator_id="operator-1",
    )

    titles = [row["title"] for row in payload["cards"][1]["items"]]
    assert "Proactive delivery recovery" not in titles
    assert "Proactive OODA approval outcome" not in titles


def test_admin_view_runtime_bundle_uses_repo_root(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def _fake_resolve_proactive_ooda_capture_bundle(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {"bundle": {}}

    monkeypatch.setattr(
        admin_view_models,
        "resolve_proactive_ooda_capture_bundle",
        _fake_resolve_proactive_ooda_capture_bundle,
    )

    assert admin_view_models._load_current_proactive_ooda_runtime_bundle() == {}
    assert observed["root"] == Path(__file__).resolve().parents[2]


def test_admin_gold_action_surface_requires_current_user_approval() -> None:
    receipt = {
        "status": "ready_for_approval_outcome_capture",
        "next_action": "record_proactive_ooda_approval_outcome",
        "next_action_href": "/admin/proactive-ooda/approval",
    }

    assert (
        admin_view_models._proactive_gold_action_surface_visible(
            {"current_packet_live_pending_count": 1},
            receipt=receipt,
        )
        is True
    )
    assert (
        admin_view_models._proactive_gold_action_surface_visible(
            {
                "current_packet_live_pending_count": 0,
                "approval_callback_noncurrent_pending_count": 1,
                "approval_callback_stale_pending_count": 1,
                "current_packet_callback_stale_pending_count": 1,
            },
            receipt=receipt,
        )
        is False
    )
    verified_receipt = {
        "evidence_receipts": {
            "approval_capture_surface": {
                "ready": True,
                "current_packet_user_action_required": True,
                "current_packet_matches_packet_artifacts": True,
                "manual_outcome_capture_ready": True,
            }
        }
    }
    assert (
        admin_view_models._proactive_gold_action_surface_visible(
            {},
            receipt=verified_receipt,
        )
        is True
    )


def test_admin_view_runtime_bundle_prefers_live_bundle_resolution(monkeypatch) -> None:
    monkeypatch.setattr(
        admin_view_models,
        "resolve_proactive_ooda_capture_bundle",
        lambda **_kwargs: {
            "bundle_source": "live_runtime",
            "bundle": {
                "state_path": "/data/provider-ledger/proactive_ooda_notified.json",
                "current_packet_live_pending_count": 0,
                "stage_packet": {"packet_ref": "stage_packet:live"},
            },
        },
    )

    bundle = admin_view_models._load_current_proactive_ooda_runtime_bundle()

    assert bundle["state_path"] == "/data/provider-ledger/proactive_ooda_notified.json"
    assert bundle["stage_packet"]["packet_ref"] == "stage_packet:live"


def test_admin_goals_payload_hides_proactive_rows_when_receipts_indicate_property_scope(monkeypatch) -> None:
    container = SimpleNamespace(
        readiness=SimpleNamespace(check=lambda: (True, "Ready")),
        onboarding=SimpleNamespace(status=lambda **_kwargs: {"privacy": {}, "delivery_preferences": {}}),
        orchestrator=SimpleNamespace(
            list_pending_approvals_for_principal=lambda **_kwargs: [],
            list_approval_history_for_principal=lambda **_kwargs: [],
            list_human_tasks=lambda **_kwargs: [],
            summarize_human_task_priorities=lambda **_kwargs: {"counts_json": {}, "total": 0},
            list_operator_profiles=lambda **_kwargs: [],
        ),
        channel_runtime=SimpleNamespace(list_pending_delivery=lambda **_kwargs: []),
        provider_registry=SimpleNamespace(registry_read_model=lambda **_kwargs: {"providers": [], "lanes": [], "provider_count": 0}),
    )

    def _fake_load_receipt(path):  # type: ignore[no-untyped-def]
        if path == admin_view_models.PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT:
            return {
                "status": "ready_with_live_receipt",
                "summary": "Reviewing non-property live receipt and operator actions.",
                "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
                "next_action_href": "https://myexternalbrain.com/admin/proactive-ooda/approval",
                "next_action_label": "Record packet verdict",
                "next_action_method": "get",
                "operator_action_state": "apartment_search_pending",
            }
        if path == admin_view_models.PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT:
            return {
                "status": "pass",
                "summary": "A proactive OODA packet is in approval workflow.",
                "next_action": "maintain_proactive_ooda_gold_acceptance_evidence",
                "next_action_href": "https://myexternalbrain.com/admin/goals",
                "next_action_label": "Open goals",
                "next_action_method": "get",
                "gold_acceptance_state": "flat_candidate_waiting",
            }
        if path == admin_view_models.EXECUTIVE_ASSISTANT_ACCEPTANCE_EVIDENCE_RECEIPT:
            return {
                "status": "ready_real_world_acceptance_evidence",
                "acceptance_keys": {},
                "accepted_keys": [],
                "next_action_proof_key": "real_daily_morning_brief_accepted",
            }
        if path == admin_view_models.WHOLE_PROJECT_SIGNAL_TO_DECISION_RECEIPT:
            return {
                "status": "ready_local_packet_pending_operator_acceptance",
                "next_action_evidence_part": "review",
                "signal_evidence_capture_requirements": [
                    {"evidence_part": "review", "status": "pending_real_world_evidence"},
                    {"evidence_part": "followthrough", "status": "pending_real_world_evidence"},
                ],
            }
        return {}

    monkeypatch.setattr(admin_view_models, "build_product_service", lambda _container: _fake_admin_product())
    monkeypatch.setattr(admin_view_models, "_provider_lane_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_provider_contract_rows", lambda: [])
    monkeypatch.setattr(admin_view_models, "_load_receipt", _fake_load_receipt)
    monkeypatch.setattr(
        admin_view_models,
        "_load_current_proactive_ooda_runtime_bundle",
        lambda: {
            "artifact_filter_reason": "",
            "current_packet_live_pending_count": 1,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_stale_pending_count": 1,
            "current_packet_callback_stale_pending_count": 1,
            "run_receipt": {"schema": "proactive_ooda.run_receipt.v1", "status": "ready"},
        },
    )

    payload = admin_view_models.build_admin_section_payload(
        "goals",
        container=container,
        principal_id="principal-1",
        operator_id="operator-1",
    )

    titles = [row["title"] for row in payload["cards"][1]["items"]]
    assert "Proactive delivery recovery" not in titles
    assert "Proactive OODA approval outcome" not in titles
