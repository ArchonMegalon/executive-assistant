from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.services.google_oauth import build_google_oauth_start, read_google_oauth_state_unchecked
from app.api.routes.landing_setup import _google_oauth_denial_detail


def test_google_oauth_access_denied_names_expected_test_user_blocker() -> None:
    detail = _google_oauth_denial_detail(
        error="access_denied",
        state_payload={
            "expected_google_email": "work.owner@example.test",
            "oauth_client_project_id": "propertyquarry-498318",
            "oauth_client_project_number": "95627800296",
        },
    )

    assert "work.owner@example.test" in detail
    assert "OAuth test user" in detail
    assert "Full Workspace link" in detail
    assert "propertyquarry-498318" in detail
    assert "95627800296" in detail
    assert "Google Auth Platform > Audience > Test users" in detail
    assert "select that same account" in detail
    assert "already listed" in detail
    assert "OAuth project/client shown here" in detail


def test_google_location_history_access_denied_keeps_portability_detail() -> None:
    detail = _google_oauth_denial_detail(
        error="access_denied",
        state_payload={"oauth_lane": "google_location_history"},
    )

    assert "Data Portability consent" in detail
    assert "OAuth test user" in detail


def test_google_oauth_non_access_denied_preserves_google_description() -> None:
    detail = _google_oauth_denial_detail(
        error="temporarily_unavailable",
        error_description="Google provider is temporarily unavailable.",
    )

    assert detail == "Google provider is temporarily unavailable."


def test_google_oauth_start_state_carries_non_secret_project_metadata(monkeypatch) -> None:
    monkeypatch.setenv(
        "EA_GOOGLE_OAUTH_CLIENT_ID",
        "95627800296-5p8etgg3vvc210mfs9hkphqohtd6bsdg.apps.googleusercontent.com",
    )
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://myexternalbrain.com/google/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret-key")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_PROJECT_ID", "propertyquarry-498318")

    packet = build_google_oauth_start(
        principal_id="cf-email:tibor.girschele@gmail.com",
        scope_bundle="full_workspace",
        expected_google_email="work.tibor.girschele@gmail.com",
    )

    state = read_google_oauth_state_unchecked(packet.state)
    query = parse_qs(urlparse(packet.auth_url).query)
    assert state["oauth_client_project_id"] == "propertyquarry-498318"
    assert state["oauth_client_project_number"] == "95627800296"
    assert state["expected_google_email"] == "work.tibor.girschele@gmail.com"
    assert query["login_hint"] == ["work.tibor.girschele@gmail.com"]
    assert query["prompt"] == ["select_account consent"]
