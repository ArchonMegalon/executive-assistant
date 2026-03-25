from __future__ import annotations

from tests.product_test_helpers import build_operator_product_client, build_product_client


def test_personal_plan_blocks_browser_messaging_setup_routes() -> None:
    client = build_product_client(principal_id="unused-browser-header")
    container = client.app.state.container
    container.onboarding.start_workspace(
        principal_id="local-user",
        workspace_name="Pilot Workspace",
        workspace_mode="personal",
        region="AT",
        language="en",
        timezone="Europe/Vienna",
        selected_channels=("google",),
    )

    telegram = client.post("/setup/telegram", data={"telegram_ref": "@ops"}, follow_redirects=False)
    assert telegram.status_code == 303
    assert telegram.headers["location"] == "/pricing"

    whatsapp = client.post(
        "/setup/whatsapp/business",
        data={"phone_number": "+43123456", "business_name": "Acme"},
        follow_redirects=False,
    )
    assert whatsapp.status_code == 303
    assert whatsapp.headers["location"] == "/pricing"


def test_operator_seat_limit_is_enforced_by_workspace_plan() -> None:
    principal_id = "exec-operator-plan"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    container = client.app.state.container
    container.onboarding.start_workspace(
        principal_id=principal_id,
        workspace_name="Pilot Workspace",
        workspace_mode="personal",
        region="AT",
        language="en",
        timezone="Europe/Vienna",
        selected_channels=("google",),
    )

    first = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-office",
            "display_name": "Office Operator",
            "roles": ["operator"],
            "trust_tier": "trusted",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-two",
            "display_name": "Second Operator",
            "roles": ["operator"],
            "trust_tier": "trusted",
        },
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "operator_seat_limit_reached"
