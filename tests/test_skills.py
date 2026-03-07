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

    listed = client.get("/v1/skills", params={"limit": 10})
    assert listed.status_code == 200
    assert any(row["skill_key"] == "meeting_prep" for row in listed.json())

    fetched = client.get("/v1/skills/meeting_prep")
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["name"] == "Meeting Prep"
    assert fetched_body["human_policy_json"]["review_roles"] == ["briefing_reviewer"]
    assert fetched_body["authority_profile_json"]["authority_class"] == "draft"
    assert fetched_body["evaluation_cases_json"][0]["case_key"] == "meeting_prep_golden"

    contract = client.get("/v1/tasks/contracts/meeting_prep")
    assert contract.status_code == 200
    budget = contract.json()["budget_policy_json"]
    assert budget["workflow_template"] == "artifact_then_memory_candidate"
    assert budget["skill_catalog_json"]["skill_key"] == "meeting_prep"
    assert budget["skill_catalog_json"]["name"] == "Meeting Prep"

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
    assert body["tool_policy_json"]["allowed_tools"] == ["artifact_repository"]

    compiled = client.post(
        "/v1/plans/compile",
        json={"task_key": "stakeholder_briefing", "goal": "prepare a stakeholder briefing"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["skill_key"] == "stakeholder_briefing"
