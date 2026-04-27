from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.services.skills import SkillCatalogService
from app.services.task_contracts import TaskContractService


DESIGN_SKILL_BOOTSTRAP_PATH = Path("/docker/EA/scripts/bootstrap_design_governance_skills.py")
CHUMMER_GUIDE_BOOTSTRAP_PATH = Path("/docker/EA/scripts/bootstrap_chummer6_guide_skill.py")


def load_design_skill_bootstrap_module():
    spec = importlib.util.spec_from_file_location("design_governance_skill_bootstrap", DESIGN_SKILL_BOOTSTRAP_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {DESIGN_SKILL_BOOTSTRAP_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_chummer_guide_bootstrap_module():
    spec = importlib.util.spec_from_file_location("chummer6_guide_skill_bootstrap", CHUMMER_GUIDE_BOOTSTRAP_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {CHUMMER_GUIDE_BOOTSTRAP_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _client() -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = "test-token"
    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    os.environ["EA_OPERATOR_PRINCIPAL_IDS"] = "exec-1"
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"Authorization": "Bearer test-token"})
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
    contract_body = contract.json()
    budget = contract_body["budget_policy_json"]
    runtime_policy = contract_body["runtime_policy_json"]
    assert runtime_policy["workflow_template"] == "artifact_then_memory_candidate"
    assert runtime_policy["skill_catalog_json"]["skill_key"] == "meeting_prep"
    assert runtime_policy["skill_catalog_json"]["name"] == "Meeting Prep"
    assert runtime_policy["skill_catalog_json"]["provider_hints_json"]["output"] == ["MarkupGo"]
    assert budget["memory_candidate_category"] == "meeting_pack_fact"

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

    compiled_via_skill = client.post(
        "/v1/plans/compile",
        json={"skill_key": "meeting_prep", "goal": "prepare the board meeting packet"},
    )
    assert compiled_via_skill.status_code == 200
    assert compiled_via_skill.json()["skill_key"] == "meeting_prep"
    assert compiled_via_skill.json()["plan"]["task_key"] == "meeting_prep"

    mismatched = client.post(
        "/v1/plans/compile",
        json={
            "task_key": "rewrite_text",
            "skill_key": "meeting_prep",
            "goal": "prepare the board meeting packet",
        },
    )
    assert mismatched.status_code == 422
    assert mismatched.json()["error"]["code"] == "task_skill_key_mismatch"

    executed = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "meeting_prep",
            "goal": "prepare the board meeting packet",
            "input_json": {"source_text": "Board packet context."},
        },
    )
    assert executed.status_code in {200, 202}
    assert executed.json()["skill_key"] == "meeting_prep"
    assert executed.json()["deliverable_type"] == "meeting_pack"

    executed_via_skill = client.post(
        "/v1/plans/execute",
        json={
            "skill_key": "meeting_prep",
            "goal": "prepare the board meeting packet",
            "input_json": {"source_text": "Board packet context via skill."},
        },
    )
    assert executed_via_skill.status_code == 200
    assert executed_via_skill.json()["skill_key"] == "meeting_prep"
    assert executed_via_skill.json()["task_key"] == "meeting_prep"

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


def test_skill_catalog_projects_builtin_campaign_workspace_v4_skill() -> None:
    client = _client()

    fetched = client.get("/v1/skills/campaign_workspace_v4_brief")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["skill_key"] == "campaign_workspace_v4_brief"
    assert body["task_key"] == "campaign_workspace_v4_brief"
    assert body["deliverable_type"] == "campaign_workspace_v4_brief"
    assert body["workflow_template"] == "tool_then_artifact"
    assert "provider.gemini_vortex.structured_generate" in body["allowed_tools"]
    assert "artifact_repository" in body["allowed_tools"]

    compiled = client.post(
        "/v1/plans/compile",
        json={
            "task_key": "campaign_workspace_v4_brief",
            "goal": "prepare one campaign workspace v4 continuity brief across downtime diary contacts heat aftermath return gm ops and offline mobile continuity",
        },
    )
    assert compiled.status_code == 200
    assert compiled.json()["skill_key"] == "campaign_workspace_v4_brief"
    assert compiled.json()["plan"]["task_key"] == "campaign_workspace_v4_brief"

    compiled = client.post(
        "/v1/plans/compile",
        json={"task_key": "stakeholder_briefing", "goal": "prepare a stakeholder briefing"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["skill_key"] == "stakeholder_briefing"


def test_design_governance_skills_round_trip_through_catalog() -> None:
    client = _client()
    module = load_design_skill_bootstrap_module()

    for skill in module.SKILLS:
        created = client.post("/v1/skills", json=skill)
        assert created.status_code == 200
        body = created.json()
        assert body["skill_key"] == skill["skill_key"]
        assert body["task_key"] == skill["task_key"]
        assert body["workflow_template"] == skill["workflow_template"]

    petition = client.get("/v1/skills/design_petition")
    assert petition.status_code == 200
    assert petition.json()["model_policy_json"]["brain_profile"] == "review_light"
    assert petition.json()["memory_writes"] == ["design_petition_fact"]

    synthesis = client.get("/v1/skills/design_synthesis")
    assert synthesis.status_code == 200
    assert synthesis.json()["model_policy_json"]["brain_profile"] == "groundwork"
    assert synthesis.json()["provider_hints_json"]["primary"] == ["Gemini Vortex"]

    mirror_brief = client.get("/v1/skills/mirror_status_brief")
    assert mirror_brief.status_code == 200
    assert mirror_brief.json()["memory_writes"] == []
    assert mirror_brief.json()["workflow_template"] == "rewrite"

    filtered = client.get("/v1/skills", params={"provider_hint": "Gemini Vortex", "limit": 20})
    assert filtered.status_code == 200
    assert {row["skill_key"] for row in filtered.json()} >= {"design_petition", "design_synthesis"}


def test_skill_catalog_service_exposes_typed_skill_records() -> None:
    contracts = TaskContractService(InMemoryTaskContractRepository())
    skills = SkillCatalogService(contracts)

    skills.upsert_skill(
        skill_key="research_decision_memo",
        task_key="research_decision_memo",
        name="Research Decision Memo",
        description="Build a grounded decision memo from structured research.",
        deliverable_type="decision_summary",
        workflow_template="artifact_then_memory_candidate",
        allowed_tools=("artifact_repository",),
        evidence_requirements=("decision_context",),
        memory_write_policy="reviewed_only",
        memory_reads=("decision_windows", "stakeholders"),
        memory_writes=("decision_research_fact",),
        tags=("research", "memo"),
        provider_hints_json={"primary": ["BrowserAct"], "secondary": ["Paperguide"]},
        budget_policy_json={"class": "low"},
    )

    record = skills.get_skill_record("research_decision_memo")
    assert record is not None
    assert record.skill_key == "research_decision_memo"
    assert record.provider_hints_json["primary"] == ["BrowserAct"]
    assert record.workflow_template == "artifact_then_memory_candidate"

    filtered = skills.list_skill_records(limit=10, provider_hint="browseract")
    assert [row.skill_key for row in filtered] == ["research_decision_memo"]


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
    assert fetched_body["input_schema_json"]["properties"]["account_hints_json"]["type"] == "object"
    assert fetched_body["input_schema_json"]["properties"]["run_url"]["type"] == "string"
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

    compiled_via_skill = client.post(
        "/v1/plans/compile",
        json={"skill_key": "ltd_inventory_refresh", "goal": "refresh LTD inventory facts"},
    )
    assert compiled_via_skill.status_code == 200
    assert compiled_via_skill.json()["skill_key"] == "ltd_inventory_refresh"

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

    executed_via_skill = client.post(
        "/v1/plans/execute",
        json={
            "skill_key": "ltd_inventory_refresh",
            "goal": "refresh LTD inventory facts",
            "input_json": {
                "binding_id": binding_id,
                "service_names": ["BrowserAct", "Teable", "UnknownService"],
                "requested_fields": ["tier", "account_email", "status"],
            },
        },
    )
    assert executed_via_skill.status_code == 200
    assert executed_via_skill.json()["skill_key"] == "ltd_inventory_refresh"
    assert executed_via_skill.json()["task_key"] == "ltd_inventory_refresh"

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


def test_skill_catalog_can_execute_chummer6_visual_director_skill(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "response": json.dumps(
                        {
                            "packet": "guide_refresh",
                            "scene": "Rain-slick street runner with a troll union sticker on the signal box.",
                            "flavor": "The dev promised one tiny cleanup. The city filed a weather warning.",
                        }
                    ),
                    "stats": {
                        "models": {
                            "gemini-2.5-flash": {
                                "tokens": {"input": 111, "candidates": 37}
                            }
                        }
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "app.services.tool_execution_gemini_vortex_adapter.subprocess.run",
        fake_run,
    )

    client = _client()

    created = client.post(
        "/v1/skills",
        json={
            "skill_key": "chummer6_visual_director",
            "task_key": "chummer6_guide_refresh",
            "name": "Chummer6 Visual Director",
            "description": "Planner-executed Chummer6 scene planning, style-epoch selection, scene-ledger guidance, and structured visual-direction skill for the public-facing guide.",
            "deliverable_type": "chummer6_guide_refresh_packet",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "workflow_template": "tool_then_artifact",
            "allowed_tools": ["provider.gemini_vortex.structured_generate", "artifact_repository"],
            "evidence_requirements": ["public_page_registry", "public_part_registry", "public_faq_registry", "public_status", "source_prompt"],
            "memory_write_policy": "reviewed_only",
            "memory_reads": ["entities", "relationships", "public_page_registry", "public_part_registry", "public_faq_registry", "public_status"],
            "memory_writes": ["chummer6_style_epoch", "chummer6_scene_ledger", "chummer6_visual_critic_fact"],
            "tags": ["chummer6", "guide", "visual-direction", "style-epoch", "scene-ledger"],
            "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
            "model_policy_json": {
                "provider": "gemini_vortex",
                "default_model": "gemini-2.5-flash",
                "output_mode": "json",
            },
            "provider_hints_json": {
                "primary": ["Gemini Vortex"],
                "research": ["BrowserAct"],
                "output": ["Gemini Vortex", "AI Magicx", "Prompting Systems", "BrowserAct"],
                "media": ["AI Magicx", "Prompting Systems", "BrowserAct"],
                "style": ["Gemini Vortex"],
            },
            "tool_policy_json": {"allowed_tools": ["provider.gemini_vortex.structured_generate", "artifact_repository"]},
            "human_policy_json": {"review_roles": ["guide_reviewer"]},
            "evaluation_cases_json": [{"case_key": "chummer6_guide_refresh_golden", "priority": "medium"}],
            "budget_policy_json": {
                "class": "low",
                "workflow_template": "tool_then_artifact",
                "pre_artifact_capability_key": "structured_generate",
                "artifact_failure_strategy": "retry",
                "artifact_max_attempts": 2,
                "artifact_retry_backoff_seconds": 1,
                "style_epoch_enabled": True,
                "variation_guard_enabled": True,
            },
        },
    )
    assert created.status_code == 200
    assert created.json()["skill_key"] == "chummer6_visual_director"
    assert created.json()["task_key"] == "chummer6_guide_refresh"
    assert created.json()["workflow_template"] == "tool_then_artifact"
    assert created.json()["provider_hints_json"]["primary"] == ["Gemini Vortex"]

    fetched = client.get("/v1/skills/chummer6_visual_director")
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["task_key"] == "chummer6_guide_refresh"
    assert fetched_body["model_policy_json"]["provider"] == "gemini_vortex"
    assert fetched_body["memory_writes"] == [
        "chummer6_style_epoch",
        "chummer6_scene_ledger",
        "chummer6_visual_critic_fact",
    ]

    compiled = client.post(
        "/v1/plans/compile",
        json={"skill_key": "chummer6_visual_director", "goal": "author a structured Chummer6 guide refresh packet"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["skill_key"] == "chummer6_visual_director"
    assert [step["step_key"] for step in compiled.json()["plan"]["steps"]] == [
        "step_input_prepare",
        "step_structured_generate",
        "step_artifact_save",
    ]

    executed = client.post(
        "/v1/plans/execute",
        json={
            "skill_key": "chummer6_visual_director",
            "goal": "author a structured Chummer6 guide refresh packet",
            "input_json": {"source_text": "Draft the next Chummer6 guide packet with JSON only."},
        },
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["skill_key"] == "chummer6_visual_director"
    assert body["task_key"] == "chummer6_guide_refresh"
    assert body["kind"] == "chummer6_guide_refresh_packet"
    assert body["structured_output_json"]["packet"] == "guide_refresh"
    assert "troll union sticker" in body["structured_output_json"]["scene"]

    session = client.get(f"/v1/rewrite/sessions/{body['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["intent_skill_key"] == "chummer6_visual_director"
    assert [row["tool_name"] for row in session_body["receipts"]] == [
        "provider.gemini_vortex.structured_generate",
        "artifact_repository",
    ]
    assert session_body["artifacts"][0]["skill_key"] == "chummer6_visual_director"
    assert session_body["artifacts"][0]["structured_output_json"]["packet"] == "guide_refresh"


def test_skill_catalog_can_execute_chummer6_public_writer_skill(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "response": json.dumps(
                        {
                            "packet": "guide_refresh",
                            "copy": "Players get the table-first version instead of the repo talking to itself.",
                            "flavor": "The doc finally stopped writing love letters to its own folder structure.",
                        }
                    ),
                    "stats": {
                        "models": {
                            "gemini-2.5-flash": {
                                "tokens": {"input": 101, "candidates": 29}
                            }
                        }
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "app.services.tool_execution_gemini_vortex_adapter.subprocess.run",
        fake_run,
    )

    client = _client()

    created = client.post(
        "/v1/skills",
        json={
            "skill_key": "chummer6_public_writer",
            "task_key": "chummer6_public_copy_refresh",
            "name": "Chummer6 Public Writer",
            "description": "Planner-executed public-writer lane for Chummer6 guide copy, audience translation, and reader-safe OODA framing.",
            "deliverable_type": "chummer6_guide_refresh_packet",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "workflow_template": "tool_then_artifact",
            "allowed_tools": ["provider.gemini_vortex.structured_generate", "artifact_repository"],
            "evidence_requirements": ["public_page_registry", "public_part_registry", "public_faq_registry", "public_status", "source_prompt"],
            "memory_write_policy": "reviewed_only",
            "memory_reads": ["entities", "relationships", "public_page_registry", "public_part_registry", "public_faq_registry", "public_status"],
            "memory_writes": ["chummer6_public_copy_fact"],
            "tags": ["chummer6", "guide", "public-writer", "audience", "copy"],
            "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
            "model_policy_json": {
                "provider": "gemini_vortex",
                "default_model": "gemini-2.5-flash",
                "output_mode": "json",
            },
            "provider_hints_json": {
                "primary": ["Gemini Vortex"],
                "research": ["BrowserAct"],
                "output": ["Gemini Vortex", "Prompting Systems"],
                "style": ["Gemini Vortex"],
            },
            "tool_policy_json": {"allowed_tools": ["provider.gemini_vortex.structured_generate", "artifact_repository"]},
            "human_policy_json": {"review_roles": ["guide_reviewer"]},
            "evaluation_cases_json": [{"case_key": "chummer6_guide_refresh_golden", "priority": "medium"}],
            "budget_policy_json": {
                "class": "low",
                "workflow_template": "tool_then_artifact",
                "pre_artifact_capability_key": "structured_generate",
                "artifact_failure_strategy": "retry",
                "artifact_max_attempts": 2,
                "artifact_retry_backoff_seconds": 1,
                "style_epoch_enabled": True,
                "variation_guard_enabled": True,
            },
        },
    )
    assert created.status_code == 200
    assert created.json()["skill_key"] == "chummer6_public_writer"
    assert created.json()["task_key"] == "chummer6_public_copy_refresh"
    assert created.json()["provider_hints_json"]["primary"] == ["Gemini Vortex"]

    fetched = client.get("/v1/skills/chummer6_public_writer")
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["task_key"] == "chummer6_public_copy_refresh"
    assert fetched_body["model_policy_json"]["provider"] == "gemini_vortex"
    assert fetched_body["memory_writes"] == ["chummer6_public_copy_fact"]

    compiled = client.post(
        "/v1/plans/compile",
        json={"skill_key": "chummer6_public_writer", "goal": "author reader-safe Chummer6 guide copy"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["skill_key"] == "chummer6_public_writer"
    assert [step["step_key"] for step in compiled.json()["plan"]["steps"]] == [
        "step_input_prepare",
        "step_structured_generate",
        "step_artifact_save",
    ]

    executed = client.post(
        "/v1/plans/execute",
        json={
            "skill_key": "chummer6_public_writer",
            "goal": "author reader-safe Chummer6 guide copy",
            "input_json": {"source_text": "Draft the next Chummer6 public-facing page bundle with JSON only."},
        },
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["skill_key"] == "chummer6_public_writer"
    assert body["task_key"] == "chummer6_public_copy_refresh"
    assert body["kind"] == "chummer6_guide_refresh_packet"
    assert body["structured_output_json"]["packet"] == "guide_refresh"
    assert "table-first" in body["structured_output_json"]["copy"]

    session = client.get(f"/v1/rewrite/sessions/{body['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["intent_skill_key"] == "chummer6_public_writer"
    assert [row["tool_name"] for row in session_body["receipts"]] == [
        "provider.gemini_vortex.structured_generate",
        "artifact_repository",
    ]
    assert session_body["artifacts"][0]["skill_key"] == "chummer6_public_writer"
    assert session_body["artifacts"][0]["structured_output_json"]["packet"] == "guide_refresh"


def test_chummer6_skill_catalog_keeps_writer_and_visual_director_distinct() -> None:
    client = _client()

    writer = client.post(
        "/v1/skills",
        json={
            "skill_key": "chummer6_public_writer",
            "task_key": "chummer6_public_copy_refresh",
            "name": "Chummer6 Public Writer",
            "description": "Planner-executed public-writer lane for Chummer6 guide copy, audience translation, and reader-safe OODA framing.",
            "deliverable_type": "chummer6_guide_refresh_packet",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "workflow_template": "tool_then_artifact",
            "allowed_tools": ["provider.gemini_vortex.structured_generate", "artifact_repository"],
            "evidence_requirements": ["public_page_registry", "public_part_registry", "public_faq_registry", "public_status", "source_prompt"],
            "memory_write_policy": "reviewed_only",
            "memory_reads": ["entities", "relationships", "public_page_registry", "public_part_registry", "public_faq_registry", "public_status"],
            "memory_writes": ["chummer6_public_copy_fact"],
            "tags": ["chummer6", "guide", "public-writer", "audience", "copy"],
            "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
            "model_policy_json": {"provider": "gemini_vortex", "default_model": "gemini-2.5-flash", "output_mode": "json"},
            "provider_hints_json": {"primary": ["Gemini Vortex"]},
            "tool_policy_json": {"allowed_tools": ["provider.gemini_vortex.structured_generate", "artifact_repository"]},
            "human_policy_json": {"review_roles": ["guide_reviewer"]},
            "evaluation_cases_json": [{"case_key": "chummer6_guide_refresh_golden", "priority": "medium"}],
            "budget_policy_json": {"class": "low", "workflow_template": "tool_then_artifact", "pre_artifact_capability_key": "structured_generate"},
        },
    )
    assert writer.status_code == 200

    director = client.post(
        "/v1/skills",
        json={
            "skill_key": "chummer6_visual_director",
            "task_key": "chummer6_guide_refresh",
            "name": "Chummer6 Visual Director",
            "description": "Planner-executed Chummer6 scene planning, style-epoch selection, scene-ledger guidance, and structured visual-direction skill for the public-facing guide.",
            "deliverable_type": "chummer6_guide_refresh_packet",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "workflow_template": "tool_then_artifact",
            "allowed_tools": ["provider.gemini_vortex.structured_generate", "artifact_repository"],
            "evidence_requirements": ["public_page_registry", "public_part_registry", "public_faq_registry", "public_status", "source_prompt"],
            "memory_write_policy": "reviewed_only",
            "memory_reads": ["entities", "relationships", "public_page_registry", "public_part_registry", "public_faq_registry", "public_status"],
            "memory_writes": ["chummer6_style_epoch", "chummer6_scene_ledger", "chummer6_visual_critic_fact"],
            "tags": ["chummer6", "guide", "visual-direction", "style-epoch", "scene-ledger"],
            "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
            "model_policy_json": {"provider": "gemini_vortex", "default_model": "gemini-2.5-flash", "output_mode": "json"},
            "provider_hints_json": {"primary": ["Gemini Vortex"]},
            "tool_policy_json": {"allowed_tools": ["provider.gemini_vortex.structured_generate", "artifact_repository"]},
            "human_policy_json": {"review_roles": ["guide_reviewer"]},
            "evaluation_cases_json": [{"case_key": "chummer6_guide_refresh_golden", "priority": "medium"}],
            "budget_policy_json": {"class": "low", "workflow_template": "tool_then_artifact", "pre_artifact_capability_key": "structured_generate"},
        },
    )
    assert director.status_code == 200

    writer_fetch = client.get("/v1/skills/chummer6_public_writer")
    director_fetch = client.get("/v1/skills/chummer6_visual_director")
    assert writer_fetch.status_code == 200
    assert director_fetch.status_code == 200
    assert writer_fetch.json()["task_key"] == "chummer6_public_copy_refresh"
    assert director_fetch.json()["task_key"] == "chummer6_guide_refresh"

    writer_plan = client.post(
        "/v1/plans/compile",
        json={"skill_key": "chummer6_public_writer", "goal": "author reader-safe Chummer6 guide copy"},
    )
    director_plan = client.post(
        "/v1/plans/compile",
        json={"skill_key": "chummer6_visual_director", "goal": "author scene-ledger-aware Chummer6 art direction"},
    )
    assert writer_plan.status_code == 200
    assert director_plan.status_code == 200
    assert writer_plan.json()["plan"]["task_key"] == "chummer6_public_copy_refresh"
    assert director_plan.json()["plan"]["task_key"] == "chummer6_guide_refresh"


def test_chummer6_guide_bootstrap_keeps_publish_schedule_off_auditor_skills() -> None:
    bootstrap = load_chummer_guide_bootstrap_module()
    payloads = {payload["skill_key"]: payload for payload in bootstrap.build_skill_payloads()}

    writer_budget = payloads["chummer6_public_writer"]["budget_policy_json"]
    director_budget = payloads["chummer6_visual_director"]["budget_policy_json"]
    assert writer_budget["publish_on_success"] is True
    assert director_budget["publish_on_success"] is True
    assert "refresh_schedule_utc" in writer_budget
    assert "refresh_schedule_utc" in director_budget

    for skill_key in (
        "chummer6_public_auditor",
        "chummer6_scene_auditor",
        "chummer6_visual_auditor",
        "chummer6_pack_auditor",
    ):
        budget = payloads[skill_key]["budget_policy_json"]
        assert "publish_on_success" not in budget
        assert "publish_repo" not in budget
        assert "publish_branch" not in budget
        assert "refresh_schedule_utc" not in budget


def test_chummer6_public_writer_declares_post_generation_audit_loop() -> None:
    bootstrap = load_chummer_guide_bootstrap_module()
    payloads = {payload["skill_key"]: payload for payload in bootstrap.build_skill_payloads()}

    audit_contract = payloads["chummer6_public_writer"]["budget_policy_json"]["post_generation_audit_json"]
    assert audit_contract["enabled"] is True
    assert audit_contract["auditor_skill_key"] == "chummer6_public_auditor"
    assert audit_contract["max_revision_attempts"] == 2
    assert audit_contract["feedback_fields"] == ["findings", "improvement_suggestions", "risky_scopes"]

    auditor = payloads["chummer6_public_auditor"]
    assert auditor["runtime_policy_json"]["audit_position"] == "post_generation_pre_publish"
    assert auditor["runtime_policy_json"]["send_rejected_copy_back_to_generator"] is True
    assert auditor["output_schema_json"]["properties"]["approval_state"]["enum"] == ["approved", "rejected"]
    assert "improvement_suggestions" in auditor["output_schema_json"]["required"]


def test_chummer6_visual_skill_bootstrap_reads_public_media_briefs_and_accepts_targeted_rerun_scope() -> None:
    bootstrap = load_chummer_guide_bootstrap_module()
    payloads = {payload["skill_key"]: payload for payload in bootstrap.build_skill_payloads()}

    for skill_key in (
        "chummer6_visual_director",
        "chummer6_scene_auditor",
        "chummer6_visual_auditor",
        "chummer6_pack_auditor",
    ):
        payload = payloads[skill_key]
        assert "public_media_briefs" in payload["memory_reads"]
        assert "public_media_briefs" in payload["evidence_requirements"]
        properties = payload["input_schema_json"]["properties"]
        assert "critical_asset_targets" in properties
        assert "asset_contract_overrides" in properties
        assert "rerun_scope" in properties
        assert "story_arc_required" in properties
        assert "runner_question_ladder" in properties
        assert "anticipatory_overlay_brief" in properties
        assert "flagship_visual_bar" in properties
        assert "overlay_second_pass_required" in properties
        assert "overlay_first_pass_input_required" in properties
        assert "overlay_vision_provider" in properties
        assert "overlay_vision_model" in properties

    assert "public_media_briefs" not in payloads["chummer6_public_writer"]["memory_reads"]


@pytest.mark.parametrize(
    ("skill_key", "task_key", "memory_fact_key"),
    [
        ("chummer6_public_auditor", "chummer6_public_copy_audit", "copy"),
        ("chummer6_scene_auditor", "chummer6_scene_plan_audit", "scene"),
        ("chummer6_visual_auditor", "chummer6_visual_audit", "visual"),
        ("chummer6_pack_auditor", "chummer6_pack_audit", "pack"),
    ],
)
def test_skill_catalog_can_execute_chummer6_auditor_skills(monkeypatch, skill_key: str, task_key: str, memory_fact_key: str) -> None:
    bootstrap = load_chummer_guide_bootstrap_module()
    payloads = {payload["skill_key"]: payload for payload in bootstrap.build_skill_payloads()}

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "response": json.dumps(
                        {
                            "packet": "guide_refresh",
                            memory_fact_key: f"{skill_key} keeps the pack reader-safe.",
                        }
                    ),
                    "stats": {
                        "models": {
                            "gemini-2.5-flash": {
                                "tokens": {"input": 88, "candidates": 21}
                            }
                        }
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "app.services.tool_execution_gemini_vortex_adapter.subprocess.run",
        fake_run,
    )

    client = _client()

    created = client.post("/v1/skills", json=payloads[skill_key])
    assert created.status_code == 200
    assert created.json()["skill_key"] == skill_key
    assert created.json()["task_key"] == task_key

    fetched = client.get(f"/v1/skills/{skill_key}")
    assert fetched.status_code == 200
    assert fetched.json()["task_key"] == task_key

    compiled = client.post(
        "/v1/plans/compile",
        json={"skill_key": skill_key, "goal": f"run {skill_key} against the Chummer6 guide packet"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["plan"]["task_key"] == task_key
    assert [step["step_key"] for step in compiled.json()["plan"]["steps"]] == [
        "step_input_prepare",
        "step_structured_generate",
        "step_artifact_save",
    ]

    executed = client.post(
        "/v1/plans/execute",
        json={
            "skill_key": skill_key,
            "goal": f"run {skill_key} against the Chummer6 guide packet",
            "input_json": {"source_text": "Audit the generated Chummer6 guide packet with JSON only."},
        },
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["skill_key"] == skill_key
    assert body["task_key"] == task_key
    assert body["structured_output_json"]["packet"] == "guide_refresh"
    assert memory_fact_key in body["structured_output_json"]


def test_skill_catalog_can_execute_browseract_bootstrap_manager_skill() -> None:
    client = _client()

    created = client.post(
        "/v1/skills",
        json={
            "skill_key": "browseract_bootstrap_manager",
            "task_key": "browseract_bootstrap_manager",
            "name": "BrowserAct Bootstrap Manager",
            "description": "Planner-executed BrowserAct workflow-spec builder for stage-0 BrowserAct template creation and architect packets.",
            "deliverable_type": "browseract_workflow_spec_packet",
            "default_risk_class": "medium",
            "default_approval_class": "none",
            "workflow_template": "tool_then_artifact",
            "allowed_tools": ["browseract.build_workflow_spec", "artifact_repository"],
            "evidence_requirements": ["target_domain_brief", "workflow_spec", "browseract_seed_state"],
            "memory_write_policy": "none",
            "memory_reads": ["entities", "relationships"],
            "memory_writes": [],
            "tags": ["browseract", "bootstrap", "workflow", "architect"],
            "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
            "provider_hints_json": {
                "primary": ["BrowserAct"],
                "notes": ["Stage-0 architect compiles prepared workflow specs into BrowserAct-ready packets."],
            },
            "tool_policy_json": {"allowed_tools": ["browseract.build_workflow_spec", "artifact_repository"]},
            "human_policy_json": {"review_roles": ["automation_architect"]},
            "evaluation_cases_json": [{"case_key": "browseract_bootstrap_manager_golden", "priority": "medium"}],
            "budget_policy_json": {
                "class": "medium",
                "workflow_template": "tool_then_artifact",
                "pre_artifact_capability_key": "workflow_spec_build",
                "browseract_failure_strategy": "retry",
                "browseract_max_attempts": 2,
                "browseract_retry_backoff_seconds": 1,
            },
        },
    )
    assert created.status_code == 200
    assert created.json()["skill_key"] == "browseract_bootstrap_manager"
    assert created.json()["task_key"] == "browseract_bootstrap_manager"

    fetched = client.get("/v1/skills/browseract_bootstrap_manager")
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["workflow_template"] == "tool_then_artifact"
    assert fetched_body["provider_hints_json"]["primary"] == ["BrowserAct"]

    compiled = client.post(
        "/v1/plans/compile",
        json={"skill_key": "browseract_bootstrap_manager", "goal": "build a BrowserAct workflow spec packet"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["skill_key"] == "browseract_bootstrap_manager"
    assert [step["step_key"] for step in compiled.json()["plan"]["steps"]] == [
        "step_input_prepare",
        "step_browseract_workflow_spec_build",
        "step_artifact_save",
    ]

    executed = client.post(
        "/v1/plans/execute",
        json={
            "skill_key": "browseract_bootstrap_manager",
            "goal": "build a BrowserAct workflow spec packet",
            "input_json": {
                "workflow_name": "Prompt Forge",
                "purpose": "Build a prepared BrowserAct workflow spec for prompt refinement.",
                "login_url": "https://browseract.example/login",
                "tool_url": "https://browseract.example/tools/prompting-systems",
            },
        },
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["skill_key"] == "browseract_bootstrap_manager"
    assert body["task_key"] == "browseract_bootstrap_manager"
    assert body["kind"] == "browseract_workflow_spec_packet"
    assert body["structured_output_json"]["workflow_name"] == "Prompt Forge"
    assert body["structured_output_json"]["meta"]["slug"] == "prompt_forge"

    session = client.get(f"/v1/rewrite/sessions/{body['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["intent_skill_key"] == "browseract_bootstrap_manager"
    assert [row["tool_name"] for row in session_body["receipts"]] == [
        "browseract.build_workflow_spec",
        "artifact_repository",
    ]
    assert session_body["artifacts"][0]["skill_key"] == "browseract_bootstrap_manager"


def test_skill_catalog_can_execute_create_property_tour_skill() -> None:
    client = _client()

    created = client.post(
        "/v1/skills",
        json={
            "skill_key": "create_property_tour",
            "task_key": "create_property_tour",
            "name": "Create Property Tour",
            "description": "Planner-executed Crezlo property tour builder for steerable real-estate walkthrough variants.",
            "deliverable_type": "property_tour_packet",
            "default_risk_class": "medium",
            "default_approval_class": "none",
            "workflow_template": "tool_then_artifact",
            "allowed_tools": ["browseract.crezlo_property_tour", "artifact_repository"],
            "evidence_requirements": ["property_listing", "tour_brief", "property_media"],
            "memory_write_policy": "none",
            "memory_reads": ["entities", "relationships"],
            "memory_writes": [],
            "tags": ["browseract", "crezlo", "property", "tour"],
            "input_schema_json": {
                "type": "object",
                "required": ["binding_id", "tour_title", "property_url"],
                "properties": {
                    "binding_id": {"type": "string"},
                    "workflow_id": {"type": "string"},
                    "run_url": {"type": "string"},
                    "tour_title": {"type": "string"},
                    "property_url": {"type": "string"},
                    "media_urls_json": {"type": "array", "items": {"type": "string"}},
                    "floorplan_urls_json": {"type": "array", "items": {"type": "string"}},
                    "property_facts_json": {"type": "object"},
                    "creative_brief": {"type": "string"},
                    "variant_key": {"type": "string"},
                    "language": {"type": "string"},
                    "theme_name": {"type": "string"},
                    "tour_style": {"type": "string"},
                    "audience": {"type": "string"},
                    "call_to_action": {"type": "string"},
                    "runtime_inputs_json": {"type": "object"},
                    "timeout_seconds": {"type": "integer"},
                    "login_email": {"type": "string"},
                    "login_password": {"type": "string"},
                },
            },
            "output_schema_json": {
                "type": "object",
                "required": ["deliverable_type"],
                "properties": {
                    "deliverable_type": {"const": "property_tour_packet"},
                    "tour_title": {"type": "string"},
                    "tour_status": {"type": "string"},
                    "share_url": {"type": ["string", "null"]},
                    "editor_url": {"type": ["string", "null"]},
                    "public_url": {"type": ["string", "null"]},
                    "hosted_url": {"type": ["string", "null"]},
                    "crezlo_public_url": {"type": ["string", "null"]},
                    "workflow_id": {"type": ["string", "null"]},
                    "task_id": {"type": ["string", "null"]},
                    "structured_output_json": {"type": "object"},
                },
            },
            "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
            "provider_hints_json": {
                "primary": ["BrowserAct"],
                "output": ["Crezlo"],
                "notes": ["Steerable property-tour workflow backed by a BrowserAct Crezlo template."],
            },
            "tool_policy_json": {"allowed_tools": ["browseract.crezlo_property_tour", "artifact_repository"]},
            "evaluation_cases_json": [{"case_key": "create_property_tour_golden", "priority": "medium"}],
            "budget_policy_json": {
                "class": "medium",
                "workflow_template": "tool_then_artifact",
                "pre_artifact_capability_key": "crezlo_property_tour",
                "browseract_failure_strategy": "retry",
                "browseract_max_attempts": 2,
                "browseract_retry_backoff_seconds": 1,
            },
        },
    )
    assert created.status_code == 200
    assert created.json()["skill_key"] == "create_property_tour"
    assert created.json()["task_key"] == "create_property_tour"

    binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "crezlo-workspace-1",
            "scope_json": {"scopes": ["browseract", "crezlo"]},
            "auth_metadata_json": {"crezlo_property_tour_workflow_id": "wf-crezlo-1"},
            "status": "enabled",
        },
    )
    assert binding.status_code == 200
    binding_id = binding.json()["binding_id"]

    container = client.app.state.container

    def _fake_crezlo_property_tour(**kwargs: object) -> dict[str, object]:
        requested_inputs = dict(kwargs.get("requested_inputs") or {})
        return {
            "task_id": "task-crezlo-skill-1",
            "status": "completed",
            "output": {
                "result": {
                    "tour_title": requested_inputs["tour_title"],
                    "tour_status": "published",
                    "share_url": "https://tours.crezlo.com/share/augarten-variant-b",
                    "editor_url": "https://tours.crezlo.com/admin/tours/augarten-variant-b",
                    "public_url": "https://ea-property-tours-20260320.crezlotours.com/tours/augarten-variant-b",
                }
            },
        }

    container.tool_execution._browseract_crezlo_property_tour = _fake_crezlo_property_tour

    compiled = client.post(
        "/v1/plans/compile",
        json={"skill_key": "create_property_tour", "goal": "create a steerable property tour"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["skill_key"] == "create_property_tour"
    assert [step["step_key"] for step in compiled.json()["plan"]["steps"]] == [
        "step_input_prepare",
        "step_browseract_crezlo_property_tour",
        "step_artifact_save",
    ]

    executed = client.post(
        "/v1/plans/execute",
        json={
            "skill_key": "create_property_tour",
            "goal": "create a steerable property tour",
            "input_json": {
                "binding_id": binding_id,
                "tour_title": "Augarten Variant B",
                "property_url": "https://www.willhaben.at/listing/augarten",
                "theme_name": "Editorial Bright",
                "creative_brief": "Lead with the loggia, natural light, and practical flow for young professionals.",
                "variant_key": "variant_b",
                "media_urls_json": [
                    "https://assets.example/augarten-photo-1.jpg",
                    "https://assets.example/augarten-photo-2.jpg",
                ],
                "floorplan_urls_json": ["https://assets.example/augarten-floorplan-1.jpg"],
            },
        },
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["skill_key"] == "create_property_tour"
    assert body["task_key"] == "create_property_tour"
    assert body["kind"] == "property_tour_packet"
    assert body["structured_output_json"]["tour_title"] == "Augarten Variant B"
    assert body["structured_output_json"]["share_url"] == "https://tours.crezlo.com/share/augarten-variant-b"

    session = client.get(f"/v1/rewrite/sessions/{body['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["intent_skill_key"] == "create_property_tour"
    assert [row["tool_name"] for row in session_body["receipts"]] == [
        "browseract.crezlo_property_tour",
        "artifact_repository",
    ]
    assert session_body["artifacts"][0]["skill_key"] == "create_property_tour"


def test_skill_catalog_can_execute_create_mootion_movie_skill() -> None:
    client = _client()

    created = client.post(
        "/v1/skills",
        json={
            "skill_key": "create_mootion_movie",
            "task_key": "create_mootion_movie",
            "name": "Create Mootion Movie",
            "description": "Steerable BrowserAct-backed Mootion movie generator for short clips and property teasers.",
            "deliverable_type": "mootion_movie_packet",
            "default_risk_class": "medium",
            "default_approval_class": "none",
            "workflow_template": "tool_then_artifact",
            "allowed_tools": ["browseract.mootion_movie", "artifact_repository"],
            "evidence_requirements": ["service_prompt", "ui_render_request", "browseract_template"],
            "memory_write_policy": "none",
            "memory_reads": ["entities", "relationships"],
            "memory_writes": [],
            "tags": ["browseract", "mootion", "video", "movie"],
            "input_schema_json": {
                "type": "object",
                "required": ["binding_id", "script_text"],
                "properties": {
                    "binding_id": {"type": "string"},
                    "workflow_id": {"type": "string"},
                    "run_url": {"type": "string"},
                    "runtime_inputs_json": {"type": "object"},
                    "timeout_seconds": {"type": "integer"},
                    "result_title": {"type": "string"},
                    "script_text": {"type": "string"},
                    "visual_style": {"type": "string"},
                    "aspect_ratio": {"type": "string"},
                    "title": {"type": "string"},
                },
            },
            "output_schema_json": {
                "type": "object",
                "required": ["deliverable_type"],
                "properties": {
                    "deliverable_type": {"const": "mootion_movie_packet"},
                    "service_key": {"type": "string"},
                    "result_title": {"type": "string"},
                    "render_status": {"type": "string"},
                    "asset_url": {"type": ["string", "null"]},
                    "public_url": {"type": ["string", "null"]},
                    "editor_url": {"type": ["string", "null"]},
                    "structured_output_json": {"type": "object"},
                },
            },
            "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
            "provider_hints_json": {
                "primary": ["BrowserAct"],
                "output": ["Mootion"],
            },
            "tool_policy_json": {"allowed_tools": ["browseract.mootion_movie", "artifact_repository"]},
            "evaluation_cases_json": [{"case_key": "create_mootion_movie_golden", "priority": "medium"}],
            "budget_policy_json": {
                "class": "medium",
                "workflow_template": "tool_then_artifact",
                "pre_artifact_capability_key": "mootion_movie",
                "browseract_failure_strategy": "retry",
                "browseract_max_attempts": 2,
                "browseract_retry_backoff_seconds": 1,
            },
        },
    )
    assert created.status_code == 200
    assert created.json()["skill_key"] == "create_mootion_movie"

    binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"scopes": ["browseract", "mootion"]},
            "auth_metadata_json": {"mootion_movie_workflow_id": "wf-mootion-1"},
            "status": "enabled",
        },
    )
    assert binding.status_code == 200
    binding_id = binding.json()["binding_id"]

    container = client.app.state.container

    def _fake_mootion_movie(**kwargs: object) -> dict[str, object]:
        requested_inputs = dict(kwargs.get("requested_inputs") or {})
        return {
            "task_id": "task-mootion-skill-1",
            "status": "completed",
            "output": {
                "result": {
                    "title": requested_inputs.get("title") or "Brigittenau Mood Reel",
                    "status": "rendered",
                    "video_url": "https://cdn.example/mootion/brigittenau-mood-reel.mp4",
                    "preview_url": "https://viewer.example/mootion/brigittenau-mood-reel",
                    "editor_url": "https://mootion.com/projects/brigittenau-mood-reel",
                }
            },
        }

    container.tool_execution._browseract_ui_service_callbacks["mootion_movie"] = _fake_mootion_movie

    compiled = client.post(
        "/v1/plans/compile",
        json={"skill_key": "create_mootion_movie", "goal": "create a property teaser movie"},
    )
    assert compiled.status_code == 200
    assert [step["step_key"] for step in compiled.json()["plan"]["steps"]] == [
        "step_input_prepare",
        "step_browseract_mootion_movie",
        "step_artifact_save",
    ]

    executed = client.post(
        "/v1/plans/execute",
        json={
            "skill_key": "create_mootion_movie",
            "goal": "create a property teaser movie",
            "input_json": {
                "binding_id": binding_id,
                "script_text": "Present the Augarten and Kahlenberg properties as a fast-paced comparison teaser.",
                "title": "Brigittenau Mood Reel",
                "visual_style": "cinematic_real_estate",
                "aspect_ratio": "16:9",
            },
        },
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["skill_key"] == "create_mootion_movie"
    assert body["kind"] == "mootion_movie_packet"
    assert body["structured_output_json"]["service_key"] == "mootion_movie"
    assert body["structured_output_json"]["asset_url"] == "https://cdn.example/mootion/brigittenau-mood-reel.mp4"

    session = client.get(f"/v1/rewrite/sessions/{body['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["intent_skill_key"] == "create_mootion_movie"
    assert [row["tool_name"] for row in session_body["receipts"]] == [
        "browseract.mootion_movie",
        "artifact_repository",
    ]
    assert session_body["artifacts"][0]["skill_key"] == "create_mootion_movie"


def test_skill_catalog_can_execute_browseract_bootstrap_manager_for_page_extract_templates() -> None:
    client = _client()

    created = client.post(
        "/v1/skills",
        json={
            "skill_key": "browseract_bootstrap_manager",
            "task_key": "browseract_bootstrap_manager",
            "name": "BrowserAct Bootstrap Manager",
            "description": "Planner-executed BrowserAct workflow-spec builder for stage-0 BrowserAct template creation and architect packets.",
            "deliverable_type": "browseract_workflow_spec_packet",
            "default_risk_class": "medium",
            "default_approval_class": "none",
            "workflow_template": "tool_then_artifact",
            "allowed_tools": ["browseract.build_workflow_spec", "artifact_repository"],
            "evidence_requirements": ["target_domain_brief", "workflow_spec", "browseract_seed_state"],
            "memory_write_policy": "none",
            "memory_reads": ["entities", "relationships"],
            "memory_writes": [],
            "tags": ["browseract", "bootstrap", "workflow", "architect"],
            "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
            "provider_hints_json": {"primary": ["BrowserAct"]},
            "tool_policy_json": {"allowed_tools": ["browseract.build_workflow_spec", "artifact_repository"]},
            "human_policy_json": {"review_roles": ["automation_architect"]},
            "evaluation_cases_json": [{"case_key": "browseract_bootstrap_manager_golden", "priority": "medium"}],
            "budget_policy_json": {
                "class": "medium",
                "workflow_template": "tool_then_artifact",
                "pre_artifact_capability_key": "workflow_spec_build",
                "browseract_failure_strategy": "retry",
                "browseract_max_attempts": 2,
                "browseract_retry_backoff_seconds": 1,
            },
        },
    )
    assert created.status_code == 200

    executed = client.post(
        "/v1/plans/execute",
        json={
            "skill_key": "browseract_bootstrap_manager",
            "goal": "build an article-reader workflow spec packet",
            "input_json": {
                "workflow_name": "NYTimes Reader",
                "purpose": "Open a logged-in New York Times article and extract the readable article body.",
                "login_url": "https://myaccount.nytimes.com/auth/login",
                "tool_url": "https://www.nytimes.com",
                "workflow_kind": "page_extract",
                "runtime_input_name": "article_url",
                "wait_selector": "article",
                "title_selector": "article h1",
                "result_selector": "article",
                "dismiss_selectors": ["button[aria-label='Close']"],
            },
        },
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["structured_output_json"]["meta"]["workflow_kind"] == "page_extract"
    assert body["structured_output_json"]["inputs"][0]["name"] == "article_url"
    assert body["structured_output_json"]["workflow_name"] == "NYTimes Reader"


def test_skill_catalog_can_execute_browseract_workflow_repair_manager_skill(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "response": json.dumps(
                        {
                            "diagnosis": "The workflow typed /text literally instead of using a runtime input binding.",
                            "repair_strategy": "Restore value_from_input and keep the extraction path short.",
                            "operator_checks": [
                                "Check that the input_text node references value_from_input text.",
                                "Check that the output still exposes humanized_text.",
                            ],
                            "workflow_spec": {
                                "workflow_name": "Undetectable Humanizer",
                                "description": "Repair the BrowserAct humanizer workflow after a literal input binding failure.",
                                "publish": True,
                                "mcp_ready": False,
                                "nodes": [
                                    {
                                        "id": "open_tool",
                                        "type": "visit_page",
                                        "config": {"url": "https://undetectable.ai/ai-humanizer"},
                                    },
                                    {
                                        "id": "input_text",
                                        "type": "input_text",
                                        "config": {
                                            "selector": "textarea[aria-label='Input text']",
                                            "value_from_input": "text",
                                        },
                                    },
                                ],
                                "edges": [["open_tool", "input_text"]],
                                "meta": {"slug": "undetectable_humanizer_live"},
                            },
                        }
                    ),
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "app.services.tool_execution_browseract_adapter.subprocess.run",
        fake_run,
    )

    client = _client()

    created = client.post(
        "/v1/skills",
        json={
            "skill_key": "browseract_workflow_repair_manager",
            "task_key": "browseract_workflow_repair_manager",
            "name": "BrowserAct Workflow Repair Manager",
            "description": "Repair BrowserAct workflow specs after runtime failures.",
            "deliverable_type": "browseract_workflow_repair_packet",
            "default_risk_class": "medium",
            "default_approval_class": "none",
            "workflow_template": "tool_then_artifact",
            "allowed_tools": ["browseract.repair_workflow_spec", "artifact_repository"],
            "evidence_requirements": ["workflow_runtime_failure", "workflow_spec"],
            "memory_write_policy": "none",
            "memory_reads": ["entities", "relationships"],
            "memory_writes": [],
            "tags": ["browseract", "repair", "workflow"],
            "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
            "provider_hints_json": {
                "primary": ["BrowserAct", "Gemini Vortex"],
                "notes": ["Repair a failing BrowserAct workflow without handing it to Codex."],
            },
            "tool_policy_json": {"allowed_tools": ["browseract.repair_workflow_spec", "artifact_repository"]},
            "human_policy_json": {"review_roles": ["automation_architect"]},
            "evaluation_cases_json": [{"case_key": "browseract_workflow_repair_manager_golden", "priority": "medium"}],
            "budget_policy_json": {
                "class": "medium",
                "workflow_template": "tool_then_artifact",
                "pre_artifact_capability_key": "workflow_spec_repair",
                "browseract_failure_strategy": "retry",
                "browseract_max_attempts": 2,
                "browseract_retry_backoff_seconds": 1,
            },
        },
    )
    assert created.status_code == 200
    assert created.json()["skill_key"] == "browseract_workflow_repair_manager"

    compiled = client.post(
        "/v1/plans/compile",
        json={"skill_key": "browseract_workflow_repair_manager", "goal": "repair a broken BrowserAct workflow"},
    )
    assert compiled.status_code == 200
    assert [step["step_key"] for step in compiled.json()["plan"]["steps"]] == [
        "step_input_prepare",
        "step_browseract_workflow_spec_repair",
        "step_artifact_save",
    ]

    executed = client.post(
        "/v1/plans/execute",
        json={
            "skill_key": "browseract_workflow_repair_manager",
            "goal": "repair a broken BrowserAct workflow",
            "input_json": {
                "workflow_name": "Undetectable Humanizer",
                "purpose": "Repair the BrowserAct humanizer workflow after a literal input binding failure.",
                "tool_url": "https://undetectable.ai/ai-humanizer",
                "failure_summary": "browseract:literal_input_binding:/text",
                "failing_step_goals": ['Input "/text" into the main textarea'],
                "current_workflow_spec_json": {
                    "workflow_name": "Undetectable Humanizer",
                    "nodes": [{"id": "input_text", "type": "input_text", "config": {"value": "/text"}}],
                    "edges": [["open_tool", "input_text"]],
                },
            },
        },
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["skill_key"] == "browseract_workflow_repair_manager"
    assert body["task_key"] == "browseract_workflow_repair_manager"
    assert body["kind"] == "browseract_workflow_repair_packet"
    assert body["structured_output_json"]["workflow_spec"]["meta"]["repair_source"] == "gemini_vortex"

    session = client.get(f"/v1/rewrite/sessions/{body['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["intent_skill_key"] == "browseract_workflow_repair_manager"
    assert [row["tool_name"] for row in session_body["receipts"]] == [
        "browseract.repair_workflow_spec",
        "artifact_repository",
    ]
