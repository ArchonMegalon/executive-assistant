from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.errors import install_error_handlers


def test_operator_scope_denial_logs_correlation_and_request_context(caplog) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/scope-denied")
    def scope_denied(request: Request) -> dict[str, object]:
        request.state.ea_request_context = SimpleNamespace(
            principal_id="principal-test",
            operator_id="",
            operator_authorized=False,
            auth_source="api_token",
        )
        raise HTTPException(status_code=403, detail="operator_scope_required")

    client = TestClient(app)
    with caplog.at_level("WARNING"):
        response = client.get(
            "/scope-denied",
            headers={
                "x-correlation-id": "corr-test-operator-scope",
                "user-agent": "pytest-agent",
            },
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "operator_scope_required"
    assert any(
        "request_scope_denied correlation_id=corr-test-operator-scope code=operator_scope_required" in record.message
        and "path=/scope-denied" in record.message
        and "principal_id=principal-test" in record.message
        and "auth_source=api_token" in record.message
        for record in caplog.records
    )


def test_operator_scope_denial_browser_get_redirects_to_operator_bootstrap() -> None:
    app = FastAPI()
    app.state.container = SimpleNamespace(
        orchestrator=SimpleNamespace(list_operator_profiles=lambda **_kwargs: []),
    )
    install_error_handlers(app)

    @app.get("/admin/actions/signal-to-decision-evidence")
    def scope_denied(request: Request) -> dict[str, object]:
        request.state.ea_request_context = SimpleNamespace(
            principal_id="principal-test",
            operator_id="",
            operator_authorized=False,
            authenticated=True,
            auth_source="workspace_session",
        )
        raise HTTPException(status_code=403, detail="operator_scope_required")

    client = TestClient(app)
    response = client.get(
        "/admin/actions/signal-to-decision-evidence?return_to=%2Fadmin%2Fgoals&evidence_part=review",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (
        response.headers["location"]
        == "/admin/bootstrap-operator?return_to=%2Fadmin%2Factions%2Fsignal-to-decision-evidence%3Freturn_to%3D%252Fadmin%252Fgoals%26evidence_part%3Dreview"
    )
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive, nosnippet"


def test_operator_scope_denial_api_request_stays_json_error() -> None:
    app = FastAPI()
    app.state.container = SimpleNamespace(
        orchestrator=SimpleNamespace(list_operator_profiles=lambda **_kwargs: []),
    )
    install_error_handlers(app)

    @app.get("/admin/actions/signal-to-decision-evidence")
    def scope_denied(request: Request) -> dict[str, object]:
        request.state.ea_request_context = SimpleNamespace(
            principal_id="principal-test",
            operator_id="",
            operator_authorized=False,
            authenticated=True,
            auth_source="api_token",
        )
        raise HTTPException(status_code=403, detail="operator_scope_required")

    client = TestClient(app)
    response = client.get(
        "/admin/actions/signal-to-decision-evidence?return_to=%2Fadmin%2Fgoals&evidence_part=review",
        headers={"accept": "application/json"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "operator_scope_required"
