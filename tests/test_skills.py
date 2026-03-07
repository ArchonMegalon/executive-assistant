from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client() -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": "exec-1"})
    return client


def test_skill_catalog_round_trips_product_metadata_and_backing_contract() -> None:
    client = _client()

    created = client.post(
        "/v1/skills",
        json={
            "skill_key": "meeting_prep",
            "task_key": "meeting_prep",
            "name": "Meeting Prep",
            "description": "Build an executive-ready meeting prep packet.",
            "deliverable_type": "meeting_pack",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "workflow_template": "artifact_then_memory_candidate",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["stakeholder_context", "decision_context"],
            "memory_write_policy": "reviewed_only",
            "memory_reads": ["stakeholders", "commitments", "decision_windows"],
            "memory_writes": ["meeting_pack_fact"],
            "tags": ["executive", "meeting", "briefing"],
            "input_schema_json": {
                "type": "object",
                "properties": {"source_text": {"type": "string"}, "meeting_ref": {"type": "string"}},
            },
            "output_schema_json": {"type": "object", "properties": {"deliverable_type": {"const": "meeting_pack"}}},
            "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
            "provider_hints_json": {
                "primary": ["1min.AI"],
                "research": ["BrowserAct", "Paperguide"],
                "output": ["MarkupGo"],
            },
            "tool_policy_json": {"allowed_tools": ["artifact_repository"]},
            "human_policy_json": {"review_roles": ["briefing_reviewer"]},
            "evaluation_cases_json": [{"case_key": "meeting_prep_golden", "priority": "high"}],
            "budget_policy_json": {
                "class": "low",
                "memory_candidate_category": "meeting_pack_fact",
                "memory_candidate_confidence": 0.8,
                "memory_candidate_sensitivity": "internal",
            },
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["skill_key"] == "meeting_prep"
    assert body["workflow_template"] == "artifact_then_memory_candidate"
    assert body["memory_reads"] == ["stakeholders", "commitments", "decision_windows"]
    assert body["memory_writes"] == ["meeting_pack_fact"]
    assert body["tags"] == ["executive", "meeting", "briefing"]
    assert body["provider_hints_json"]["primary"] == ["1min.AI"]

    listed = client.get("/v1/skills", params={"limit": 10})
    assert listed.status_code == 200
    assert any(row["skill_key"] == "meeting_prep" for row in listed.json())
    filtered = client.get("/v1/skills", params={"limit": 10, "provider_hint": "browseract"})
    assert filtered.status_code == 200
    assert [row["skill_key"] for row in filtered.json()] == ["meeting_prep"]
    empty_filter = client.get("/v1/skills", params={"limit": 10, "provider_hint": "chatplayground"})
    assert empty_filter.status_code == 200
    assert empty_filter.json() == []

    fetched = client.get("/v1/skills/meeting_prep")
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["name"] == "Meeting Prep"
    assert fetched_body["human_policy_json"]["review_roles"] == ["briefing_reviewer"]
    assert fetched_body["authority_profile_json"]["authority_class"] == "draft"
    assert fetched_body["provider_hints_json"]["research"] == ["BrowserAct", "Paperguide"]
    assert fetched_body["evaluation_cases_json"][0]["case_key"] == "meeting_prep_golden"

    contract = client.get("/v1/tasks/contracts/meeting_prep")
    assert contract.status_code == 200
    budget = contract.json()["budget_policy_json"]
    assert budget["workflow_template"] == "artifact_then_memory_candidate"
    assert budget["skill_catalog_json"]["skill_key"] == "meeting_prep"
    assert budget["skill_catalog_json"]["name"] == "Meeting Prep"
    assert budget["skill_catalog_json"]["provider_hints_json"]["output"] == ["MarkupGo"]

    compiled = client.post(
        "/v1/plans/compile",
        json={"task_key": "meeting_prep", "goal": "prepare the board meeting packet"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["skill_key"] == "meeting_prep"
    assert [step["step_key"] for step in compiled.json()["plan"]["steps"]] == [
        "step_input_prepare",
        "step_policy_evaluate",
        "step_artifact_save",
        "step_memory_candidate_stage",
    ]

    executed = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "meeting_prep",
            "goal": "prepare the board meeting packet",
            "input_json": {"source_text": "Board packet context."},
        },
    )
    assert executed.status_code == 200
    assert executed.json()["skill_key"] == "meeting_prep"
    assert executed.json()["deliverable_type"] == "meeting_pack"

    session = client.get(f"/v1/rewrite/sessions/{executed.json()['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["intent_skill_key"] == "meeting_prep"
    assert session_body["artifacts"][0]["skill_key"] == "meeting_prep"
    assert session_body["receipts"][0]["skill_key"] == "meeting_prep"
    assert session_body["run_costs"][0]["skill_key"] == "meeting_prep"

    fetched_artifact = client.get(f"/v1/rewrite/artifacts/{executed.json()['artifact_id']}")
    assert fetched_artifact.status_code == 200
    assert fetched_artifact.json()["skill_key"] == "meeting_prep"

    fetched_receipt = client.get(f"/v1/rewrite/receipts/{session_body['receipts'][0]['receipt_id']}")
    assert fetched_receipt.status_code == 200
    assert fetched_receipt.json()["skill_key"] == "meeting_prep"

    fetched_cost = client.get(f"/v1/rewrite/run-costs/{session_body['run_costs'][0]['cost_id']}")
    assert fetched_cost.status_code == 200
    assert fetched_cost.json()["skill_key"] == "meeting_prep"


def test_skill_catalog_can_derive_a_skill_view_from_existing_task_contract() -> None:
    client = _client()
    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "stakeholder_briefing",
            "deliverable_type": "stakeholder_briefing",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {"class": "low"},
        },
    )
    assert contract.status_code == 200

    fetched = client.get("/v1/skills/stakeholder_briefing")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["skill_key"] == "stakeholder_briefing"
    assert body["task_key"] == "stakeholder_briefing"
    assert body["name"] == "Stakeholder Briefing"
    assert body["workflow_template"] == "rewrite"
    assert body["memory_reads"] == ["stakeholder_context"]
    assert body["provider_hints_json"] == {}
    assert body["tool_policy_json"]["allowed_tools"] == ["artifact_repository"]

    compiled = client.post(
        "/v1/plans/compile",
        json={"task_key": "stakeholder_briefing", "goal": "prepare a stakeholder briefing"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["skill_key"] == "stakeholder_briefing"


def test_skill_catalog_can_execute_ltd_inventory_refresh_skill() -> None:
    client = _client()

    binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct", "Teable", "UnknownService"]},
            "auth_metadata_json": {
                "service_accounts_json": {
                    "BrowserAct": {
                        "tier": "Tier 3",
                        "account_email": "ops@example.com",
                        "status": "activated",
                    },
                    "Teable": {
                        "tier": "License Tier 4",
                        "account_email": "ops@teable.example",
                        "status": "activated",
                    },
                }
            },
            "status": "enabled",
        },
    )
    assert binding.status_code == 200
    binding_id = binding.json()["binding_id"]

    created = client.post(
        "/v1/skills",
        json={
            "skill_key": "ltd_inventory_refresh",
            "task_key": "ltd_inventory_refresh",
            "name": "LTD Inventory Refresh",
            "description": "Refresh BrowserAct-backed LTD account facts.",
            "deliverable_type": "ltd_inventory_profile",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "workflow_template": "tool_then_artifact",
            "allowed_tools": ["browseract.extract_account_inventory", "artifact_repository"],
            "evidence_requirements": ["account_inventory"],
            "memory_write_policy": "none",
            "memory_reads": ["account_inventory"],
            "memory_writes": [],
            "tags": ["ltd", "inventory", "operations"],
            "authority_profile_json": {"authority_class": "observe", "review_class": "none"},
            "provider_hints_json": {
                "primary": ["BrowserAct"],
                "ops": ["Teable"],
                "output": ["MarkupGo"],
            },
            "tool_policy_json": {
                "allowed_tools": ["browseract.extract_account_inventory", "artifact_repository"]
            },
            "evaluation_cases_json": [{"case_key": "ltd_inventory_refresh_golden", "priority": "medium"}],
            "budget_policy_json": {
                "class": "low",
                "pre_artifact_tool_name": "browseract.extract_account_inventory",
            },
        },
    )
    assert created.status_code == 200
    assert created.json()["skill_key"] == "ltd_inventory_refresh"
    assert created.json()["workflow_template"] == "tool_then_artifact"

    filtered = client.get("/v1/skills", params={"limit": 10, "provider_hint": "browseract"})
    assert filtered.status_code == 200
    assert [row["skill_key"] for row in filtered.json()] == ["ltd_inventory_refresh"]

    fetched = client.get("/v1/skills/ltd_inventory_refresh")
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["provider_hints_json"]["ops"] == ["Teable"]
    assert fetched_body["tool_policy_json"]["allowed_tools"] == [
        "browseract.extract_account_inventory",
        "artifact_repository",
    ]

    compiled = client.post(
        "/v1/plans/compile",
        json={"task_key": "ltd_inventory_refresh", "goal": "refresh LTD inventory facts"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["skill_key"] == "ltd_inventory_refresh"
    assert [step["step_key"] for step in compiled.json()["plan"]["steps"]] == [
        "step_input_prepare",
        "step_browseract_inventory_extract",
        "step_artifact_save",
    ]

    executed = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "ltd_inventory_refresh",
            "goal": "refresh LTD inventory facts",
            "input_json": {
                "binding_id": binding_id,
                "service_names": ["BrowserAct", "Teable", "UnknownService"],
                "requested_fields": ["tier", "account_email", "status"],
            },
        },
    )
    assert executed.status_code == 200
    assert executed.json()["skill_key"] == "ltd_inventory_refresh"
    assert executed.json()["kind"] == "ltd_inventory_profile"
    assert executed.json()["structured_output_json"]["missing_services"] == ["UnknownService"]

    session = client.get(f"/v1/rewrite/sessions/{executed.json()['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["intent_skill_key"] == "ltd_inventory_refresh"
    assert [row["tool_name"] for row in session_body["receipts"]] == [
        "browseract.extract_account_inventory",
        "artifact_repository",
    ]
    assert session_body["artifacts"][0]["skill_key"] == "ltd_inventory_refresh"
    assert session_body["receipts"][0]["skill_key"] == "ltd_inventory_refresh"
    assert session_body["run_costs"][0]["skill_key"] == "ltd_inventory_refresh"
