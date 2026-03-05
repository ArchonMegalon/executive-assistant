from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.domain.models import Artifact, RewriteRequest


@dataclass(frozen=True)
class _Auth:
    api_token: str = ""


@dataclass(frozen=True)
class _Settings:
    auth: _Auth = _Auth()


class _FakeOrchestrator:
    def build_artifact(self, req: RewriteRequest) -> Artifact:
        assert req.text == "from-fake"
        return Artifact(
            artifact_id="artifact-fake",
            kind="rewrite_note",
            content="fake-content",
            execution_session_id="session-fake",
        )

    def fetch_session(self, session_id: str):
        return None

    def list_policy_decisions(self, limit: int = 50, session_id: str | None = None):
        return []


class _FakeRuntime:
    def ingest_observation(
        self,
        principal_id: str,
        channel: str,
        event_type: str,
        payload: dict | None = None,
        **_: object,
    ):
        raise AssertionError("not expected in this test")

    def list_recent_observations(self, limit: int = 50):
        return []

    def queue_delivery(
        self,
        channel: str,
        recipient: str,
        content: str,
        metadata: dict | None = None,
        **_: object,
    ):
        raise AssertionError("not expected in this test")

    def mark_delivery_sent(self, delivery_id: str, **_: object):
        return None

    def mark_delivery_failed(self, delivery_id: str, *, error: str, next_attempt_at: str | None = None, dead_letter: bool = False):
        return None

    def list_pending_delivery(self, limit: int = 50):
        return []


class _FakeReadiness:
    def check(self) -> tuple[bool, str]:
        return True, "fake-ready"


class _FakeToolRuntime:
    def list_enabled_tools(self, limit: int = 100):
        return []


class _FakeMemoryRuntime:
    def stage_candidate(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_candidates(self, **_: object):
        return []

    def promote_candidate(self, candidate_id: str, **_: object):
        return None

    def reject_candidate(self, candidate_id: str, **_: object):
        return None

    def list_items(self, **_: object):
        return []

    def get_item(self, item_id: str):
        return None

    def upsert_entity(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_entities(self, **_: object):
        return []

    def get_entity(self, entity_id: str):
        return None

    def upsert_relationship(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_relationships(self, **_: object):
        return []

    def get_relationship(self, relationship_id: str):
        return None

    def upsert_commitment(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_commitments(self, **_: object):
        return []

    def get_commitment(self, commitment_id: str, **_: object):
        return None

    def upsert_deadline_window(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_deadline_windows(self, **_: object):
        return []

    def get_deadline_window(self, window_id: str, **_: object):
        return None

    def upsert_stakeholder(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_stakeholders(self, **_: object):
        return []

    def get_stakeholder(self, stakeholder_id: str, **_: object):
        return None

    def upsert_decision_window(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_decision_windows(self, **_: object):
        return []

    def get_decision_window(self, decision_window_id: str, **_: object):
        return None

    def upsert_communication_policy(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_communication_policies(self, **_: object):
        return []

    def get_communication_policy(self, policy_id: str, **_: object):
        return None

    def upsert_follow_up_rule(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_follow_up_rules(self, **_: object):
        return []

    def get_follow_up_rule(self, rule_id: str, **_: object):
        return None

    def upsert_interruption_budget(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_interruption_budgets(self, **_: object):
        return []

    def get_interruption_budget(self, budget_id: str, **_: object):
        return None

    def upsert_authority_binding(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_authority_bindings(self, **_: object):
        return []

    def get_authority_binding(self, binding_id: str, **_: object):
        return None

    def upsert_delivery_preference(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_delivery_preferences(self, **_: object):
        return []

    def get_delivery_preference(self, preference_id: str, **_: object):
        return None

    def upsert_follow_up(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_follow_ups(self, **_: object):
        return []

    def get_follow_up(self, follow_up_id: str, **_: object):
        return None


class _FakeTaskContracts:
    def list_contracts(self, limit: int = 100):
        return []


class _FakePlanner:
    def build_plan(self, *, task_key: str, principal_id: str, goal: str):
        return None


class _FakeContainer:
    def __init__(self) -> None:
        self.settings = _Settings()
        self.orchestrator = _FakeOrchestrator()
        self.channel_runtime = _FakeRuntime()
        self.tool_runtime = _FakeToolRuntime()
        self.memory_runtime = _FakeMemoryRuntime()
        self.task_contracts = _FakeTaskContracts()
        self.planner = _FakePlanner()
        self.readiness = _FakeReadiness()


def test_routes_use_app_state_container_dependency() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_API_TOKEN"] = ""
    from app.api.app import create_app

    app = create_app()
    app.state.container = _FakeContainer()
    client = TestClient(app)

    resp = client.post("/v1/rewrite/artifact", json={"text": "from-fake"})
    assert resp.status_code == 200
    assert resp.json()["artifact_id"] == "artifact-fake"
    assert resp.json()["content"] == "fake-content"
