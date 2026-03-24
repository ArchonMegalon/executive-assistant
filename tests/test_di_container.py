from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import container as app_container
from app.domain.models import Artifact, RewriteRequest
from app.services.policy import PolicyDeniedError


@dataclass(frozen=True)
class _Auth:
    api_token: str = ""
    default_principal_id: str = "local-user"


@dataclass(frozen=True)
class _Runtime:
    mode: str = "dev"


@dataclass(frozen=True)
class _Settings:
    auth: _Auth = _Auth()
    runtime: _Runtime = _Runtime()


class _FakeOrchestrator:
    def build_artifact(self, req: RewriteRequest) -> Artifact:
        principal_id = str(req.principal_id or "").strip() or "local-user"
        return Artifact(
            artifact_id="artifact-fake",
            kind="rewrite_note",
            content="fake-content",
            execution_session_id="session-fake",
            principal_id=principal_id,
        )

    def fetch_session(self, session_id: str):
        return None

    def list_policy_decisions(self, limit: int = 50, session_id: str | None = None):
        return []


class _FakeDeniedOrchestrator:
    def build_artifact(self, req: RewriteRequest) -> Artifact:
        raise PolicyDeniedError("tool_not_allowed")

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


class _FakeToolExecution:
    def execute_invocation(self, request):
        raise AssertionError("not expected in this test")


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

    def get_item(self, item_id: str, **_: object):
        return None

    def upsert_entity(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_entities(self, **_: object):
        return []

    def get_entity(self, entity_id: str, **_: object):
        return None

    def upsert_relationship(self, **_: object):
        raise AssertionError("not expected in this test")

    def list_relationships(self, **_: object):
        return []

    def get_relationship(self, relationship_id: str, **_: object):
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
        self.tool_execution = _FakeToolExecution()
        self.memory_runtime = _FakeMemoryRuntime()
        self.task_contracts = _FakeTaskContracts()
        self.planner = _FakePlanner()
        self.readiness = _FakeReadiness()


class _ProdContainer(_FakeContainer):
    def __init__(self) -> None:
        super().__init__()
        self.settings = _Settings(auth=_Auth(api_token="secret-token"), runtime=_Runtime(mode="prod"))


class _ProdContainerCaseInsensitive(_FakeContainer):
    def __init__(self) -> None:
        super().__init__()
        self.settings = _Settings(auth=_Auth(api_token="secret-token"), runtime=_Runtime(mode="PROD"))


class _FakeDeniedContainer(_FakeContainer):
    def __init__(self) -> None:
        super().__init__()
        self.orchestrator = _FakeDeniedOrchestrator()


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


def test_non_prod_mode_allows_default_principal_fallback() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_API_TOKEN"] = ""
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "ops-fallback"
    from app.api.app import create_app

    app = create_app()
    app.state.container = _FakeContainer()
    app.state.container.settings = _Settings(auth=_Auth(default_principal_id="ops-fallback"))
    client = TestClient(app)

    response = client.post(
        "/v1/rewrite/artifact",
        json={"text": "fallback-principal"},
    )
    assert response.status_code == 200
    assert response.json()["principal_id"] == "ops-fallback"


def test_non_prod_mode_allows_default_principal_fallback_on_rewrite_route() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_API_TOKEN"] = ""
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "rewrite-fallback"
    from app.api.app import create_app

    app = create_app()
    app.state.container = _FakeContainer()
    app.state.container.settings = _Settings(auth=_Auth(default_principal_id="rewrite-fallback"))
    client = TestClient(app)

    response = client.post(
        "/v1/rewrite/artifact",
        json={"text": "rewrite-fallback"},
    )
    assert response.status_code == 200
    assert response.json()["principal_id"] == "rewrite-fallback"


def test_non_prod_mode_allows_principal_header_without_authentication() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_API_TOKEN"] = ""
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "ops-fallback"
    from app.api.app import create_app

    app = create_app()
    app.state.container = _FakeContainer()
    app.state.container.settings = _Settings(auth=_Auth(default_principal_id="ops-fallback"))
    client = TestClient(app)

    response = client.post(
        "/v1/rewrite/artifact",
        json={"text": "header-override-attempt"},
        headers={"x-ea-principal-id": "spoofed-user"},
    )

    assert response.status_code == 200
    assert response.json()["principal_id"] == "spoofed-user"


def test_prod_mode_rejects_missing_configured_api_token_at_request() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_API_TOKEN"] = "secret-token"
    from app.api.app import create_app

    app = create_app()
    app.state.container = _FakeContainer()
    app.state.container.settings = _Settings(
        auth=_Auth(api_token=""),
        runtime=_Runtime(mode="prod"),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/memory/candidates",
        json={
            "category": "stakeholder_pref",
            "summary": "Missing token should fail in prod",
            "fact_json": {"source": "container-route"},
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


def test_prod_mode_rejects_blank_api_token_startup() -> None:
    saved_env = {
        "EA_RUNTIME_MODE": os.environ.get("EA_RUNTIME_MODE"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_LEDGER_BACKEND": os.environ.get("EA_LEDGER_BACKEND"),
    }
    try:
        os.environ["EA_RUNTIME_MODE"] = "prod"
        os.environ["EA_API_TOKEN"] = "  \t"
        os.environ["EA_STORAGE_BACKEND"] = "postgres"
        os.environ.pop("EA_LEDGER_BACKEND", None)

        from app.api.app import create_app

        with pytest.raises(RuntimeError, match="EA_RUNTIME_MODE=prod requires EA_API_TOKEN"):
            create_app()
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_prod_mode_rejects_default_principal_fallback() -> None:
    saved_env = {
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_DEFAULT_PRINCIPAL_ID": os.environ.get("EA_DEFAULT_PRINCIPAL_ID"),
        "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER": os.environ.get("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"),
        "EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER": os.environ.get("EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER"),
        "EA_TRUST_API_TOKEN_PRINCIPAL_HEADER": os.environ.get("EA_TRUST_API_TOKEN_PRINCIPAL_HEADER"),
    }
    try:
        os.environ["EA_STORAGE_BACKEND"] = "memory"
        os.environ["EA_API_TOKEN"] = "secret-token"
        os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
        os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
        os.environ.pop("EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER", None)
        os.environ.pop("EA_TRUST_API_TOKEN_PRINCIPAL_HEADER", None)
        from app.api.app import create_app

        app = create_app()
        app.state.container = _ProdContainer()
        client = TestClient(app)

        response = client.post(
            "/v1/memory/candidates",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "category": "stakeholder_pref",
                "summary": "Principal fallback blocked in prod",
                "fact_json": {"source": "container-route"},
            },
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "principal_required"
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_prod_mode_rejects_default_principal_fallback_on_rewrite_route() -> None:
    saved_env = {
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_DEFAULT_PRINCIPAL_ID": os.environ.get("EA_DEFAULT_PRINCIPAL_ID"),
        "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER": os.environ.get("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"),
        "EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER": os.environ.get("EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER"),
        "EA_TRUST_API_TOKEN_PRINCIPAL_HEADER": os.environ.get("EA_TRUST_API_TOKEN_PRINCIPAL_HEADER"),
    }
    try:
        os.environ["EA_STORAGE_BACKEND"] = "memory"
        os.environ["EA_API_TOKEN"] = "secret-token"
        os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
        os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
        os.environ.pop("EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER", None)
        os.environ.pop("EA_TRUST_API_TOKEN_PRINCIPAL_HEADER", None)
        from app.api.app import create_app

        app = create_app()
        app.state.container = _ProdContainer()
        client = TestClient(app)

        response = client.post(
            "/v1/rewrite/artifact",
            headers={"Authorization": "Bearer secret-token"},
            json={"text": "rewrite-principal-required"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "principal_required"
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_prod_mode_with_empty_token_rejects_auth_dependency() -> None:
    from app.api.dependencies import require_request_auth

    probe = FastAPI()
    probe_container = _FakeContainer()
    probe_container.settings = _Settings(auth=_Auth(api_token=""), runtime=_Runtime(mode="prod"))
    probe.state.container = probe_container

    @probe.get("/probe", dependencies=[Depends(require_request_auth)])
    def probe_route() -> dict[str, str]:
        return {"ok": "yes"}

    client = TestClient(probe)
    response = client.get("/probe", headers={"Authorization": "Bearer any-token"})
    assert response.status_code == 401


def test_prod_mode_case_insensitive_value_rejects_default_principal_fallback() -> None:
    saved_env = {
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_DEFAULT_PRINCIPAL_ID": os.environ.get("EA_DEFAULT_PRINCIPAL_ID"),
        "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER": os.environ.get("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"),
        "EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER": os.environ.get("EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER"),
        "EA_TRUST_API_TOKEN_PRINCIPAL_HEADER": os.environ.get("EA_TRUST_API_TOKEN_PRINCIPAL_HEADER"),
    }
    try:
        os.environ["EA_STORAGE_BACKEND"] = "memory"
        os.environ["EA_API_TOKEN"] = "secret-token"
        os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
        os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
        os.environ.pop("EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER", None)
        os.environ.pop("EA_TRUST_API_TOKEN_PRINCIPAL_HEADER", None)
        from app.api.app import create_app

        app = create_app()
        app.state.container = _ProdContainerCaseInsensitive()
        client = TestClient(app)

        response = client.post(
            "/v1/memory/candidates",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "category": "stakeholder_pref",
                "summary": "Principal fallback blocked with case-variant prod mode",
                "fact_json": {"source": "container-route"},
            },
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "principal_required"
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_prod_mode_rejects_channel_runtime_fallback_during_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved_env = {
        "EA_RUNTIME_MODE": os.environ.get("EA_RUNTIME_MODE"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_LEDGER_BACKEND": os.environ.get("EA_LEDGER_BACKEND"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
    }

    class _FakeArtifactRepo:
        pass

    class _FakeTaskContracts:
        def list_contracts(self, limit: int = 100):
            return []

    try:
        os.environ["EA_RUNTIME_MODE"] = "PROD"
        os.environ["EA_API_TOKEN"] = "secret-token"
        os.environ["EA_STORAGE_BACKEND"] = "postgres"
        os.environ["EA_LEDGER_BACKEND"] = ""
        os.environ["DATABASE_URL"] = "postgresql://127.0.0.1:5432/ea"

        monkeypatch.setattr(app_container, "build_artifact_repo", lambda _settings: _FakeArtifactRepo())
        monkeypatch.setattr(app_container, "build_task_contract_service", lambda **kwargs: _FakeTaskContracts())
        monkeypatch.setattr(app_container, "build_provider_binding_service_repo", lambda _settings: None)
        def _raise_runtime_failure(*args, **kwargs) -> None:
            raise RuntimeError("forced failure")

        monkeypatch.setattr(app_container, "build_channel_runtime", _raise_runtime_failure)

        with pytest.raises(RuntimeError, match="EA_RUNTIME_MODE=prod forbids memory fallback\\(channel runtime bootstrap\\)"):
            app_container.build_container()
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_build_container_rejects_prod_mode_with_whitespace_api_token() -> None:
    settings = _Settings(auth=_Auth(api_token="  \t"), runtime=_Runtime(mode="prod"))
    with pytest.raises(RuntimeError, match="EA_RUNTIME_MODE=prod requires EA_API_TOKEN"):
        app_container.build_container(settings=settings)


def test_prod_mode_rejects_memory_runtime_fallback_during_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved_env = {
        "EA_RUNTIME_MODE": os.environ.get("EA_RUNTIME_MODE"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_LEDGER_BACKEND": os.environ.get("EA_LEDGER_BACKEND"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
    }

    class _FakeArtifactRepo:
        pass

    class _FakeTaskContracts:
        def list_contracts(self, limit: int = 100):
            return []

    class _FakeChannelRuntime:
        pass

    try:
        os.environ["EA_RUNTIME_MODE"] = "PROD"
        os.environ["EA_API_TOKEN"] = "secret-token"
        os.environ["EA_STORAGE_BACKEND"] = "postgres"
        os.environ["EA_LEDGER_BACKEND"] = ""
        os.environ["DATABASE_URL"] = "postgresql://127.0.0.1:5432/ea"

        monkeypatch.setattr(app_container, "build_artifact_repo", lambda _settings: _FakeArtifactRepo())
        monkeypatch.setattr(app_container, "build_task_contract_service", lambda **kwargs: _FakeTaskContracts())
        monkeypatch.setattr(app_container, "build_provider_binding_service_repo", lambda _settings: None)
        monkeypatch.setattr(app_container, "build_channel_runtime", lambda **kwargs: _FakeChannelRuntime())

        def _raise_runtime_failure(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("forced failure")

        monkeypatch.setattr(app_container, "build_memory_runtime", _raise_runtime_failure)

        with pytest.raises(RuntimeError, match="EA_RUNTIME_MODE=prod forbids memory fallback\\(memory runtime bootstrap\\)"):
            app_container.build_container()
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_build_container_auto_storage_falls_back_to_memory_profile_when_postgres_bootstrap_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved_env = {
        "EA_RUNTIME_MODE": os.environ.get("EA_RUNTIME_MODE"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_LEDGER_BACKEND": os.environ.get("EA_LEDGER_BACKEND"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
    }

    try:
        os.environ.pop("EA_RUNTIME_MODE", None)
        os.environ["EA_API_TOKEN"] = ""
        os.environ["EA_STORAGE_BACKEND"] = "auto"
        os.environ["EA_LEDGER_BACKEND"] = ""
        os.environ["DATABASE_URL"] = "postgresql://127.0.0.1:5432/ea"

        def _fake_build_container_for_settings(settings, profile):
            if settings.storage.backend == "postgres":
                raise RuntimeError("forced postgres bootstrap failure")
            return SimpleNamespace(settings=settings, runtime_profile=profile)

        monkeypatch.setattr(app_container, "_build_container_for_settings", _fake_build_container_for_settings)

        container = app_container.build_container()
        assert container.settings.storage.backend == "memory"
        assert container.runtime_profile.storage_backend == "memory"
        assert container.runtime_profile.source_backend == "memory"
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_rewrite_route_maps_tool_not_allowed_policy_denial() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_API_TOKEN"] = ""
    from app.api.app import create_app

    app = create_app()
    app.state.container = _FakeDeniedContainer()
    client = TestClient(app)

    resp = client.post("/v1/rewrite/artifact", json={"text": "from-fake"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "policy_denied:tool_not_allowed"
