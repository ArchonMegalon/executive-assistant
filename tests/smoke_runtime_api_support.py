from __future__ import annotations

import os

from fastapi.testclient import TestClient


def _seed_operator_profiles(client: TestClient) -> None:
    seed_profiles = (
        {
            "operator_id": "operator-sorter",
            "display_name": "Queue Sorter",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone", "accuracy"],
            "trust_tier": "standard",
            "status": "active",
        },
        {
            "operator_id": "operator-priority-summary",
            "display_name": "Priority Summary Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone", "accuracy"],
            "trust_tier": "standard",
            "status": "active",
        },
        {
            "operator_id": "operator-auto-summary",
            "display_name": "Auto Summary Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone", "accuracy"],
            "trust_tier": "standard",
            "status": "active",
        },
        {
            "operator_id": "operator-manual-summary",
            "display_name": "Manual Summary Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone", "accuracy"],
            "trust_tier": "standard",
            "status": "active",
        },
        {
            "operator_id": "briefing-reviewer",
            "display_name": "Briefing Reviewer",
            "roles": ["briefing_reviewer"],
            "skill_tags": ["tone", "accuracy", "stakeholder_sensitivity"],
            "trust_tier": "senior",
            "status": "active",
        },
        {
            "operator_id": "reviewer-1",
            "display_name": "Reviewer One",
            "roles": ["communications_reviewer", "briefing_reviewer"],
            "skill_tags": ["tone", "accuracy"],
            "trust_tier": "standard",
            "status": "active",
        },
    )
    for payload in seed_profiles:
        response = client.post("/v1/human/tasks/operators", json=payload)
        if response.status_code not in {200, 409}:
            raise RuntimeError(f"failed_to_seed_operator_profile:{payload['operator_id']}:{response.status_code}")


def build_client(
    *,
    storage_backend: str = "memory",
    auth_token: str = "",
    database_url: str = "",
    approval_threshold_chars: int | None = None,
    principal_id: str = "exec-1",
    operator: bool = False,
    authenticated: bool = True,
) -> TestClient:
    effective_auth_token = auth_token or "smoke-token"
    os.environ["EA_STORAGE_BACKEND"] = storage_backend
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = effective_auth_token
    os.environ.pop("EA_ALLOW_LOOPBACK_NO_AUTH", None)
    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    if operator and principal_id:
        os.environ["EA_OPERATOR_PRINCIPAL_IDS"] = principal_id
    else:
        os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    if approval_threshold_chars is None:
        os.environ.pop("EA_APPROVAL_THRESHOLD_CHARS", None)
    else:
        os.environ["EA_APPROVAL_THRESHOLD_CHARS"] = str(approval_threshold_chars)
    if database_url:
        os.environ["DATABASE_URL"] = database_url
    else:
        os.environ.pop("DATABASE_URL", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    if authenticated:
        client.headers.update({"Authorization": f"Bearer {effective_auth_token}"})
    if principal_id:
        client.headers.update({"X-EA-Principal-ID": principal_id})
    if operator:
        _seed_operator_profiles(client)
    return client


def build_headers(token: str = "", principal_id: str = "") -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if principal_id:
        headers["X-EA-Principal-ID"] = principal_id
    return headers
