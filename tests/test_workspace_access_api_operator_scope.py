from __future__ import annotations

from tests.product_test_helpers import build_product_client, start_workspace


def test_workspace_access_api_upgrades_principal_session_when_only_specialized_profiles_exist() -> None:
    principal_id = "exec-workspace-access-api-operator"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal")

    container = client.app.state.container
    container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id="briefing-reviewer",
        display_name="Briefing Reviewer",
        roles=("briefing_reviewer",),
        trust_tier="standard",
        status="active",
        notes="Specialized reviewer profile should not block owner operator access.",
    )

    access_session = client.post(
        "/app/api/workspace-access",
        json={
            "email": "tibor.girschele@gmail.com",
            "role": "principal",
            "display_name": "Tibor Girschele",
        },
    )

    assert access_session.status_code == 200
    access_body = access_session.json()
    assert access_body["role"] == "operator"
    assert access_body["operator_id"] == "operator-tibor-girschele"

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_body["access_url"], follow_redirects=False)

    assert opened_access.status_code == 303
    assert opened_access.headers["location"] == "/admin/office"
    assert "ea_workspace_session=" in str(opened_access.headers.get("set-cookie") or "")

    operator_only = client.get("/v1/skills")

    assert operator_only.status_code == 200
